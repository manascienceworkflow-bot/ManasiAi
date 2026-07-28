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
    # Structured knowledge corpora (data/knowledge/**). Mirrors app/graph/state.py.
    "concern_knowledge",
    "condition_knowledge",
    "therapy_knowledge",
    "assessment_knowledge",
    "milestone_knowledge",
]

CONCERN_CONTENT_TYPE = "concern_knowledge"
MATCHER_SECTION = "matcher"

# Corroboration across sections is evidence, but it must never let a broadly-mediocre
# concern beat a strongly-matched one -- hence the cap.
_SECTION_BONUS_PER_EXTRA = 0.05
_SECTION_BONUS_CAP = 0.15
# The matcher chunk is the phrasing surface authored precisely for query matching.
_MATCHER_BONUS = 0.03

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
    # Stage B output. Optional with a default so every existing caller and test that
    # builds a knowledge payload without it keeps working unchanged.
    resolved_concern: Optional[dict] = None

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


def _score_concerns(relevant: list[tuple[Any, float]]) -> list[tuple[float, str, dict]]:
    """Group concern chunks by concern_id and score each concern (spec Section 10.5).

    score = max_similarity
          + min(0.05 * (distinct_sections - 1), 0.15)
          + 0.03 if the matcher chunk hit
    """
    by_concern: dict[str, dict] = {}
    for doc, score in relevant:
        metadata = getattr(doc, "metadata", {}) or {}
        if metadata.get("content_type") != CONCERN_CONTENT_TYPE:
            continue
        concern_id = metadata.get("concern_id")
        if not concern_id:
            continue
        entry = by_concern.setdefault(concern_id, {"max_similarity": 0.0, "sections": set()})
        entry["max_similarity"] = max(entry["max_similarity"], score)
        entry["sections"].add(metadata.get("section", ""))

    scored = []
    for concern_id, entry in by_concern.items():
        bonus = min(_SECTION_BONUS_PER_EXTRA * (len(entry["sections"]) - 1), _SECTION_BONUS_CAP)
        if MATCHER_SECTION in entry["sections"]:
            bonus += _MATCHER_BONUS
        scored.append((entry["max_similarity"] + bonus, concern_id, entry))
    # Sort by score desc, then concern_id asc so ties resolve deterministically rather
    # than by dict iteration order.
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored


def _related_summaries(record: Any, concern_lookup: Any) -> list[dict]:
    summaries = []
    for related in record.related_concerns[: settings.concern_max_related]:
        target = concern_lookup(related.id)
        if target is None:
            continue
        summaries.append(
            {
                "concern_id": target.concern_id,
                "title": target.title,
                "summary": target.section_text("summary"),
                "relation": related.relation,
            }
        )
    return summaries


def _build_resolved_concern(
    record: Any, score: float, margin: float, entry: dict, concern_lookup: Any
) -> dict:
    sections = {
        key: list(section.bullets)
        for key, section in record.sections.items()
        if section.bullets and not section.is_not_applicable()
    }
    return {
        "concern_id": record.concern_id,
        "title": record.title,
        "category": record.category,
        "topic": record.topic,
        "score": round(score, 3),
        "margin": round(margin, 3),
        "matched_sections": sorted(s for s in entry["sections"] if s),
        "development_domains": list(record.development_domains),
        "related_therapies": list(record.related_therapies),
        "sections": sections,
        "summary": record.section_text("summary"),
        "related_concerns": _related_summaries(record, concern_lookup),
    }


def _qualifies(scored: list[tuple[float, str, dict]], chunk_counts: dict[str, int]) -> bool:
    """Does the leading concern clear either resolution bar?

    Two bars, because measurement against the live index showed two distinct signals:

    * **Score.** A phrasing that lands squarely on a concern scores high on its own
      (0.7-0.9 for the questions parents actually type).
    * **Dominance.** Colloquial phrasings ("every evening ends in screaming over nothing")
      score much lower in absolute terms -- 0.24-0.39 -- yet the correct concern still
      sweeps almost every retrieved chunk. Concentration is the real signal there, not
      magnitude.

    The distinction matters because the failure mode looks the opposite way round: a query
    like "what is neuroplasticity?" pulls one `neuroplasticity_explanation` chunk from
    *every* concern at ~0.5. High score, no dominance -- and no concern is what that
    question is actually about.
    """
    score, concern_id, _ = scored[0]
    if score >= settings.concern_resolution_threshold:
        return True

    total_chunks = sum(chunk_counts.values())
    own_chunks = chunk_counts.get(concern_id, 0)
    share = own_chunks / total_chunks if total_chunks else 0.0
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    return (
        score >= settings.concern_dominance_min_score
        and own_chunks >= settings.concern_dominance_min_chunks
        and share >= settings.concern_dominance_ratio
        and (score - runner_up) >= settings.concern_dominance_margin
    )


