from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import settings
from app.rag.chroma_client import get_client
from app.rag.embeddings import get_embeddings

INTENT_CONTENT_TYPE_MAP: dict[str, list[str]] = {
    "concept_explanation": ["neuroplasticity_content", "blog", "research_article"],
    "therapy_information": ["therapy_info", "faq", "blog"],
    "course_information": ["course", "faq"],
    "research_information": ["research_article", "pdf_document"],
    "website_information": ["website_content", "faq"],
    "personal_concern": ["therapy_info", "practitioner_info", "neuroplasticity_content", "faq"],
    "emotional_support": ["faq", "website_content"],
}


def _build_vectorstore() -> Chroma:
    return Chroma(
        client=get_client(),
        collection_name=settings.chroma_collection_name,
        embedding_function=get_embeddings(),
    )


def _search(
    vectorstore: Chroma, search_query: str, allowed_content_types: "list[str] | None"
) -> list[tuple[Document, float]]:
    filter_ = {"content_type": {"$in": allowed_content_types}} if allowed_content_types else None
    return vectorstore.similarity_search_with_relevance_scores(
        query=search_query, k=settings.knowledge_top_k, filter=filter_
    )


def retrieve(search_query: str, intent: str) -> "tuple[list[tuple[Document, float]], list[str]]":
    """Similarity-search search_query, biased toward intent's allowed content types.

    Retries once against the full collection (no content-type filter) if the filtered pass
    doesn't clear settings.rag_min_relevant_chunks above settings.rag_similarity_threshold,
    so a narrow filter never silently starves retrieval. Performs no thresholding/ranking
    decision itself and lets chromadb/openai exceptions propagate untouched -- that belongs
    to the caller (app/nodes/knowledge_node.py).

    Returns (scored_chunks, content_types_searched), where content_types_searched is the
    content-type filter that scoped the winning pass ([] for the unfiltered retry pass).
    """
    vectorstore = _build_vectorstore()
    allowed_content_types = INTENT_CONTENT_TYPE_MAP.get(intent)

    scored_chunks = _search(vectorstore, search_query, allowed_content_types)
    relevant_count = sum(1 for _, score in scored_chunks if score >= settings.rag_similarity_threshold)

    if allowed_content_types and relevant_count < settings.rag_min_relevant_chunks:
        scored_chunks = _search(vectorstore, search_query, None)
        return scored_chunks, []

    return scored_chunks, list(allowed_content_types) if allowed_content_types else []
