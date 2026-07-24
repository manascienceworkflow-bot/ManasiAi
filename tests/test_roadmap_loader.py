import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.roadmap.roadmap_loader import RoadmapValidationError, load_roadmap  # noqa: E402


def _valid(**overrides):
    obj = {
        "user_id": "u_demo",
        "Classification": "neurodivergent",
        "score": [
            {"domain": "communication", "Score": "72%", "Severity": "moderate"},
            {"domain": "social", "Score": 40, "Severity": "low"},
        ],
    }
    obj.update(overrides)
    return obj


def test_valid_list_wrapped_payload():
    result = load_roadmap([_valid()])
    assert result.user_id == "u_demo"
    assert result.classification == "ND"
    assert result.classification_raw == "neurodivergent"
    assert len(result.scores) == 2


def test_accepts_bare_object_too():
    result = load_roadmap(_valid())
    assert result.classification == "ND"


def test_classification_normalization_case_insensitive():
    assert load_roadmap(_valid(Classification="NEUROTYPICAL")).classification == "NT"
    assert load_roadmap(_valid(Classification="Nd")).classification == "ND"
    assert load_roadmap(_valid(Classification="nt")).classification == "NT"


def test_scores_stored_verbatim_no_coercion():
    result = load_roadmap(_valid())
    by_domain = {s.domain: s for s in result.scores}
    # "72%" stays a string; 40 stays an int -- neither is normalized (P1).
    assert by_domain["communication"].score == "72%"
    assert by_domain["social"].score == 40
    assert by_domain["communication"].severity == "moderate"


def test_severity_optional():
    result = load_roadmap(_valid(score=[{"domain": "d", "Score": 1}]))
    assert result.scores[0].severity is None


def test_raw_preserves_unknown_extra_keys():
    result = load_roadmap(_valid(roadmap_id="rm_1", extra_stuff={"k": "v"}))
    assert result.raw["roadmap_id"] == "rm_1"
    assert result.raw["extra_stuff"] == {"k": "v"}


@pytest.mark.parametrize(
    "payload,expected_code",
    [
        ([], "payload_not_object"),
        (42, "payload_not_object"),
        ([{"a": 1}, {"b": 2}], "ambiguous_batch"),
        ({"Classification": "ND", "score": [{"domain": "d", "Score": 1}]}, "missing_field"),
        ({"user_id": "", "Classification": "ND", "score": [{"domain": "d", "Score": 1}]}, "missing_field"),
        (_valid(Classification="maybe"), "invalid_classification"),
        (_valid(score=[]), "empty_scores"),
        (_valid(score="not a list"), "empty_scores"),
        (_valid(score=[{"domain": "", "Score": 1}]), "invalid_score_entry"),
        (_valid(score=[{"domain": "d"}]), "invalid_score_entry"),
        (_valid(score=[{"domain": "d", "Score": True}]), "invalid_score_entry"),
    ],
)
def test_validation_error_codes(payload, expected_code):
    with pytest.raises(RoadmapValidationError) as exc:
        load_roadmap(payload)
    assert exc.value.code == expected_code


def test_missing_field_names_the_field():
    with pytest.raises(RoadmapValidationError) as exc:
        load_roadmap({"Classification": "ND", "score": [{"domain": "d", "Score": 1}]})
    assert exc.value.field == "user_id"
