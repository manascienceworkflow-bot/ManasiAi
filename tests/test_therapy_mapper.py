import copy
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
import pydantic  # noqa: E402

from app.roadmap.mapping_models import MappingBundle, MappingDataset, ModalityRow  # noqa: E402
from app.roadmap.models import (  # noqa: E402
    FilterDiagnostics,
    FilteredDomainScore,
    FilteredRoadmapResult,
)
from app.roadmap.therapy_mapper import (  # noqa: E402
    TherapyMappingError,
    domain_key,
    map_domains_to_therapies,
)


# --------------------------------------------------------------------------- #
# Builders -- construct the loader's / filter's OUTPUT objects directly. No
# .xlsx is opened here; that is mapping_loader's own test's job.
# --------------------------------------------------------------------------- #

_START_ROW = 5  # the real files put data from sheet row 5 on


def _rows(*specs):
    """Each spec is (domain_or_None, modality, relevance_or_None[, track]).
    source_row is auto-assigned from 5 upward to mirror the real layout."""
    out = []
    for i, spec in enumerate(specs):
        domain, modality, relevance = spec[0], spec[1], spec[2]
        track = spec[3] if len(spec) > 3 else "Spine"
        out.append(
            ModalityRow(
                domain=domain,
                track=track,
                modality=modality,
                relevance=relevance,
                source_row=_START_ROW + i,
            )
        )
    return tuple(out)


def _dataset(source, rows):
    return MappingDataset(
        source=source,
        path=f"/fake/{source}.xlsx",
        sheet_name="Neurodivergent Path" if source == "ND" else "Neurotypical Path",
        header_row=4,
        rows=rows,
    )


def _bundle(nd_rows=(), nt_rows=()):
    return MappingBundle(
        neurodivergent=_dataset("ND", nd_rows),
        neurotypical=_dataset("NT", nt_rows),
    )


_RANK = {"high": 3, "moderate": 2}


def _score(domain, severity="High", domain_type=None):
    key = severity.strip().casefold()
    return FilteredDomainScore(
        domain=domain,
        domain_type=domain_type,
        score=80,
        severity=severity,
        severity_key=key,
        severity_rank=_RANK[key],
    )


def _filtered(*scores, classification="ND", user_id="u_test"):
    kept = list(scores)
    diagnostics = FilterDiagnostics(
        total_received=len(kept),
        total_kept=len(kept),
        total_dropped=0,
        dropped_low=0,
        dropped_missing_severity=0,
        dropped_unknown_severity=0,
        dropped_duplicate=0,
    )
    return FilteredRoadmapResult(
        user_id=user_id,
        classification=classification,
        classification_raw="neurodivergent" if classification == "ND" else "neurotypical",
        filtered_scores=kept,
        dropped=[],
        diagnostics=diagnostics,
    )


# The canonical ND fixture: two domains, each with a merged-cell continuation row
# (domain=None) -- exactly the real sheet shape.
_ND_ROWS = _rows(
    ("A. Sensory Processing", "MNRI", "Primary"),
    (None, "Feldenkrais", "Secondary"),
    ("C. Cognitive Function", "Arrowsmith", "Primary"),
    (None, "Stowell", "Secondary"),
)
_NT_ROWS = _rows(
    ("A. Attention & Concentration", "Arrowsmith", "Primary"),
    (None, "Tomatis", "Secondary"),
    ("E. Mood & Emotional Wellbeing", "Yoga Nidra", "Complementary", "Complementary"),
)


# --------------------------------------------------------------------------- #
# Unit -- dataset selection
# --------------------------------------------------------------------------- #


def test_u1_selects_nd_dataset():
    out = map_domains_to_therapies(_filtered(_score("Sensory Processing"), classification="ND"),
                                   _bundle(nd_rows=_ND_ROWS, nt_rows=_NT_ROWS))
    assert out.diagnostics.dataset_source == "ND"
    assert [t.therapy for t in out.mappings[0].therapies] == ["MNRI", "Feldenkrais"]


def test_u2_selects_nt_dataset():
    out = map_domains_to_therapies(_filtered(_score("Attention & Concentration"), classification="NT"),
                                   _bundle(nd_rows=_ND_ROWS, nt_rows=_NT_ROWS))
    assert out.diagnostics.dataset_source == "NT"
    assert [t.therapy for t in out.mappings[0].therapies] == ["Arrowsmith", "Tomatis"]


# --------------------------------------------------------------------------- #
# Unit -- forward-fill / matching / order / verbatim
# --------------------------------------------------------------------------- #


