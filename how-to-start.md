# How to Start — Manasi RAG Chatbot

A FastAPI + LangChain RAG chatbot that answers questions about ManaScience using the markdown
knowledge base in `data/`.

## 1. Prerequisites

- Python 3.10+
- An OpenAI API key (used for both chat completions and embeddings)

## 2. Set up the environment

Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> If you already have a `venv/` directory (as in this project), just run the `pip install`
> step with `venv/bin/pip install -r requirements.txt`.

## 3. Configure your API key

Copy the example env file and fill in your key:

```bash
cp .env.example .env
```

Then edit `.env` and set `OPENAI_API_KEY` to your real key. `python-dotenv` loads `.env`
automatically — `.env.example` is just a template and is never read by the app.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | Your OpenAI API key |
| `OPENAI_CHAT_MODEL` | No | `gpt-4o-mini` | Chat model used to generate answers |
| `OPENAI_EMBEDDING_MODEL` | No | `text-embedding-3-small` | Embedding model used to index `data/` |
| `DATA_DIR` | No | `data` | Folder of markdown files to index |
| `VECTORSTORE_DIR` | No | `vectorstore` | Where the FAISS index is persisted |
| `RETRIEVER_TOP_K` | No | `4` | Number of chunks retrieved per question |

## 4. Build the vector index

```bash
venv/bin/python scripts/build_index.py
```

This reads every `.md` file in `data/`, chunks it, embeds it, and saves a FAISS index to
`vectorstore/`. Re-run this any time you add or edit files in `data/`. If you skip this step,
the server builds the index automatically on first startup (just adds a bit of startup time).

## 5. Chat in the terminal (quickest way to try it)

> ⚠️ **Run this in your own terminal application** (Terminal.app, a terminal tab in your IDE,
> PuTTY, etc.) — a real shell where you can type and press Enter. It is **not** the chat window
> you're using to talk to your coding assistant — that's a separate conversation and Manasi
> won't see anything typed there.

Step by step:

1. Open a terminal.
2. Go to the project folder:
   ```bash
   cd /home/user/NEW_manasi
   ```
3. Start the chat (no API server needed — this talks to the RAG chain directly in-process):
   ```bash
   venv/bin/python scripts/chat_cli.py
   ```
4. Wait for the `You:` prompt to appear, then type your question and press Enter. Repeat for
   each turn.
5. Type `exit`, `quit`, or press `Ctrl+C` whenever you want to leave.

Expected output:

```
Loading the Manasi knowledge base...

Manasi — ManaScience AI guide. Type 'exit' or 'quit' to leave.

You: What is Manasi?
Manasi: Manasi is ManaScience's AI guide, designed to help individuals, families, ...

You: exit
Goodbye!
```

Conversation history is kept only for the duration of that session (lost when you exit).

## 6. Run the API server (optional — for HTTP/curl access)

Start the API in the background and confirm it's healthy:

```bash
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 &> /tmp/manasi_server.log &
disown

for i in {1..30}; do
  curl -sf http://localhost:8000/health > /dev/null && break
  sleep 1
done
curl http://localhost:8000/health
# → {"status":"ok"}
```

For local development with auto-reload on code changes, run it in the foreground instead:

```bash
venv/bin/uvicorn app.main:app --reload
```

You can also start it directly from `main.py` (equivalent, no `--reload`):

```bash
venv/bin/python -m app.main
```

> Note: `python app/main.py` (running the file by path) will fail with
> `ModuleNotFoundError: No module named 'app'` — Python needs `-m app.main` so the `app`
> package's internal imports resolve correctly.

Logs are written to `/tmp/manasi_server.log` when run in the background.

## 7. Talk to it via the API

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is Manasi and what can it help me with?"}'
```

Pass a `session_id` to keep conversation history across turns (kept in memory, not persisted
across restarts):

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What therapies do you cover for sensory processing?", "session_id": "demo"}'

curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Tell me more about the second one.", "session_id": "demo"}'
```

Reset a conversation:

```bash
curl -X DELETE http://localhost:8000/chat/demo
```

## 8. Chat in the browser (Streamlit UI)

The Streamlit app is a separate frontend that talks to the API server over HTTP, so the
server from step 6 must be running first.

```bash
venv/bin/streamlit run streamlit_app.py
```

Streamlit prints a `Local URL` (default `http://localhost:8501`) — open it in your browser.
The sidebar shows whether the backend is reachable and has a button to reset the conversation.

If the API server runs on a different host/port, point the UI at it:

```bash
MANASI_API_URL=http://localhost:8000 venv/bin/streamlit run streamlit_app.py
```

## 9. Stop the servers

```bash
pkill -f "uvicorn app.main:app"
pkill -f "streamlit run"
```

## Troubleshooting

- **`OPENAI_API_KEY is not set` on startup** — make sure `.env` exists (not just
  `.env.example`) and contains a real key.
- **Answers don't reflect a recent edit to `data/`** — rebuild the index
  (`python scripts/build_index.py`) and restart the server; the FAISS index is only rebuilt
  automatically if `vectorstore/` doesn't exist yet.
- **Port already in use** — another instance is likely still running; `pkill -f "uvicorn app.main:app"`
  or pick a different `--port`.
