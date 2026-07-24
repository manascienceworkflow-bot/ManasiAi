import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import chromadb.errors  # noqa: E402
import httpx  # noqa: E402
import openai  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from app.config import settings  # noqa: E402
from app.nodes.knowledge_node import knowledge_node  # noqa: E402


class FakeRetriever:
    """Scripted fake retriever: returns (scored_chunks, content_types_searched), or raises."""

    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls: list[tuple[str, str]] = []

    def __call__(self, search_query: str, intent: str):
        self.calls.append((search_query, intent))
        if self.raises is not None:
            raise self.raises
        return self.result


def make_understanding(intent="therapy_information", search_query="ManaScience therapies offered"):
    return {
        "intent": intent,
        "topic": "ManaScience therapies",
        "search_query": search_query,
        "emotional_state": "curious",
    }


def make_state(understanding=None):
    return {
        "user_message": "What therapies does ManaScience offer?",
        "chat_history": [],
        "understanding": understanding if understanding is not None else make_understanding(),
        "knowledge": None,
    }


def make_doc(chunk_id, content, content_type="therapy_info", metadata_extra=None):
    metadata = {
        "chunk_id": chunk_id,
        "content_type": content_type,
        "source_id": "manascience_therapies.md",
        "source_title": "ManaScience Therapies",
        "source_url": None,
        "chunk_index": 0,
        "ingested_at": "2026-01-01T00:00:00+00:00",
    }
    metadata.update(metadata_extra or {})
    return Document(page_content=content, metadata=metadata)


def test_general_chat_skips_retrieval_entirely():
    retriever = FakeRetriever(result=([], []))
    state = make_state(understanding=make_understanding(intent="general_chat", search_query=""))
    result = knowledge_node(state, retriever=retriever)["knowledge"]
    assert result["retrieval_skipped"] is True
    assert result["source"] == "llm"
    assert result["confidence"] == 0.0
    assert result["retrieved_docs"] == []
    assert result["query_used"] == ""
    assert retriever.calls == []


def test_rag_source_when_chunk_above_threshold():
    doc = make_doc("c1", "ManaScience offers occupational therapy...", metadata_extra={"therapy_name": "MNRI"})
    retriever = FakeRetriever(result=([(doc, 0.91)], ["therapy_info"]))
    result = knowledge_node(make_state(), retriever=retriever)["knowledge"]
    assert result["source"] == "rag"
    assert result["confidence"] == 0.91
    assert len(result["retrieved_docs"]) == 1
    assert result["retrieved_docs"][0]["chunk_id"] == "c1"
    assert result["retrieved_docs"][0]["content_type"] == "therapy_info"
    assert result["retrieved_docs"][0]["metadata"] == {"therapy_name": "MNRI"}
    assert result["content_types_searched"] == ["therapy_info"]
    assert result["error"] is None


def test_llm_source_when_all_chunks_below_threshold():
    doc = make_doc("c1", "weak match")
    retriever = FakeRetriever(result=([(doc, 0.05)], ["faq"]))
    result = knowledge_node(make_state(), retriever=retriever)["knowledge"]
    assert result["source"] == "llm"
    assert result["confidence"] == 0.0
    assert result["retrieved_docs"] == []


def test_dedup_by_chunk_id():
    doc_a = make_doc("dup", "content A", content_type="faq")
    doc_b = make_doc("dup", "content A duplicate", content_type="faq")
    retriever = FakeRetriever(result=([(doc_a, 0.9), (doc_b, 0.85)], ["faq"]))
    result = knowledge_node(make_state(), retriever=retriever)["knowledge"]
    assert len(result["retrieved_docs"]) == 1
    assert result["retrieved_docs"][0]["content"] == "content A"


def test_caps_at_max_returned_chunks():
    docs = [(make_doc(f"c{i}", f"content {i}", content_type="faq"), 0.9 - i * 0.01) for i in range(10)]
    retriever = FakeRetriever(result=(docs, ["faq"]))
    result = knowledge_node(make_state(), retriever=retriever)["knowledge"]
    assert len(result["retrieved_docs"]) == settings.knowledge_max_returned_chunks
    returned_ids = [d["chunk_id"] for d in result["retrieved_docs"]]
    assert returned_ids == [f"c{i}" for i in range(settings.knowledge_max_returned_chunks)]


