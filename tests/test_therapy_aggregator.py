"""Unit tests for the Therapy Recommendation Aggregation layer.

Pure -- no HTTP, no Excel I/O. Builds `MappedDomainOut` lists directly and asserts
the therapy-centric transpose: one object per unique therapy, domains merged
(unique, first-seen order), relevance collected (unique, first-seen order), and
the defensive skip paths for malformed data.

See .claude/spec/therapy-recommendation-aggregation.md
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.roadmap.serializers import MappedDomainOut, TherapyOut  # noqa: E402
from app.roadmap.therapy_aggregator import (  # noqa: E402
    aggregate_therapies,
    therapy_key,
)


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------


def _t(name, relevance=None):
    return TherapyOut(therapy=name, relevance=relevance)


def _d(domain, therapies):
    return MappedDomainOut(domain=domain, therapies=list(therapies))


def _by_name(result):
    return {a.therapy: a for a in result}


# --------------------------------------------------------------------------
# therapy_key -- canonical identity
# --------------------------------------------------------------------------


def test_therapy_key_case_and_whitespace_insensitive():
    assert therapy_key("MNRI") == therapy_key("mnri") == therapy_key("Mnri")
    assert therapy_key("  MNRI  ") == therapy_key("MNRI")
    assert therapy_key("Speech   Therapy") == therapy_key("speech therapy")


def test_therapy_key_none_for_bad_input():
    assert therapy_key(None) is None
    assert therapy_key(123) is None
    assert therapy_key("") is None
    assert therapy_key("   ") is None


def test_therapy_key_does_not_strip_ordinal_prefix():
    # domain_key strips "B. "; therapy_key must NOT -- a therapy could look ordinal.
    assert therapy_key("B. Something") != therapy_key("Something")


# --------------------------------------------------------------------------
# Happy path -- the spec S2 example
# --------------------------------------------------------------------------


def test_happy_path_merges_therapies_across_domains():
    domains = [
        _d("Sensory Processing", [_t("MNRI", "Primary"), _t("Feldenkrais", "Secondary")]),
        _d("Body Awareness & Skills", [_t("MNRI", "Secondary"), _t("Feldenkrais", "Secondary")]),
        _d("Emotional Regulation", [_t("MNRI", "Primary")]),
        _d("Academic & Learning", [_t("Arrowsmith", "Primary")]),
    ]

    result = aggregate_therapies(domains)

    # One object per unique therapy, in first-appearance order.
    assert [a.therapy for a in result] == ["MNRI", "Feldenkrais", "Arrowsmith"]

    by_name = _by_name(result)
    assert by_name["MNRI"].domains == [
        "Sensory Processing",
        "Body Awareness & Skills",
        "Emotional Regulation",
    ]
    assert by_name["MNRI"].relevance == ["Primary", "Secondary"]
    assert by_name["Feldenkrais"].domains == ["Sensory Processing", "Body Awareness & Skills"]
    assert by_name["Feldenkrais"].relevance == ["Secondary"]
    assert by_name["Arrowsmith"].domains == ["Academic & Learning"]
    assert by_name["Arrowsmith"].relevance == ["Primary"]


# --------------------------------------------------------------------------
# Case-insensitive dedup -- one therapy, first-seen spelling
# --------------------------------------------------------------------------


def test_case_insensitive_dedup_keeps_first_seen_spelling():
    domains = [
        _d("D1", [_t("MNRI", "Primary")]),
        _d("D2", [_t("mnri", "Secondary")]),
        _d("D3", [_t("Mnri", "Primary")]),
    ]

    result = aggregate_therapies(domains)

    assert len(result) == 1
    assert result[0].therapy == "MNRI"  # first-seen spelling, not lowercased key
    assert result[0].domains == ["D1", "D2", "D3"]
    assert result[0].relevance == ["Primary", "Secondary"]


def test_whitespace_only_difference_is_same_therapy():
    result = aggregate_therapies([
        _d("D1", [_t(" MNRI ")]),
        _d("D2", [_t("MNRI")]),
    ])
    assert len(result) == 1
    assert result[0].domains == ["D1", "D2"]


# --------------------------------------------------------------------------
# Relevance rules
# --------------------------------------------------------------------------


def test_relevance_unique_and_first_seen_order():
    domains = [
        _d("D1", [_t("MNRI", "Primary")]),
        _d("D2", [_t("MNRI", "Secondary")]),
        _d("D3", [_t("MNRI", "Complementary")]),
        _d("D4", [_t("MNRI", "Primary")]),  # duplicate -- not re-added
    ]
    assert aggregate_therapies(domains)[0].relevance == [
        "Primary",
        "Secondary",
        "Complementary",
    ]


def test_all_null_relevance_yields_empty_list():
    result = aggregate_therapies([
        _d("D1", [_t("MNRI", None)]),
        _d("D2", [_t("MNRI", "")]),
        _d("D3", [_t("MNRI", "   ")]),
    ])
    assert result[0].relevance == []


def test_unknown_relevance_value_preserved_verbatim():
    result = aggregate_therapies([_d("D1", [_t("MNRI", "SomeCustomLabel")])])
    assert result[0].relevance == ["SomeCustomLabel"]


# --------------------------------------------------------------------------
# Domain rules
# --------------------------------------------------------------------------


def test_same_domain_listed_once_per_therapy():
    # Same domain (case variant) recommending the therapy twice -> listed once.
    result = aggregate_therapies([
        _d("Sensory Processing", [_t("MNRI", "Primary")]),
        _d("sensory   processing", [_t("MNRI", "Secondary")]),
    ])
    assert result[0].domains == ["Sensory Processing"]  # first-seen verbatim
    assert result[0].relevance == ["Primary", "Secondary"]


def test_intra_domain_duplicate_therapy():
    # One domain lists the same therapy twice (EC-3): therapy once, domain once,
    # relevance from both merged.
    result = aggregate_therapies([
        _d("D1", [_t("MNRI", "Primary"), _t("MNRI", "Secondary")]),
    ])
    assert len(result) == 1
    assert result[0].domains == ["D1"]
    assert result[0].relevance == ["Primary", "Secondary"]


def test_therapy_in_ten_plus_domains_no_truncation():
    domains = [_d(f"Domain {i}", [_t("MNRI", "Primary")]) for i in range(12)]
    result = aggregate_therapies(domains)
    assert len(result) == 1
    assert result[0].domains == [f"Domain {i}" for i in range(12)]


# --------------------------------------------------------------------------
# Defensive / malformed inputs -- never raise
# --------------------------------------------------------------------------


def test_empty_input_yields_empty_list():
    assert aggregate_therapies([]) == []
    assert aggregate_therapies(None) == []


def test_domain_present_but_no_therapies():
    result = aggregate_therapies([
        _d("Empty Domain", []),
        _d("Good Domain", [_t("MNRI", "Primary")]),
    ])
    assert [a.therapy for a in result] == ["MNRI"]
    assert result[0].domains == ["Good Domain"]


def test_blank_domain_name_skipped():
    result = aggregate_therapies([
        _d("   ", [_t("MNRI", "Primary")]),
        _d("Real Domain", [_t("MNRI", "Secondary")]),
    ])
    assert result[0].domains == ["Real Domain"]
    assert result[0].relevance == ["Secondary"]


def test_malformed_therapy_objects_skipped():
    # A therapy with an empty/None name is skipped; valid ones survive.
    result = aggregate_therapies([
        _d("D1", [_t("", "Primary"), _t("MNRI", "Primary")]),
    ])
    assert [a.therapy for a in result] == ["MNRI"]


def test_therapies_none_is_safe():
    # A MappedDomainOut whose therapies is an empty list contributes nothing.
    result = aggregate_therapies([MappedDomainOut(domain="D1", therapies=[])])
    assert result == []


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_deterministic_output():
    domains = [
        _d("Sensory Processing", [_t("MNRI", "Primary"), _t("Feldenkrais", "Secondary")]),
        _d("Body Awareness", [_t("MNRI", "Secondary")]),
    ]
    first = aggregate_therapies(domains)
    second = aggregate_therapies(domains)
    assert [a.model_dump() for a in first] == [a.model_dump() for a in second]