def test_u3_forward_fill_groups_continuation_rows():
    """The domain=None continuation row joins the domain header above it."""
    out = map_domains_to_therapies(_filtered(_score("Cognitive Function")), _bundle(nd_rows=_ND_ROWS))
    assert [t.therapy for t in out.mappings[0].therapies] == ["Arrowsmith", "Stowell"]


def test_u4_ordinal_prefix_match():
    out = map_domains_to_therapies(_filtered(_score("Sensory Processing")), _bundle(nd_rows=_ND_ROWS))
    assert out.mappings[0].matched_domain == "A. Sensory Processing"
    assert out.diagnostics.total_mapped == 1


def test_u5_case_and_whitespace_insensitive():
    out = map_domains_to_therapies(_filtered(_score("  sensory   PROCESSING ")), _bundle(nd_rows=_ND_ROWS))
    assert out.diagnostics.total_mapped == 1
    assert out.diagnostics.total_unmapped == 0


def test_u6_preserves_therapy_order():
    out = map_domains_to_therapies(_filtered(_score("Sensory Processing")), _bundle(nd_rows=_ND_ROWS))
    assert [t.therapy for t in out.mappings[0].therapies] == ["MNRI", "Feldenkrais"]


def test_u7_preserves_relevance_verbatim_including_none():
    rows = _rows(("A. X", "T1", "Primary"), (None, "T2", None))
    out = map_domains_to_therapies(_filtered(_score("X")), _bundle(nd_rows=rows))
    assert [t.relevance for t in out.mappings[0].therapies] == ["Primary", None]


def test_u8_keeps_duplicate_therapy_rows():
    rows = _rows(("A. X", "MNRI", "Primary"), (None, "MNRI", "Primary"))
    out = map_domains_to_therapies(_filtered(_score("X")), _bundle(nd_rows=rows))
    assert [t.therapy for t in out.mappings[0].therapies] == ["MNRI", "MNRI"]


def test_u9_domain_verbatim_vs_matched_domain():
    out = map_domains_to_therapies(_filtered(_score("Sensory Processing")), _bundle(nd_rows=_ND_ROWS))
    assert out.mappings[0].domain == "Sensory Processing"          # incoming, verbatim
    assert out.mappings[0].matched_domain == "A. Sensory Processing"  # table label


def test_u10_to_list_shape():
    out = map_domains_to_therapies(
        _filtered(_score("Sensory Processing", "High"), _score("Cognitive Function", "Moderate")),
        _bundle(nd_rows=_ND_ROWS),
    )
    assert out.to_list() == [
        {"domain": "Sensory Processing", "domain_type": None, "severity": "High",
         "therapies": [{"therapy": "MNRI", "relevance": "Primary"},
                       {"therapy": "Feldenkrais", "relevance": "Secondary"}]},
        {"domain": "Cognitive Function", "domain_type": None, "severity": "Moderate",
         "therapies": [{"therapy": "Arrowsmith", "relevance": "Primary"},
                       {"therapy": "Stowell", "relevance": "Secondary"}]},
    ]


def test_domain_type_carried_verbatim():
    """The frontend's per-domain `domain_type` flows through the mapper verbatim --
    onto DomainTherapyMapping and into the to_list() JSON -- and is never used for
    matching (the therapies are unchanged from the no-domain_type case)."""
    out = map_domains_to_therapies(
        _filtered(_score("Sensory Processing", "High", domain_type="Spine")),
        _bundle(nd_rows=_ND_ROWS),
    )
    assert out.mappings[0].domain_type == "Spine"
    assert out.to_list() == [
        {"domain": "Sensory Processing", "domain_type": "Spine", "severity": "High",
         "therapies": [{"therapy": "MNRI", "relevance": "Primary"},
                       {"therapy": "Feldenkrais", "relevance": "Secondary"}]},
    ]


def test_domain_type_is_the_frontend_value_never_the_excel_track():
    """domain_type must be preserved exactly as received -- NOT inferred from the
    Excel `Track` column. Here the frontend sends domain_type='from_frontend' while
    the matched Excel rows carry Track='Complementary'; the output must echo the
    frontend value."""
    rows = _rows(
        ("A. Sensory Processing", "MNRI", "Primary", "Complementary"),  # Track != domain_type
    )
    out = map_domains_to_therapies(
        _filtered(_score("Sensory Processing", "High", domain_type="from_frontend")),
        _bundle(nd_rows=rows),
    )
    assert out.mappings[0].domain_type == "from_frontend"  # frontend value, not "Complementary"


def test_domain_type_carried_onto_unmapped_domain():
    """An actionable domain that matches nothing still carries its frontend
    domain_type verbatim on the UnmappedDomain record."""
    out = map_domains_to_therapies(
        _filtered(_score("Telepathy", "High", domain_type="Spine")),
        _bundle(nd_rows=_ND_ROWS),
    )
    assert out.mappings == ()
    assert out.unmapped[0].domain == "Telepathy"
    assert out.unmapped[0].domain_type == "Spine"
    assert out.unmapped[0].reason == "domain_not_found"


