import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, model_validator

from app.config import settings

logger = logging.getLogger("app.services.cta_loader")

# ---------------------------------------------------------------------------
# Section-label recognition (spec Section 8.2)
# ---------------------------------------------------------------------------

KNOWN_LABELS = [
    "Status", "Category", "CTA Type", "Priority", "Match Rule",
    "Do NOT display this CTA if", "Description",
    "Trigger Examples", "Trigger Conditions",
    "Aliases", "Related Topics",
    "Do NOT Trigger", "Do NOT Trigger for",
    "Fallback Rule", "Output Label", "CTA",
]

# Multiple labels that mean the same logical field are merged, in file order,
# under the canonical name on the right (spec Section 6.2 / 8.2).
LABEL_ALIASES = {
    "Trigger Conditions": "Trigger Examples",
    "Do NOT Trigger for": "Do NOT Trigger",
}

REQUIRED_LABELS = [
    "Status", "Category", "CTA Type", "Priority", "Match Rule",
    "Description", "Trigger Examples", "Do NOT Trigger",
    "Fallback Rule", "Output Label", "CTA",
]
# Optional (default to an empty list when absent): "Do NOT display this CTA
# if", "Aliases", "Related Topics".

_PREAMBLE_LINE = "Display this CTA ONLY when:"

_H1_LINE = re.compile(r"^#\s+(.+)$")
_LABEL_LINE = re.compile(r"^([A-Za-z][A-Za-z /]+):(.*)$")
_SUBHEADING = re.compile(r"^##\s+(.+)$")
_BULLET = re.compile(r"^-\s+(.+)$")


class _CTAParseError(Exception):
    """Carries one of Section 11.2's machine-readable reason codes out of the
    parser, so the scan loop can record the precise cause of a skip instead
    of a generic catch-all."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# Title extraction (spec Section 8.3)
# ---------------------------------------------------------------------------


def _extract_title(lines: list[str]) -> tuple[str, list[str]]:
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        match = _H1_LINE.match(line.strip())
        if not match:
            raise _CTAParseError("missing_title", f"first non-blank line is not a valid H1: {line!r}")
        return match.group(1).strip(), lines[i + 1 :]
    raise _CTAParseError("missing_title", "file is empty or contains only blank lines")


# ---------------------------------------------------------------------------
# The splitter (spec Section 8.4)
# ---------------------------------------------------------------------------


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    """Splits the file body (everything after the H1 title) into a dict of
    canonical-label -> body lines. Multiple occurrences of the same canonical
    label (e.g. "Do NOT Trigger" + "Do NOT Trigger for") are merged in file
    order, separated by a blank line. Lines before the first recognized
    label are discarded."""
    sections: dict[str, list[list[str]]] = defaultdict(list)
    current_label: Optional[str] = None
    current_body: list[str] = []

    def _flush() -> None:
        if current_label is not None:
            sections[current_label].append(current_body)

    for line in lines:
        match = _LABEL_LINE.match(line.strip())
        candidate = match.group(1).strip() if match else None
        if candidate in KNOWN_LABELS:
            _flush()
            current_label = LABEL_ALIASES.get(candidate, candidate)
            remainder = match.group(2).strip()
            current_body = [remainder] if remainder else []
        elif current_label is not None:
            current_body.append(line)
    _flush()

    return {
        label: [ln for body in bodies for ln in (body + [""])][:-1]
        for label, bodies in sections.items()
    }


# ---------------------------------------------------------------------------
# Field-extraction helpers (spec Sections 8.5-8.7)
# ---------------------------------------------------------------------------


def _join_scalar(body: list[str], label: str) -> str:
    non_blank = [ln.strip() for ln in body if ln.strip()]
    if len(non_blank) > 1:
        logger.warning("cta_loader: %s has multiple non-blank lines, joining with a space", label)
    return " ".join(non_blank)


def _extract_bullets(body: list[str]) -> list[str]:
    bullets = []
    for line in body:
        match = _BULLET.match(line.strip())
        if match:
            bullets.append(match.group(1).strip())
    return bullets


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _extract_match_conditions(body: list[str]) -> list[str]:
    lines = list(body)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == _PREAMBLE_LINE:
            lines = lines[i + 1 :]
        break
    return _extract_bullets(lines)


def _parse_grouped_bullets(body: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Returns (flat_examples, groups). `groups` is {} when the body has no
    ## subheadings at all -- the flat-list case (most Aliases sections,
    Related Topics). Order-preserving; exact-string dedup only, no case
    normalization (the loader never decides two phrases are 'the same')."""
    groups: dict[str, list[str]] = {}
    current_group = "_default"
    flat: list[str] = []
    seen: set[str] = set()

    for line in body:
        stripped = line.strip()
        heading_match = _SUBHEADING.match(stripped)
        bullet_match = _BULLET.match(stripped)
        if heading_match:
            current_group = heading_match.group(1).strip()
            groups.setdefault(current_group, [])
            continue
        if bullet_match:
            example = bullet_match.group(1).strip()
            groups.setdefault(current_group, []).append(example)
            if example not in seen:
                flat.append(example)
                seen.add(example)

    if set(groups) <= {"_default"}:
        groups = {}  # no real subheadings were ever seen -- pure flat-list file
    return flat, groups


