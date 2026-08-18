"""Parser and in-memory cache for the Concern Knowledge Library.

Spec: `.claude/spec/manasi-ai-concern-knowledge-library-spec.md` (§7 schema, §8 metadata,
§18.2 loader design principles). Structurally mirrors `app/services/cta_loader.py`, which
established the house pattern: never raise, record a machine-readable reason per skipped
file, eager-load at import, and let an explicit `base_dir` bypass the module cache so tests
can point at a fixture corpus.

Division of labour with `scripts/validate_knowledge.py`: this module answers "can this file
be used at runtime?" (structure, required fields, closed vocabularies, identity
consistency). The validator answers "should this file merge?" (cardinalities, style,
hedging, cross-file relationships, content safety). A file that fails the validator still
loads if it is structurally sound -- that is deliberate, so a style regression degrades
review, not serving.
"""

import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.knowledge.vocabularies import load_vocabularies

logger = logging.getLogger("app.knowledge.concern_loader")

SUPPORTED_SCHEMA_MAJORS = {1}

# ---------------------------------------------------------------------------
# Section catalog (spec Section 7.4). Order here IS the canonical file order.
# ---------------------------------------------------------------------------

REQUIRED_SECTIONS: "list[tuple[str, str]]" = [
    ("Summary", "summary"),
    ("Typical User Questions", "typical_user_questions"),
    ("Alternative User Phrasings", "alternative_user_phrasings"),
    ("Possible Explanations", "possible_explanations"),
    ("Things to Observe", "things_to_observe"),
    ("Everyday Support Ideas", "everyday_support_ideas"),
    ("ManaScience Perspective", "manascience_perspective"),
    ("Neuroplasticity Explanation", "neuroplasticity_explanation"),
    ("Professional Boundary", "professional_boundary"),
    ("When Professional Evaluation May Help", "when_professional_evaluation_may_help"),
]

OPTIONAL_SECTIONS: "list[tuple[str, str]]" = [
    ("Common Misunderstandings", "common_misunderstandings"),
    ("What This Concern Is Not", "what_this_concern_is_not"),
    ("Age-Specific Notes", "age_specific_notes"),
    ("Family Perspective Notes", "family_perspective_notes"),
    ("Cultural and Multilingual Notes", "cultural_and_multilingual_notes"),
    ("Questions a Professional May Ask", "questions_a_professional_may_ask"),
    ("References", "references"),
]

SECTION_ORDER: "list[tuple[str, str]]" = REQUIRED_SECTIONS + OPTIONAL_SECTIONS
SECTION_KEY_BY_NAME = {name: key for name, key in SECTION_ORDER}
SECTION_NAME_BY_KEY = {key: name for name, key in SECTION_ORDER}
SECTION_RANK_BY_KEY = {key: rank for rank, (_, key) in enumerate(SECTION_ORDER)}
REQUIRED_SECTION_KEYS = [key for _, key in REQUIRED_SECTIONS]

# `## Summary` is prose rather than bullets -- the one documented exception to S-10.
PROSE_SECTION_KEYS = {"summary"}

# The sentinel that distinguishes "considered and rejected" from "forgotten" (S-9).
NOT_APPLICABLE_SENTINEL = "Not applicable for this concern."

# ---------------------------------------------------------------------------
# Front-matter contract (spec Section 8)
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "schema_version", "content_type", "concern_id", "concern_uid", "title", "status",
    "category", "topic", "development_domains",
    "primary_intents", "common_emotional_states", "age_groups", "family_perspectives",
    "keywords", "search_terms",
    "related_concerns", "related_conditions", "related_therapies", "cta_mapping",
    "professional_boundary_required", "escalation_sensitive", "clinical_review_status",
    "content_version", "last_updated", "authors",
}

OPTIONAL_FIELDS = {
    "subtopics", "tags", "negative_terms", "clinical_reviewer", "sources",
    "supersedes", "superseded_by",
}

KNOWN_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

