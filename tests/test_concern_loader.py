import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.knowledge.concern_loader import (  # noqa: E402
    REQUIRED_SECTIONS,
    get_concern_by_id,
    get_published_concerns,
    load_concern_data,
)

# ---------------------------------------------------------------------------
# Fixture builder -- assembles a valid minimal concern file, with any part
# overridable or removable per test.
# ---------------------------------------------------------------------------

DEFAULT_SECTIONS = {
    "Summary": (
        "Speech delay describes a pattern where a child develops spoken words later than "
        "most children of a similar age. It refers to what a family observes about "
        "talking, not to any diagnosis. Children reach speech milestones across a wide "
        "range of timelines, and the same delay can arise from very different underlying "
        "reasons, which is why an individual assessment matters more than comparison."
    ),
    "Typical User Questions": "\n".join(f"- Sample question number {i}?" for i in range(1, 13)),
    "Alternative User Phrasings": "\n".join(f"- Sample phrasing {i}." for i in range(1, 9)),
    "Possible Explanations": "\n".join(
        f"- Some children may show this for reason number {i} in ordinary development." for i in range(1, 7)
    ),
    "Things to Observe": "\n".join(f"- Whether the child does observable thing number {i} at home." for i in range(1, 7)),
    "Everyday Support Ideas": "\n".join(f"- Families often find that support idea number {i} helps." for i in range(1, 7)),
    "ManaScience Perspective": "\n".join(f"- ManaScience looks at this concern through lens number {i}." for i in range(1, 5)),
    "Neuroplasticity Explanation": "\n".join(f"- The brain continues to develop in way number {i} over time." for i in range(1, 5)),
    "Professional Boundary": (
        "- Manasi can provide educational information, but cannot diagnose medical conditions.\n"
        "- Only a qualified healthcare professional can determine what is happening here.\n"
        "- A speech-language pathologist is usually the professional who assesses this."
    ),
    "When Professional Evaluation May Help": "\n".join(
        f"- When situation number {i} has been going on for some time for a family." for i in range(1, 5)
    ),
}

DEFAULT_FRONT_MATTER = """schema_version: "1.0.0"
content_type: concern_knowledge
concern_id: {concern_id}
concern_uid: concerns/{category}/{concern_id}
title: {title}
status: published

category: {category}
topic: sample topic
development_domains:
  - speech_language

primary_intents:
  - personal_concern
common_emotional_states:
  - worried
age_groups:
  - toddler_1_3y
family_perspectives:
  - parent
keywords: [alpha, beta, gamma, delta, epsilon, zeta, eta, theta]
search_terms:
  - my child is not speaking
  - toddler not talking at two years
  - child not saying any words yet
  - my son is a late talker
  - when should a child start talking

related_concerns: []
related_conditions: []
related_therapies: []
cta_mapping: []

professional_boundary_required: true
escalation_sensitive: false
clinical_review_status: reviewed
clinical_reviewer: "Test Reviewer"
content_version: "1.0.0"
last_updated: 2026-07-28
authors:
  - "Test Author"
"""


def build_concern_text(
    *,
    concern_id="sample_concern",
    category="communication",
    title="Sample Concern",
    front_matter=None,
    front_matter_extra="",
    sections=None,
    omit_sections=(),
    section_order=None,
    include_front_matter=True,
    body_prefix="",
) -> str:
    merged = dict(DEFAULT_SECTIONS)
    merged.update(sections or {})
    order = section_order or [name for name, _ in REQUIRED_SECTIONS]

    parts = []
    if include_front_matter:
        fm = front_matter if front_matter is not None else DEFAULT_FRONT_MATTER.format(
            concern_id=concern_id, category=category, title=title
        )
        parts.append("---\n" + fm + front_matter_extra + "\n---")
    parts.append(f"# {title}")
    if body_prefix:
        parts.append(body_prefix)
    for name in order:
        if name in omit_sections or name not in merged:
            continue
        parts.append(f"## {name}\n\n{merged[name]}")
    return "\n\n".join(parts) + "\n"


def write_corpus(tmp_path, files: "dict[str, str]") -> Path:
    """files maps 'category/name.md' -> file text. Returns the concerns dir to scan."""
    base = tmp_path / "concerns"
    for relative, text in files.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    base.mkdir(parents=True, exist_ok=True)
    return base


def load_one(tmp_path, text, relative="communication/sample_concern.md"):
    base = write_corpus(tmp_path, {relative: text})
    return load_concern_data(base_dir=base)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_file_loads_with_all_sections(tmp_path):
    result = load_one(tmp_path, build_concern_text())
    assert result.files_loaded == 1
    assert result.issues == []
    record = result.records[0]
    assert record.concern_id == "sample_concern"
    assert record.concern_uid == "concerns/communication/sample_concern"
    assert record.category == "communication"
    assert set(record.sections) == {key for _, key in REQUIRED_SECTIONS}
    assert len(record.section_bullets("possible_explanations")) == 6
    assert record.source_path == "communication/sample_concern.md"