def _normalize_raw_block(body: list[str]) -> str:
    lines = [ln.rstrip() for ln in body]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    normalized: list[str] = []
    prev_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and prev_blank:
            continue
        normalized.append(line)
        prev_blank = is_blank
    return "\n".join(normalized)


# ---------------------------------------------------------------------------
# Data model (spec Section 9)
# ---------------------------------------------------------------------------


class CTARecord(BaseModel):
    cta_id: str
    title: str
    source_path: str
    category_dir: str

    status: str
    category: str
    cta_type: str
    priority: str

    match_rule_raw: str
    match_conditions: list[str]
    exclusion_conditions: list[str]

    description: str

    trigger_examples: list[str]
    trigger_groups: dict[str, list[str]]

    aliases: list[str]
    related_topics: list[str]

    do_not_trigger_raw: str
    do_not_trigger_examples: list[str]

    fallback_rule: str

    output_label: str
    cta_url: str

    extra_fields: dict[str, str]
    raw_text: str

    @model_validator(mode="after")
    def _validate_required_nonempty(self) -> "CTARecord":
        for field_name in (
            "title", "status", "category", "cta_type", "priority",
            "match_rule_raw", "description", "do_not_trigger_raw",
            "fallback_rule", "output_label", "cta_url",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if not self.trigger_examples:
            raise ValueError("trigger_examples must contain at least one example")
        return self

    @model_validator(mode="after")
    def _validate_cta_url(self) -> "CTARecord":
        if not (self.cta_url.startswith("http://") or self.cta_url.startswith("https://")):
            raise ValueError(f"cta_url is not an absolute http(s) URL: {self.cta_url!r}")
        return self


@dataclass
class CTALoadIssue:
    source_path: str
    reason: str
    detail: str


@dataclass
class CTALoadResult:
    records: list[CTARecord]
    issues: list[CTALoadIssue]
    files_scanned: int
    files_loaded: int
    files_skipped: int
    load_time_ms: float


# ---------------------------------------------------------------------------
# Per-file parsing (spec Section 8.8 / Section 10)
# ---------------------------------------------------------------------------


def _parse_cta_file(path: Path, base_dir: Path) -> CTARecord:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _CTAParseError("file_read_error", str(exc)) from exc

    lines = raw_text.splitlines()
    title, remaining_lines = _extract_title(lines)
    sections = _split_sections(remaining_lines)

    for label in REQUIRED_LABELS:
        if label not in sections:
            raise _CTAParseError("missing_required_field", f"missing section: {label}")

    status = _join_scalar(sections["Status"], "Status")
    category = _join_scalar(sections["Category"], "Category")
    cta_type = _join_scalar(sections["CTA Type"], "CTA Type")
    priority = _join_scalar(sections["Priority"], "Priority")
    output_label = _join_scalar(sections["Output Label"], "Output Label")
    cta_url = _join_scalar(sections["CTA"], "CTA")
    description = _join_scalar(sections["Description"], "Description")

    for label, value in (
        ("Status", status), ("Category", category), ("CTA Type", cta_type),
        ("Priority", priority), ("Output Label", output_label), ("CTA", cta_url),
        ("Description", description),
    ):
        if not value:
            raise _CTAParseError("missing_required_field", f"empty section: {label}")

    match_rule_body = sections["Match Rule"]
    match_rule_raw = _normalize_raw_block(match_rule_body)
    if not match_rule_raw:
        raise _CTAParseError("missing_required_field", "empty section: Match Rule")
    match_conditions = _extract_match_conditions(match_rule_body)

    exclusion_conditions = _extract_bullets(sections.get("Do NOT display this CTA if", []))
    related_topics = _extract_bullets(sections.get("Related Topics", []))

    trigger_examples, trigger_groups = _parse_grouped_bullets(sections["Trigger Examples"])
    if not trigger_examples:
        raise _CTAParseError("no_trigger_examples", "Trigger Examples section yielded zero bullets")

    aliases, _ = _parse_grouped_bullets(sections.get("Aliases", []))

    do_not_trigger_body = sections["Do NOT Trigger"]
    do_not_trigger_raw = _normalize_raw_block(do_not_trigger_body)
    if not do_not_trigger_raw:
        raise _CTAParseError("missing_required_field", "empty section: Do NOT Trigger")
    do_not_trigger_examples = _dedup(_extract_bullets(do_not_trigger_body))

    fallback_rule = _normalize_raw_block(sections["Fallback Rule"])
    if not fallback_rule:
        raise _CTAParseError("missing_required_field", "empty section: Fallback Rule")

    if not (cta_url.startswith("http://") or cta_url.startswith("https://")):
        raise _CTAParseError("invalid_cta_url", cta_url)

    rel_path = path.relative_to(base_dir)
    source_path = rel_path.as_posix()
    category_dir = rel_path.parts[0]
    cta_id = source_path[: -len(".md")] if source_path.endswith(".md") else source_path

    return CTARecord(
        cta_id=cta_id,
        title=title,
        source_path=source_path,
        category_dir=category_dir,
        status=status,
        category=category,
        cta_type=cta_type,
        priority=priority,
        match_rule_raw=match_rule_raw,
        match_conditions=match_conditions,
        exclusion_conditions=exclusion_conditions,
        description=description,
        trigger_examples=trigger_examples,
        trigger_groups=trigger_groups,
        aliases=aliases,
        related_topics=related_topics,
        do_not_trigger_raw=do_not_trigger_raw,
        do_not_trigger_examples=do_not_trigger_examples,
        fallback_rule=fallback_rule,
        output_label=output_label,
        cta_url=cta_url,
        extra_fields={},
        raw_text=raw_text,
    )


# ---------------------------------------------------------------------------
# Directory scan (spec Section 7 / Section 11)
# ---------------------------------------------------------------------------


def _scan(base_dir: Path) -> CTALoadResult:
    start = time.monotonic()
    if not base_dir.is_dir():
        logger.error("cta_loader: base_dir_missing path=%s", base_dir)
        return CTALoadResult(
            records=[],
            issues=[CTALoadIssue(str(base_dir), "base_dir_missing", "not a directory")],
            files_scanned=0,
            files_loaded=0,
            files_skipped=0,
            load_time_ms=(time.monotonic() - start) * 1000,
        )

    paths = sorted(
        p for p in base_dir.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(base_dir).parts)
    )
    records: list[CTARecord] = []
    issues: list[CTALoadIssue] = []
    seen_ids: set[str] = set()

    for path in paths:
        rel = path.relative_to(base_dir).as_posix()
        try:
            record = _parse_cta_file(path, base_dir)
        except _CTAParseError as exc:
            issues.append(CTALoadIssue(rel, exc.reason, exc.detail))
            logger.warning("cta_loader skip: path=%s reason=%s detail=%s", rel, exc.reason, exc.detail)
            continue
        except Exception as exc:  # belt-and-suspenders -- never propagate (FR-3)
            issues.append(CTALoadIssue(rel, "schema_validation_failed", str(exc)))
            logger.error("cta_loader skip: path=%s reason=schema_validation_failed detail=%s", rel, exc)
            continue

        if record.cta_id in seen_ids:
            issues.append(CTALoadIssue(rel, "duplicate_cta_id", record.cta_id))
            logger.warning("cta_loader skip: path=%s reason=duplicate_cta_id detail=%s", rel, record.cta_id)
            continue
        seen_ids.add(record.cta_id)
        records.append(record)

    result = CTALoadResult(
        records=records,
        issues=issues,
        files_scanned=len(paths),
        files_loaded=len(records),
        files_skipped=len(paths) - len(records),
        load_time_ms=(time.monotonic() - start) * 1000,
    )
    logger.info(
        "cta_loader ok: scanned=%d loaded=%d skipped=%d elapsed_ms=%.2f",
        result.files_scanned, result.files_loaded, result.files_skipped, result.load_time_ms,
    )
    if not records:
        logger.warning("cta_loader: zero CTA records loaded from %s", base_dir)
    return result


