import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.validators.boundary_validator import (  # noqa: E402
    fails_domain_boundary,
    has_supported_domain_content,
)
from app.validators.hallucination_validator import (  # noqa: E402
    KNOWN_SAFE_SELF_REFERENCES,
    flagged_entities,
)
from app.validators.medical_validator import fails_medical_safety  # noqa: E402


def test_fails_medical_safety_true_for_diagnostic_phrase():
    assert fails_medical_safety("Based on this, your child has ADHD.") is True


def test_fails_medical_safety_true_for_medication_phrase():
    assert fails_medical_safety("You should stop taking medication X now.") is True


def test_fails_medical_safety_false_for_clean_educational_text():
    assert fails_medical_safety(
        "An evaluation by an appropriate professional may help provide more clarity."
    ) is False


def test_fails_medical_safety_is_case_insensitive():
    assert fails_medical_safety("YOU HAVE ADHD, no question about it.") is True


def test_fails_domain_boundary_true_for_unsupported_keyword():
    assert fails_domain_boundary("Python is a popular programming language.", "general") is True


def test_fails_domain_boundary_false_for_indomain_text():
    assert (
        fails_domain_boundary(
            "Neuroplasticity is the brain's ability to reorganize itself.", "neuroplasticity"
        )
        is False
    )


def test_has_supported_domain_content_true_for_manascience_terms():
    assert has_supported_domain_content("This therapy focuses on primitive reflexes.") is True


def test_has_supported_domain_content_false_for_off_domain_text():
    assert has_supported_domain_content("Bitcoin is a decentralized cryptocurrency.") is False


def test_flagged_entities_source_llm_flags_all_candidates():
    answer = "Dr Sarah Chen runs the Reflex Reset Method clinic."
    flagged = flagged_entities(answer, "llm", [])
    assert "Reflex Reset Method" in flagged


def test_flagged_entities_source_rag_flags_only_ungrounded():
    answer = "The Sensory Integration Program helps with this, per Jane Smith's notes."
    retrieved_docs = [{"content": "The Sensory Integration Program is a core ManaScience offering."}]
    flagged = flagged_entities(answer, "rag", retrieved_docs)
    assert "Sensory Integration Program" not in flagged
    assert "Jane Smith" in flagged


def test_flagged_entities_known_safe_self_references_excluded():
    answer = "ManaScience and Manasi both focus on neuroplasticity-informed support."
    flagged = flagged_entities(answer, "llm", [])
    assert "ManaScience" not in flagged
    assert "Manasi" not in flagged
    assert {"manascience", "manasi"} == KNOWN_SAFE_SELF_REFERENCES
