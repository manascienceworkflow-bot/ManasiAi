"""Unit tests for the Roadmap Step 3 serialization layer (build_mapped_response).

Builds the upstream models directly -- no HTTP, no Excel I/O -- and asserts the
public JSON contract: score joined back verbatim, domain_type/severity passed
through, internal fields dropped, tuples flattened to lists, and the defensive
score-join-miss path.
"""

import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.roadmap.models import (  # noqa: E402
    FilterDiagnostics,
    FilteredDomainScore,
    FilteredRoadmapResult,
)
from app.roadmap.serializers import build_mapped_response  # noqa: E402
from app.roadmap.therapy_models import (  # noqa: E402
    DomainTherapyMapping,
    DomainTherapyResult,
    TherapyMappingDiagnostics,
    TherapyRef,
)


# --------------------------------------------------------------------------
# Builders -- construct the upstream models directly.
# --------------------------------------------------------------------------


def _filtered_score(domain, score, *, domain_type=None, severity="High", key="high", rank=3):
    return FilteredDomainScore(
        domain=domain,
        domain_type=domain_type,
        score=score,
        severity=severity,
        severity_key=key,
        severity_rank=rank,
    )


def _filtered(scores, *, user_id="u1", classification="ND"):
    diag = FilterDiagnostics(
        total_received=len(scores),
        total_kept=len(scores),
        total_dropped=0,
        dropped_low=0,
        dropped_missing_severity=0,
        dropped_unknown_severity=0,
        dropped_duplicate=0,
    )
    return FilteredRoadmapResult(
        user_id=user_id,
        classification=classification,
        classification_raw=classification,
        filtered_scores=scores,
        dropped=[],
        diagnostics=diag,
    )


def _therapy(name, relevance, row):
    return TherapyRef(therapy=name, relevance=relevance, source_row=row)


def _mapping(domain, therapies, *, domain_type=None, severity="High", matched=None):
    return DomainTherapyMapping(
        domain=domain,
        domain_type=domain_type,
        severity=severity,
        matched_domain=matched or f"A. {domain}",
        therapies=tuple(therapies),
    )


def _mapped(mappings, *, user_id="u1", classification="ND", unmapped=()):
    diag = TherapyMappingDiagnostics(
        classification=classification,
        dataset_source=classification,
        total_domains=len(mappings) + len(unmapped),
        total_mapped=len(mappings),
        total_unmapped=len(unmapped),
        total_therapies=sum(len(m.therapies) for m in mappings),
    )
    return DomainTherapyResult(
        user_id=user_id,
        classification=classification,
        mappings=tuple(mappings),
        unmapped=tuple(unmapped),
        diagnostics=diag,
    )


# --------------------------------------------------------------------------
# U1 -- single matched domain, two therapies in order, relevance preserved
# --------------------------------------------------------------------------


def test_single_domain_two_therapies_in_order():
    filtered = _filtered([_filtered_score("Sensory Processing", 85, domain_type="Spine")])
    mapped = _mapped([
        _mapping(
            "Sensory Processing",
            [_therapy("MNRI", "Primary", 5), _therapy("Feldenkrais", "Secondary", 6)],
            domain_type="Spine",
        )
    ])

    resp = build_mapped_response(filtered, mapped)

    assert resp.user_id == "u1"
    assert resp.classification == "ND"
    assert len(resp.mapped_domains) == 1
    d = resp.mapped_domains[0]
    assert d.domain == "Sensory Processing"
    assert [t.therapy for t in d.therapies] == ["MNRI", "Feldenkrais"]
    assert [t.relevance for t in d.therapies] == ["Primary", "Secondary"]


# --------------------------------------------------------------------------
# U2 -- score joined back VERBATIM (number, percent string, float)
# --------------------------------------------------------------------------


def test_score_joined_verbatim_for_each_type():
    filtered = _filtered([
        _filtered_score("A", 85),
        _filtered_score("B", "72%"),
        _filtered_score("C", 88.5),
    ])
    mapped = _mapped([
        _mapping("A", [_therapy("t1", "Primary", 5)]),
        _mapping("B", [_therapy("t2", "Primary", 6)]),
        _mapping("C", [_therapy("t3", "Primary", 7)]),
    ])

    by_domain = {d.domain: d.score for d in build_mapped_response(filtered, mapped).mapped_domains}
    assert by_domain["A"] == 85
    assert by_domain["B"] == "72%"
    assert by_domain["C"] == 88.5


def test_score_join_matches_despite_ordinal_prefix_and_case():
    # Filtered domain is bare + differently cased; mapper's domain keeps the ordinal
    # prefix. domain_key normalizes both to the same key so the score still joins.
    filtered = _filtered([_filtered_score("sensory   PROCESSING", 90)])
    mapped = _mapped([_mapping("A. Sensory Processing", [_therapy("t", "Primary", 5)])])

    d = build_mapped_response(filtered, mapped).mapped_domains[0]
    assert d.score == 90


# --------------------------------------------------------------------------
# U3 -- domain_type passthrough (present + absent)
# --------------------------------------------------------------------------


def test_domain_type_passthrough():
    filtered = _filtered([
        _filtered_score("A", 1, domain_type="Spine"),
        _filtered_score("B", 2),
    ])
    mapped = _mapped([
        _mapping("A", [_therapy("t", "Primary", 5)], domain_type="Spine"),
        _mapping("B", [_therapy("t", "Primary", 6)], domain_type=None),
    ])

    out = {d.domain: d.domain_type for d in build_mapped_response(filtered, mapped).mapped_domains}
    assert out["A"] == "Spine"
    assert out["B"] is None


