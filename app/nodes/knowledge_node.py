import logging
import time
from typing import Any, Literal, Optional

import chromadb.errors
import openai
from pydantic import BaseModel, model_validator

from app.config import settings
from app.graph.state import GraphState
from app.rag.retriever import retrieve

logger = logging.getLogger("app.nodes.knowledge_node")

CONTENT_TYPES = Literal[
    "course",
    "blog",
    "research_article",
    "faq",
    "practitioner_info",
    "therapy_info",
    "website_content",
    "neuroplasticity_content",
    "pdf_document",
]

# Common envelope fields stored on every chunk's metadata (app/rag/chroma_client.py / build_knowledge_index.py);
# excluded from RetrievedDocument.metadata since they're already surfaced as top-level fields.
_COMMON_METADATA_KEYS = {
    "chunk_id",
    "content_type",
    "source_id",
    "source_title",
    "source_url",
    "chunk_index",
    "ingested_at",
}


class RetrievedDocumentModel(BaseModel):
    chunk_id: str
    content: str
    content_type: CONTENT_TYPES
    source_title: str
    source_url: Optional[str]
    similarity_score: float
    metadata: dict


class KnowledgeOutput(BaseModel):
    source: Literal["rag", "llm"]
    retrieved_docs: list[RetrievedDocumentModel]
    confidence: float
    query_used: str
    intent: str
    retrieval_skipped: bool
    content_types_searched: list[str]
    retrieval_time_ms: float
    error: Optional[str]

    @model_validator(mode="after")
    def _validate_source_consistency(self) -> "KnowledgeOutput":
        if self.source == "llm":
            if self.retrieved_docs or self.confidence != 0.0:
                raise ValueError("source=='llm' requires empty retrieved_docs and confidence==0.0")
        else:
            if not self.retrieved_docs or self.confidence <= 0.0:
                raise ValueError("source=='rag' requires non-empty retrieved_docs and confidence>0.0")
        if len(self.retrieved_docs) > settings.knowledge_max_returned_chunks:
            raise ValueError("retrieved_docs exceeds knowledge_max_returned_chunks")
        return self


def _skipped_result(understanding: dict) -> dict:
    return {
        "source": "llm",
        "retrieved_docs": [],
        "confidence": 0.0,
        "query_used": "",
        "intent": understanding["intent"],
        "retrieval_skipped": True,
        "content_types_searched": [],
        "error": None,
    }


def _error_result(understanding: dict, error: str) -> dict:
    return {
        "source": "llm",
        "retrieved_docs": [],
        "confidence": 0.0,
        "query_used": understanding["search_query"],
        "intent": understanding["intent"],
        "retrieval_skipped": False,
        "content_types_searched": [],
        "error": error,
    }


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, openai.OpenAIError):
        return "embedding_failure"
    return "vectorstore_unavailable"


def _decide_source(scored_chunks: list[tuple[Any, float]]) -> tuple[str, float, list[tuple[Any, float]]]:
    relevant = [(doc, score) for doc, score in scored_chunks if score >= settings.rag_similarity_threshold]
    relevant.sort(key=lambda pair: pair[1], reverse=True)

    if len(relevant) >= settings.rag_min_relevant_chunks:
        return "rag", round(relevant[0][1], 2), relevant
    return "llm", 0.0, []


def _to_retrieved_document(doc: Any, score: float) -> dict:
    metadata = doc.metadata
    type_specific = {k: v for k, v in metadata.items() if k not in _COMMON_METADATA_KEYS}
    return {
        "chunk_id": metadata.get("chunk_id", ""),
        "content": doc.page_content,
        "content_type": metadata.get("content_type", ""),
        "source_title": metadata.get("source_title", ""),
        "source_url": metadata.get("source_url"),
        "similarity_score": round(score, 2),
        "metadata": type_specific,
    }


