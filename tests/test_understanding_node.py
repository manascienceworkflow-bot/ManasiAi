import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import json  # noqa: E402

from app.nodes.understanding_node import FALLBACK_UNDERSTANDING, understanding_node  # noqa: E402


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    """Scripted fake LLM: returns each item in `responses` in sequence on successive .invoke() calls."""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls: list[str] = []

    def invoke(self, prompt: str):
        self.calls.append(prompt)
        text = self.responses[len(self.calls) - 1]
        return _FakeResponse(text)


VALID_JSON = json.dumps(
    {
        "intent": "concept_explanation",
        "topic": "neuroplasticity",
        "search_query": "Explain neuroplasticity in simple language",
        "emotional_state": "curious",
    }
)

GENERAL_CHAT_JSON = json.dumps(
    {
        "intent": "general_chat",
        "topic": "",
        "search_query": "",
        "emotional_state": "neutral",
    }
)


def make_state(message="Can you elaborate neuroplasticity?", history=None):
    return {"user_message": message, "chat_history": history or [], "understanding": None}


def test_successful_parse_on_first_try():
    llm = FakeLLM([VALID_JSON])
    result = understanding_node(make_state(), llm=llm)
    assert result == {
        "understanding": {
            "intent": "concept_explanation",
            "topic": "neuroplasticity",
            "search_query": "Explain neuroplasticity in simple language",
            "emotional_state": "curious",
        }
    }
    assert len(llm.calls) == 1


def test_retry_then_success_after_malformed_json():
    llm = FakeLLM(["not valid json {{{", VALID_JSON])
    result = understanding_node(make_state(), llm=llm)
    assert result["understanding"]["intent"] == "concept_explanation"
    assert len(llm.calls) == 2
    assert "previous output was not valid JSON" in llm.calls[1]


def test_retry_then_fallback_after_two_malformed_responses():
    llm = FakeLLM(["not json", "still not json"])
    result = understanding_node(make_state(), llm=llm)
    assert result == {"understanding": dict(FALLBACK_UNDERSTANDING)}
    assert len(llm.calls) == 2


def test_business_rule_validator_rejects_empty_topic_for_non_general_chat():
    bad_json = json.dumps(
        {
            "intent": "concept_explanation",
            "topic": "",
            "search_query": "",
            "emotional_state": "curious",
        }
    )
    llm = FakeLLM([bad_json, VALID_JSON])
    result = understanding_node(make_state(), llm=llm)
    assert len(llm.calls) == 2
    assert result["understanding"]["intent"] == "concept_explanation"
    assert result["understanding"]["topic"] == "neuroplasticity"


def test_general_chat_happy_path_with_empty_fields_is_valid():
    llm = FakeLLM([GENERAL_CHAT_JSON])
    result = understanding_node(make_state(message="Hi Manasi!"), llm=llm)
    assert result["understanding"] == {
        "intent": "general_chat",
        "topic": "",
        "search_query": "",
        "emotional_state": "neutral",
    }
    assert len(llm.calls) == 1


def test_chat_history_formatted_into_prompt():
    history = [
        {"role": "user", "content": "What therapies for attention issues in children?"},
        {"role": "assistant", "content": "We offer several options for children."},
    ]
    llm = FakeLLM([VALID_JSON])
    understanding_node(make_state(message="What about for adults?", history=history), llm=llm)
    sent_prompt = llm.calls[0]
    assert "User: What therapies for attention issues in children?" in sent_prompt
    assert "Manasi: We offer several options for children." in sent_prompt
    assert "What about for adults?" in sent_prompt


def test_does_not_mutate_input_state():
    state = make_state(history=[{"role": "user", "content": "hello"}])
    original_message = state["user_message"]
    original_history = list(state["chat_history"])
    llm = FakeLLM([GENERAL_CHAT_JSON])
    understanding_node(state, llm=llm)
    assert state["user_message"] == original_message
    assert state["chat_history"] == original_history


def test_markdown_code_fence_stripped():
    fenced = f"```json\n{VALID_JSON}\n```"
    llm = FakeLLM([fenced])
    result = understanding_node(make_state(), llm=llm)
    assert result["understanding"]["intent"] == "concept_explanation"
    assert len(llm.calls) == 1