# --------------------------------------------------------------------------
# U4 -- original severity string preserved (not the normalized key)
# --------------------------------------------------------------------------


def test_severity_original_string_preserved():
    filtered = _filtered([_filtered_score("A", 1, severity="High", key="high")])
    mapped = _mapped([_mapping("A", [_therapy("t", "Primary", 5)], severity="High")])

    d = build_mapped_response(filtered, mapped).mapped_domains[0]
    assert d.severity == "High"  # not "high"


# --------------------------------------------------------------------------
# U5 / U8 -- internal fields dropped; tuples become JSON lists
# --------------------------------------------------------------------------


def test_internal_fields_dropped_and_tuples_become_lists():
    filtered = _filtered([_filtered_score("A", 85, domain_type="Spine")])
    mapped = _mapped([_mapping("A", [_therapy("MNRI", "Primary", 5)], domain_type="Spine")])

    dumped = build_mapped_response(filtered, mapped).model_dump()

    assert isinstance(dumped["mapped_domains"], list)
    domain = dumped["mapped_domains"][0]
    assert isinstance(domain["therapies"], list)
    assert set(domain) == {"domain", "domain_type", "score", "severity", "therapies"}
    assert set(domain["therapies"][0]) == {"therapy", "relevance"}
    # None of the internal provenance / normalization fields leak.
    blob = str(dumped)
    for leaked in ("source_row", "matched_domain", "severity_key", "severity_rank", "diagnostics"):
        assert leaked not in blob


# --------------------------------------------------------------------------
# U6 -- empty mappings still yield a valid envelope
# --------------------------------------------------------------------------


def test_empty_mappings_yields_empty_list_not_error():
    filtered = _filtered([], user_id="u9", classification="NT")
    mapped = _mapped([], user_id="u9", classification="NT")

    resp = build_mapped_response(filtered, mapped)
    assert resp.user_id == "u9"
    assert resp.classification == "NT"
    assert resp.mapped_domains == []


# --------------------------------------------------------------------------
# U7 -- score-join miss: null score + warning, never raises
# --------------------------------------------------------------------------


def test_score_join_miss_sets_none_and_warns(caplog):
    # A mapping whose domain is absent from the filtered scores (upstream drift).
    filtered = _filtered([_filtered_score("Present", 50)])
    mapped = _mapped([_mapping("Ghost Domain", [_therapy("t", "Primary", 5)])])

    with caplog.at_level(logging.WARNING, logger="app.roadmap.serializers"):
        resp = build_mapped_response(filtered, mapped)

    assert resp.mapped_domains[0].score is None
    assert any("score_join_miss" in r.message for r in caplog.records)


# --------------------------------------------------------------------------
# U10 -- frozen inputs are not mutated
# --------------------------------------------------------------------------


def test_frozen_inputs_untouched():
    mapping = _mapping("A", [_therapy("t", "Primary", 5)])
    filtered = _filtered([_filtered_score("A", 85)])
    mapped = _mapped([mapping])

    build_mapped_response(filtered, mapped)

    # frozen models raise on mutation; simply confirm they still read back intact.
    assert mapped.mappings[0].therapies[0].source_row == 5
    assert mapping.matched_domain == "A. A"


# --------------------------------------------------------------------------
# U14 -- ND vs NT classification carried through from the mapper
# --------------------------------------------------------------------------


def test_classification_carried_from_mapper():
    for cls in ("ND", "NT"):
        filtered = _filtered([_filtered_score("A", 1)], classification=cls)
        mapped = _mapped([_mapping("A", [_therapy("t", "Primary", 5)])], classification=cls)
        assert build_mapped_response(filtered, mapped).classification == cls


# --------------------------------------------------------------------------
# U15 -- aggregated_therapies is emitted and consistent with mapped_domains
# --------------------------------------------------------------------------


def test_aggregated_therapies_transposes_mapped_domains():
    # MNRI recommended by two domains, Feldenkrais by one.
    filtered = _filtered([
        _filtered_score("Sensory Processing", 85),
        _filtered_score("Body Awareness", 70, severity="Moderate", key="moderate", rank=2),
    ])
    mapped = _mapped([
        _mapping("Sensory Processing", [_therapy("MNRI", "Primary", 5), _therapy("Feldenkrais", "Secondary", 6)]),
        _mapping("Body Awareness", [_therapy("MNRI", "Secondary", 7)]),
    ])

    resp = build_mapped_response(filtered, mapped)

    # mapped_domains is untouched (still lists MNRI twice, once per domain).
    assert [t.therapy for d in resp.mapped_domains for t in d.therapies] == [
        "MNRI", "Feldenkrais", "MNRI",
    ]

    # aggregated_therapies collapses MNRI to one, merging domains + relevance.
    agg = {a.therapy: a for a in resp.aggregated_therapies}
    assert [a.therapy for a in resp.aggregated_therapies] == ["MNRI", "Feldenkrais"]
    assert agg["MNRI"].domains == ["Sensory Processing", "Body Awareness"]
    assert agg["MNRI"].relevance == ["Primary", "Secondary"]
    assert agg["Feldenkrais"].domains == ["Sensory Processing"]

    # No aggregated therapy name repeats.
    names = [a.therapy for a in resp.aggregated_therapies]
    assert len(names) == len(set(names))


def test_aggregated_therapies_empty_when_no_mappings():
    filtered = _filtered([], user_id="u9", classification="NT")
    mapped = _mapped([], user_id="u9", classification="NT")
    resp = build_mapped_response(filtered, mapped)
    assert resp.mapped_domains == []
    assert resp.aggregated_therapies == []