def test_multi_line_bullets_are_joined(tmp_path):
    sections = {
        "Possible Explanations": (
            "- Some children may take longer to reach this point,\n"
            "  and that difference alone tells a family very little.\n"
            "- Another explanation may apply for some children in some cases here.\n"
            "- A third explanation can sometimes apply to children of this age.\n"
            "- A fourth explanation may sometimes apply in ordinary development.\n"
            "- A fifth explanation can apply for some children learning to talk.\n"
            "- A sixth explanation may apply when other things are also going on."
        )
    }
    result = load_one(tmp_path, build_concern_text(sections=sections))
    bullets = result.records[0].section_bullets("possible_explanations")
    assert bullets[0].endswith("tells a family very little.")
    assert "\n" not in bullets[0]
    assert len(bullets) == 6


def test_summary_is_prose_and_needs_no_bullets(tmp_path):
    record = load_one(tmp_path, build_concern_text()).records[0]
    assert record.sections["summary"].bullets == []
    assert record.section_text("summary").startswith("Speech delay describes")


def test_not_applicable_sentinel_is_recognized(tmp_path):
    sections = {"Everyday Support Ideas": "- Not applicable for this concern."}
    record = load_one(tmp_path, build_concern_text(sections=sections)).records[0]
    assert record.sections["everyday_support_ideas"].is_not_applicable()
    assert record.section_bullets("everyday_support_ideas") == []


# ---------------------------------------------------------------------------
# Parse errors -- one per reason code
# ---------------------------------------------------------------------------


def _reason(result) -> str:
    assert result.files_loaded == 0, "expected the file to be skipped"
    return result.issues[0].reason


def test_missing_front_matter_is_skipped(tmp_path):
    assert _reason(load_one(tmp_path, build_concern_text(include_front_matter=False))) == "missing_front_matter"


def test_unclosed_front_matter_is_skipped(tmp_path):
    text = "---\nconcern_id: sample_concern\n\n# Sample Concern\n"
    assert _reason(load_one(tmp_path, text)) == "missing_front_matter"


def test_invalid_yaml_is_skipped(tmp_path):
    assert _reason(load_one(tmp_path, build_concern_text(front_matter="key: [unclosed\n"))) == "invalid_yaml"


def test_missing_required_field_is_skipped(tmp_path):
    fm = DEFAULT_FRONT_MATTER.format(concern_id="sample_concern", category="communication", title="Sample Concern")
    fm = "\n".join(line for line in fm.splitlines() if not line.startswith("topic:"))
    assert _reason(load_one(tmp_path, build_concern_text(front_matter=fm))) == "missing_required_field"


def test_unknown_front_matter_key_is_rejected(tmp_path):
    result = load_one(tmp_path, build_concern_text(front_matter_extra="\nfavourite_colour: blue\n"))
    assert _reason(result) == "unknown_field"


def test_concern_id_must_match_filename(tmp_path):
    result = load_one(tmp_path, build_concern_text(concern_id="other_id"))
    assert _reason(result) == "id_filename_mismatch"


def test_title_must_match_h1(tmp_path):
    fm = DEFAULT_FRONT_MATTER.format(concern_id="sample_concern", category="communication", title="Different Title")
    assert _reason(load_one(tmp_path, build_concern_text(front_matter=fm))) == "title_h1_mismatch"


def test_category_must_match_directory(tmp_path):
    result = load_one(tmp_path, build_concern_text(category="sensory"))
    assert _reason(result) == "category_dir_mismatch"


def test_concern_uid_must_be_path_qualified(tmp_path):
    fm = DEFAULT_FRONT_MATTER.format(concern_id="sample_concern", category="communication", title="Sample Concern")
    fm = fm.replace("concerns/communication/sample_concern", "communication/sample_concern")
    assert _reason(load_one(tmp_path, build_concern_text(front_matter=fm))) == "uid_mismatch"


def test_unsupported_schema_major_is_skipped(tmp_path):
    fm = DEFAULT_FRONT_MATTER.format(concern_id="sample_concern", category="communication", title="Sample Concern")
    fm = fm.replace('schema_version: "1.0.0"', 'schema_version: "2.0.0"')
    assert _reason(load_one(tmp_path, build_concern_text(front_matter=fm))) == "unsupported_schema_version"


def test_invalid_vocabulary_value_is_skipped(tmp_path):
    fm = DEFAULT_FRONT_MATTER.format(concern_id="sample_concern", category="communication", title="Sample Concern")
    fm = fm.replace("  - speech_language", "  - telepathy")
    assert _reason(load_one(tmp_path, build_concern_text(front_matter=fm))) == "invalid_vocabulary_value"


