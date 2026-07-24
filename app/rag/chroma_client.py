import chromadb

from app.config import settings


def get_client() -> chromadb.ClientAPI:
    """Return the persistent Chroma client, rooted at settings.chroma_persist_dir."""
    return chromadb.PersistentClient(path=str(settings.chroma_persist_dir))


def get_collection():
    """Return the (get-or-create) ManaScience knowledge collection, configured for cosine similarity.

    Single source of truth for collection configuration, used by both ingestion
    (scripts/build_knowledge_index.py) and retrieval (app/rag/retriever.py).
    """
    return get_client().get_or_create_collection(
        name=settings.chroma_collection_name,
        metadata={"hnsw:space": "cosine"},
    )
