import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
print("=" * 60, flush=True)
print("BUILD SCRIPT STARTED", flush=True)
print("=" * 60, flush=True)
sys.path.append(str(Path(__file__).resolve().parent.parent))

from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

from app.config import settings  # noqa: E402
from app.rag.chroma_client import get_collection  # noqa: E402
from app.rag.embeddings import get_embeddings  # noqa: E402

BATCH_SIZE = 100


def _split_on_dash_separator(text: str) -> list[str]:
    """Split on lines containing only '---', tolerant of surrounding blank-line padding."""
    blocks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            blocks.append("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    blocks.append("\n".join(current).strip())
    return [block for block in blocks if block]


def load_faq_chunks(path: Path) -> list[dict]:
    """One chunk per '---'-delimited Q&A block -- splitting an FAQ answer would sever it
    from its question (spec Section 5.3, FAQs row). No category taxonomy exists in the
    source file, so faq_category defaults to "general" for every chunk.
    """
    text = path.read_text(encoding="utf-8")
    chunks = []
    for block in _split_on_dash_separator(text):
        chunks.append(
            {
                "content": block,
                "content_type": "faq",
                "source_id": path.name,
                "source_title": "ManaScience FAQ",
                "source_url": None,
                "type_metadata": {"faq_category": "general"},
            }
        )
    return chunks


def load_therapy_chunks(path: Path) -> list[dict]:
    """Chunk on therapy sub-section boundaries (spec Section 5.3, Therapy Information row --
    explicitly modeled on this file's structure). therapy_name is derived from the nearest
    heading inside each chunk; chunks that don't contain a named therapy (e.g. the intro/outro
    sections) get therapy_name="".
    """
    text = path.read_text(encoding="utf-8")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=700,
        chunk_overlap=100,
        separators=["\n### ", "\n# ", "\n---\n", "\n\n", "\n", " ", ""],
    )
    chunks = []
    for piece in splitter.split_text(text):
        heading_match = re.search(r"^#{1,3}\s*(.+)$", piece, re.MULTILINE)
        therapy_name = heading_match.group(1).strip() if heading_match else ""
        chunks.append(
            {
                "content": piece,
                "content_type": "therapy_info",
                "source_id": path.name,
                "source_title": "ManaScience Therapies",
                "source_url": None,
                "type_metadata": {
                    "therapy_name": therapy_name,
                    "age_group": "",
                    "conditions_addressed": "",
                },
            }
        )
    return chunks


def load_website_chunks(path: Path) -> list[dict]:
    """Standard prose chunking for short product-positioning content (spec Section 5.3,
    Website Content row). page_section is derived from the nearest heading inside each chunk.
    """
    text = path.read_text(encoding="utf-8")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=100,
        separators=["\n## ", "\n# ", "\n\n", "\n", " ", ""],
    )
    chunks = []
    for piece in splitter.split_text(text):
        heading_match = re.search(r"^#{1,2}\s*(.+)$", piece, re.MULTILINE)
        page_section = heading_match.group(1).strip() if heading_match else "What is Manasi?"
        chunks.append(
            {
                "content": piece,
                "content_type": "website_content",
                "source_id": path.name,
                "source_title": "What is Manasi?",
                "source_url": None,
                "type_metadata": {"page_section": page_section},
            }
        )
    return chunks


def compute_chunk_id(source_id: str, chunk_index: int) -> str:
    return hashlib.sha256(f"{source_id}:{chunk_index}".encode("utf-8")).hexdigest()


def build_metadata_envelope(chunk: dict, chunk_index: int) -> dict:
    envelope = {
        "chunk_id": compute_chunk_id(chunk["source_id"], chunk_index),
        "content_type": chunk["content_type"],
        "source_id": chunk["source_id"],
        "source_title": chunk["source_title"],
        "source_url": chunk["source_url"],
        "chunk_index": chunk_index,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    envelope.update(chunk["type_metadata"])
    return envelope


def main():
    import os

    print("CHROMA_PERSIST_DIR ENV =", os.getenv("CHROMA_PERSIST_DIR"), flush=True)
    print("Resolved Persist Dir =", settings.chroma_persist_dir, flush=True)
    print("Current Working Dir =", Path.cwd(), flush=True)
    settings.validate()

    chunks_by_type = {
        "faq": load_faq_chunks(settings.data_dir / "manascience_faq.md"),
        "therapy_info": load_therapy_chunks(settings.data_dir / "manascience_therapies.md"),
        "website_content": load_website_chunks(settings.data_dir / "manasi_overview.md"),
    }
    # The other six content types (course, blog, research_article, practitioner_info,
    # neuroplasticity_content, pdf_document) have no real ManaScience content yet and are
    # deliberately not wired up here -- sourcing them is a separate, later task.

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []
    for chunks in chunks_by_type.values():
        for index, chunk in enumerate(chunks):
            metadata = build_metadata_envelope(chunk, index)
            ids.append(metadata["chunk_id"])
            documents.append(chunk["content"])
            metadatas.append(metadata)
    print(f"Data dir: {settings.data_dir}", flush=True)
    print(f"Persist dir: {settings.chroma_persist_dir}", flush=True)
    embeddings = get_embeddings()
    vectors: list[list[float]] = []
    for start in range(0, len(documents), BATCH_SIZE):
        vectors.extend(embeddings.embed_documents(documents[start : start + BATCH_SIZE]))
    print("Creating embeddings...", flush=True)
    collection = get_collection()
    print("Opening Chroma collection...", flush=True)
    collection.upsert(ids=ids, embeddings=vectors, documents=documents, metadatas=metadatas)
    print(f"Upserting {len(documents)} documents...", flush=True)
    breakdown = ", ".join(f"{content_type}={len(chunks)}" for content_type, chunks in chunks_by_type.items())
    print(
        f"Ingested {len(documents)} chunks into '{settings.chroma_collection_name}' "
        f"at {settings.chroma_persist_dir} ({breakdown})"
    )


if __name__ == "__main__":
    main()