# field name -> vocabulary name in _schema/vocabularies.md
CLOSED_SCALAR_FIELDS = {
    "content_type": "content_type",
    "status": "status",
    "category": "category",
    "clinical_review_status": "clinical_review_status",
}

CLOSED_LIST_FIELDS = {
    "development_domains": "development_domains",
    "primary_intents": "primary_intents",
    "common_emotional_states": "common_emotional_states",
    "age_groups": "age_groups",
    "family_perspectives": "family_perspectives",
    "related_conditions": "related_conditions",
    "related_therapies": "related_therapies",
}

_FRONT_MATTER_FENCE = "---"
_H1_LINE = re.compile(r"^#\s+(.+?)\s*$")
_H2_LINE = re.compile(r"^##\s+(.+?)\s*$")
_DEEPER_HEADING = re.compile(r"^#{3,}\s+")
_BULLET = re.compile(r"^-\s+(.+?)\s*$")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class ConcernParseError(Exception):
    """Carries a machine-readable reason code out of the parser so the scan loop can
    record the precise cause of a skip instead of a generic catch-all."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# Data model (spec Section 8)
# ---------------------------------------------------------------------------


class ConcernSection(BaseModel):
    name: str
    key: str
    rank: int
    bullets: "list[str]"
    raw: str

    def is_not_applicable(self) -> bool:
        return len(self.bullets) == 1 and self.bullets[0].rstrip(".") == NOT_APPLICABLE_SENTINEL.rstrip(".")


class RelatedConcern(BaseModel):
    id: str
    relation: str
    weight: float = 1.0


class CTAMapping(BaseModel):
    cta_id: str
    priority: str


class ConcernRecord(BaseModel):
    # identity
    schema_version: str
    content_type: str
    concern_id: str
    concern_uid: str
    title: str
    status: str

    # classification
    category: str
    topic: str
    subtopics: "list[str]" = Field(default_factory=list)
    development_domains: "list[str]"
    tags: "list[str]" = Field(default_factory=list)

    # query affinity
    primary_intents: "list[str]"
    common_emotional_states: "list[str]"
    age_groups: "list[str]"
    family_perspectives: "list[str]"
    keywords: "list[str]"
    search_terms: "list[str]"
    negative_terms: "list[str]" = Field(default_factory=list)

    # relationships
    related_concerns: "list[RelatedConcern]"
    related_conditions: "list[str]"
    related_therapies: "list[str]"
    cta_mapping: "list[CTAMapping]"

    # governance
    professional_boundary_required: bool
    escalation_sensitive: bool
    clinical_review_status: str
    clinical_reviewer: Optional[str] = None
    content_version: str
    last_updated: date
    authors: "list[str]"
    sources: "list[str]" = Field(default_factory=list)
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None

    # body + provenance
    sections: "dict[str, ConcernSection]"
    source_path: str
    raw_text: str

    def section_bullets(self, key: str) -> "list[str]":
        """Bullets for a section, or [] when absent or marked not-applicable."""
        section = self.sections.get(key)
        if section is None or section.is_not_applicable():
            return []
        return list(section.bullets)

    def section_text(self, key: str) -> str:
        section = self.sections.get(key)
        return section.raw if section is not None else ""

    def is_ingestable(self) -> bool:
        """Spec Section 10.2: only reviewed, published content is ever embedded."""
        return self.status == "published" and self.clinical_review_status == "reviewed"


@dataclass
class ConcernLoadIssue:
    source_path: str
    reason: str
    detail: str


@dataclass
class ConcernLoadResult:
    records: "list[ConcernRecord]"
    issues: "list[ConcernLoadIssue]"
    files_scanned: int
    files_loaded: int
    files_skipped: int
    load_time_ms: float


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _split_front_matter(text: str) -> "tuple[str, list[str]]":
    """Return (front_matter_text, body_lines). Raises if the opening fence is missing or
    never closes -- a file without machine-readable metadata is not a concern file."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONT_MATTER_FENCE:
        raise ConcernParseError("missing_front_matter", "file does not begin with a '---' fence")
    for index in range(1, len(lines)):
        if lines[index].strip() == _FRONT_MATTER_FENCE:
            return "\n".join(lines[1:index]), lines[index + 1 :]
    raise ConcernParseError("missing_front_matter", "front-matter fence is never closed")


