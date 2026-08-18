import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.knowledge.concern_loader import load_concern_data  # noqa: E402
from app.knowledge.vocabularies import load_vocabularies  # noqa: E402
from tests.test_concern_loader import (  # noqa: E402
    DEFAULT_FRONT_MATTER,
    build_concern_text,
    write_corpus,
)

# scripts/ is not a package, so load the validator by path.
_SPEC = importlib.util.spec_from_file_location(
    "validate_knowledge", Path(__file__).resolve().parent.parent / "scripts" / "validate_knowledge.py"
)
validator = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(validator)

VOCABULARIES = load_vocabularies()


def make_record(tmp_path, **kwargs):
    base = write_corpus(tmp_path, {"communication/sample_concern.md": build_concern_text(**kwargs)})
    result = load_concern_data(base_dir=base)
    assert result.files_loaded == 1, result.issues
    return result.records[0]


def rules(findings) -> "set[str]":
    return {finding.rule for finding in findings}


def safety(record):
    return validator.check_content_safety(record, VOCABULARIES)


# ---------------------------------------------------------------------------
# The baseline fixture must be clean, or every other assertion is meaningless
# ---------------------------------------------------------------------------


def test_baseline_fixture_has_no_content_safety_errors(tmp_path):
    findings = safety(make_record(tmp_path))
    assert [f for f in findings if f.severity == validator.ERROR] == []


# ---------------------------------------------------------------------------
# V-30 / V-31 -- diagnosis and hedging (Playbook Part 4)
# ---------------------------------------------------------------------------


def test_v30_rejects_diagnostic_assertion(tmp_path):
    record = make_record(tmp_path, sections={
        "ManaScience Perspective": (
            "- This means your child is autistic and needs a formal assessment now.\n"
            "- ManaScience looks at this concern through a developmental lens.\n"
            "- ManaScience considers the whole profile of an individual child.\n"
            "- ManaScience treats current difficulty as a present state only."
        )
    })
    assert "V-30" in rules(safety(record))


def test_v30_rejects_soft_reassurance_that_closes_the_question(tmp_path):
    """Playbook Part 4 forbids ruling a concern out as firmly as ruling one in."""
    from app.knowledge.concern_loader import REQUIRED_SECTIONS

    record = make_record(
        tmp_path,
        sections={"Common Misunderstandings": "- This is perfectly normal and nothing to worry about at all."},
        section_order=[name for name, _ in REQUIRED_SECTIONS] + ["Common Misunderstandings"],
    )
    assert "V-30" in rules(safety(record))


def test_v31_requires_a_hedge_in_every_explanation(tmp_path):
    record = make_record(tmp_path, sections={
        "Possible Explanations": (
            "- Reduced hearing causes this behaviour in children of this age.\n"
            "- Some children may show this for another ordinary developmental reason.\n"
            "- Some children may show this for a third ordinary developmental reason.\n"
            "- Some children may show this for a fourth ordinary developmental reason.\n"
            "- Some children may show this for a fifth ordinary developmental reason.\n"
            "- Some children may show this for a sixth ordinary developmental reason."
        )
    })
    findings = [f for f in safety(record) if f.rule == "V-31"]
    assert len(findings) == 1
    assert "bullet 1" in findings[0].message


def test_v31_accepts_a_hedge_on_a_wrapped_continuation_line(tmp_path):
    record = make_record(tmp_path, sections={
        "Possible Explanations": (
            "- Reduced hearing, including temporary loss from infections,\n"
            "  may make it harder to pick up the sounds of speech.\n"
            "- Some children may show this for another ordinary developmental reason.\n"
            "- Some children may show this for a third ordinary developmental reason.\n"
            "- Some children may show this for a fourth ordinary developmental reason.\n"
            "- Some children may show this for a fifth ordinary developmental reason.\n"
            "- Some children may show this for a sixth ordinary developmental reason."
        )
    })
    assert "V-31" not in rules(safety(record))


# ---------------------------------------------------------------------------
# V-32 / V-33 / V-34 / V-35 / V-36 / V-37
# ---------------------------------------------------------------------------


def test_v32_rejects_prescription(tmp_path):
    record = make_record(tmp_path, sections={
        "Everyday Support Ideas": "- We recommend therapy for children who show this pattern at home."
    })
    assert "V-32" in rules(safety(record))


