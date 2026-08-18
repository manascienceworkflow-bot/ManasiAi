"""Validation gate for the Concern Knowledge Library.

Implements Section 12 of `.claude/spec/manasi-ai-concern-knowledge-library-spec.md`. Every
finding is tagged with its spec rule ID (V-4, V-31, V-47 ...) so output maps straight back
to the specification.

The content-safety rules (V-30..V-37, V-47..V-50) are NOT a second safety policy. They are
the file-level linter for `docs/MANASI_ANSWER_PLAYBOOK.md` Part 4 ("Never"/"Always") and
Part 6 (answer the behaviour, not the condition), so a violation is caught in a diff rather
than at runtime by the Safety Node. When Part 4 changes, this file follows it.

Usage:
    python scripts/validate_knowledge.py                  # whole corpus
    python scripts/validate_knowledge.py --changed-only   # files changed vs. HEAD
    python scripts/validate_knowledge.py --files a.md b.md
    python scripts/validate_knowledge.py --strict         # WARN counts as failure

Exit code 1 if any ERROR (or, with --strict, any finding) is reported.
"""

import argparse
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.knowledge.concern_loader import (  # noqa: E402
    REQUIRED_SECTIONS,
    ConcernRecord,
    concerns_dir,
    load_concern_data,
)
from app.knowledge.vocabularies import load_vocabularies  # noqa: E402

ERROR = "ERROR"
WARN = "WARN"

# Loader reason code -> the spec rule it corresponds to, so a skipped file is reported
# against the same rule numbering as everything else.
LOADER_REASON_TO_RULE = {
    "missing_front_matter": "V-1",
    "invalid_yaml": "V-1",
    "file_read_error": "V-1",
    "missing_required_field": "V-2",
    "unknown_field": "V-3",
    "id_filename_mismatch": "V-4",
    "title_h1_mismatch": "V-5",
    "category_dir_mismatch": "V-6",
    "uid_mismatch": "V-7",
    "duplicate_concern_id": "V-8",
    "invalid_heading": "V-9",
    "missing_title": "V-9",
    "unknown_section": "V-10",
    "duplicate_section": "V-10",
    "section_order": "V-10",
    "missing_required_section": "V-10",
    "empty_section": "V-11",
    "invalid_vocabulary_value": "V-16",
    "invalid_field_type": "V-16",
    "unsupported_schema_version": "V-19",
    "schema_validation_failed": "V-20",
    "base_dir_missing": "V-1",
    "unexpected_parse_failure": "V-1",
}

# Section bullet-count ranges (spec 7.4).
BULLET_RANGES = {
    "typical_user_questions": (12, 30),
    "alternative_user_phrasings": (8, 25),
    "possible_explanations": (6, 15),
    "things_to_observe": (6, 12),
    "everyday_support_ideas": (6, 14),
    "manascience_perspective": (4, 8),
    "neuroplasticity_explanation": (4, 8),
    "professional_boundary": (3, 6),
    "when_professional_evaluation_may_help": (4, 10),
}

# Front-matter list cardinalities (spec Section 8).
LIST_RANGES = {
    "subtopics": (0, 6),
    "development_domains": (1, 4),
    "tags": (0, 10),
    "primary_intents": (1, 3),
    "common_emotional_states": (1, 4),
    "age_groups": (1, 7),
    "family_perspectives": (1, 8),
    "keywords": (8, 25),
    "search_terms": (5, 15),
    "negative_terms": (0, 10),
    "related_concerns": (0, 8),
    "related_conditions": (0, 8),
    "related_therapies": (0, 8),
    "cta_mapping": (0, 8),
    "authors": (1, 10),
}

# Sections holding verbatim parent language. Content-safety rules do not apply to them:
# a parent's own question legitimately says "my child" and "should I be worried", and
# rewriting those into clinical register would destroy the retrieval surface (G-3).
QUOTED_SECTION_KEYS = {"typical_user_questions", "alternative_user_phrasings"}
LINK_ALLOWED_SECTION_KEYS = {"references", "what_this_concern_is_not"}