def _parse_front_matter(front_matter_text: str) -> "dict[str, Any]":
    try:
        parsed = yaml.safe_load(front_matter_text)
    except yaml.YAMLError as exc:
        raise ConcernParseError("invalid_yaml", str(exc)) from exc
    if not isinstance(parsed, dict):
        raise ConcernParseError("invalid_yaml", "front matter is not a YAML mapping")
    return parsed


def _extract_title(body_lines: "list[str]") -> "tuple[str, list[str]]":
    for index, line in enumerate(body_lines):
        if not line.strip():
            continue
        match = _H1_LINE.match(line.strip())
        if not match:
            raise ConcernParseError(
                "missing_title", f"first non-blank line after front matter is not an H1: {line!r}"
            )
        return match.group(1).strip(), body_lines[index + 1 :]
    raise ConcernParseError("missing_title", "body is empty")


def _extract_bullets(body_lines: "list[str]") -> "list[str]":
    """Collect bullets, joining wrapped continuation lines into one logical bullet.

    Authors wrap long bullets to keep diffs readable, so a bullet is "- " plus every
    following indented line until a blank line or the next bullet. Taking only the first
    line would silently truncate the content -- and truncation is not cosmetic here: a
    hedge or a boundary phrase living on the second line would vanish from both the
    validator's view and the embedded chunk.
    """
    bullets: "list[str]" = []
    current: Optional[str] = None
    for line in body_lines:
        stripped = line.strip()
        match = _BULLET.match(stripped)
        if match:
            if current is not None:
                bullets.append(current)
            current = match.group(1).strip()
        elif not stripped:
            if current is not None:
                bullets.append(current)
                current = None
        elif current is not None:
            current = f"{current} {stripped}"
    if current is not None:
        bullets.append(current)
    return bullets


def _split_sections(lines: "list[str]") -> "dict[str, ConcernSection]":
    """Split the body into recognized `##` sections, in file order.

    Unknown section names and `###`+ headings are rejected rather than ignored: silently
    dropping an author's section is how content goes missing from answers without anyone
    noticing (V-3's rationale applied to the body).
    """
    sections: dict[str, ConcernSection] = {}
    encountered_keys: list[str] = []
    current_name: Optional[str] = None
    current_body: list[str] = []

    def _flush() -> None:
        if current_name is None:
            return
        key = SECTION_KEY_BY_NAME[current_name]
        if key in sections:
            raise ConcernParseError("duplicate_section", f"section appears twice: {current_name}")
        raw = "\n".join(current_body).strip()
        bullets = _extract_bullets(current_body)
        sections[key] = ConcernSection(
            name=current_name, key=key, rank=SECTION_RANK_BY_KEY[key], bullets=bullets, raw=raw
        )
        encountered_keys.append(key)

    for line in lines:
        stripped = line.strip()
        if _DEEPER_HEADING.match(stripped):
            raise ConcernParseError("invalid_heading", f"headings deeper than ## are not allowed: {stripped!r}")
        if _H1_LINE.match(stripped) and not stripped.startswith("##"):
            raise ConcernParseError("invalid_heading", "more than one H1 in the file")
        heading = _H2_LINE.match(stripped)
        if heading:
            _flush()
            name = heading.group(1).strip()
            if name not in SECTION_KEY_BY_NAME:
                raise ConcernParseError("unknown_section", f"unrecognized section: {name}")
            current_name = name
            current_body = []
            continue
        if current_name is not None:
            current_body.append(line)
    _flush()

    _check_section_order(encountered_keys)
    return sections


