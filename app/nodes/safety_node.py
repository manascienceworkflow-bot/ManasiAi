import logging
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, model_validator

from app.graph.state import GraphState
from app.services.empathy_service import EMPATHY_BANNED_PHRASES
from app.services.safety_service import validate_response
from app.validators.medical_validator import MEDICAL_BANNED_PHRASES, MEDICAL_SAFE_REDIRECT_PHRASES

logger = logging.getLogger("app.nodes.safety_node")

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


class SafetyOutput(BaseModel):
    safe_response: str
    safety_status: Literal["approved", "modified", "escalated"]
    violations_detected: list[str]
    escalation_level: Literal["none", "moderate", "high"]
    disclaimer_added: bool
    original_final_answer: str
    emotional_state: Literal[
        "neutral", "curious", "confused", "worried", "overwhelmed", "frustrated"
    ]
    source: Literal["rag", "llm"]
    answer_type: ANSWER_TYPES
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    validation_time_ms: float
    error: Optional[str]

    @model_validator(mode="after")
    def _validate_safe_response_quality(self) -> "SafetyOutput":
        stripped = self.safe_response.strip()
        if not stripped:
            raise ValueError("safe_response must not be empty")
        lowered = stripped.lower()
        if any(phrase in lowered for phrase in MEDICAL_BANNED_PHRASES):
            raise ValueError("safe_response still contains a medical-safety violation")
        if any(phrase in lowered for phrase in EMPATHY_BANNED_PHRASES):
            raise ValueError("safe_response contains an identity-violation phrase")
        return self

    @model_validator(mode="after")
    def _validate_status_consistency(self) -> "SafetyOutput":
        if self.escalation_level == "high" and self.safety_status != "escalated":
            raise ValueError("escalation_level=='high' requires safety_status=='escalated'")
        if self.safety_status == "escalated" and self.violations_detected:
            raise ValueError("escalated turns must not carry validators-style violations")
        if self.safety_status == "approved" and (
            self.violations_detected or self.disclaimer_added
        ):
            raise ValueError("approved turns must have no violations and no disclaimer")
        return self


def safety_node(state: GraphState, llm: Optional[Any] = None) -> dict:
    """LangGraph node: review state["empathy"]["final_answer"] for medical/
    domain/hallucination/trust violations, and resolve crisis signals from
    state["user_message"].

    Pure function of (state["empathy"], state["user_message"],
    state["knowledge"]["retrieved_docs"] when source=="rag") -> partial state
    update; does not mutate any input. Returns {"safety": {...}}.
    """
    empathy = state["empathy"]
    user_message = state["user_message"]
    knowledge = state.get("knowledge")
    retrieved_docs = (
        knowledge["retrieved_docs"] if empathy["source"] == "rag" and knowledge else []
    )

    start = time.monotonic()
    try:
        result = validate_response(empathy, user_message, retrieved_docs, llm=llm)
        result["validation_time_ms"] = (time.monotonic() - start) * 1000
        validated = SafetyOutput.model_validate(result).model_dump()
    except Exception as exc:
        logger.error("safety_node_failure: topic=%r error=%s", empathy.get("topic"), exc)
        validated = _safe_fallback_result(empathy, start)

    if validated["safety_status"] == "escalated":
        logger.warning(
            "safety_escalation: escalation_level=%s elapsed_ms=%.1f",
            validated["escalation_level"],
            validated["validation_time_ms"],
        )
    logger.info(
        "safety_node ok: safety_status=%s violations=%s escalation_level=%s error=%s elapsed_ms=%.1f",
        validated["safety_status"],
        validated["violations_detected"],
        validated["escalation_level"],
        validated["error"],
        validated["validation_time_ms"],
    )
    return {"safety": validated}


def _safe_fallback_result(empathy: dict, start: float) -> dict:
    """Hand-built result that is correct by construction -- bypasses SafetyOutput
    validation entirely so this path cannot itself raise. Conservative default is
    the medical/identity safe-redirect phrase, NOT the unreviewed final_answer,
    since an unexpected internal error is not evidence the content was clean."""
    return {
        "safe_response": MEDICAL_SAFE_REDIRECT_PHRASES[2],
        "safety_status": "modified",
        "violations_detected": ["medical_safety"],
        "escalation_level": "none",
        "disclaimer_added": True,
        "original_final_answer": empathy.get("final_answer", ""),
        "emotional_state": empathy.get("emotional_state", "neutral"),
        "source": empathy.get("source", "llm"),
        "answer_type": empathy.get("answer_type", "general_knowledge"),
        "topic": empathy.get("topic", ""),
        "intent": empathy.get("intent", "general_chat"),
        "confidence": empathy.get("confidence", 0.0),
        "grounded_chunk_ids": empathy.get("grounded_chunk_ids", []),
        "validation_time_ms": (time.monotonic() - start) * 1000,
        "error": "quality_guard_exhausted_safe_fallback",
    }


def build_safety_graph():
    """Compile the full five-node StateGraph (understanding -> knowledge ->
    response -> empathy -> safety) -- the production Manasi AI pipeline."""
    from langgraph.graph import END, START, StateGraph

    from app.nodes.empathy_node import empathy_node
    from app.nodes.knowledge_node import knowledge_node
    from app.nodes.response_node import response_node
    from app.nodes.understanding_node import understanding_node

    graph = StateGraph(GraphState)
    graph.add_node("understanding_node", understanding_node)
    graph.add_node("knowledge_node", knowledge_node)
    graph.add_node("response_node", response_node)
    graph.add_node("empathy_node", empathy_node)
    graph.add_node("safety_node", safety_node)
    graph.add_edge(START, "understanding_node")
    graph.add_edge("understanding_node", "knowledge_node")
    graph.add_edge("knowledge_node", "response_node")
    graph.add_edge("response_node", "empathy_node")
    graph.add_edge("empathy_node", "safety_node")
    graph.add_edge("safety_node", END)
    return graph.compile()
