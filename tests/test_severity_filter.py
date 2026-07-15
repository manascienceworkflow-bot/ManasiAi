import copy
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.roadmap.models import RoadmapDomainScore, RoadmapResult  # noqa: E402
from app.roadmap.roadmap_loader import RoadmapValidationError  # noqa: E402
from app.roadmap.severity_filter import MAX_DOMAINS, filter_by_severity  # noqa: E402


def _result(*entries, user_id="u_test", classification="ND"):
    """Build a RoadmapResult directly. Step 2's input is the LOADER'S OUTPUT, so
    these tests construct that object rather than raw wire JSON -- the filter
    never sees the wire format."""
    return RoadmapResult(
        user_id=user_id,
        classification_raw="neurodivergent" if classification == "ND" else "neurotypical",
        classification=classification,
        scores=[RoadmapDomainScore(**e) for e in entries],
        raw={},
    )


def _entry(domain, severity, score=50):
    return {"domain": domain, "score": score, "severity": severity}


def _domains(filtered):
    return [s.domain for s in filtered.filtered_scores]


def _severities(filtered):
    return [s.severity for s in filtered.filtered_scores]


# --------------------------------------------------------------------------
# Core filtering
# --------------------------------------------------------------------------


def test_worked_example_from_the_spec():
    """High, Moderate, Low, High, Low -> High, Moderate, High. Nothing else."""
    out = filter_by_severity(
        _result(
            _entry("Attention", "High"),
            _entry("Memory", "Moderate"),
            _entry("Executive", "Low"),
            _entry("Language", "High"),
            _entry("Motor", "Low"),
        )
    )
    assert _severities(out) == ["High", "Moderate", "High"]
    assert _domains(out) == ["Attention", "Memory", "Language"]
    assert out.diagnostics.dropped_low == 2
    assert out.diagnostics.total_kept == 3


def test_single_high_domain_is_kept():
    out = filter_by_severity(_result(_entry("Attention", "High")))
    assert _domains(out) == ["Attention"]


def test_single_moderate_domain_is_kept():
    out = filter_by_severity(_result(_entry("Attention", "Moderate")))
    assert _domains(out) == ["Attention"]


def test_single_low_domain_is_dropped_without_error():
    out = filter_by_severity(_result(_entry("Attention", "Low")))
    assert out.filtered_scores == []
    assert out.is_empty is True
    assert out.dropped[0].reason == "low_severity"


def test_all_high_all_kept_in_input_order():
    out = filter_by_severity(
        _result(_entry("A", "High"), _entry("B", "High"), _entry("C", "High"))
    )
    assert _domains(out) == ["A", "B", "C"]
    assert out.dropped == []


def test_all_low_yields_empty_actionable_set_not_an_error():
    out = filter_by_severity(
        _result(_entry("A", "Low"), _entry("B", "Low"), _entry("C", "Low"))
    )
    assert out.is_empty is True
    assert out.diagnostics.dropped_low == 3
    assert out.diagnostics.warnings == []


def test_survivors_keep_input_order_and_are_not_sorted_by_rank():
    """Moderate arrives before High; the output must NOT re-rank them."""
    out = filter_by_severity(
        _result(_entry("A", "Moderate"), _entry("B", "High"), _entry("C", "Moderate"))
    )
    assert _domains(out) == ["A", "B", "C"]


# --------------------------------------------------------------------------
# Case / whitespace / unicode
# --------------------------------------------------------------------------


@pytest.mark.parametrize("severity", ["High", "HIGH", "high", "HiGh", "hIGH"])
def test_high_is_case_insensitive(severity):
    out = filter_by_severity(_result(_entry("A", severity)))
    assert _domains(out) == ["A"]


@pytest.mark.parametrize("severity", ["Moderate", "MODERATE", "moderate", "MoDeRaTe"])
def test_moderate_is_case_insensitive(severity):
    out = filter_by_severity(_result(_entry("A", severity)))
    assert _domains(out) == ["A"]