def _check_section_order(encountered_keys: "list[str]") -> None:
    """Encountered sections must be a subsequence of the canonical order (S-8)."""
    canonical = [key for _, key in SECTION_ORDER]
    position = -1
    for key in encountered_keys:
        index = canonical.index(key)
        if index <= position:
            raise ConcernParseError(
                "section_order", f"section '{SECTION_NAME_BY_KEY[key]}' is out of canonical order"
            )
        position = index


def _require_sections(sections: "dict[str, ConcernSection]") -> None:
    for key in REQUIRED_SECTION_KEYS:
        section = sections.get(key)
        if section is None:
            raise ConcernParseError("missing_required_section", f"missing section: {SECTION_NAME_BY_KEY[key]}")
        if not section.raw.strip():
            raise ConcernParseError("empty_section", f"empty section: {SECTION_NAME_BY_KEY[key]}")
        if key not in PROSE_SECTION_KEYS and not section.bullets:
            raise ConcernParseError(
                "empty_section", f"section has no bullets: {SECTION_NAME_BY_KEY[key]}"
            )


def _check_fields_present(front_matter: "dict[str, Any]") -> None:
    unknown = sorted(set(front_matter) - KNOWN_FIELDS)
    if unknown:
        raise ConcernParseError("unknown_field", f"unrecognized front-matter keys: {', '.join(unknown)}")
    missing = sorted(REQUIRED_FIELDS - set(front_matter))
    if missing:
        raise ConcernParseError("missing_required_field", f"missing keys: {', '.join(missing)}")


def _check_schema_version(front_matter: "dict[str, Any]") -> None:
    raw = str(front_matter.get("schema_version", "")).strip()
    if not _SEMVER.match(raw):
        raise ConcernParseError("unsupported_schema_version", f"schema_version is not semver: {raw!r}")
    major = int(raw.split(".")[0])
    if major not in SUPPORTED_SCHEMA_MAJORS:
        raise ConcernParseError(
            "unsupported_schema_version",
            f"schema_version major {major} is not supported by this loader",
        )


def _check_vocabularies(front_matter: "dict[str, Any]", vocabularies: "dict[str, list[str]]") -> None:
    """Validate closed-vocabulary values. Skipped entirely when the vocabularies file is
    unavailable -- see `load_vocabularies` for why that degrades rather than fails."""
    if not vocabularies:
        return
    for field, vocab_name in CLOSED_SCALAR_FIELDS.items():
        allowed = vocabularies.get(vocab_name, [])
        value = front_matter.get(field)
        if allowed and str(value).lower() not in allowed:
            raise ConcernParseError("invalid_vocabulary_value", f"{field}={value!r} is not in {vocab_name}")
    for field, vocab_name in CLOSED_LIST_FIELDS.items():
        allowed = vocabularies.get(vocab_name, [])
        values = front_matter.get(field) or []
        if not isinstance(values, list):
            raise ConcernParseError("invalid_field_type", f"{field} must be a list")
        if not allowed:
            continue
        for value in values:
            if str(value).lower() not in allowed:
                raise ConcernParseError(
                    "invalid_vocabulary_value", f"{field} contains {value!r}, which is not in {vocab_name}"
                )
    relation_values = vocabularies.get("relation", [])
    if relation_values:
        for entry in front_matter.get("related_concerns") or []:
            relation = (entry or {}).get("relation") if isinstance(entry, dict) else None
            if relation is not None and str(relation).lower() not in relation_values:
                raise ConcernParseError("invalid_vocabulary_value", f"unknown relation: {relation!r}")
    priority_values = vocabularies.get("cta_priority", [])
    if priority_values:
        for entry in front_matter.get("cta_mapping") or []:
            priority = (entry or {}).get("priority") if isinstance(entry, dict) else None
            if priority is not None and str(priority).lower() not in priority_values:
                raise ConcernParseError("invalid_vocabulary_value", f"unknown cta priority: {priority!r}")


