import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import app.services.cta_loader as cta_loader  # noqa: E402
from app.config import settings  # noqa: E402
from app.services.cta_loader import (  # noqa: E402
    REQUIRED_LABELS,
    get_all_ctas,
    get_cta_by_id,
    get_ctas_by_category,
    get_ctas_by_status,
    load_cta_data,
    reload_cta_data,
)

# ---------------------------------------------------------------------------
# Fixture builder -- assembles a syntactically-valid minimal CTA file from a
# base template, with individual sections overridable/removable per test.
# ---------------------------------------------------------------------------


def _build_cta_text(
    *,
    title="Sample CTA",
    status="Active",
    category="Therapy",
    cta_type="Individual Therapy",
    priority="Specific Therapy",
    match_rule="Display this CTA ONLY when:\n- Category = Therapy\n- Specific Therapy = Sample",
    exclusion=None,
    description="Display this CTA when discussing the Sample therapy.",
    trigger_examples="## Learning About Sample\n- What is Sample?\n- Tell me about Sample.",
    trigger_label="Trigger Examples",
    aliases=None,
    related_topics=None,
    do_not_trigger="- What therapies are available?\n- Tell me about therapies.",
    do_not_trigger_label="Do NOT Trigger",
    fallback_rule="If the Understanding Node cannot confidently identify Sample, do not display this CTA.",
    output_label="Learn More About Sample",
    cta_url="https://manascience.webflow.io/post/sample",
    omit=(),
) -> str:
    parts = [f"# {title}"]
    if "Status" not in omit:
        parts.append(f"Status: {status}")
    if "Category" not in omit:
        parts.append(f"Category: {category}")
    if "CTA Type" not in omit:
        parts.append(f"CTA Type: {cta_type}")
    if "Priority" not in omit:
        parts.append(f"Priority: {priority}")
    if "Match Rule" not in omit:
        parts.append(f"Match Rule:\n{match_rule}")
    if exclusion is not None and "Do NOT display this CTA if" not in omit:
        parts.append(f"Do NOT display this CTA if:\n{exclusion}")
    if "Description" not in omit:
        parts.append(f"Description:\n\n{description}")
    if "Trigger Examples" not in omit:
        parts.append(f"{trigger_label}:\n\n{trigger_examples}")
    if aliases is not None and "Aliases" not in omit:
        parts.append(f"Aliases:\n{aliases}")
    if related_topics is not None and "Related Topics" not in omit:
        parts.append(f"Related Topics:\n{related_topics}")
    if "Do NOT Trigger" not in omit:
        parts.append(f"{do_not_trigger_label}:\n\n{do_not_trigger}")
    if "Fallback Rule" not in omit:
        parts.append(f"Fallback Rule:\n\n{fallback_rule}")
    if "Output Label" not in omit:
        parts.append(f"Output Label:\n\n{output_label}")
    if "CTA" not in omit:
        parts.append(f"CTA:\n\n{cta_url}")
    return "\n\n".join(parts) + "\n"


