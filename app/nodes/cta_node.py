import logging
import time
from typing import Literal, Optional

from pydantic import BaseModel, model_validator

from app.graph.state import GraphState
from app.services.cta_service import process

logger = logging.getLogger("app.nodes.cta_node")


class CTAOutput(BaseModel):
    cta_found: bool
    cta_id: Optional[str]
    cta_url: Optional[str]
    cta_trigger: Optional[str]
    cta_category: Optional[str]
    match_reason: Literal["specific_match", "category_fallback", "no_match"]
    matched_phrase: Optional[str]
    response: str
    lookup_time_ms: float
    error: Optional[str]

    @model_validator(mode="after")
    def _validate_found_consistency(self) -> "CTAOutput":
        if self.cta_found:
            if not (self.cta_id and self.cta_url and self.cta_trigger and self.cta_category):
                raise ValueError("cta_found=True requires cta_id, cta_url, cta_trigger, and cta_category")
            if self.match_reason == "no_match":
                raise ValueError("cta_found=True is inconsistent with match_reason=='no_match'")
        else:
            if self.cta_id or self.cta_url or self.cta_trigger or self.cta_category or self.matched_phrase:
                raise ValueError("cta_found=False requires every CTA field to be null")
            if self.match_reason != "no_match":
                raise ValueError("cta_found=False requires match_reason=='no_match'")
        return self


def cta_node(state: GraphState) -> dict:
    """LangGraph node: decide whether state["safety"]["safe_response"] should
    carry a CTA, using only state["user_message"], state["understanding"], and
    app.services.cta_loader (via cta_service).

    Pure function of (state["user_message"], state["understanding"],
    state["safety"]["safe_response"]) -> partial state update; does not mutate
    any input, and never reads state["knowledge"] or state["empathy"]. Returns
    {"cta": {...}}.
    """
    user_message = state["user_message"]
    understanding = state.get("understanding") or {}
    safe_response = state["safety"]["safe_response"]

    start = time.monotonic()
    try:
        result = process(user_message, understanding, safe_response)
        result["lookup_time_ms"] = (time.monotonic() - start) * 1000
        result["error"] = None
        validated = CTAOutput.model_validate(result).model_dump()
    except Exception as exc:
        logger.error("cta_node_failure: error=%s", exc)
        validated = _safe_fallback_result(safe_response, start)

    logger.info(
        "cta_node ok: cta_found=%s cta_id=%s match_reason=%s error=%s elapsed_ms=%.2f",
        validated["cta_found"],
        validated["cta_id"],
        validated["match_reason"],
        validated["error"],
        validated["lookup_time_ms"],
    )
    return {"cta": validated}


def _safe_fallback_result(safe_response: str, start: float) -> dict:
    """Hand-built result that is correct by construction -- bypasses CTAOutput
    validation entirely so this path cannot itself raise. Always cta_found=False:
    an internal error is not evidence a CTA exists, so the conservative outcome
    is no CTA, exactly mirroring safety_node/empathy_node's posture toward their
    own internal failures."""
    return {
        "cta_found": False,
        "cta_id": None,
        "cta_url": None,
        "cta_trigger": None,
        "cta_category": None,
        "match_reason": "no_match",
        "matched_phrase": None,
        "response": safe_response,
        "lookup_time_ms": (time.monotonic() - start) * 1000,
        "error": "cta_lookup_failure",
    }


def build_cta_graph():
    """Compile the full six-node StateGraph (understanding -> knowledge ->
    response -> empathy -> safety -> cta) -- the complete Manasi AI pipeline."""
    from langgraph.graph import END, START, StateGraph

    from app.nodes.empathy_node import empathy_node
    from app.nodes.knowledge_node import knowledge_node
    from app.nodes.response_node import response_node
    from app.nodes.safety_node import safety_node
    from app.nodes.understanding_node import understanding_node

    graph = StateGraph(GraphState)
    graph.add_node("understanding_node", understanding_node)
    graph.add_node("knowledge_node", knowledge_node)
    graph.add_node("response_node", response_node)
    graph.add_node("empathy_node", empathy_node)
    graph.add_node("safety_node", safety_node)
    graph.add_node("cta_node", cta_node)
    graph.add_edge(START, "understanding_node")
    graph.add_edge("understanding_node", "knowledge_node")
    graph.add_edge("knowledge_node", "response_node")
    graph.add_edge("response_node", "empathy_node")
    graph.add_edge("empathy_node", "safety_node")
    graph.add_edge("safety_node", "cta_node")
    graph.add_edge("cta_node", END)
    return graph.compile()