def test_u11_track_not_interpreted():
    """Spine and Complementary rows both come back; no grouping/splitting."""
    out = map_domains_to_therapies(_filtered(_score("Mood & Emotional Wellbeing"), classification="NT"),
                                   _bundle(nt_rows=_NT_ROWS))
    assert [t.therapy for t in out.mappings[0].therapies] == ["Yoga Nidra"]


def test_u12_orphan_row_skipped():
    """A therapy row before any domain header is warned + skipped, others fine."""
    rows = _rows((None, "OrphanTherapy", "Primary"), ("A. X", "MNRI", "Primary"))
    out = map_domains_to_therapies(_filtered(_score("X")), _bundle(nd_rows=rows))
    assert [t.therapy for t in out.mappings[0].therapies] == ["MNRI"]
    assert any("OrphanTherapy" in w for w in out.diagnostics.warnings)


# --------------------------------------------------------------------------- #
# domain_key normalization unit tests
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("value", [
    "A. Sensory Processing", "Sensory Processing", "  sensory   processing ",
    "SENSORY PROCESSING", "1) Sensory Processing", "iv. Sensory Processing",
])
def test_domain_key_collapses_variants(value):
    assert domain_key(value) == "sensory processing"


@pytest.mark.parametrize("value", [None, 42, ""])
def test_domain_key_none_for_unusable(value):
    assert domain_key(value) is None


def test_domain_key_does_not_eat_single_word_domain():
    # "Sleep" must not be read as ordinal "S" + "leep": no separator after prefix.
    assert domain_key("Sleep") == "sleep"


# --------------------------------------------------------------------------- #
# Validation / edge cases
# --------------------------------------------------------------------------- #


def test_empty_filtered_result_returns_empty_no_error():
    out = map_domains_to_therapies(_filtered(), _bundle(nd_rows=_ND_ROWS))
    assert out.mappings == ()
    assert out.unmapped == ()
    assert out.diagnostics.total_domains == 0


def test_unknown_domain_recorded_not_raised_in_prod():
    out = map_domains_to_therapies(_filtered(_score("Telepathy")), _bundle(nd_rows=_ND_ROWS))
    assert out.mappings == ()
    assert len(out.unmapped) == 1
    assert out.unmapped[0].reason == "domain_not_found"
    assert out.unmapped[0].domain == "Telepathy"


def test_unknown_domain_raises_in_strict():
    with pytest.raises(TherapyMappingError) as exc:
        map_domains_to_therapies(_filtered(_score("Telepathy")), _bundle(nd_rows=_ND_ROWS), strict=True)
    assert exc.value.code == "domain_not_found"
    assert exc.value.domain == "Telepathy"


def test_empty_dataset_prod_records_unmapped():
    out = map_domains_to_therapies(_filtered(_score("Sensory Processing")), _bundle(nd_rows=()))
    assert out.unmapped[0].reason == "empty_dataset"


def test_empty_dataset_strict_raises():
    with pytest.raises(TherapyMappingError) as exc:
        map_domains_to_therapies(_filtered(_score("Sensory Processing")), _bundle(nd_rows=()), strict=True)
    assert exc.value.code == "empty_dataset"


def test_missing_relevance_preserved_as_none():
    rows = _rows(("A. X", "T1", None))
    out = map_domains_to_therapies(_filtered(_score("X")), _bundle(nd_rows=rows))
    assert out.mappings[0].therapies[0].relevance is None


def test_accounting_mapped_plus_unmapped_equals_input():
    out = map_domains_to_therapies(
        _filtered(_score("Sensory Processing"), _score("Telepathy"), _score("Cognitive Function")),
        _bundle(nd_rows=_ND_ROWS),
    )
    assert out.diagnostics.total_mapped + out.diagnostics.total_unmapped == 3
    assert out.diagnostics.total_domains == 3


def test_two_blocks_same_domain_merge_under_one_key():
    rows = _rows(
        ("A. X", "T1", "Primary"),
        ("B. Y", "T2", "Primary"),
        ("A. X", "T3", "Secondary"),  # second block for the same domain
    )
    out = map_domains_to_therapies(_filtered(_score("X")), _bundle(nd_rows=rows))
    assert [t.therapy for t in out.mappings[0].therapies] == ["T1", "T3"]


# --------------------------------------------------------------------------- #
# Failure -- wrong input types
# --------------------------------------------------------------------------- #