DIAGNOSTIC_PATTERNS = [
    r"\byour child has\b",
    r"\bthis means your child\b",
    r"\byour child is (autistic|dyslexic|adhd)\b",
    r"\bis autistic\b",
    r"\bindicates (autism|adhd|dyslexia)\b",
    r"\bthis is (autism|adhd|dyslexia)\b",
    r"\bconfirms? (a )?diagnosis\b",
    r"\bdiagnosed with\b",
    r"\bthat's nothing to worry about\b",
    r"\bperfectly normal\b",
]

PRESCRIPTION_PATTERNS = [
    r"\byou should start\b",
    r"\bwe recommend (therapy|treatment)\b",
    r"\bthe right treatment is\b",
    r"\byou (must|need to) (start|begin|try)\b",
    r"\b\d+\s*(sessions?|weeks? of therapy|months? of therapy)\b",
    r"\b(dose|dosage|mg\b)",
]

CHATBOT_VOICE_PATTERNS = [
    r"\bi understand how\b",
    r"\bi know how you feel\b",
    r"\bdon't worry\b",
    r"\blet me explain\b",
    r"\bgreat question\b",
    r"\bthank you for sharing\b",
    r"\bthat's a (good|fair|thoughtful) (thing|question)\b",
    r"\bif you'd like, we can\b",
    r"\byou're doing\b",
    r"\byour child\b",
    r"\byour son\b",
    r"\byour daughter\b",
    r"(?<![a-z])i'm\b",
    r"(?<![a-z])i am\b",
]

MARKETING_PATTERNS = [
    r"\bclick here\b",
    r"\bsign up\b",
    r"\bbook a\b",
    r"\bsubscribe\b",
    r"\b(price|pricing|₹|\$\d)",
]

GUARANTEE_PATTERNS = [
    r"\bwill cure\b",
    r"\bguarantee(s|d)?\b",
    r"\bcompletely resolves?\b",
    r"\bfixes (it|the problem)\b",
    r"\balways works\b",
    r"\bwill definitely\b",
]

URGENCY_PATTERNS = [
    r"\bimmediately\b",
    r"\burgent(ly)?\b",
    r"\bserious warning sign\b",
    r"\bbefore it's too late\b",
    r"\bemergency\b",
]

THRESHOLD_PATTERNS = [
    r"\b(fewer|less|more) than \d+\b",
    r"\bat least \d+ words\b",
    r"\bby (age )?\d+ (months?|years?)\b.*\bshould\b",
]

CONDITION_MENTION_TERMS = [
    "autism", "asd", "adhd", "dyslexia", "dyspraxia", "dyscalculia", "ocd",
]

URL_PATTERN = re.compile(r"https?://", re.IGNORECASE)


@dataclass
class Finding:
    rule: str
    severity: str
    path: str
    message: str


def _match_any(text: str, patterns: "list[str]") -> "str | None":
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return None


def _prose_sections(record: ConcernRecord):
    """Sections subject to content-safety rules: everything except quoted parent language."""
    for key, section in record.sections.items():
        if key in QUOTED_SECTION_KEYS:
            continue
        yield key, section


def _word_count(text: str) -> int:
    return len(text.split())


# ---------------------------------------------------------------------------
# Rule groups
# ---------------------------------------------------------------------------


def check_structural(record: ConcernRecord) -> "list[Finding]":
    """V-13 (size). Most structural rules are enforced by the loader and surface as skips."""
    findings = []
    line_count = len(record.raw_text.splitlines())
    if line_count > 1500 or len(record.raw_text.encode("utf-8")) > 60_000:
        findings.append(Finding("V-13", WARN, record.source_path, f"file is large ({line_count} lines)"))
    for key, section in record.sections.items():
        if any(line.strip() == "---" for line in section.raw.splitlines()):
            findings.append(
                Finding("V-12", ERROR, record.source_path, f"'---' separator inside {section.name}")
            )
        if key in LINK_ALLOWED_SECTION_KEYS:
            continue
        if URL_PATTERN.search(section.raw):
            findings.append(
                Finding("V-12", ERROR, record.source_path, f"URL outside ## References in {section.name}")
            )
        if "|" in section.raw or "<" in section.raw or "```" in section.raw:
            findings.append(
                Finding("V-12", ERROR, record.source_path, f"table/HTML/code fence in {section.name}")
            )
    return findings