def _cap_by_context_chars(docs: list[dict]) -> list[dict]:
    result: list[dict] = []
    total = 0
    for doc in docs:
        content_len = len(doc["content"])
        if result and total + content_len > settings.knowledge_max_context_chars:
            break
        result.append(doc)
        total += content_len
    return result


def _aggregate_and_cap(relevant: list[tuple[Any, float]]) -> list[dict]:
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for doc, score in relevant:
        retrieved = _to_retrieved_document(doc, score)
        if retrieved["chunk_id"] in seen_ids:
            continue
        seen_ids.add(retrieved["chunk_id"])
        deduped.append(retrieved)

    capped = deduped[: settings.knowledge_max_returned_chunks]
    return _cap_by_context_chars(capped)


def knowledge_node(state: GraphState, retriever: Optional[Any] = None) -> dict:
    """LangGraph node: retrieve ManaScience knowledge for the current turn's understanding.

    Pure function of state["understanding"] -> partial state update; does not mutate
    user_message, chat_history, or understanding. Returns {"knowledge": {...}}.
    """
    understanding = state["understanding"]
    retriever = retriever or retrieve

    if understanding["intent"] == "general_chat":
        result = _skipped_result(understanding)
        result["retrieval_time_ms"] = 0.0
        logger.info("knowledge_node skipped: intent=general_chat")
        return {"knowledge": KnowledgeOutput.model_validate(result).model_dump()}

    start = time.monotonic()
    try:
        scored_chunks, content_types_searched = retriever(
            understanding["search_query"], understanding["intent"]
        )
    except (chromadb.errors.ChromaError, openai.OpenAIError, OSError) as exc:
        logger.error(
            "knowledge_node_failure: query=%r error=%s", understanding["search_query"], exc
        )
        result = _error_result(understanding, error=_classify_error(exc))
        result["retrieval_time_ms"] = (time.monotonic() - start) * 1000
        return {"knowledge": KnowledgeOutput.model_validate(result).model_dump()}

    # Aggregation + validation are wrapped too: a retrieved chunk with a missing
    # or unrecognized content_type would otherwise raise a ValidationError out of
    # the node (a 500), unlike every other node which degrades gracefully. On any
    # such failure, fall back to an llm-source result instead of crashing.
    try:
        source, confidence, relevant = _decide_source(scored_chunks)
        retrieved_docs = _aggregate_and_cap(relevant) if source == "rag" else []

        result = {
            "source": source,
            "retrieved_docs": retrieved_docs,
            "confidence": confidence,
            "query_used": understanding["search_query"],
            "intent": understanding["intent"],
            "retrieval_skipped": False,
            "content_types_searched": content_types_searched,
            "error": None,
        }
        result["retrieval_time_ms"] = (time.monotonic() - start) * 1000

        validated = KnowledgeOutput.model_validate(result).model_dump()
    except Exception as exc:
        logger.error(
            "knowledge_node_processing_failure: query=%r error=%s",
            understanding["search_query"], exc,
        )
        result = _error_result(understanding, error="malformed_retrieval")
        result["retrieval_time_ms"] = (time.monotonic() - start) * 1000
        return {"knowledge": KnowledgeOutput.model_validate(result).model_dump()}

    logger.info(
        "knowledge_node ok: query=%r source=%s confidence=%.2f elapsed_ms=%.1f",
        understanding["search_query"],
        validated["source"],
        validated["confidence"],
        validated["retrieval_time_ms"],
    )
    return {"knowledge": validated}


def build_knowledge_graph():
    """Compile a two-node StateGraph (understanding -> knowledge) for Phase 2 isolated testing/deployment."""
    from langgraph.graph import END, START, StateGraph

    from app.nodes.understanding_node import understanding_node

    graph = StateGraph(GraphState)
    graph.add_node("understanding_node", understanding_node)
    graph.add_node("knowledge_node", knowledge_node)
    graph.add_edge(START, "understanding_node")
    graph.add_edge("understanding_node", "knowledge_node")
    graph.add_edge("knowledge_node", END)
    return graph.compile()
