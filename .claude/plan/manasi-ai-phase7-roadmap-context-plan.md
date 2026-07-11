# Plan — Phase 7: Roadmap Result Ingestion & Manasi `/chat` Context

> Implemented 2026-07-11. Source spec: `.claude/spec/manasi-ai-phase7-roadmap-context-spec.md`.
> Status: **complete** — 35 new tests + 263 total passing.

## Context

The ManaScience frontend already runs the full roadmap assessment (Q0 → ND/NT →
Q1 → scoring engine) and emits a finished score JSON. Nothing on the backend
received it. This phase builds the receiving end: an endpoint that ingests that
JSON, validates it, converts it to one canonical internal object, persists it
per user, and makes it available to Manasi **as read-only context on the live
`/chat` path** so Manasi can answer factual follow-ups ("what was my
communication score?", "was I classified ND or NT?"). The backend must **not**
re-score, diagnose, or recommend therapies — those are later phases.

Two decisions from the user refined the spec:

1. **Integration surface = the live `/chat` RAG chain** (`app/rag/chain.py` /
   `chat_chain`), not the LangGraph pipeline. Consequence: **no changes to
   `app/graph/state.py` or the response node** — context reaches Manasi as a
   string injected into the chat chain's system prompt (`{roadmap_context}`).
2. **Real frontend payload** (authoritative) is a list-wrapped object, simpler
   than the spec's Section 8.2 contract:
   ```json
   [{ "user_id": "...", "Classification": "neurodivergent" | "neurotypical",
      "score": [{ "domain": "...", "Score": "...", "Severity": "..." }] }]
   ```
   The loader/models are built to this shape. No `roadmap_id`/`answers`/
   `metadata`/`overall` required (unknown keys preserved in `raw`).

## What was built

**New — `app/db.py`**: shared module-level `supabase` client (extracted from
`main.py`) so `main.py` and `app/roadmap/services.py` share one client without an
import cycle.

**New — `app/roadmap/` package** (self-contained, house conventions throughout):
- `models.py` — Pydantic `RoadmapDomainScore`, `RoadmapResult`,
  `RoadmapSubmitResponse`; `RoadmapContext` TypedDict.
- `roadmap_loader.py` — `load_roadmap(payload) -> RoadmapResult` +
  `RoadmapValidationError(code, message, field)`. The **only** module that
  touches the raw wire format. Pure, no I/O, **no arithmetic on any score**
  (verbatim). Handles list-unwrap, odd key casing, ND/NT normalization.
- `context_builder.py` — `build_context`, `empty_context`, `render_context_text`.
  Renders the read-only summary with a literal "do not recommend therapies"
  guardrail line; preserves scores verbatim and in insertion order (no
  magnitude ranking).
- `services.py` — `submit_roadmap(payload, supabase)` (validate→persist→ack,
  fail-loud) and `get_roadmap_context_text(user_id, supabase)` (fetch→build→
  render, **fail-safe to ""**).
- `routes.py` — `APIRouter`; `POST /roadmap/submit`. Raw JSON in via `Request`;
  `RoadmapValidationError`→422 (with `code`/`field`), persistence error→503.

**Modified**:
- `app/rag/chain.py` — added a `{roadmap_context}` slot to `SYSTEM_PROMPT`.
- `app/main.py` — use `from app.db import supabase`; `include_router`; fetch
  roadmap context in `/chat` and pass `roadmap_context` (always, "" when none)
  into `chat_chain.invoke(...)`.

**Tests** (flat `tests/`, pytest, hand-rolled fakes + TestClient):
`test_roadmap_loader.py`, `test_roadmap_context_builder.py`,
`test_roadmap_services.py`, `test_roadmap_routes.py`.

## Validation rules (loader → `RoadmapValidationError` → 422)

`payload_not_object`, `ambiguous_batch`, `missing_field` (names field),
`invalid_classification`, `empty_scores`, `invalid_score_entry`.
**Non-rules (never checked, per P1):** no score-aggregate check, no severity
vocabulary, no classification-vs-scores consistency.

## Deploy step (manual — repo has no migrations)

Create the Supabase table before use:
```sql
create table if not exists user_roadmap_results (
  user_id        text primary key,
  classification text,
  result         jsonb not null,
  raw            jsonb,
  received_at    timestamptz default now(),
  updated_at     timestamptz default now()
);
```

## Verification (all passing)

- `python -m pytest tests/ -q` → 263 passed (35 new).
- Purity guard: no `openai|langchain|requests|httpx|supabase|.execute()` in
  `roadmap_loader.py` / `context_builder.py`.
- `POST /roadmap/submit` reachable through `app.main.app`; classification
  normalized (neurotypical→NT) and stored.
- Chat chain prompt formats with `{roadmap_context}`; empty roadmap collapses
  cleanly; contextualize step ignores the extra key.

## Future phases (out of scope, reserved per spec Section 13)

Therapy recommendation, PDF, email, roadmap history/versioning, admin review.
