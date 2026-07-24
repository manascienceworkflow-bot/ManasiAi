import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import openai  # noqa: E402
import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.nodes.safety_node import SafetyOutput, safety_node  # noqa: E402
from app.services.safety_service import (  # noqa: E402
    CRISIS_RESPONSE_TEMPLATE_CHILD,
    CRISIS_RESPONSE_TEMPLATE_HIGH,
    VIOLATION_REVIEW_INSTRUCTIONS,
)
from app.validators.boundary_validator import BOUNDARY_REDIRECT_TEMPLATE  # noqa: E402
from app.validators.medical_validator import MEDICAL_SAFE_REDIRECT_PHRASES  # noqa: E402


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    """Scripted fake LLM: returns or raises each item in `responses` in sequence on
    successive .invoke() calls."""

    def __init__(self, responses: list):
        self.responses = responses
        self.calls: list[str] = []

    def invoke(self, prompt: str):
        self.calls.append(prompt)
        item = self.responses[len(self.calls) - 1]
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


def safety_review_json(safe_response: str, is_clean: bool) -> str:
    return json.dumps({"is_clean": is_clean, "safe_response": safe_response})


CLEAN_FINAL_ANSWER = (
    "That's a great question. Neuroplasticity is your brain's ability to "
    "reorganize itself by forming new connections, throughout your whole "
    "life. Would you like a simple example?"
)


def make_empathy(
    final_answer=CLEAN_FINAL_ANSWER,
    emotional_state="curious",
    source="rag",
    answer_type="concept_explanation",
    topic="neuroplasticity",
    intent="concept_explanation",
    confidence=0.89,
    grounded_chunk_ids=None,
):
    return {
        "final_answer": final_answer,
        "emotional_state": emotional_state,
        "source": source,
        "answer_type": answer_type,
        "topic": topic,
        "intent": intent,
        "confidence": confidence,
        "grounded_chunk_ids": grounded_chunk_ids if grounded_chunk_ids is not None else ["c1"],
        "humanization_time_ms": 100.0,
        "error": None,
    }


def make_state(empathy=None, user_message="What is neuroplasticity?", knowledge=None):
    return {
        "user_message": user_message,
        "chat_history": [],
        "understanding": None,
        "knowledge": knowledge,
        "response": None,
        "empathy": empathy if empathy is not None else make_empathy(),
        "safety": None,
    }


def test_holistic_pass_clean_is_approved_with_one_llm_call():
    llm = FakeLLM([safety_review_json(CLEAN_FINAL_ANSWER, True)])
    result = safety_node(make_state(), llm=llm)["safety"]
    assert result["safety_status"] == "approved"
    assert result["safe_response"] == CLEAN_FINAL_ANSWER
    assert result["violations_detected"] == []
    assert result["escalation_level"] == "none"
    assert result["disclaimer_added"] is False
    assert result["error"] is None
    assert len(llm.calls) == 1


def test_crisis_high_short_circuits_with_zero_llm_calls():
    llm = FakeLLM([])
    state = make_state(user_message="I don't see the point anymore. I just want to end my life.")
    result = safety_node(state, llm=llm)["safety"]
    assert result["safety_status"] == "escalated"
    assert result["escalation_level"] == "high"
    assert result["safe_response"] == CRISIS_RESPONSE_TEMPLATE_HIGH
    assert result["violations_detected"] == []
    assert len(llm.calls) == 0


def test_crisis_high_child_context_selects_child_template():
    llm = FakeLLM([])
    state = make_state(
        user_message="My daughter told me last night she wants to kill herself."
    )
    result = safety_node(state, llm=llm)["safety"]
    assert result["safety_status"] == "escalated"
    assert result["safe_response"] == CRISIS_RESPONSE_TEMPLATE_CHILD
    assert len(llm.calls) == 0


def test_severe_distress_moderate_is_modified_not_escalated():
    llm = FakeLLM([safety_review_json("It sounds like you're carrying a lot. " + CLEAN_FINAL_ANSWER, False)])
    state = make_state(
        user_message="I have nothing left. I can't take this anymore, between therapy and everything else."
    )
    result = safety_node(state, llm=llm)["safety"]
    assert result["safety_status"] == "modified"
    assert result["escalation_level"] == "moderate"
    assert result["disclaimer_added"] is True
    assert len(llm.calls) == 1


def test_ordinary_overwhelm_without_crisis_language_is_not_escalated():
    llm = FakeLLM([safety_review_json(CLEAN_FINAL_ANSWER, True)])
    state = make_state(
        user_message="There's a whole list of reflexes to check and I don't even know where to start."
    )
    result = safety_node(state, llm=llm)["safety"]
    assert result["escalation_level"] == "none"
    assert result["safety_status"] == "approved"


