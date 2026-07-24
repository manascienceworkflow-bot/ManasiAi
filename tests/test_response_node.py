import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import openai  # noqa: E402

from app.nodes.response_node import response_node  # noqa: E402
from app.services.response_generator import ANSWER_TYPE_BY_INTENT, INFRA_FAILURE_FALLBACK_ANSWER  # noqa: E402


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


def answer_json(answer: str) -> str:
    return json.dumps({"answer": answer})


CLEAN_ANSWER = (
    "Neuroplasticity is your brain's built-in ability to rewire itself by forming new "
    "connections between neurons across your whole lifetime, not only during "
    "childhood. This matters because it means skills, habits, and recovery from "
    "injury are not fixed -- they can change with the right kind of practice. For "
    "example, practicing a movement repeatedly in therapy strengthens the specific "
    "pathways the brain uses for that movement."
)

LONG_DOC_CONTENT = (
    "Primitive reflexes are automatic, involuntary movement patterns that are "
    "present from birth and gradually integrate as the nervous system matures over "
    "the first year of life."
)


def make_understanding(intent="concept_explanation", topic="neuroplasticity"):
    return {
        "intent": intent,
        "topic": topic,
        "search_query": f"what is {topic}",
        "emotional_state": "curious",
    }


def make_knowledge(source="rag", retrieved_docs=None, confidence=0.89):
    if retrieved_docs is None:
        retrieved_docs = (
            [
                {
                    "chunk_id": "c1",
                    "content": "Neuroplasticity is the brain's ability to reorganize and adapt.",
                    "content_type": "neuroplasticity_content",
                    "source_title": "Understanding Neuroplasticity",
                    "source_url": "https://manascience.com/learn/neuroplasticity",
                    "similarity_score": confidence,
                    "metadata": {},
                }
            ]
            if source == "rag"
            else []
        )
    return {
        "source": source,
        "retrieved_docs": retrieved_docs,
        "confidence": confidence if source == "rag" else 0.0,
        "query_used": "what is neuroplasticity",
        "intent": "concept_explanation",
        "retrieval_skipped": False,
        "content_types_searched": ["neuroplasticity_content"],
        "retrieval_time_ms": 100.0,
        "error": None,
    }


def make_dump_knowledge():
    return make_knowledge(
        source="rag",
        retrieved_docs=[
            {
                "chunk_id": "c1",
                "content": LONG_DOC_CONTENT,
                "content_type": "neuroplasticity_content",
                "source_title": "Primitive Reflexes",
                "source_url": None,
                "similarity_score": 0.81,
                "metadata": {},
            }
        ],
        confidence=0.81,
    )


def make_state(understanding=None, knowledge=None, user_message="What is neuroplasticity?"):
    return {
        "user_message": user_message,
        "chat_history": [],
        "understanding": understanding if understanding is not None else make_understanding(),
        "knowledge": knowledge if knowledge is not None else make_knowledge(),
        "response": None,
    }


def test_rag_happy_path_grounds_answer_and_passes_through_confidence():
    llm = FakeLLM([answer_json(CLEAN_ANSWER)])
    result = response_node(make_state(), llm=llm)["response"]
    assert result["source"] == "rag"
    assert result["answer_type"] == "concept_explanation"
    assert result["confidence"] == 0.89
    assert result["grounded_chunk_ids"] == ["c1"]
    assert result["error"] is None
    assert result["answer"] == CLEAN_ANSWER
    assert len(llm.calls) == 1


def test_llm_fallback_happy_path_has_empty_grounded_chunk_ids():
    knowledge = make_knowledge(source="llm")
    llm = FakeLLM([answer_json(CLEAN_ANSWER)])
    result = response_node(make_state(knowledge=knowledge), llm=llm)["response"]
    assert result["source"] == "llm"
    assert result["confidence"] == 0.0
    assert result["grounded_chunk_ids"] == []
    assert result["error"] is None


def test_answer_type_derived_from_each_intent():
    knowledge = make_knowledge(source="llm")
    for intent, expected_answer_type in ANSWER_TYPE_BY_INTENT.items():
        understanding = make_understanding(intent=intent)
        llm = FakeLLM([answer_json(CLEAN_ANSWER)])
        state = make_state(understanding=understanding, knowledge=knowledge)
        result = response_node(state, llm=llm)["response"]
        assert result["answer_type"] == expected_answer_type, intent
        assert result["intent"] == intent


def test_banned_phrase_triggers_retry_then_succeeds():
    refusal = "I'm not sure, I don't have enough information about that topic to help."
    llm = FakeLLM([answer_json(refusal), answer_json(CLEAN_ANSWER)])
    knowledge = make_knowledge(source="llm")
    result = response_node(make_state(knowledge=knowledge), llm=llm)["response"]
    assert result["answer"] == CLEAN_ANSWER
    assert result["error"] is None
    assert len(llm.calls) == 2
    assert "refusal or near-refusal" in llm.calls[1]


