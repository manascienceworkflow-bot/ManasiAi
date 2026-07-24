import json
import logging
import time
from pathlib import Path
from typing import Any, Literal, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError, model_validator

from app.config import settings
from app.graph.state import ChatTurn, GraphState, Understanding

logger = logging.getLogger("app.nodes.understanding_node")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "understanding_prompt.txt"
_PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")

FALLBACK_UNDERSTANDING: Understanding = {
    "intent": "general_chat",
    "topic": "",
    "search_query": "",
    "emotional_state": "neutral",
}

CORRECTIVE_REPROMPT_SUFFIX = (
    "\n\nYour previous output was not valid JSON matching the required schema. "
    "Return ONLY a valid JSON object with the four required fields: "
    "intent, topic, search_query, emotional_state."
)


class UnderstandingOutput(BaseModel):
    intent: Literal[
        "concept_explanation",
        "therapy_information",
        "course_information",
        "research_information",
        "website_information",
        "personal_concern",
        "emotional_support",
        "general_chat",
    ]
    topic: str
    search_query: str
    emotional_state: Literal[
        "neutral", "curious", "confused", "worried", "overwhelmed", "frustrated"
    ]

    @model_validator(mode="after")
    def _validate_empty_fields_match_general_chat(self) -> "UnderstandingOutput":
        is_general_chat = self.intent == "general_chat"
        topic_empty = self.topic == ""
        query_empty = self.search_query == ""
        if is_general_chat and not (topic_empty and query_empty):
            raise ValueError("general_chat must have empty topic and search_query")
        if not is_general_chat and (topic_empty or query_empty):
            raise ValueError("non-general_chat intent must have non-empty topic and search_query")
        return self


def _build_llm() -> ChatOpenAI:
    return ChatOpenAI(model=settings.understanding_model, temperature=0)


def _format_history(chat_history: list[ChatTurn]) -> str:
    if not chat_history:
        return "(no prior turns)"
    lines = []
    for turn in chat_history:
        speaker = "User" if turn["role"] == "user" else "Manasi"
        lines.append(f"{speaker}: {turn['content']}")
    return "\n".join(lines)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _build_prompt(user_message: str, chat_history: list[ChatTurn]) -> str:
    return (
        _PROMPT_TEMPLATE.replace("{{chat_history}}", _format_history(chat_history))
        .replace("{{user_message}}", user_message.strip())
    )


def _parse_and_validate(raw_text: str) -> UnderstandingOutput:
    cleaned = _strip_code_fences(raw_text)
    parsed = json.loads(cleaned)
    return UnderstandingOutput.model_validate(parsed)


def _invoke(llm: Any, prompt: str) -> str:
    response = llm.invoke(prompt)
    return response.content if hasattr(response, "content") else str(response)


def understanding_node(state: GraphState, llm: Optional[Any] = None) -> dict:
    """LangGraph node: classify user_message + chat_history into structured understanding.

    Pure function of state -> partial state update; does not mutate state["user_message"]
    or state["chat_history"]. Returns {"understanding": {...}} for LangGraph to merge.
    """
    llm = llm or _build_llm()
    user_message = state["user_message"]
    chat_history = state.get("chat_history", [])

    start = time.monotonic()
    prompt = _build_prompt(user_message, chat_history)

    try:
        result = _parse_and_validate(_invoke(llm, prompt))
    except (json.JSONDecodeError, ValidationError) as first_error:
        logger.warning("understanding_node retry triggered: %s", first_error)
        try:
            retry_prompt = prompt + CORRECTIVE_REPROMPT_SUFFIX
            result = _parse_and_validate(_invoke(llm, retry_prompt))
        except (json.JSONDecodeError, ValidationError) as second_error:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error(
                "understanding_node_failure: message=%r error=%s elapsed_ms=%.1f",
                user_message,
                second_error,
                elapsed_ms,
            )
            return {"understanding": dict(FALLBACK_UNDERSTANDING)}

    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(
        "understanding_node ok: message=%r intent=%s emotional_state=%s elapsed_ms=%.1f",
        user_message,
        result.intent,
        result.emotional_state,
        elapsed_ms,
    )
    return {
        "understanding": {
            "intent": result.intent,
            "topic": result.topic,
            "search_query": result.search_query,
            "emotional_state": result.emotional_state,
        }
    }


def build_understanding_graph():
    """Compile a minimal single-node StateGraph for Phase 1 isolated testing/deployment."""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(GraphState)
    graph.add_node("understanding_node", understanding_node)
    graph.add_edge(START, "understanding_node")
    graph.add_edge("understanding_node", END)
    return graph.compile()