def test_medical_diagnosis_phrase_triggers_modified_rewrite():
    final_answer = "Based on what you've described, you definitely have a sensory processing disorder."
    rewrite = f"{MEDICAL_SAFE_REDIRECT_PHRASES[2]} An evaluation may help clarify things."
    llm = FakeLLM([safety_review_json(rewrite, False)])
    empathy = make_empathy(final_answer=final_answer, source="llm")
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert result["safety_status"] == "modified"
    assert result["violations_detected"] == ["medical_safety"]
    assert result["disclaimer_added"] is True
    assert result["safe_response"] == rewrite
    assert len(llm.calls) == 1


def test_medical_violation_retries_after_first_rewrite_still_fails_guard():
    final_answer = "Based on what you've described, your child has ADHD."
    still_bad_rewrite = "I'd diagnose this as ADHD based on what you've shared."
    clean_rewrite = f"{MEDICAL_SAFE_REDIRECT_PHRASES[0]} It's worth raising with a professional."
    llm = FakeLLM(
        [
            safety_review_json(still_bad_rewrite, True),
            safety_review_json(clean_rewrite, False),
        ]
    )
    empathy = make_empathy(final_answer=final_answer, source="llm")
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert result["safe_response"] == clean_rewrite
    assert result["error"] is None
    assert len(llm.calls) == 2
    assert VIOLATION_REVIEW_INSTRUCTIONS["medical_safety"] in llm.calls[1]


def test_medical_violation_both_attempts_fail_falls_back_to_safe_template():
    final_answer = "Start taking medication X immediately, twice daily."
    still_bad = "You should start taking medication X right away."
    llm = FakeLLM([safety_review_json(still_bad, False), safety_review_json(still_bad, False)])
    empathy = make_empathy(final_answer=final_answer, source="llm")
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert result["safety_status"] == "modified"
    assert result["safe_response"] == MEDICAL_SAFE_REDIRECT_PHRASES[2]
    assert result["safe_response"] != final_answer
    assert result["error"] == "quality_guard_exhausted_safe_fallback"
    assert len(llm.calls) == 2


def test_fully_off_domain_answer_skips_llm_and_uses_redirect_template():
    final_answer = (
        "Python is a programming language known for being easy to read and write, "
        "often used for web development, data analysis, automation, and AI."
    )
    llm = FakeLLM([])
    empathy = make_empathy(final_answer=final_answer, source="llm", intent="general_chat")
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert result["safety_status"] == "modified"
    assert result["safe_response"] == BOUNDARY_REDIRECT_TEMPLATE
    assert result["violations_detected"] == ["domain_boundary"]
    assert len(llm.calls) == 0


def test_mixed_domain_answer_goes_through_llm_rewrite_preserving_indomain_part():
    final_answer = (
        "Sensory processing disorder is a real, well-documented challenge some "
        "children face. As for your other question, a good index fund is "
        "generally a lower-risk way to invest in the stock market than picking "
        "individual stocks."
    )
    rewrite = (
        "Sensory processing disorder is a real, well-documented challenge some "
        "children face. The investing question is outside what I'm able to help "
        "with, though -- I'm focused on ManaScience topics."
    )
    llm = FakeLLM([safety_review_json(rewrite, False)])
    empathy = make_empathy(final_answer=final_answer, source="llm")
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert len(llm.calls) == 1
    assert "Sensory processing disorder is a real" in result["safe_response"]
    assert result["violations_detected"] == ["domain_boundary"]


def test_hallucination_source_llm_flags_unverifiable_entity():
    final_answer = (
        "Dr Michael Torres at our Boston clinic specializes in exactly this kind of case."
    )
    rewrite = "I don't have verified details about a specific clinic or practitioner to point you to here."
    llm = FakeLLM([safety_review_json(rewrite, False)])
    empathy = make_empathy(final_answer=final_answer, source="llm")
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert "hallucination_risk" in result["violations_detected"]
    assert result["safety_status"] == "modified"


def test_hallucination_source_rag_grounded_entity_does_not_fire():
    final_answer = "The Sensory Integration Program is part of ManaScience's course offerings."
    knowledge = {
        "retrieved_docs": [
            {"content": "The Sensory Integration Program is a core ManaScience course."}
        ]
    }
    llm = FakeLLM([safety_review_json(final_answer, True)])
    empathy = make_empathy(final_answer=final_answer, source="rag")
    result = safety_node(make_state(empathy=empathy, knowledge=knowledge), llm=llm)["safety"]
    assert "hallucination_risk" not in result["violations_detected"]
    assert result["safety_status"] == "approved"


def test_hallucination_source_rag_ungrounded_entity_fires():
    final_answer = "The Neuroplasticity Acceleration Program is designed for this exact case."
    knowledge = {
        "retrieved_docs": [
            {"content": "ManaScience offers structured course support for primitive reflex topics."}
        ]
    }
    rewrite = "I don't have a program by that specific name, but I can share what is covered."
    llm = FakeLLM([safety_review_json(rewrite, False)])
    empathy = make_empathy(final_answer=final_answer, source="rag")
    result = safety_node(make_state(empathy=empathy, knowledge=knowledge), llm=llm)["safety"]
    assert "hallucination_risk" in result["violations_detected"]