def check_vocabulary_and_typing(record: ConcernRecord, today: date) -> "list[Finding]":
    findings = []
    if record.status == "published" and record.clinical_review_status != "reviewed":
        findings.append(
            Finding("V-14", ERROR, record.source_path, "status=published requires clinical_review_status=reviewed")
        )
    if record.clinical_review_status == "reviewed" and not (record.clinical_reviewer or "").strip():
        findings.append(
            Finding("V-15", ERROR, record.source_path, "clinical_review_status=reviewed requires clinical_reviewer")
        )
    if record.last_updated > today:
        findings.append(Finding("V-17", ERROR, record.source_path, f"last_updated is in the future: {record.last_updated}"))
    for field_name in ("content_version", "schema_version"):
        value = getattr(record, field_name)
        if not re.match(r"^\d+\.\d+\.\d+$", value):
            findings.append(Finding("V-18", ERROR, record.source_path, f"{field_name} is not semver: {value!r}"))
    for field_name, (low, high) in LIST_RANGES.items():
        values = getattr(record, field_name, None)
        if values is None:
            continue
        if not (low <= len(values) <= high):
            findings.append(
                Finding("V-20", ERROR, record.source_path, f"{field_name} has {len(values)} entries, expected {low}-{high}")
            )
    for field_name in ("keywords", "search_terms", "negative_terms"):
        values = getattr(record, field_name)
        if len(set(values)) != len(values):
            findings.append(Finding("V-21", WARN, record.source_path, f"{field_name} contains duplicates"))
        for value in values:
            if value != value.lower():
                findings.append(Finding("V-21", WARN, record.source_path, f"{field_name} entry not lowercase: {value!r}"))
    return findings


def check_relationships(record: ConcernRecord, all_ids: "set[str]", cta_lookup) -> "list[Finding]":
    findings = []
    for related in record.related_concerns:
        if related.id == record.concern_id:
            findings.append(Finding("V-29", ERROR, record.source_path, "related_concerns references itself"))
        elif related.id not in all_ids:
            findings.append(Finding("V-22", ERROR, record.source_path, f"related concern does not exist: {related.id}"))
        if not (0.0 <= related.weight <= 1.0):
            findings.append(Finding("V-20", ERROR, record.source_path, f"relation weight out of range: {related.weight}"))

    primaries = [entry for entry in record.cta_mapping if entry.priority == "primary"]
    if len(primaries) > 1:
        findings.append(Finding("V-27", ERROR, record.source_path, f"{len(primaries)} primary CTAs, at most 1 allowed"))
    for entry in record.cta_mapping:
        if cta_lookup(entry.cta_id) is None:
            findings.append(Finding("V-27", ERROR, record.source_path, f"cta_id not found in the CTA corpus: {entry.cta_id}"))

    for key, section in record.sections.items():
        for target in re.findall(r"\]\(([^)]+\.md)\)", section.raw):
            target_id = Path(target).stem
            if target_id not in all_ids:
                findings.append(Finding("V-25", ERROR, record.source_path, f"prose link target does not exist: {target}"))
            elif target_id not in {r.id for r in record.related_concerns}:
                findings.append(
                    Finding("V-26", WARN, record.source_path, f"prose-linked concern missing from related_concerns: {target_id}")
                )
    return findings