def test_caps_at_max_context_chars_without_truncating_mid_chunk():
    big_content = "x" * (settings.knowledge_max_context_chars - 100)
    doc1 = make_doc("c1", big_content, content_type="faq")
    doc2 = make_doc("c2", "y" * 500, content_type="faq")
    retriever = FakeRetriever(result=([(doc1, 0.9), (doc2, 0.8)], ["faq"]))
    result = knowledge_node(make_state(), retriever=retriever)["knowledge"]
    assert len(result["retrieved_docs"]) == 1
    assert result["retrieved_docs"][0]["content"] == big_content


def test_oversized_single_chunk_is_kept_whole_not_truncated():
    huge_content = "z" * (settings.knowledge_max_context_chars + 500)
    doc = make_doc("c1", huge_content, content_type="faq")
    retriever = FakeRetriever(result=([(doc, 0.9)], ["faq"]))
    result = knowledge_node(make_state(), retriever=retriever)["knowledge"]
    assert len(result["retrieved_docs"]) == 1
    assert result["retrieved_docs"][0]["content"] == huge_content


def test_embedding_failure_returns_llm_fallback_with_error_code():
    exc = openai.APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/embeddings"))
    retriever = FakeRetriever(raises=exc)
    result = knowledge_node(make_state(), retriever=retriever)["knowledge"]
    assert result["source"] == "llm"
    assert result["confidence"] == 0.0
    assert result["retrieved_docs"] == []
    assert result["error"] == "embedding_failure"


def test_chroma_failure_returns_llm_fallback_with_error_code():
    retriever = FakeRetriever(raises=chromadb.errors.InternalError("boom"))
    result = knowledge_node(make_state(), retriever=retriever)["knowledge"]
    assert result["source"] == "llm"
    assert result["error"] == "vectorstore_unavailable"


def test_does_not_mutate_input_state():
    understanding = make_understanding()
    state = make_state(understanding=understanding)
    original_understanding = dict(understanding)
    doc = make_doc("c1", "content")
    retriever = FakeRetriever(result=([(doc, 0.9)], ["therapy_info"]))
    knowledge_node(state, retriever=retriever)
    assert state["understanding"] == original_understanding


def test_real_chroma_collection_end_to_end(tmp_path, monkeypatch):
    """Integration test against a real local Chroma collection (no FakeRetriever) -- this is
    the first test in the suite that makes a real OpenAI embeddings API call (requires
    OPENAI_API_KEY and network access), consistent with the project's existing convention of
    not mocking the LLM/embeddings layer.
    """
    monkeypatch.setattr(settings, "chroma_persist_dir", tmp_path / "chroma_store")
    monkeypatch.setattr(settings, "chroma_collection_name", "test_knowledge_collection")

    from app.rag.chroma_client import get_collection
    from app.rag.embeddings import get_embeddings

    docs = [
        ("therapy-1", "ManaScience offers occupational therapy for sensory integration challenges.", "therapy_info"),
        ("faq-1", "ManaScience is a guidance platform rooted in the science of neuroplasticity.", "faq"),
    ]
    embeddings = get_embeddings()
    vectors = embeddings.embed_documents([content for _, content, _ in docs])
    collection = get_collection()
    collection.upsert(
        ids=[chunk_id for chunk_id, _, _ in docs],
        embeddings=vectors,
        documents=[content for _, content, _ in docs],
        metadatas=[
            {"content_type": content_type, "source_id": "test", "source_title": "Test", "source_url": None}
            for _, _, content_type in docs
        ],
    )

    understanding = make_understanding(
        intent="therapy_information", search_query="occupational therapy sensory integration"
    )
    result = knowledge_node(make_state(understanding=understanding))["knowledge"]

    assert result["source"] == "rag"
    assert result["confidence"] > 0
    assert any(d["content_type"] == "therapy_info" for d in result["retrieved_docs"])
