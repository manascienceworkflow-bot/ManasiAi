import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.rag.ingest import build_vectorstore  # noqa: E402


def main():
    settings.validate()
    vectorstore = build_vectorstore()
    print(f"Vector store built with {vectorstore.index.ntotal} chunks at {settings.vectorstore_dir}")


if __name__ == "__main__":
    main()
