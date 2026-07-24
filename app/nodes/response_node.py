import logging
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, model_validator

from app.config import settings
from app.graph.state import GraphState
from app.services.response_generator import (
    ANSWER_TYPE_BY_INTENT,
    BANNED_PHRASES,
    INFRA_FAILURE_FALLBACK_ANSWER,
    generate_response,
)

logger = logging.getLogger("app.nodes.response_node")

ANSWER_TYPES = Literal[
    "concept_explanation",
    "therapy_information",
    "course_information",
    "research_summary",
    "website_information",
    "personal_guidance",
    "supportive_information",
    "general_knowledge",
]


class ResponseOutput(BaseModel):
    answer: str
    source: Literal["rag", "llm"]
    answer_type: ANSWER_TYPES
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    generation_time_ms: float
    error: Optional[str]

    @model_validator(mode="after")
    def _validate_answer_quality(self) -> "ResponseOutput":
        stripped = self.answer.strip()
        if len(stripped) < settings.response_min_answer_length:
            raise ValueError("answer shorter than response_min_answer_length")
        lowered = stripped.lower()
        if any(phrase in lowered for phrase in BANNED_PHRASES):
            raise ValueError("answer contains a banned refusal phrase")
        return self

    @model_validator(mode="after")
    def _validate_source_consistency(self) -> "ResponseOutput":
        if self.source == "llm" and self.grounded_chunk_ids:
            raise ValueError("source=='llm' requires empty grounded_chunk_ids")
        if self.source == "rag" and not self.grounded_chunk_ids:
            raise ValueError("source=='rag' requires non-empty grounded_chunk_ids")
        return self


def response_node(state: GraphState, llm: Optional[Any] = None) -> dict:
    """LangGraph node: generate a simplified, freshly-written answer for the current
    turn's understanding + knowledge.

    Pure function of (state["understanding"], state["knowledge"], state["user_message"])
    -> partial state update; does not mutate any input. Returns {"response": {...}}.
    """
    understanding = state["understanding"]
    knowledge = state["knowledge"]

    start = time.monotonic()
    try:
        result = generate_response(understanding, knowledge, state["user_message"], llm=llm)
        result["generation_time_ms"] = (time.monotonic() - start) * 1000
        validated = ResponseOutput.model_validate(result).model_dump()
    except Exception as exc:
        # generate_response is designed to never raise, and its own best-effort
        # fallback is designed to always pass ResponseOutput's checks -- but if either
        # assumption is ever violated (an unforeseen bug, or a best-effort answer that
        # still fails the quality validator), fall through to a hand-built, guaranteed
        # -safe result instead of letting the exception escape (FR-12: never raise).
        logger.error("response_node_failure: topic=%r error=%s", understanding.get("topic"), exc)
        validated = _safe_fallback_result(understanding, knowledge, start)

    logger.info(
        "response_node ok: intent=%s source=%s answer_type=%s error=%s elapsed_ms=%.1f",
        validated["intent"],
        validated["source"],
        validated["answer_type"],
        validated["error"],
        validated["generation_time_ms"],
    )
    return {"response": validated}


def _safe_fallback_result(understanding: dict, knowledge: dict, start: float) -> dict:
    """Hand-built result that is correct by construction -- bypasses ResponseOutput
    validation entirely so this path cannot itself raise."""
    source = knowledge.get("source", "llm")
    intent = understanding.get("intent", "general_chat")
    retrieved_docs = knowledge.get("retrieved_docs", []) if source == "rag" else []
    return {
        "answer": INFRA_FAILURE_FALLBACK_ANSWER,
        "source": source,
        "answer_type": ANSWER_TYPE_BY_INTENT.get(intent, "general_knowledge"),
        "topic": understanding.get("topic", ""),
        "intent": intent,
        "confidence": knowledge.get("confidence", 0.0),
        "grounded_chunk_ids": [doc["chunk_id"] for doc in retrieved_docs],
        "generation_time_ms": (time.monotonic() - start) * 1000,
        "error": "llm_call_failure",
    }


def build_response_graph():
    """Compile a three-node StateGraph (understanding -> knowledge -> response) for
    Phase 3 isolated testing/deployment."""
    from langgraph.graph import END, START, StateGraph

    from app.nodes.knowledge_node import knowledge_node
    from app.nodes.understanding_node import understanding_node

    graph = StateGraph(GraphState)
    graph.add_node("understanding_node", understanding_node)
    graph.add_node("knowledge_node", knowledge_node)
    graph.add_node("response_node", response_node)
    graph.add_edge(START, "understanding_node")
    graph.add_edge("understanding_node", "knowledge_node")
    graph.add_edge("knowledge_node", "response_node")
    graph.add_edge("response_node", END)
    return graph.compile()