def test_too_short_answer_triggers_retry_then_succeeds():
    llm = FakeLLM([answer_json("Too short."), answer_json(CLEAN_ANSWER)])
    knowledge = make_knowledge(source="llm")
    result = response_node(make_state(knowledge=knowledge), llm=llm)["response"]
    assert result["answer"] == CLEAN_ANSWER
    assert result["error"] is None
    assert len(llm.calls) == 2


def test_document_dump_triggers_retry_then_succeeds():
    copied_answer = "Well, " + LONG_DOC_CONTENT + " That's the gist of it."
    rewritten_answer = (
        "Primitive reflexes are the automatic movements babies are born with, like "
        "gripping a finger placed in their palm. They usually fade on their own "
        "during the first year as a baby's nervous system develops further, which "
        "matters because reflexes that stick around longer than expected can "
        "sometimes signal a need for extra support."
    )
    llm = FakeLLM([answer_json(copied_answer), answer_json(rewritten_answer)])
    result = response_node(make_state(knowledge=make_dump_knowledge()), llm=llm)["response"]
    assert result["answer"] == rewritten_answer
    assert result["error"] is None
    assert len(llm.calls) == 2
    assert "copied wording directly" in llm.calls[1]


def test_both_attempts_copy_source_returns_best_effort_with_quality_guard_exhausted():
    """Both attempts fail only the document-dump guard (not banned-phrase or
    min-length) -- the best-effort survivor still passes ResponseOutput's stricter
    validator, so it surfaces as genuine content with error="quality_guard_exhausted"."""
    copied_answer_1 = "Well, " + LONG_DOC_CONTENT
    copied_answer_2 = LONG_DOC_CONTENT + " That's basically it."
    llm = FakeLLM([answer_json(copied_answer_1), answer_json(copied_answer_2)])
    result = response_node(make_state(knowledge=make_dump_knowledge()), llm=llm)["response"]
    assert result["error"] == "quality_guard_exhausted"
    assert result["answer"] == copied_answer_2  # longer of the two equally-violating attempts
    assert len(llm.calls) == 2


def test_both_attempts_are_refusals_escalates_to_llm_call_failure_fallback():
    """Even the 'best effort' retry survivor can still contain a banned phrase if every
    attempt refused -- in that case the node's own validator rejects it and escalates
    to the guaranteed-safe templated answer, so a refusal never reaches the user."""
    refusal_1 = "I don't know."
    refusal_2 = "I'm not sure about that one, and I don't have enough information to help further."
    llm = FakeLLM([answer_json(refusal_1), answer_json(refusal_2)])
    knowledge = make_knowledge(source="llm")
    result = response_node(make_state(knowledge=knowledge), llm=llm)["response"]
    assert result["error"] == "llm_call_failure"
    assert result["answer"] == INFRA_FAILURE_FALLBACK_ANSWER
    assert len(llm.calls) == 2


def test_llm_call_raises_both_times_returns_llm_call_failure():
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    llm = FakeLLM([exc, exc])
    knowledge = make_knowledge(source="llm")
    result = response_node(make_state(knowledge=knowledge), llm=llm)["response"]
    assert result["error"] == "llm_call_failure"
    assert result["answer"] == INFRA_FAILURE_FALLBACK_ANSWER
    assert len(llm.calls) == 2


def test_source_and_confidence_exactly_match_knowledge_input():
    knowledge = make_knowledge(source="rag", confidence=0.77)
    llm = FakeLLM([answer_json(CLEAN_ANSWER)])
    result = response_node(make_state(knowledge=knowledge), llm=llm)["response"]
    assert result["source"] == knowledge["source"]
    assert result["confidence"] == knowledge["confidence"]


def test_does_not_mutate_input_state():
    understanding = make_understanding()
    knowledge = make_knowledge()
    state = make_state(understanding=understanding, knowledge=knowledge)
    original_understanding = dict(understanding)
    original_knowledge = dict(knowledge)
    llm = FakeLLM([answer_json(CLEAN_ANSWER)])
    response_node(state, llm=llm)
    assert state["understanding"] == original_understanding
    assert state["knowledge"] == original_knowledge


def test_markdown_code_fence_stripped():
    fenced = f"```json\n{answer_json(CLEAN_ANSWER)}\n```"
    llm = FakeLLM([fenced])
    result = response_node(make_state(), llm=llm)["response"]
    assert result["answer"] == CLEAN_ANSWER
    assert len(llm.calls) == 1