def test_v33_rejects_chatbot_voice_and_direct_address(tmp_path):
    record = make_record(tmp_path, sections={
        "Things to Observe": "- Thank you for sharing this, and try not to worry about it too much."
    })
    assert "V-33" in rules(safety(record))


def test_v33_rejects_second_person_reference_to_the_child(tmp_path):
    record = make_record(tmp_path, sections={
        "Things to Observe": "- Whether your child responds consistently to their own name at home."
    })
    assert "V-33" in rules(safety(record))


def test_v33_does_not_fire_on_quoted_parent_questions(tmp_path):
    """The phrasing sections are verbatim parent language: 'my child', 'I'm worried' and
    direct address are exactly what belongs there (spec 12.4 exemption)."""
    record = make_record(tmp_path, sections={
        "Typical User Questions": "\n".join(
            ["- I'm worried that your child comparison is unfair."] +
            [f"- My child does thing number {i}?" for i in range(1, 13)]
        )
    })
    assert "V-33" not in rules(safety(record))


def test_v34_rejects_marketing_copy_and_stray_urls(tmp_path):
    record = make_record(tmp_path, sections={
        "ManaScience Perspective": (
            "- Click here to sign up for the programme that supports this concern.\n"
            "- ManaScience looks at this concern through a developmental lens.\n"
            "- ManaScience considers the whole profile of an individual child.\n"
            "- ManaScience treats current difficulty as a present state only."
        )
    })
    assert "V-34" in rules(safety(record))


def test_v35_rejects_guaranteed_outcomes_in_the_neuroplasticity_section(tmp_path):
    record = make_record(tmp_path, sections={
        "Neuroplasticity Explanation": (
            "- Targeted practice will cure this difficulty within a few short months.\n"
            "- The brain continues to develop through repeated everyday interaction.\n"
            "- Small frequent interactions support these pathways over time.\n"
            "- Progress often appears in uneven steps rather than steadily."
        )
    })
    assert "V-35" in rules(safety(record))


def test_v36_rejects_urgency_unless_the_file_is_flagged_escalation_sensitive(tmp_path):
    sections = {
        "When Professional Evaluation May Help": (
            "- When a family notices this, an assessment is urgently needed immediately.\n"
            "- When situation number two has been going on for some time for a family.\n"
            "- When situation number three has been going on for some time for a family.\n"
            "- When situation number four has been going on for some time for a family."
        )
    }
    assert "V-36" in rules(safety(make_record(tmp_path, sections=sections)))

    escalating = DEFAULT_FRONT_MATTER.format(
        concern_id="sample_concern", category="communication", title="Sample Concern"
    ).replace("escalation_sensitive: false", "escalation_sensitive: true")
    record = make_record(tmp_path, sections=sections, front_matter=escalating)
    assert "V-36" not in rules(safety(record))


def test_v37_rejects_numeric_screening_thresholds(tmp_path):
    record = make_record(tmp_path, sections={
        "Things to Observe": "- Whether the child uses fewer than 50 words at this stage of development."
    })
    assert "V-37" in rules(safety(record))


# ---------------------------------------------------------------------------
# V-47 / V-48 -- the playbook-derived rules
# ---------------------------------------------------------------------------


def test_v47_requires_an_approved_boundary_phrasing(tmp_path):
    record = make_record(tmp_path, sections={
        "Professional Boundary": (
            "- Manasi is not able to say what is going on for a particular child here.\n"
            "- Speaking to someone qualified is a sensible step for most families.\n"
            "- This material describes general possibilities rather than individual cases."
        )
    })
    assert "V-47" in rules(safety(record))


def test_v47_accepts_each_approved_phrasing(tmp_path):
    approved = [
        "- Only a qualified healthcare professional can determine that.",
        "- An evaluation by an appropriate professional may help provide more clarity.",
        "- Manasi can provide educational information, but cannot diagnose medical conditions.",
    ]
    for phrasing in approved:
        record = make_record(tmp_path, sections={
            "Professional Boundary": (
                f"{phrasing}\n"
                "- This material describes general possibilities rather than individual cases.\n"
                "- Manasi does not recommend any specific programme for an individual child."
            )
        })
        assert "V-47" not in rules(safety(record)), phrasing