def _check_identity(front_matter: "dict[str, Any]", title: str, path: Path, base_dir: Path) -> None:
    relative = path.relative_to(base_dir)
    stem = path.stem
    concern_id = str(front_matter.get("concern_id", ""))
    if concern_id != stem:
        raise ConcernParseError("id_filename_mismatch", f"concern_id={concern_id!r} but filename stem is {stem!r}")
    if str(front_matter.get("title", "")) != title:
        raise ConcernParseError(
            "title_h1_mismatch", f"title={front_matter.get('title')!r} but H1 is {title!r}"
        )
    parts = relative.parts
    if len(parts) < 2:
        raise ConcernParseError("category_dir_mismatch", "concern files must live in a category directory")
    category_dir = parts[-2]
    if str(front_matter.get("category", "")) != category_dir:
        raise ConcernParseError(
            "category_dir_mismatch",
            f"category={front_matter.get('category')!r} but parent directory is {category_dir!r}",
        )
    # `concern_uid` is corpus-qualified (`concerns/<category>/<id>`), and the corpus name
    # is the scan root's own directory name -- so a fixture corpus rooted at
    # <tmp>/concerns/ validates identically to the real one.
    expected_uid = f"{base_dir.name}/{category_dir}/{concern_id}"
    if str(front_matter.get("concern_uid", "")) != expected_uid:
        raise ConcernParseError(
            "uid_mismatch", f"concern_uid should be {expected_uid!r}, got {front_matter.get('concern_uid')!r}"
        )


def _parse_concern_file(path: Path, base_dir: Path, vocabularies: "dict[str, list[str]]") -> ConcernRecord:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConcernParseError("file_read_error", str(exc)) from exc

    front_matter_text, body_lines = _split_front_matter(raw_text)
    front_matter = _parse_front_matter(front_matter_text)

    _check_fields_present(front_matter)
    _check_schema_version(front_matter)
    _check_vocabularies(front_matter, vocabularies)

    title, remaining = _extract_title(body_lines)
    _check_identity(front_matter, title, path, base_dir)

    sections = _split_sections(remaining)
    _require_sections(sections)

    payload = dict(front_matter)
    payload["sections"] = sections
    payload["source_path"] = path.relative_to(base_dir).as_posix()
    payload["raw_text"] = raw_text

    try:
        return ConcernRecord.model_validate(payload)
    except ValidationError as exc:
        raise ConcernParseError("schema_validation_failed", str(exc)) from exc


# ---------------------------------------------------------------------------
# Directory scan
# ---------------------------------------------------------------------------


def _is_infrastructure(relative: Path) -> bool:
    """`_`- and `.`-prefixed path parts are infrastructure, never content (spec 6.3)."""
    return any(part.startswith(("_", ".")) for part in relative.parts)