def test_type_guard_rejects_raw_json_input():
    with pytest.raises(TypeError):
        map_domains_to_therapies({"classification": "ND"}, _bundle(nd_rows=_ND_ROWS))


def test_type_guard_rejects_non_bundle():
    with pytest.raises(TypeError):
        map_domains_to_therapies(_filtered(_score("Sensory Processing")), {"neurodivergent": []})


# --------------------------------------------------------------------------- #
# Immutability & purity
# --------------------------------------------------------------------------- #


def test_output_models_are_frozen():
    out = map_domains_to_therapies(_filtered(_score("Sensory Processing")), _bundle(nd_rows=_ND_ROWS))
    with pytest.raises(pydantic.ValidationError):
        out.mappings[0].therapies[0].therapy = "hacked"


def test_inputs_unmutated_after_call():
    filtered = _filtered(_score("Sensory Processing"), _score("Telepathy"))
    bundle = _bundle(nd_rows=_ND_ROWS, nt_rows=_NT_ROWS)
    before_filtered = copy.deepcopy(filtered)
    before_bundle = copy.deepcopy(bundle)
    map_domains_to_therapies(filtered, bundle)
    assert filtered == before_filtered
    assert bundle == before_bundle


# --------------------------------------------------------------------------- #
# Integration -- compose with the real loader against data/roadmap/
# --------------------------------------------------------------------------- #


def test_i1_end_to_end_with_real_loader_nd():
    from app.roadmap.mapping_loader import load_mappings

    repo_root = Path(__file__).resolve().parent.parent
    bundle = load_mappings(base_dir=repo_root / "data" / "roadmap")
    out = map_domains_to_therapies(_filtered(_score("Sensory Processing")), bundle)
    therapies = [t.therapy for t in out.mappings[0].therapies]
    assert therapies[:2] == ["MNRI", "Feldenkrais"]
    assert out.mappings[0].matched_domain.endswith("Sensory Processing")


def test_i2_end_to_end_with_real_loader_nt():
    from app.roadmap.mapping_loader import load_mappings

    repo_root = Path(__file__).resolve().parent.parent
    bundle = load_mappings(base_dir=repo_root / "data" / "roadmap")
    out = map_domains_to_therapies(
        _filtered(_score("Attention & Concentration"), classification="NT"), bundle
    )
    assert out.diagnostics.total_mapped == 1
    assert len(out.mappings[0].therapies) >= 1


def test_i3_filter_then_map_compose():
    from app.roadmap.models import RoadmapDomainScore, RoadmapResult
    from app.roadmap.severity_filter import filter_by_severity

    result = RoadmapResult(
        user_id="u_compose",
        classification_raw="neurodivergent",
        classification="ND",
        scores=[
            RoadmapDomainScore(domain="Sensory Processing", score=82, severity="High"),
            RoadmapDomainScore(domain="Cognitive Function", score=40, severity="Low"),
        ],
        raw={},
    )
    filtered = filter_by_severity(result)
    out = map_domains_to_therapies(filtered, _bundle(nd_rows=_ND_ROWS))
    # Only the High domain survived the filter, so only it is mapped.
    assert out.diagnostics.total_domains == 1
    assert out.mappings[0].domain == "Sensory Processing"


# --------------------------------------------------------------------------- #
# Architecture -- structurally enforce "no Excel / no reload / pure & injected"
# --------------------------------------------------------------------------- #


def test_architecture_no_forbidden_dependencies():
    src = (Path(__file__).resolve().parent.parent / "app" / "roadmap" / "therapy_mapper.py").read_text()
    for forbidden in ("openpyxl", "fastapi", "supabase", "app.db", "requests"):
        assert forbidden not in src, f"therapy_mapper must not depend on {forbidden!r}"
    for call in ("load_mappings", "get_mappings", "filter_by_severity"):
        assert f"{call}(" not in src, f"therapy_mapper must not call {call}()"


# --------------------------------------------------------------------------- #
# Performance
# --------------------------------------------------------------------------- #


def test_performance_500_domains_under_budget():
    # 100 domains x 3 therapies in the table; 500 incoming domains to map.
    rows = []
    for d in range(100):
        rows.append((f"{d}. Domain{d}", f"T{d}a", "Primary"))
        rows.append((None, f"T{d}b", "Secondary"))
        rows.append((None, f"T{d}c", None))
    bundle = _bundle(nd_rows=_rows(*rows))
    scores = [_score(f"Domain{i % 100}") for i in range(500)]
    filtered = _filtered(*scores)

    start = time.perf_counter()
    out = map_domains_to_therapies(filtered, bundle)
    elapsed = time.perf_counter() - start

    assert out.diagnostics.total_mapped == 500
    assert elapsed < 0.25, f"mapping 500 domains took {elapsed:.3f}s"
