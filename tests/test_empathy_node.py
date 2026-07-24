import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import openai  # noqa: E402

from app.nodes.empathy_node import empathy_node  # noqa: E402
from app.services.empathy_service import (  # noqa: E402
    CORRECTIVE_REPROMPT_SUFFIX_FACT_DROP,
    CORRECTIVE_REPROMPT_SUFFIX_IDENTITY,
    CORRECTIVE_REPROMPT_SUFFIX_MALFORMED,
    CORRECTIVE_REPROMPT_SUFFIX_TOO_LONG,
    CORRECTIVE_REPROMPT_SUFFIX_TOO_SHORT,
    EMOTIONAL_TONE_INSTRUCTIONS,
)


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


def final_answer_json(final_answer: str) -> str:
    return json.dumps({"final_answer": final_answer})


CLEAN_ANSWER = (
    "Neuroplasticity is the brain's ability to reorganize itself by forming new "
    "neural connections throughout life. Researchers at Stanford have tracked this in "
    "over 200 participants since 1960."
)

CLEAN_FINAL_ANSWER = (
    "Thanks for asking! Neuroplasticity is your brain's incredible ability to reorganize "
    "itself by forming new connections throughout your whole life. Researchers at Stanford "
    "have actually tracked this in over 200 participants going back to 1960, which is "
    "pretty remarkable. Want me to share more about what they found?"
)

IDENTITY_VIOLATION_FINAL_ANSWER = (
    "That's such a relatable question -- speaking as someone who has spent a lot of time "
    "with this topic, your brain's ability to reorganize itself by forming new connections "
    "throughout your whole life is remarkable. Researchers at Stanford have tracked this in "
    "over 200 participants since 1960, which I find truly fascinating. Want to hear more?"
)

TOO_SHORT_FINAL_ANSWER = "Researchers at Stanford tracked 200 people since 1960."

TOO_LONG_FINAL_ANSWER = (
    "Oh, what a truly wonderful and thoughtful question for you to bring to me today, and "
    "I am so glad that you took a moment out of your day to ask about this fascinating "
    "subject, because honestly, neuroplasticity is such a wonderful and extraordinary topic "
    "that more people should really take time to think carefully and slowly about whenever "
    "they get the chance. Anyway, getting back to your actual question now, your brain "
    "truly has this remarkable, almost magical ability to reorganize itself over and over "
    "again by forming brand new connections throughout your entire life, and interestingly "
    "enough, researchers working at Stanford have actually tracked this exact phenomenon "
    "happening in over 200 different participants going all the way back to 1960, which I "
    "personally find absolutely fascinating and remarkable to think about."
)

FACT_DROP_FINAL_ANSWER = (
    "Thanks for asking! Neuroplasticity is your brain incredible ability to reorganize "
    "itself by forming new connections throughout your whole life, and people have studied "
    "this for a long time. Pretty amazing, right? Let me know if you want to explore more!"
)

# Fails both the length guard (too short) and the fact-retention guard simultaneously.
MULTI_FAIL_FINAL_ANSWER = "Your brain can change a lot over your whole life."

MALFORMED_OUTPUT = "Sure, here's my answer: the brain can change!"


def make_response(
    answer=CLEAN_ANSWER,
    source="rag",
    answer_type="concept_explanation",
    topic="neuroplasticity",
    intent="concept_explanation",
    confidence=0.89,
    grounded_chunk_ids=None,
):
    return {
        "answer": answer,
        "source": source,
        "answer_type": answer_type,
        "topic": topic,
        "intent": intent,
        "confidence": confidence,
        "grounded_chunk_ids": grounded_chunk_ids if grounded_chunk_ids is not None else ["c1"],
        "generation_time_ms": 100.0,
        "error": None,
    }


def make_understanding(emotional_state="curious"):
    return {
        "intent": "concept_explanation",
        "topic": "neuroplasticity",
        "search_query": "what is neuroplasticity",
        "emotional_state": emotional_state,
    }