def _resolve_concern(
    scored_chunks: list[tuple[Any, float]], concern_lookup: Any, intent: str
) -> Optional[dict]:
    """Resolve the retrieved chunks to a single concern record, or None.

    Operates on every retrieved chunk rather than only those above
    rag_similarity_threshold: this stage applies its own calibrated bars (see `_qualifies`),
    and a concern the corpus was written for should not be discarded by a threshold tuned
    for generic prose chunks.

    Returning None is a normal outcome, not a failure -- the turn then behaves exactly as
    it did before this stage existed. Resolving to the *wrong* concern is worse than
    resolving to none, which is why both bars sit above the global retrieval threshold.
    """
    if not settings.concern_resolution_enabled:
        return None

    scored = _score_concerns(scored_chunks)
    if not scored:
        return None

    chunk_counts: dict[str, int] = {}
    for doc, _score in scored_chunks:
        concern_id = (getattr(doc, "metadata", {}) or {}).get("concern_id")
        if concern_id:
            chunk_counts[concern_id] = chunk_counts.get(concern_id, 0) + 1

    score, concern_id, entry = scored[0]
    if not _qualifies(scored, chunk_counts):
        logger.info(
            "concern_resolution declined: best=%s score=%.3f share=%.2f threshold=%.2f",
            concern_id, score,
            chunk_counts.get(concern_id, 0) / max(sum(chunk_counts.values()), 1),
            settings.concern_resolution_threshold,
        )
        return None

    record = concern_lookup(concern_id)
    if record is None:
        # A vector survived for a concern file that no longer loads (deleted, renamed, or
        # failing validation). Degrade to chunk-only grounding rather than inventing one.
        logger.warning("concern_resolution: no record for concern_id=%s (stale index?)", concern_id)
        return None

    # The file itself declares which intents it serves. A concept question such as "what is
    # neuroplasticity?" matches every concern's Neuroplasticity Explanation section, but no
    # concern file claims concept_explanation -- so none of them is what is being asked
    # about, and forcing the answer into the concern structure would be wrong.
    if intent not in record.primary_intents:
        logger.info(
            "concern_resolution declined: intent=%s not in %s.primary_intents=%s",
            intent, concern_id, record.primary_intents,
        )
        return None

    margin = score - scored[1][0] if len(scored) > 1 else score
    return _build_resolved_concern(record, score, margin, entry, concern_lookup)


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


def knowledge_node(
    state: GraphState, retriever: Optional[Any] = None, concern_lookup: Optional[Any] = None
) -> dict:
    """LangGraph node: retrieve ManaScience knowledge for the current turn's understanding.

    Two stages: (A) vector search over the shared collection, and (B) resolution of the
    surviving concern chunks to a single structured concern record, so Response Generation
    assembles an answer from named sections instead of chunk fragments.

    Pure function of state["understanding"] -> partial state update; does not mutate
    user_message, chat_history, or understanding. Returns {"knowledge": {...}}.
    """
    understanding = state["understanding"]
    retriever = retriever or retrieve
    if concern_lookup is None:
        from app.knowledge.concern_loader import get_concern_by_id

        concern_lookup = get_concern_by_id

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
        resolved_concern = _resolve_concern(scored_chunks, concern_lookup, understanding["intent"])

        if resolved_concern is not None and source == "llm":
            # Stage A found nothing clearing the generic relevance bar, but stage B is
            # confident which concern this is. ManaScience content that was written for
            # exactly this question outranks a generic LLM answer (Phase 2 spec: own
            # knowledge first), so ground the turn in the concern's own chunks.
            concern_chunks = [
                (doc, score) for doc, score in scored_chunks
                if (getattr(doc, "metadata", {}) or {}).get("concern_id") == resolved_concern["concern_id"]
            ]
            concern_chunks.sort(key=lambda pair: pair[1], reverse=True)
            retrieved_docs = _aggregate_and_cap(concern_chunks)
            if retrieved_docs:
                source = "rag"
                confidence = round(resolved_concern["score"], 2)
                logger.info(
                    "concern_resolution promoted source to rag: concern=%s score=%.3f",
                    resolved_concern["concern_id"], resolved_concern["score"],
                )
            else:
                resolved_concern = None

        result = {
            "source": source,
            "retrieved_docs": retrieved_docs,
            "confidence": confidence,
            "query_used": understanding["search_query"],
            "intent": understanding["intent"],
            "retrieval_skipped": False,
            "content_types_searched": content_types_searched,
            "error": None,
            "resolved_concern": resolved_concern,
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

    resolved = validated.get("resolved_concern")
    logger.info(
        "knowledge_node ok: query=%r source=%s confidence=%.2f concern=%s concern_score=%s "
        "concern_margin=%s sections=%s elapsed_ms=%.1f",
        understanding["search_query"],
        validated["source"],
        validated["confidence"],
        resolved["concern_id"] if resolved else None,
        resolved["score"] if resolved else None,
        resolved["margin"] if resolved else None,
        ",".join(resolved["matched_sections"]) if resolved else "",
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