def test_certainty_overclaim_is_softened():
    final_answer = "This therapy is guaranteed to work for your son -- it always fixes this exact issue."
    rewrite = "Many children see real improvement with this therapy, though it varies by child."
    llm = FakeLLM([safety_review_json(rewrite, False)])
    empathy = make_empathy(final_answer=final_answer, source="rag")
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert result["violations_detected"] == ["trust_overclaim"]
    assert "guaranteed to work" not in result["safe_response"].lower()


def test_identity_violation_re_check_catches_empathy_banned_phrase():
    final_answer = "Speaking as someone who's worked with families for years, I've seen this pattern often."
    rewrite = "That's a pattern that comes up across many families' experiences with this."
    llm = FakeLLM([safety_review_json(rewrite, False)])
    empathy = make_empathy(final_answer=final_answer, source="rag")
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert result["violations_detected"] == ["identity_violation"]


def test_llm_failure_with_no_guard_fired_falls_back_to_approved_unchanged():
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    llm = FakeLLM([exc, exc])
    empathy = make_empathy(final_answer=CLEAN_FINAL_ANSWER)
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert result["safety_status"] == "approved"
    assert result["safe_response"] == CLEAN_FINAL_ANSWER
    assert result["error"] == "llm_call_failure"
    assert len(llm.calls) == 2


def test_llm_failure_with_guard_fired_falls_back_to_safe_template_not_unreviewed_answer():
    final_answer = "Your child has autism. The signs you described are consistent with that diagnosis."
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    llm = FakeLLM([exc, exc])
    empathy = make_empathy(final_answer=final_answer, source="llm")
    result = safety_node(make_state(empathy=empathy), llm=llm)["safety"]
    assert result["safety_status"] == "modified"
    assert result["safe_response"] != final_answer
    assert result["safe_response"] == MEDICAL_SAFE_REDIRECT_PHRASES[2]
    assert result["error"] == "quality_guard_exhausted_safe_fallback"
    assert len(llm.calls) == 2


def test_does_not_mutate_input_state_and_passes_through_metadata():
    empathy = make_empathy(emotional_state="worried", confidence=0.73)
    state = make_state(empathy=empathy)
    original_empathy = dict(empathy)
    llm = FakeLLM([safety_review_json(CLEAN_FINAL_ANSWER, True)])
    result = safety_node(state, llm=llm)["safety"]
    assert state["empathy"] == original_empathy
    assert result["emotional_state"] == empathy["emotional_state"]
    assert result["source"] == empathy["source"]
    assert result["answer_type"] == empathy["answer_type"]
    assert result["topic"] == empathy["topic"]
    assert result["intent"] == empathy["intent"]
    assert result["confidence"] == empathy["confidence"]
    assert result["grounded_chunk_ids"] == empathy["grounded_chunk_ids"]
    assert result["original_final_answer"] == empathy["final_answer"]


def test_retrieved_docs_only_read_when_source_is_llm_no_rag_leak():
    distinctive_marker = "ZZZ_DISTINCTIVE_RETRIEVED_DOC_MARKER_ZZZ"
    knowledge = {"retrieved_docs": [{"content": distinctive_marker}]}
    empathy = make_empathy(final_answer=CLEAN_FINAL_ANSWER, source="llm")
    llm = FakeLLM([safety_review_json(CLEAN_FINAL_ANSWER, True)])
    safety_node(make_state(empathy=empathy, knowledge=knowledge), llm=llm)
    assert distinctive_marker not in llm.calls[0]


def test_safety_output_rejects_high_escalation_without_escalated_status():
    with pytest.raises(ValidationError):
        SafetyOutput(
            safe_response="some text",
            safety_status="modified",
            violations_detected=[],
            escalation_level="high",
            disclaimer_added=False,
            original_final_answer="some text",
            emotional_state="worried",
            source="rag",
            answer_type="concept_explanation",
            topic="neuroplasticity",
            intent="concept_explanation",
            confidence=0.5,
            grounded_chunk_ids=[],
            validation_time_ms=10.0,
            error=None,
        )


def test_safety_output_rejects_approved_with_violations():
    with pytest.raises(ValidationError):
        SafetyOutput(
            safe_response="some text",
            safety_status="approved",
            violations_detected=["medical_safety"],
            escalation_level="none",
            disclaimer_added=False,
            original_final_answer="some text",
            emotional_state="worried",
            source="rag",
            answer_type="concept_explanation",
            topic="neuroplasticity",
            intent="concept_explanation",
            confidence=0.5,
            grounded_chunk_ids=[],
            validation_time_ms=10.0,
            error=None,
        )