def make_state(response=None, understanding=None, user_message="What is neuroplasticity?"):
    return {
        "user_message": user_message,
        "chat_history": [],
        "understanding": understanding if understanding is not None else make_understanding(),
        "knowledge": None,
        "response": response if response is not None else make_response(),
        "empathy": None,
    }


def test_happy_path_passes_through_all_response_fields():
    llm = FakeLLM([final_answer_json(CLEAN_FINAL_ANSWER)])
    response = make_response()
    understanding = make_understanding(emotional_state="worried")
    result = empathy_node(make_state(response=response, understanding=understanding), llm=llm)["empathy"]
    assert result["final_answer"] == CLEAN_FINAL_ANSWER
    assert result["final_answer"] != response["answer"]
    assert result["emotional_state"] == "worried"
    assert result["source"] == response["source"]
    assert result["answer_type"] == response["answer_type"]
    assert result["topic"] == response["topic"]
    assert result["intent"] == response["intent"]
    assert result["confidence"] == response["confidence"]
    assert result["grounded_chunk_ids"] == response["grounded_chunk_ids"]
    assert result["error"] is None
    assert len(llm.calls) == 1


def test_emotional_state_comes_from_understanding_not_response():
    llm = FakeLLM([final_answer_json(CLEAN_FINAL_ANSWER)])
    understanding = make_understanding(emotional_state="frustrated")
    result = empathy_node(make_state(understanding=understanding), llm=llm)["empathy"]
    assert result["emotional_state"] == "frustrated"
    assert EMOTIONAL_TONE_INSTRUCTIONS["frustrated"] in llm.calls[0]


def test_identity_violation_guard_triggers_retry_then_succeeds():
    llm = FakeLLM(
        [final_answer_json(IDENTITY_VIOLATION_FINAL_ANSWER), final_answer_json(CLEAN_FINAL_ANSWER)]
    )
    result = empathy_node(make_state(), llm=llm)["empathy"]
    assert result["final_answer"] == CLEAN_FINAL_ANSWER
    assert result["error"] is None
    assert len(llm.calls) == 2
    assert CORRECTIVE_REPROMPT_SUFFIX_IDENTITY in llm.calls[1]


def test_too_short_answer_triggers_retry_then_succeeds():
    llm = FakeLLM(
        [final_answer_json(TOO_SHORT_FINAL_ANSWER), final_answer_json(CLEAN_FINAL_ANSWER)]
    )
    result = empathy_node(make_state(), llm=llm)["empathy"]
    assert result["final_answer"] == CLEAN_FINAL_ANSWER
    assert result["error"] is None
    assert len(llm.calls) == 2
    assert CORRECTIVE_REPROMPT_SUFFIX_TOO_SHORT in llm.calls[1]


def test_too_long_answer_triggers_retry_then_succeeds():
    llm = FakeLLM(
        [final_answer_json(TOO_LONG_FINAL_ANSWER), final_answer_json(CLEAN_FINAL_ANSWER)]
    )
    result = empathy_node(make_state(), llm=llm)["empathy"]
    assert result["final_answer"] == CLEAN_FINAL_ANSWER
    assert result["error"] is None
    assert len(llm.calls) == 2
    assert CORRECTIVE_REPROMPT_SUFFIX_TOO_LONG in llm.calls[1]


def test_fact_drop_triggers_retry_then_succeeds():
    llm = FakeLLM(
        [final_answer_json(FACT_DROP_FINAL_ANSWER), final_answer_json(CLEAN_FINAL_ANSWER)]
    )
    result = empathy_node(make_state(), llm=llm)["empathy"]
    assert result["final_answer"] == CLEAN_FINAL_ANSWER
    assert result["error"] is None
    assert len(llm.calls) == 2
    assert CORRECTIVE_REPROMPT_SUFFIX_FACT_DROP in llm.calls[1]