@pytest.mark.parametrize("severity", ["Low", "LOW", "low", "LoW"])
def test_low_is_case_insensitive_and_always_dropped(severity):
    out = filter_by_severity(_result(_entry("A", severity)))
    assert out.filtered_scores == []
    assert out.dropped[0].reason == "low_severity"


@pytest.mark.parametrize(
    "severity", [" High ", "High\n", "\tHigh", "High ", "\r\nHigh \t", "  HIGH  "]
)
def test_whitespace_around_severity_is_ignored(severity):
    out = filter_by_severity(_result(_entry("A", severity)))
    assert _domains(out) == ["A"]


def test_fullwidth_high_is_normalized_by_nfkc():
    out = filter_by_severity(_result(_entry("A", "Ｈｉｇｈ")))  # "High"
    assert _domains(out) == ["A"]


def test_fullwidth_moderate_is_normalized_by_nfkc():
    fullwidth = "ＭＯＤＥＲＡＴＥ"  # "MODERATE"
    out = filter_by_severity(_result(_entry("A", fullwidth)))
    assert _domains(out) == ["A"]


def test_original_severity_casing_is_preserved_alongside_the_normalized_key():
    out = filter_by_severity(_result(_entry("A", "  HIGH  ")))
    kept = out.filtered_scores[0]
    assert kept.severity == "  HIGH  "  # verbatim
    assert kept.severity_key == "high"  # normalized
    assert kept.severity_rank == 3


# --------------------------------------------------------------------------
# Missing / null / unknown severity
# --------------------------------------------------------------------------


def test_none_severity_is_dropped_and_warned():
    out = filter_by_severity(_result(_entry("A", None)))
    assert out.filtered_scores == []
    assert out.dropped[0].reason == "missing_severity"
    assert len(out.diagnostics.warnings) == 1
    assert "A" in out.diagnostics.warnings[0]


@pytest.mark.parametrize("severity", ["", "   ", "\t\n", " "])
def test_blank_severity_is_treated_as_missing(severity):
    out = filter_by_severity(_result(_entry("A", severity)))
    assert out.dropped[0].reason == "missing_severity"
    assert out.diagnostics.dropped_missing_severity == 1


@pytest.mark.parametrize(
    "severity",
    ["Severe", "Borderline", "Hgh", "N/A", "-", "3", "null", "elevated", "Hi gh"],
)
def test_unknown_severity_is_dropped_and_warned(severity):
    out = filter_by_severity(_result(_entry("A", severity)))
    assert out.filtered_scores == []
    assert out.dropped[0].reason == "unknown_severity"
    assert out.diagnostics.dropped_unknown_severity == 1
    assert len(out.diagnostics.warnings) == 1


def test_strict_mode_raises_on_unknown_severity():
    with pytest.raises(RoadmapValidationError) as exc:
        filter_by_severity(_result(_entry("A", "Severe")), strict=True)
    assert exc.value.code == "unknown_severity"
    assert exc.value.field == "score[0].Severity"


def test_strict_mode_raises_on_missing_severity():
    with pytest.raises(RoadmapValidationError) as exc:
        filter_by_severity(_result(_entry("A", None)), strict=True)
    assert exc.value.code == "missing_severity"


def test_default_mode_does_not_raise_on_unknown_severity():
    out = filter_by_severity(_result(_entry("A", "Severe"), _entry("B", "High")))
    assert _domains(out) == ["B"]  # the good domain still survives


def test_a_high_score_with_a_typod_severity_is_dropped_not_promoted():
    """The filter NEVER infers severity from the numeric score, even when the
    score obviously implies one. Inferring would be the backend recomputing
    severity -- a rule violation and a patient-safety hazard."""
    out = filter_by_severity(_result(_entry("A", "Hgh", score=95)))
    assert out.filtered_scores == []
    assert out.dropped[0].reason == "unknown_severity"


# --------------------------------------------------------------------------
# Duplicates
# --------------------------------------------------------------------------


def test_duplicate_domain_keeps_the_higher_severity():
    out = filter_by_severity(
        _result(_entry("Attention", "High", 72), _entry("Attention", "Low", 40))
    )
    assert len(out.filtered_scores) == 1
    assert out.filtered_scores[0].severity == "High"