def _write_cta(dir_: Path, name: str, **kwargs) -> Path:
    path = dir_ / name
    path.write_text(_build_cta_text(**kwargs), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Happy-path and optional-section tests
# ---------------------------------------------------------------------------


def test_loads_well_formed_minimal_file(tmp_path):
    _write_cta(tmp_path, "sample.md")
    result = load_cta_data(base_dir=tmp_path)
    assert result.files_scanned == 1
    assert result.files_loaded == 1
    assert result.issues == []
    record = result.records[0]
    assert record.cta_id == "sample"
    assert record.exclusion_conditions == []
    assert record.aliases == []
    assert record.related_topics == []


def test_loads_file_with_all_optional_sections_present(tmp_path):
    _write_cta(
        tmp_path,
        "full.md",
        exclusion="- Specific Therapy = None\n- Confidence is Low.",
        aliases="- Sample Therapy\n- Sample Treatment",
        related_topics="- Brain Health\n- Learning",
    )
    result = load_cta_data(base_dir=tmp_path)
    assert result.issues == []
    record = result.records[0]
    assert record.exclusion_conditions == ["Specific Therapy = None", "Confidence is Low."]
    assert record.aliases == ["Sample Therapy", "Sample Treatment"]
    assert record.related_topics == ["Brain Health", "Learning"]


# ---------------------------------------------------------------------------
# Required-field rejection tests
# ---------------------------------------------------------------------------


def test_rejects_file_missing_required_field(tmp_path):
    _write_cta(tmp_path, "control.md")
    for label in REQUIRED_LABELS:
        _write_cta(tmp_path, f"missing_{label.replace(' ', '_')}.md", omit=(label,))

    result = load_cta_data(base_dir=tmp_path)

    assert result.files_scanned == len(REQUIRED_LABELS) + 1
    assert result.files_loaded == 1
    assert result.files_skipped == len(REQUIRED_LABELS)
    assert len(result.issues) == len(REQUIRED_LABELS)
    assert all(issue.reason == "missing_required_field" for issue in result.issues)
    assert result.records[0].source_path == "control.md"


def test_rejects_file_with_invalid_cta_url(tmp_path):
    _write_cta(tmp_path, "bad_url.md", cta_url="not-a-url")
    result = load_cta_data(base_dir=tmp_path)
    assert result.files_loaded == 0
    assert result.issues[0].reason == "invalid_cta_url"


def test_rejects_file_with_no_title(tmp_path):
    (tmp_path / "no_title.md").write_text("Status: Active\n\nCategory: Therapy\n", encoding="utf-8")
    result = load_cta_data(base_dir=tmp_path)
    assert result.files_loaded == 0
    assert result.issues[0].reason == "missing_title"


def test_rejects_file_with_zero_trigger_examples(tmp_path):
    _write_cta(tmp_path, "no_examples.md", trigger_examples="")
    result = load_cta_data(base_dir=tmp_path)
    assert result.files_loaded == 0
    assert result.issues[0].reason == "no_trigger_examples"


# ---------------------------------------------------------------------------
# Match Rule preamble handling
# ---------------------------------------------------------------------------


def test_match_rule_without_preamble_parses_bullets(tmp_path):
    _write_cta(tmp_path, "no_preamble.md", match_rule="- Category = Therapy\n- Specific Therapy = None")
    record = load_cta_data(base_dir=tmp_path).records[0]
    assert record.match_conditions == ["Category = Therapy", "Specific Therapy = None"]


def test_match_rule_with_preamble_strips_preamble_line(tmp_path):
    _write_cta(tmp_path, "with_preamble.md")  # default match_rule includes the preamble line
    record = load_cta_data(base_dir=tmp_path).records[0]
    assert "Display this CTA ONLY when:" not in record.match_conditions
    assert record.match_conditions == ["Category = Therapy", "Specific Therapy = Sample"]


# ---------------------------------------------------------------------------
# Grouped-bullet fields: Trigger Examples / Aliases
# ---------------------------------------------------------------------------


def test_grouped_trigger_examples_flatten_correctly(tmp_path):
    trigger = (
        "## Group A\n- Phrase one\n- Phrase two\n\n"
        "## Group B\n- Phrase three\n- Phrase one"
    )
    _write_cta(tmp_path, "grouped.md", trigger_examples=trigger)
    record = load_cta_data(base_dir=tmp_path).records[0]
    assert record.trigger_examples == ["Phrase one", "Phrase two", "Phrase three"]
    assert record.trigger_groups == {
        "Group A": ["Phrase one", "Phrase two"],
        "Group B": ["Phrase three", "Phrase one"],
    }


def test_flat_aliases_parse_without_groups(tmp_path):
    _write_cta(tmp_path, "flat_aliases.md", aliases="- Alias One\n- Alias Two")
    record = load_cta_data(base_dir=tmp_path).records[0]
    assert record.aliases == ["Alias One", "Alias Two"]


def test_grouped_aliases_parse_like_mnri(tmp_path):
    aliases = "## Alternate Names\n- Alt One\n- Alt Two\n\n## Common Misspellings\n- Misspell One"
    _write_cta(tmp_path, "grouped_aliases.md", aliases=aliases)
    record = load_cta_data(base_dir=tmp_path).records[0]
    assert record.aliases == ["Alt One", "Alt Two", "Misspell One"]


# ---------------------------------------------------------------------------
# The irregular fields: Do NOT Trigger / Fallback Rule
# ---------------------------------------------------------------------------


def test_do_not_trigger_with_named_subgroups_flattens_bullets(tmp_path):
    do_not_trigger = (
        "General questions:\n\n- What therapies exist?\n- Tell me about therapies.\n\n"
        "Other specific therapies:\n\n- MNRI\n- Arrowsmith"
    )
    _write_cta(tmp_path, "subgrouped.md", do_not_trigger=do_not_trigger)
    record = load_cta_data(base_dir=tmp_path).records[0]
    assert record.do_not_trigger_examples == [
        "What therapies exist?", "Tell me about therapies.", "MNRI", "Arrowsmith",
    ]
    assert "General questions:" in record.do_not_trigger_raw
    assert "Other specific therapies:" in record.do_not_trigger_raw


def test_duplicate_do_not_trigger_headings_are_merged(tmp_path):
    text = (
        "# Dup Heading CTA\n\n"
        "Status: Active\n\n"
        "Category: Therapy\n\n"
        "CTA Type: Library\n\n"
        "Priority: General\n\n"
        "Match Rule:\n- Category = Therapy\n\n"
        "Description:\n\nSample description.\n\n"
        "Trigger Examples:\n\n## Group\n- Sample trigger\n\n"
        "Do NOT Trigger:\n\n- First bullet\n\n"
        "Do NOT Trigger for:\n\n- Second bullet\n\n"
        "Fallback Rule:\n\nIf unsure, do not display.\n\n"
        "Output Label:\n\nSample Label\n\n"
        "CTA:\n\nhttps://example.com/sample\n"
    )
    (tmp_path / "dup_heading.md").write_text(text, encoding="utf-8")
    result = load_cta_data(base_dir=tmp_path)
    assert result.issues == []
    record = result.records[0]
    assert record.do_not_trigger_examples == ["First bullet", "Second bullet"]


def test_fallback_rule_prose_only(tmp_path):
    _write_cta(tmp_path, "prose_fallback.md", fallback_rule="If unsure, do not display this CTA.")
    record = load_cta_data(base_dir=tmp_path).records[0]
    assert record.fallback_rule == "If unsure, do not display this CTA."


def test_fallback_rule_with_instead_label_and_bullets(tmp_path):
    fallback = (
        "If the Understanding Node cannot confidently identify Sample,\n\n"
        "DO NOT display this CTA.\n\n"
        "Instead:\n\n"
        "- If general, display the Library CTA.\n"
        "- Otherwise, do not display any CTA."
    )
    _write_cta(tmp_path, "instead_fallback.md", fallback_rule=fallback)
    record = load_cta_data(base_dir=tmp_path).records[0]
    assert "Instead:" in record.fallback_rule
    assert "If general, display the Library CTA." in record.fallback_rule


# ---------------------------------------------------------------------------
# Forward-compatibility: unrecognized scalar lines
# ---------------------------------------------------------------------------


def test_unrecognized_scalar_field_captured_in_extra_fields(tmp_path):
    """Per spec Section 8.8, a genuinely new top-level label is NOT detected as
    a section boundary -- it is absorbed as plain text into whichever known
    section precedes it. Real structured capture into `extra_fields` is
    explicitly deferred to a future parser revision (spec Section 8.8/17);
    today `extra_fields` is always {} and the stray line just becomes part of
    the preceding section's joined text. This test documents that actual,
    current behavior rather than a capture mechanism that doesn't exist yet."""
    text = _build_cta_text(description="Sample description.\n\nLocale: en-US")
    (tmp_path / "extra_field.md").write_text(text, encoding="utf-8")
    result = load_cta_data(base_dir=tmp_path)
    assert result.issues == []
    record = result.records[0]
    assert record.extra_fields == {}
    assert "Locale: en-US" in record.description


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_recursive_discovery_finds_nested_files(tmp_path):
    _write_cta(tmp_path, "top.md")
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    _write_cta(nested, "deep.md")
    result = load_cta_data(base_dir=tmp_path)
    assert result.files_scanned == 2
    assert {r.cta_id for r in result.records} == {"top", "a/b/c/deep"}


def test_non_markdown_files_ignored(tmp_path):
    _write_cta(tmp_path, "real.md")
    (tmp_path / "notes.txt").write_text("not a CTA file", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    result = load_cta_data(base_dir=tmp_path)
    assert result.files_scanned == 1
    assert result.files_loaded == 1


def test_missing_base_directory_returns_empty_result_no_raise(tmp_path):
    result = load_cta_data(base_dir=tmp_path / "does_not_exist")
    assert result.records == []
    assert result.files_scanned == 0
    assert len(result.issues) == 1
    assert result.issues[0].reason == "base_dir_missing"


def test_empty_base_directory_returns_empty_result_no_raise(tmp_path):
    result = load_cta_data(base_dir=tmp_path)
    assert result.records == []
    assert result.files_scanned == 0
    assert result.issues == []


# ---------------------------------------------------------------------------
# Duplicate cta_id defensive handling
# ---------------------------------------------------------------------------


def test_duplicate_cta_id_keeps_first_sorted_occurrence(tmp_path, monkeypatch):
    _write_cta(tmp_path, "a_first.md")
    _write_cta(tmp_path, "b_second.md")

    real_parse = cta_loader._parse_cta_file

    def fake_parse(path, base_dir):
        record = real_parse(path, base_dir)
        return record.model_copy(update={"cta_id": "shared_id"})

    monkeypatch.setattr(cta_loader, "_parse_cta_file", fake_parse)
    result = load_cta_data(base_dir=tmp_path)

    assert result.files_loaded == 1
    assert result.records[0].source_path == "a_first.md"
    assert len(result.issues) == 1
    assert result.issues[0].reason == "duplicate_cta_id"
    assert result.issues[0].source_path == "b_second.md"


# ---------------------------------------------------------------------------
# Public accessor functions
# ---------------------------------------------------------------------------


def test_get_cta_by_id_returns_none_for_unknown_id(tmp_path, monkeypatch):
    _write_cta(tmp_path, "real.md")
    monkeypatch.setattr(settings, "cta_data_dir", tmp_path)
    reload_cta_data()
    assert get_cta_by_id("does/not/exist") is None


def test_get_ctas_by_category_and_status_filter_correctly(tmp_path, monkeypatch):
    _write_cta(tmp_path, "active_therapy.md", category="Therapy", status="Active")
    _write_cta(tmp_path, "active_condition.md", category="Condition", status="Active")
    _write_cta(tmp_path, "draft_therapy.md", category="Therapy", status="Draft")
    monkeypatch.setattr(settings, "cta_data_dir", tmp_path)
    reload_cta_data()

    therapy = get_ctas_by_category("Therapy")
    assert {r.source_path for r in therapy} == {"active_therapy.md", "draft_therapy.md"}

    active = get_ctas_by_status("Active")
    assert {r.source_path for r in active} == {"active_therapy.md", "active_condition.md"}

    assert get_ctas_by_category("Nonexistent") == []
    assert get_ctas_by_status("Inactive") == []


def test_reload_picks_up_on_disk_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "cta_data_dir", tmp_path)
    _write_cta(tmp_path, "sample.md", output_label="Original Label")
    reload_cta_data()
    assert get_cta_by_id("sample").output_label == "Original Label"

    _write_cta(tmp_path, "sample.md", output_label="Updated Label")
    assert get_cta_by_id("sample").output_label == "Original Label"  # cache not yet refreshed

    reload_cta_data()
    assert get_cta_by_id("sample").output_label == "Updated Label"


def test_accessor_results_are_defensive_copies(tmp_path, monkeypatch):
    _write_cta(tmp_path, "sample.md")
    monkeypatch.setattr(settings, "cta_data_dir", tmp_path)
    reload_cta_data()

    records = get_all_ctas()
    original_count = len(records)
    records.append(records[0])
    assert len(get_all_ctas()) == original_count


# ---------------------------------------------------------------------------
# Regression guard against the real corpus
# ---------------------------------------------------------------------------


def test_real_cta_corpus_loads_with_zero_issues():
    result = load_cta_data(base_dir=settings.cta_data_dir, force_reload=True)
    expected = len(list(settings.cta_data_dir.rglob("*.md")))
    assert result.files_scanned == expected
    assert result.issues == []
    assert result.files_loaded == expected
