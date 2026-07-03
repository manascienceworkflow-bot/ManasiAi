import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Some hosting UIs (e.g. Railway) can save secrets with a trailing newline or
# stray whitespace. A newline in the key makes an illegal HTTP header value
# ("Bearer sk-...\n") and crashes the OpenAI client at startup, so normalize it
# in-place — the OpenAI SDK reads OPENAI_API_KEY directly from the environment.
if os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"].strip()

BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_dir(env_var: str, default: str) -> Path:
    """Resolve a directory setting. Absolute values (e.g. a Railway volume mount
    like /chroma/chroma) are used as-is; relative values are anchored to BASE_DIR."""
    value = Path(os.getenv(env_var, default))
    return value if value.is_absolute() else BASE_DIR / value


class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
    chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    understanding_model: str = os.getenv("UNDERSTANDING_MODEL", "gpt-4o-mini")
    embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    data_dir: Path = BASE_DIR / os.getenv("DATA_DIR", "data")
    vectorstore_dir: Path = BASE_DIR / os.getenv("VECTORSTORE_DIR", "vectorstore")
    retriever_top_k: int = int(os.getenv("RETRIEVER_TOP_K", "4"))

    chroma_persist_dir: Path = _resolve_dir("CHROMA_PERSIST_DIR", "chroma_store")
    chroma_collection_name: str = os.getenv("CHROMA_COLLECTION_NAME", "manascience_knowledge")
    knowledge_embedding_model: str = os.getenv("KNOWLEDGE_EMBEDDING_MODEL", "text-embedding-3-small")
    knowledge_top_k: int = int(os.getenv("KNOWLEDGE_TOP_K", "8"))
    knowledge_max_returned_chunks: int = int(os.getenv("KNOWLEDGE_MAX_RETURNED_CHUNKS", "4"))
    knowledge_max_context_chars: int = int(os.getenv("KNOWLEDGE_MAX_CONTEXT_CHARS", "6000"))
    rag_similarity_threshold: float = float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.35"))
    rag_min_relevant_chunks: int = int(os.getenv("RAG_MIN_RELEVANT_CHUNKS", "1"))

    response_model: str = os.getenv("RESPONSE_MODEL", "gpt-4o-mini")
    response_temperature: float = float(os.getenv("RESPONSE_TEMPERATURE", "0.3"))
    response_max_retries: int = int(os.getenv("RESPONSE_MAX_RETRIES", "1"))
    response_min_answer_length: int = int(os.getenv("RESPONSE_MIN_ANSWER_LENGTH", "40"))
    response_document_dump_shingle_words: int = int(os.getenv("RESPONSE_DOCUMENT_DUMP_SHINGLE_WORDS", "12"))

    empathy_model: str = os.getenv("EMPATHY_MODEL", "gpt-4o-mini")
    empathy_temperature: float = float(os.getenv("EMPATHY_TEMPERATURE", "0.5"))
    empathy_max_retries: int = int(os.getenv("EMPATHY_MAX_RETRIES", "1"))
    empathy_min_length_ratio: float = float(os.getenv("EMPATHY_MIN_LENGTH_RATIO", "0.8"))
    empathy_max_length_ratio: float = float(os.getenv("EMPATHY_MAX_LENGTH_RATIO", "2.5"))
    empathy_fact_retention_min_ratio: float = float(os.getenv("EMPATHY_FACT_RETENTION_MIN_RATIO", "0.9"))

    safety_model: str = os.getenv("SAFETY_MODEL", "gpt-4o-mini")
    safety_temperature: float = float(os.getenv("SAFETY_TEMPERATURE", "0.1"))
    safety_max_retries: int = int(os.getenv("SAFETY_MAX_RETRIES", "1"))

    cta_data_dir: Path = BASE_DIR / os.getenv("CTA_DATA_DIR", "data/cta")

    def validate(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Copy .env.example to .env and add your key."
            )


settings = Settings()