def test_duplicate_resolution_is_order_independent():
    """The Low arrives FIRST here. The High must still win -- otherwise a payload
    reordering could silently drop a High domain out of a clinical roadmap."""
    out = filter_by_severity(
        _result(_entry("Attention", "Low", 40), _entry("Attention", "High", 72))
    )
    assert len(out.filtered_scores) == 1
    assert out.filtered_scores[0].severity == "High"
    assert out.filtered_scores[0].score == 72


def test_moderate_loses_to_high_regardless_of_order():
    forward = filter_by_severity(
        _result(_entry("A", "Moderate"), _entry("A", "High"))
    )
    backward = filter_by_severity(
        _result(_entry("A", "High"), _entry("A", "Moderate"))
    )
    assert forward.filtered_scores[0].severity_key == "high"
    assert backward.filtered_scores[0].severity_key == "high"


def test_byte_identical_duplicates_collapse_to_one():
    out = filter_by_severity(
        _result(_entry("Attention", "High", 72), _entry("Attention", "High", 72))
    )
    assert len(out.filtered_scores) == 1
    assert out.diagnostics.dropped_duplicate == 1


def test_duplicate_domains_differing_only_in_case_or_whitespace_are_one_domain():
    out = filter_by_severity(
        _result(
            _entry("Attention", "High"),
            _entry("attention", "Moderate"),
            _entry("  ATTENTION  ", "Moderate"),
        )
    )
    assert len(out.filtered_scores) == 1
    # First-seen ORIGINAL spelling survives.
    assert out.filtered_scores[0].domain == "Attention"
    assert out.diagnostics.dropped_duplicate == 2


def test_two_low_entries_for_one_domain_are_both_low_drops_not_duplicates():
    out = filter_by_severity(_result(_entry("A", "Low"), _entry("A", "Low")))
    assert out.diagnostics.dropped_low == 2
    assert out.diagnostics.dropped_duplicate == 0


def test_tie_keeps_the_first_occurrence():
    out = filter_by_severity(
        _result(_entry("A", "High", 90), _entry("A", "High", 10))
    )
    assert out.filtered_scores[0].score == 90


def test_distinct_domains_produce_no_duplicate_drops():
    out = filter_by_severity(
        _result(_entry("A", "High"), _entry("B", "High"), _entry("C", "Moderate"))
    )
    assert out.diagnostics.dropped_duplicate == 0


def test_dropped_incumbent_is_recorded_at_its_own_original_index():
    out = filter_by_severity(
        _result(
            _entry("Other", "High"),
            _entry("Attention", "Moderate"),  # index 1 -- the incumbent that loses
            _entry("Attention", "High"),  # index 2 -- the winner
        )
    )
    loser = [d for d in out.dropped if d.reason == "duplicate_domain"][0]
    assert loser.index == 1
    assert loser.severity == "Moderate"


# --------------------------------------------------------------------------
# Immutability and purity -- the highest-value tests here
# --------------------------------------------------------------------------


def test_the_input_roadmap_result_is_never_modified():
    source = _result(
        _entry("A", "High"), _entry("B", "Low"), _entry("C", "Moderate")
    )
    before = copy.deepcopy(source)
    filter_by_severity(source)
    assert source == before


def test_mutating_the_output_cannot_reach_back_into_the_input():
    source = _result(_entry("Attention", "High"))
    out = filter_by_severity(source)
    out.filtered_scores[0].domain = "MUTATED"
    assert source.scores[0].domain == "Attention"


def test_raw_payload_is_never_touched():
    source = _result(_entry("A", "High"))
    source.raw = {"untouched": True}
    raw_before = source.raw
    filter_by_severity(source)
    assert source.raw is raw_before
    assert source.raw == {"untouched": True}


def test_the_input_scores_list_is_not_shortened_in_place():
    source = _result(_entry("A", "High"), _entry("B", "Low"))
    filter_by_severity(source)
    assert len(source.scores) == 2