def test_missing_required_section_is_skipped(tmp_path):
    result = load_one(tmp_path, build_concern_text(omit_sections=("Professional Boundary",)))
    assert _reason(result) == "missing_required_section"


def test_empty_required_section_is_skipped(tmp_path):
    result = load_one(tmp_path, build_concern_text(sections={"Things to Observe": ""}))
    assert _reason(result) == "empty_section"


def test_unknown_section_is_rejected(tmp_path):
    order = [name for name, _ in REQUIRED_SECTIONS] + ["Random Extra Section"]
    text = build_concern_text(sections={"Random Extra Section": "- Something."}, section_order=order)
    assert _reason(load_one(tmp_path, text)) == "unknown_section"


def test_sections_out_of_order_are_rejected(tmp_path):
    order = [name for name, _ in REQUIRED_SECTIONS]
    order[0], order[1] = order[1], order[0]
    assert _reason(load_one(tmp_path, build_concern_text(section_order=order))) == "section_order"


def test_deeper_headings_are_rejected(tmp_path):
    text = build_concern_text(body_prefix="### A Subheading")
    assert _reason(load_one(tmp_path, text)) == "invalid_heading"


def test_missing_h1_is_skipped(tmp_path):
    text = build_concern_text().replace("# Sample Concern\n", "Sample Concern\n", 1)
    assert _reason(load_one(tmp_path, text)) == "missing_title"


def test_duplicate_concern_id_skips_the_second_file(tmp_path):
    text_a = build_concern_text(concern_id="duplicate_id", category="communication", title="Duplicate Id")
    text_b = build_concern_text(concern_id="duplicate_id", category="social", title="Duplicate Id")
    text_b = text_b.replace("concerns/social/duplicate_id", "concerns/social/duplicate_id")
    base = write_corpus(
        tmp_path,
        {"communication/duplicate_id.md": text_a, "social/duplicate_id.md": text_b},
    )
    result = load_concern_data(base_dir=base)
    assert result.files_loaded == 1
    assert result.issues[0].reason == "duplicate_concern_id"


def test_loader_never_raises_on_unreadable_file(tmp_path):
    base = write_corpus(tmp_path, {"communication/sample_concern.md": build_concern_text()})
    (base / "communication" / "broken.md").write_bytes(b"\xff\xfe\x00binary garbage")
    result = load_concern_data(base_dir=base)
    assert result.files_loaded == 1
    assert any(issue.reason in {"file_read_error", "missing_front_matter"} for issue in result.issues)


# ---------------------------------------------------------------------------
# Scan behaviour
# ---------------------------------------------------------------------------


def test_underscore_directories_are_not_scanned(tmp_path):
    base = write_corpus(tmp_path, {"communication/sample_concern.md": build_concern_text()})
    template_dir = base / "_templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "concern.template.md").write_text("---\nnot: a concern\n---\n", encoding="utf-8")
    result = load_concern_data(base_dir=base)
    assert result.files_scanned == 1
    assert result.issues == []


def test_missing_base_dir_reports_an_issue_and_does_not_raise(tmp_path):
    result = load_concern_data(base_dir=tmp_path / "nope")
    assert result.records == []
    assert result.issues[0].reason == "base_dir_missing"


def test_explicit_base_dir_does_not_touch_the_module_cache(tmp_path):
    before = {record.concern_id for record in load_concern_data().records}
    load_concern_data(base_dir=write_corpus(tmp_path, {"communication/sample_concern.md": build_concern_text()}))
    after = {record.concern_id for record in load_concern_data().records}
    assert before == after
    assert "sample_concern" not in after


def test_only_published_and_reviewed_records_are_ingestable(tmp_path):
    fm = DEFAULT_FRONT_MATTER.format(concern_id="sample_concern", category="communication", title="Sample Concern")
    draft = fm.replace("status: published", "status: draft")
    result = load_one(tmp_path, build_concern_text(front_matter=draft))
    assert result.files_loaded == 1
    assert result.records[0].is_ingestable() is False


# ---------------------------------------------------------------------------
# The real corpus
# ---------------------------------------------------------------------------


def test_real_corpus_loads_cleanly():
    result = load_concern_data()
    assert result.files_loaded >= 6
    assert result.issues == []


def test_real_corpus_records_are_all_ingestable():
    published = get_published_concerns()
    assert {record.concern_id for record in published} >= {
        "speech_delay", "not_responding_to_name", "avoids_eye_contact",
        "daily_tantrums", "hyperactivity", "distressed_by_loud_sounds",
    }


def test_get_concern_by_id_returns_none_for_unknown_id():
    assert get_concern_by_id("no_such_concern_exists") is None
    assert get_concern_by_id("speech_delay") is not None