def _scan(base_dir: Path, vocabularies: "dict[str, list[str]]") -> ConcernLoadResult:
    start = time.monotonic()
    if not base_dir.is_dir():
        logger.error("concern_loader: base_dir_missing path=%s", base_dir)
        return ConcernLoadResult(
            records=[],
            issues=[ConcernLoadIssue(str(base_dir), "base_dir_missing", "not a directory")],
            files_scanned=0,
            files_loaded=0,
            files_skipped=0,
            load_time_ms=(time.monotonic() - start) * 1000,
        )

    paths = sorted(p for p in base_dir.rglob("*.md") if not _is_infrastructure(p.relative_to(base_dir)))
    records: "list[ConcernRecord]" = []
    issues: "list[ConcernLoadIssue]" = []
    seen_ids: "set[str]" = set()

    for path in paths:
        relative = path.relative_to(base_dir).as_posix()
        try:
            record = _parse_concern_file(path, base_dir, vocabularies)
        except ConcernParseError as exc:
            issues.append(ConcernLoadIssue(relative, exc.reason, exc.detail))
            logger.warning("concern_loader skip: path=%s reason=%s detail=%s", relative, exc.reason, exc.detail)
            continue
        except Exception as exc:  # belt-and-suspenders -- a content file may never 500 the API
            issues.append(ConcernLoadIssue(relative, "unexpected_parse_failure", str(exc)))
            logger.error("concern_loader skip: path=%s reason=unexpected_parse_failure detail=%s", relative, exc)
            continue

        if record.concern_id in seen_ids:
            issues.append(ConcernLoadIssue(relative, "duplicate_concern_id", record.concern_id))
            logger.warning("concern_loader skip: path=%s reason=duplicate_concern_id detail=%s", relative, record.concern_id)
            continue
        seen_ids.add(record.concern_id)
        records.append(record)

    result = ConcernLoadResult(
        records=records,
        issues=issues,
        files_scanned=len(paths),
        files_loaded=len(records),
        files_skipped=len(paths) - len(records),
        load_time_ms=(time.monotonic() - start) * 1000,
    )
    logger.info(
        "concern_loader ok: scanned=%d loaded=%d skipped=%d elapsed_ms=%.2f",
        result.files_scanned, result.files_loaded, result.files_skipped, result.load_time_ms,
    )
    return result


# ---------------------------------------------------------------------------
# Caching and public API
# ---------------------------------------------------------------------------

_CACHE: Optional[ConcernLoadResult] = None
_BY_ID: "dict[str, ConcernRecord]" = {}


def concerns_dir(knowledge_dir: Optional[Path] = None) -> Path:
    return (knowledge_dir or settings.knowledge_data_dir) / "concerns"


def load_concern_data(base_dir: Optional[Path] = None, force_reload: bool = False) -> ConcernLoadResult:
    """Scan `base_dir` (default `<knowledge_data_dir>/concerns`) and parse every concern
    file. Never raises.

    A call with an explicit `base_dir` always does a fresh scan and never touches the module
    cache -- this is what lets tests point at a temp fixture directory without affecting
    global state. A call with no `base_dir` is cache-aware; pass `force_reload=True` to
    re-scan.
    """
    global _CACHE, _BY_ID
    if base_dir is None:
        if _CACHE is not None and not force_reload:
            return _CACHE
        _CACHE = _scan(concerns_dir(), load_vocabularies(force_reload=force_reload))
        _BY_ID = {record.concern_id: record for record in _CACHE.records}
        return _CACHE
    # A fixture corpus keeps its own _schema/vocabularies.md next to its concerns/ dir;
    # fall back to the real one when it has none, so a test fixture need not restate the
    # whole vocabulary just to exercise the parser.
    fixture_knowledge_dir = base_dir.parent
    vocabularies = load_vocabularies(fixture_knowledge_dir) or load_vocabularies()
    return _scan(base_dir, vocabularies)


def reload_concern_data(base_dir: Optional[Path] = None) -> ConcernLoadResult:
    """Force a fresh scan and (when base_dir is None) replace the module cache. Intended
    for test isolation and future hot-reload tooling, not per-request use."""
    return load_concern_data(base_dir=base_dir, force_reload=True)


def get_all_concerns() -> "list[ConcernRecord]":
    """Every successfully loaded record, in deterministic (sorted-path) order."""
    return list(load_concern_data().records)


def get_concern_by_id(concern_id: str) -> Optional[ConcernRecord]:
    """Exact-match lookup. Returns None, never raises -- a missing concern is a normal
    outcome (e.g. a stale vector pointing at a since-deleted file)."""
    load_concern_data()
    return _BY_ID.get(concern_id)


def get_concerns_by_category(category: str) -> "list[ConcernRecord]":
    return [record for record in load_concern_data().records if record.category == category]


def get_published_concerns() -> "list[ConcernRecord]":
    """Records eligible for embedding: published AND clinically reviewed (spec 10.2)."""
    return [record for record in load_concern_data().records if record.is_ingestable()]


load_concern_data()  # eager load at import time, mirroring cta_loader
