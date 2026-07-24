from pathlib import Path

from langchain_community.document_loaders import TextLoader
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings


def load_documents(data_dir: Path):
    documents = []
    for md_file in sorted(data_dir.glob("*.md")):
        loaded = TextLoader(str(md_file), encoding="utf-8").load()
        for doc in loaded:
            doc.metadata["source"] = md_file.name
        documents.extend(loaded)
    return documents


def split_documents(documents):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n## ", "\n### ", "\n---\n", "\n\n", "\n", " ", ""],
    )
    return splitter.split_documents(documents)


def build_vectorstore() -> FAISS:
    """Load the markdown knowledge base, chunk it, embed it, and persist a FAISS index."""
    documents = load_documents(settings.data_dir)
    if not documents:
        raise RuntimeError(f"No markdown files found in {settings.data_dir}")

    chunks = split_documents(documents)
    embeddings = OpenAIEmbeddings(model=settings.embedding_model)
    vectorstore = FAISS.from_documents(chunks, embeddings)

    settings.vectorstore_dir.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(settings.vectorstore_dir))
    return vectorstore


def load_vectorstore() -> FAISS:
    embeddings = OpenAIEmbeddings(model=settings.embedding_model)
    return FAISS.load_local(
        str(settings.vectorstore_dir),
        embeddings,
        allow_dangerous_deserialization=True,
    )


def get_vectorstore() -> FAISS:
    """Load the persisted index if present, otherwise build it from the data directory."""
    index_file = settings.vectorstore_dir / "index.faiss"
    if index_file.exists():
        return load_vectorstore()
    return build_vectorstore()