def test_multiple_guard_failures_concatenate_correct_suffixes_only():
    llm = FakeLLM(
        [final_answer_json(MULTI_FAIL_FINAL_ANSWER), final_answer_json(CLEAN_FINAL_ANSWER)]
    )
    result = empathy_node(make_state(), llm=llm)["empathy"]
    assert result["error"] is None
    assert len(llm.calls) == 2
    retry_prompt = llm.calls[1]
    assert CORRECTIVE_REPROMPT_SUFFIX_TOO_SHORT in retry_prompt
    assert CORRECTIVE_REPROMPT_SUFFIX_FACT_DROP in retry_prompt
    assert CORRECTIVE_REPROMPT_SUFFIX_TOO_LONG not in retry_prompt
    assert CORRECTIVE_REPROMPT_SUFFIX_IDENTITY not in retry_prompt


def test_both_attempts_fail_guard_falls_back_to_verbatim_answer():
    llm = FakeLLM(
        [final_answer_json(FACT_DROP_FINAL_ANSWER), final_answer_json(FACT_DROP_FINAL_ANSWER)]
    )
    response = make_response()
    result = empathy_node(make_state(response=response), llm=llm)["empathy"]
    assert result["final_answer"] == response["answer"]
    assert result["error"] == "quality_guard_exhausted"
    assert len(llm.calls) == 2


def test_both_llm_calls_raise_falls_back_with_llm_call_failure():
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    llm = FakeLLM([exc, exc])
    response = make_response()
    result = empathy_node(make_state(response=response), llm=llm)["empathy"]
    assert result["final_answer"] == response["answer"]
    assert result["error"] == "llm_call_failure"
    assert len(llm.calls) == 2


def test_mixed_failure_first_raises_second_fails_guard_is_quality_guard_exhausted():
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    llm = FakeLLM([exc, final_answer_json(FACT_DROP_FINAL_ANSWER)])
    response = make_response()
    result = empathy_node(make_state(response=response), llm=llm)["empathy"]
    assert result["final_answer"] == response["answer"]
    assert result["error"] == "quality_guard_exhausted"
    assert len(llm.calls) == 2


def test_malformed_json_first_attempt_triggers_retry_then_succeeds():
    llm = FakeLLM([MALFORMED_OUTPUT, final_answer_json(CLEAN_FINAL_ANSWER)])
    result = empathy_node(make_state(), llm=llm)["empathy"]
    assert result["final_answer"] == CLEAN_FINAL_ANSWER
    assert result["error"] is None
    assert len(llm.calls) == 2
    assert CORRECTIVE_REPROMPT_SUFFIX_MALFORMED in llm.calls[1]


def test_does_not_mutate_input_state():
    response = make_response()
    understanding = make_understanding()
    state = make_state(response=response, understanding=understanding)
    original_response = dict(response)
    original_understanding = dict(understanding)
    llm = FakeLLM([final_answer_json(CLEAN_FINAL_ANSWER)])
    empathy_node(state, llm=llm)
    assert state["response"] == original_response
    assert state["understanding"] == original_understanding


def test_markdown_code_fence_stripped():
    fenced = f"```json\n{final_answer_json(CLEAN_FINAL_ANSWER)}\n```"
    llm = FakeLLM([fenced])
    result = empathy_node(make_state(), llm=llm)["empathy"]
    assert result["final_answer"] == CLEAN_FINAL_ANSWER
    assert len(llm.calls) == 1


def test_six_emotional_states_each_select_correct_tone_block():
    for state_name, tone_text in EMOTIONAL_TONE_INSTRUCTIONS.items():
        llm = FakeLLM([final_answer_json(CLEAN_FINAL_ANSWER)])
        understanding = make_understanding(emotional_state=state_name)
        result = empathy_node(make_state(understanding=understanding), llm=llm)["empathy"]
        assert result["emotional_state"] == state_name
        assert tone_text in llm.calls[0]


def test_node_does_not_read_user_message_or_chat_history_or_knowledge():
    distinctive_message = "ZZZ_DISTINCTIVE_USER_MESSAGE_ZZZ"
    llm = FakeLLM([final_answer_json(CLEAN_FINAL_ANSWER)])
    state = make_state(user_message=distinctive_message)
    assert state["knowledge"] is None
    result = empathy_node(state, llm=llm)["empathy"]
    assert result["error"] is None
    assert distinctive_message not in llm.calls[0]