def check_content_safety(record: ConcernRecord, vocabularies: "dict[str, list[str]]") -> "list[Finding]":
    findings = []
    hedges = vocabularies.get("hedge_terms", [])
    approved = vocabularies.get("approved_boundary_phrasings", [])
    allowed_therapies = set(vocabularies.get("related_therapies", []))
    disallowed_therapy_terms = vocabularies.get("disallowed_therapy_terms", [])

    for key, section in _prose_sections(record):
        text = section.raw
        for rule, patterns in (
            ("V-30", DIAGNOSTIC_PATTERNS),
            ("V-32", PRESCRIPTION_PATTERNS),
            ("V-33", CHATBOT_VOICE_PATTERNS),
            ("V-34", MARKETING_PATTERNS),
        ):
            hit = _match_any(text, patterns)
            if hit:
                findings.append(Finding(rule, ERROR, record.source_path, f"{section.name}: disallowed phrasing {hit!r}"))
        if key in ("manascience_perspective", "neuroplasticity_explanation"):
            hit = _match_any(text, GUARANTEE_PATTERNS)
            if hit:
                findings.append(Finding("V-35", ERROR, record.source_path, f"{section.name}: outcome claim {hit!r}"))
        if not record.escalation_sensitive:
            hit = _match_any(text, URGENCY_PATTERNS)
            if hit:
                findings.append(
                    Finding("V-36", ERROR, record.source_path, f"{section.name}: urgency language {hit!r} (set escalation_sensitive to review it)")
                )
        hit = _match_any(text, THRESHOLD_PATTERNS)
        if hit:
            findings.append(Finding("V-37", ERROR, record.source_path, f"{section.name}: numeric screening threshold {hit!r}"))
        hit = _match_any(text, disallowed_therapy_terms) if disallowed_therapy_terms else None
        if hit:
            findings.append(
                Finding("V-48", ERROR, record.source_path, f"{section.name}: names an approach ManaScience does not cover ({hit!r})")
            )

    if hedges:
        for index, bullet in enumerate(record.section_bullets("possible_explanations"), start=1):
            lowered = bullet.lower()
            if not any(hedge in lowered for hedge in hedges):
                findings.append(
                    Finding("V-31", ERROR, record.source_path, f"Possible Explanations bullet {index} has no hedge: {bullet[:60]!r}")
                )

    if approved:
        boundary = record.section_text("professional_boundary").lower()
        if not any(phrase in boundary for phrase in approved):
            findings.append(
                Finding("V-47", ERROR, record.source_path, "Professional Boundary uses no approved Playbook Part 4 phrasing")
            )

    if allowed_therapies:
        for therapy in record.related_therapies:
            if therapy.lower() not in allowed_therapies:
                findings.append(
                    Finding("V-48", ERROR, record.source_path, f"related_therapies entry outside the Playbook Part 3 allowlist: {therapy}")
                )

    prose = " ".join(section.raw.lower() for _, section in _prose_sections(record))
    for term in CONDITION_MENTION_TERMS:
        count = len(re.findall(rf"\b{re.escape(term)}\b", prose))
        if count > 5:
            findings.append(
                Finding("V-38", WARN, record.source_path, f"'{term}' appears {count} times -- this may be a condition file in disguise")
            )

    summary = record.sections.get("summary")
    if summary is not None:
        words = _word_count(summary.raw)
        if summary.bullets:
            findings.append(Finding("V-40", ERROR, record.source_path, "## Summary must be prose, not bullets"))
        if not (40 <= words <= 90):
            findings.append(Finding("V-40", ERROR, record.source_path, f"## Summary is {words} words, expected 40-90"))

    for key, (low, high) in BULLET_RANGES.items():
        section = record.sections.get(key)
        if section is None or section.is_not_applicable():
            continue
        count = len(section.bullets)
        if not (low <= count <= high):
            findings.append(
                Finding("V-42", WARN, record.source_path, f"{section.name} has {count} bullets, expected {low}-{high}")
            )
        if key in QUOTED_SECTION_KEYS:
            # Verbatim parent language: "Late talker." is exactly what someone types, and
            # padding it to eight words would destroy the matching surface it exists for.
            continue
        for bullet in section.bullets:
            words = _word_count(bullet)
            if not (8 <= words <= 45):
                findings.append(
                    Finding("V-39", WARN, record.source_path, f"{section.name}: bullet is {words} words (expected 8-45): {bullet[:50]!r}")
                )

    for _, section in _prose_sections(record):
        sentences = [s for s in re.split(r"[.!?]", section.raw) if s.strip()]
        if sentences:
            average = sum(_word_count(s) for s in sentences) / len(sentences)
            if average > 28:
                findings.append(
                    Finding("V-41", WARN, record.source_path, f"{section.name}: mean sentence length {average:.0f} words (plain-language proxy)")
                )

    missing_beats = [
        name for name, key in REQUIRED_SECTIONS
        if record.sections.get(key) is None or record.sections[key].is_not_applicable()
    ]
    if missing_beats:
        findings.append(
            Finding("V-50", ERROR, record.source_path, f"Playbook Explain beats unsourceable -- missing/not-applicable: {', '.join(missing_beats)}")
        )
    return findings