def test_filtering_is_deterministic():
    source = _result(_entry("A", "High"), _entry("B", "Low"), _entry("A", "Moderate"))
    assert filter_by_severity(source) == filter_by_severity(source)


# --------------------------------------------------------------------------
# Guards, accounting, architecture
# --------------------------------------------------------------------------


def test_payload_over_max_domains_is_rejected():
    entries = [_entry(f"D{i}", "High") for i in range(MAX_DOMAINS + 1)]
    with pytest.raises(RoadmapValidationError) as exc:
        filter_by_severity(_result(*entries))
    assert exc.value.code == "payload_too_large"
    assert exc.value.field == "score"


def test_payload_at_exactly_max_domains_succeeds():
    entries = [_entry(f"D{i}", "High") for i in range(MAX_DOMAINS)]
    out = filter_by_severity(_result(*entries))
    assert out.diagnostics.total_kept == MAX_DOMAINS


@pytest.mark.parametrize("bad", [None, {}, "not a result", 42, []])
def test_non_roadmap_result_input_raises_type_error(bad):
    """A programmer error, not a user error -- so TypeError, never
    RoadmapValidationError (which would surface as a 422 blaming a fine payload)."""
    with pytest.raises(TypeError):
        filter_by_severity(bad)


def test_empty_scores_filters_to_an_empty_result_without_error():
    out = filter_by_severity(_result())
    assert out.filtered_scores == []
    assert out.dropped == []
    assert out.is_empty is True
    assert out.diagnostics.total_received == 0


def test_mixed_anomalies_resolve_independently_and_accounting_holds():
    out = filter_by_severity(
        _result(
            _entry("A", "High"),
            _entry("B", "Low"),
            _entry("C", None),
            _entry("D", "Severe"),
            _entry("A", "Moderate"),  # duplicate of A, loses
        )
    )
    d = out.diagnostics
    assert d.total_received == 5
    assert d.total_kept == 1
    assert d.dropped_low == 1
    assert d.dropped_missing_severity == 1
    assert d.dropped_unknown_severity == 1
    assert d.dropped_duplicate == 1
    assert d.total_kept + d.total_dropped == d.total_received
    assert (
        d.dropped_low
        + d.dropped_missing_severity
        + d.dropped_unknown_severity
        + d.dropped_duplicate
        == d.total_dropped
    )


def test_classification_does_not_influence_which_domains_survive():
    entries = (_entry("A", "High"), _entry("B", "Low"), _entry("C", "Moderate"))
    nd = filter_by_severity(_result(*entries, classification="ND"))
    nt = filter_by_severity(_result(*entries, classification="NT"))
    assert _domains(nd) == _domains(nt) == ["A", "C"]


def test_a_string_percentage_score_survives_verbatim():
    out = filter_by_severity(_result(_entry("A", "High", score="72%")))
    assert out.filtered_scores[0].score == "72%"


def test_domain_type_carried_through_the_filter():
    """The frontend's `domain_type` survives severity filtering verbatim so Step 2
    can echo it -- on both the plain keep path and the dedup-winner path."""
    out = filter_by_severity(
        _result(
            {"domain": "A", "domain_type": "Spine", "score": 50, "severity": "High"},
        )
    )
    assert out.filtered_scores[0].domain_type == "Spine"

    # Dedup: the higher-severity entry wins and carries ITS domain_type.
    deduped = filter_by_severity(
        _result(
            {"domain": "A", "domain_type": "loser", "score": 50, "severity": "Moderate"},
            {"domain": "A", "domain_type": "winner", "score": 90, "severity": "High"},
        )
    )
    assert len(deduped.filtered_scores) == 1
    assert deduped.filtered_scores[0].domain_type == "winner"


def test_module_has_no_framework_or_io_dependencies():
    """The filter must stay pure: no FastAPI, no Supabase, no LLM, no db."""
    source = Path(__file__).resolve().parent.parent / "app" / "roadmap" / "severity_filter.py"
    text = source.read_text()
    for forbidden in ("fastapi", "supabase", "langchain", "openai", "app.db", "requests"):
        assert f"import {forbidden}" not in text
        assert f"from {forbidden}" not in text