def test_v48_rejects_therapies_outside_the_playbook_allowlist(tmp_path):
    front_matter = DEFAULT_FRONT_MATTER.format(
        concern_id="sample_concern", category="communication", title="Sample Concern"
    ).replace("related_therapies: []", "related_therapies:\n  - speech_therapy")
    record = make_record(tmp_path, front_matter=front_matter)
    assert "V-48" not in rules(safety(record))

    # An unlisted approach is rejected in prose (the front-matter equivalent is caught
    # earlier still, by the loader's closed-vocabulary check).
    record = make_record(tmp_path, sections={
        "Everyday Support Ideas": "- Families sometimes explore applied behaviour analysis for this concern."
    })
    assert "V-48" in rules(safety(record))


def test_v50_flags_a_section_marked_not_applicable(tmp_path):
    record = make_record(tmp_path, sections={"Possible Explanations": "- Not applicable for this concern."})
    assert "V-50" in rules(safety(record))


# ---------------------------------------------------------------------------
# Cardinality, governance, relationships
# ---------------------------------------------------------------------------


def test_v14_published_requires_clinical_review(tmp_path):
    front_matter = DEFAULT_FRONT_MATTER.format(
        concern_id="sample_concern", category="communication", title="Sample Concern"
    ).replace("clinical_review_status: reviewed", "clinical_review_status: unreviewed")
    record = make_record(tmp_path, front_matter=front_matter)
    assert "V-14" in rules(validator.check_vocabulary_and_typing(record, date.today()))


def test_v15_reviewed_requires_a_named_reviewer(tmp_path):
    front_matter = DEFAULT_FRONT_MATTER.format(
        concern_id="sample_concern", category="communication", title="Sample Concern"
    ).replace('clinical_reviewer: "Test Reviewer"\n', "")
    record = make_record(tmp_path, front_matter=front_matter)
    assert "V-15" in rules(validator.check_vocabulary_and_typing(record, date.today()))


def test_v17_rejects_a_future_last_updated(tmp_path):
    record = make_record(tmp_path)
    yesterday = record.last_updated - timedelta(days=1)
    assert "V-17" in rules(validator.check_vocabulary_and_typing(record, yesterday))


def test_v20_flags_too_few_keywords(tmp_path):
    front_matter = DEFAULT_FRONT_MATTER.format(
        concern_id="sample_concern", category="communication", title="Sample Concern"
    ).replace("keywords: [alpha, beta, gamma, delta, epsilon, zeta, eta, theta]", "keywords: [alpha, beta]")
    record = make_record(tmp_path, front_matter=front_matter)
    assert "V-20" in rules(validator.check_vocabulary_and_typing(record, date.today()))


def test_v22_and_v29_catch_dangling_and_self_relations(tmp_path):
    front_matter = DEFAULT_FRONT_MATTER.format(
        concern_id="sample_concern", category="communication", title="Sample Concern"
    ).replace(
        "related_concerns: []",
        "related_concerns:\n  - id: does_not_exist\n    relation: co_occurring\n    weight: 0.5\n"
        "  - id: sample_concern\n    relation: differential\n    weight: 0.5",
    )
    record = make_record(tmp_path, front_matter=front_matter)
    found = rules(validator.check_relationships(record, {"sample_concern"}, lambda _id: object()))
    assert {"V-22", "V-29"} <= found


def test_v27_requires_cta_ids_to_exist(tmp_path):
    front_matter = DEFAULT_FRONT_MATTER.format(
        concern_id="sample_concern", category="communication", title="Sample Concern"
    ).replace("cta_mapping: []", "cta_mapping:\n  - cta_id: conditions/nonexistent\n    priority: primary")
    record = make_record(tmp_path, front_matter=front_matter)
    findings = validator.check_relationships(record, {"sample_concern"}, lambda _id: None)
    assert "V-27" in rules(findings)


# ---------------------------------------------------------------------------
# The real corpus is the gate
# ---------------------------------------------------------------------------


def test_real_corpus_passes_validation_in_strict_mode():
    """Every rule, WARN included, over the shipped seed corpus."""
    argv = sys.argv
    sys.argv = ["validate_knowledge.py", "--strict"]
    try:
        assert validator.main() == 0
    finally:
        sys.argv = argv