# ---------------------------------------------------------------------------
# Caching and public API (spec Sections 13-14)
# ---------------------------------------------------------------------------

_CACHE: Optional[CTALoadResult] = None
_BY_ID: dict[str, CTARecord] = {}


def load_cta_data(base_dir: Optional[Path] = None, force_reload: bool = False) -> CTALoadResult:
    """Scans `base_dir` (default settings.cta_data_dir) and parses every CTA
    Markdown file into a CTARecord. Never raises (Section 11). A call with an
    explicit `base_dir` always does a fresh scan and never touches the module
    cache -- this is what lets tests point at a temp fixture directory without
    affecting global state. A call with no `base_dir` is cache-aware: pass
    force_reload=True to bypass the cache and re-scan `settings.cta_data_dir`."""
    global _CACHE, _BY_ID
    if base_dir is None:
        if _CACHE is not None and not force_reload:
            return _CACHE
        _CACHE = _scan(settings.cta_data_dir)
        _BY_ID = {record.cta_id: record for record in _CACHE.records}
        return _CACHE
    return _scan(base_dir)


def reload_cta_data(base_dir: Optional[Path] = None) -> CTALoadResult:
    """Forces a fresh scan and (when base_dir is None) replaces the module
    cache. Intended for test isolation and future hot-reload tooling, not
    per-request use."""
    return load_cta_data(base_dir=base_dir, force_reload=True)


def get_all_ctas() -> list[CTARecord]:
    """Every successfully loaded CTA record, in deterministic (sorted-path)
    order. A fresh list -- callers may not mutate the shared cache."""
    return list(load_cta_data().records)


def get_cta_by_id(cta_id: str) -> Optional[CTARecord]:
    """Exact-match lookup by cta_id (e.g. "therapies/mnri"). Returns None,
    never raises, when no such record was loaded -- a missing CTA is a
    normal outcome, not an error."""
    load_cta_data()
    return _BY_ID.get(cta_id)


def get_ctas_by_category(category: str) -> list[CTARecord]:
    """Every loaded record whose `category` field exactly equals `category`
    (case-sensitive, no normalization -- a structural filter, not a matching
    decision). [] if none match."""
    return [record for record in load_cta_data().records if record.category == category]


def get_ctas_by_status(status: str) -> list[CTARecord]:
    """Every loaded record whose `status` field exactly equals `status`."""
    return [record for record in load_cta_data().records if record.status == status]


load_cta_data()  # eager load at import time