def check_corpus(records: "list[ConcernRecord]", base_dir: Path) -> "list[Finding]":
    findings = []
    perspectives = [
        (record, " ".join(sorted(b.lower() for b in record.section_bullets("manascience_perspective"))))
        for record in records
    ]
    seen_perspectives: "dict[str, str]" = {}
    for record, blob in perspectives:
        if blob and blob in seen_perspectives:
            findings.append(
                Finding("V-49", WARN, record.source_path, f"ManaScience Perspective is identical to {seen_perspectives[blob]}")
            )
        elif blob:
            seen_perspectives[blob] = record.concern_id

    for i, first in enumerate(records):
        for second in records[i + 1 :]:
            keywords_a, keywords_b = set(first.keywords), set(second.keywords)
            if not keywords_a or not keywords_b:
                continue
            overlap = len(keywords_a & keywords_b) / min(len(keywords_a), len(keywords_b))
            if overlap > 0.6:
                findings.append(
                    Finding("V-43", WARN, first.source_path, f"{overlap:.0%} keyword overlap with {second.concern_id} -- possible duplicate")
                )

    inbound = Counter()
    for record in records:
        for related in record.related_concerns:
            inbound[related.id] += 1
    for record in records:
        if record.status == "published" and inbound[record.concern_id] == 0:
            findings.append(Finding("V-44", WARN, record.source_path, "no other concern links to this one (orphan)"))

    if base_dir.is_dir():
        for path in base_dir.rglob("*"):
            relative = path.relative_to(base_dir)
            if path.is_file() and path.suffix != ".md" and not any(p.startswith(("_", ".")) for p in relative.parts):
                findings.append(Finding("V-45", ERROR, relative.as_posix(), "non-markdown file in the concern corpus"))
    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _changed_files(base_dir: Path) -> "list[str]":
    try:
        output = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", str(base_dir)],
            capture_output=True, text=True, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [line.strip() for line in output.splitlines() if line.strip().endswith(".md")]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the Concern Knowledge Library.")
    parser.add_argument("--path", default=None, help="corpus root (default: <knowledge_data_dir>/concerns)")
    parser.add_argument("--files", nargs="*", default=None, help="restrict findings to these files")
    parser.add_argument("--changed-only", action="store_true", help="restrict findings to files changed vs HEAD")
    parser.add_argument("--strict", action="store_true", help="treat WARN as failure")
    args = parser.parse_args()

    base_dir = Path(args.path).resolve() if args.path else concerns_dir()
    knowledge_dir = base_dir.parent
    vocabularies = load_vocabularies(knowledge_dir) or load_vocabularies()
    if not vocabularies:
        print("WARNING: no vocabularies loaded -- vocabulary and content-safety rules are degraded", file=sys.stderr)

    result = load_concern_data(base_dir=base_dir)
    records = result.records
    all_ids = {record.concern_id for record in records}

    try:
        from app.services.cta_loader import get_cta_by_id as cta_lookup
    except Exception:  # a broken CTA corpus must not block content validation
        print("WARNING: CTA corpus unavailable -- V-27 skipped", file=sys.stderr)
        cta_lookup = lambda _cta_id: object()  # noqa: E731

    findings: "list[Finding]" = [
        Finding(LOADER_REASON_TO_RULE.get(issue.reason, "V-1"), ERROR, issue.source_path, f"{issue.reason}: {issue.detail}")
        for issue in result.issues
    ]

    today = date.today()
    for record in records:
        findings.extend(check_structural(record))
        findings.extend(check_vocabulary_and_typing(record, today))
        findings.extend(check_relationships(record, all_ids, cta_lookup))
        findings.extend(check_content_safety(record, vocabularies))
    findings.extend(check_corpus(records, base_dir))

    selected = args.files
    if args.changed_only:
        selected = _changed_files(base_dir)
    if selected is not None:
        stems = {Path(f).name for f in selected}
        findings = [f for f in findings if Path(f.path).name in stems]

    errors = [f for f in findings if f.severity == ERROR]
    warnings = [f for f in findings if f.severity == WARN]

    for finding in sorted(findings, key=lambda f: (f.severity != ERROR, f.path, f.rule)):
        print(f"{finding.rule:>5} {finding.severity:<5} {finding.path}: {finding.message}")

    print(
        f"\n{result.files_scanned} file(s) scanned, {result.files_loaded} loaded, "
        f"{result.files_skipped} skipped -- {len(errors)} error(s), {len(warnings)} warning(s)"
    )
    # Never claim coverage that was not run (spec: no silent caps).
    print("note: V-46 (retrieval quality gate) is not run here -- it needs an embedded index.")

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
