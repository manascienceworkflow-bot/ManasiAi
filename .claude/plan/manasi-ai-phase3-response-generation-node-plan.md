# Implementation Plan — Manasi AI Phase 3: Response Generation Node

**Source spec:** `.claude/spec/manasi-ai-phase3-response-generation-node-spec.md` (Sections 1–8)

## Context

The Phase 3 spec (Executive Summary, Business Objective, Functional Requirements,
Non-Functional Requirements, Architecture, Knowledge Utilization Logic, Simplification
Strategy, JSON Schema) is complete and is the source of truth for this implementation.
This plan builds the actual Phase 3 code on top of the existing Phase 1
(`understanding_node`) / Phase 2 (`knowledge_node`) pipeline in `app/`.

Phase 3's job per the spec: consume `understanding` (Phase 1) + `knowledge` (Phase 2)
state and produce a `response` — a freshly-written, simplified, non-copied answer, with
`source`/`answer_type`/`confidence`/`grounded_chunk_ids` computed deterministically in
Python (never self-reported by the LLM, per spec FR-9/Section 5.3). No empathy/tone/
disclaimer logic (FR-2) — that's future-phase scope.

Conventions matched from the live codebase:
- `app/graph/state.py` — `TypedDict` state (`Understanding`, `Knowledge`, `GraphState`).
- `app/nodes/understanding_node.py` — prompt-template-from-`.txt` pattern, `FakeLLM`-testable
  `llm.invoke(prompt) -> .content`, code-fence stripping, retry-once-then-fallback on
  `ValidationError`/`JSONDecodeError`.
- `app/nodes/knowledge_node.py` — Pydantic `model_validator` business-rule enforcement,
  node-catches-exceptions-from-lower-layer pattern (`rag/retriever.py` raises, node
  catches and converts to an `error`-coded fallback dict).
- `app/config.py` — flat `Settings` class, `os.getenv(...)` per field.
- `app/models.py`, `app/main.py` — per-phase Pydantic API model + FastAPI endpoint
  (`/understand`, `/knowledge`), `build_*_graph()` wired at startup via `lifespan`.
- `tests/test_understanding_node.py`, `tests/test_knowledge_node.py` — scripted fake
  LLM/retriever, no live API calls for unit tests.

## Implementation Plan

### 1. `app/graph/state.py` (edit)
Add `Response` TypedDict + `response: Optional[Response]` field on `GraphState`, per
spec Section 8.3:
```python
class Response(TypedDict):
    answer: str
    source: Literal["rag", "llm"]
    answer_type: Literal[
        "concept_explanation", "therapy_information", "course_information",
        "research_summary", "website_information", "personal_guidance",
        "supportive_information", "general_knowledge",
    ]
    topic: str
    intent: str
    confidence: float
    grounded_chunk_ids: list[str]
    generation_time_ms: float
    error: Optional[str]
```

### 2. `app/config.py` (edit)
Add, mirroring the existing `knowledge_*`/`rag_*` field style:
```python
response_model: str = os.getenv("RESPONSE_MODEL", "gpt-4o-mini")
response_temperature: float = float(os.getenv("RESPONSE_TEMPERATURE", "0.3"))
response_max_retries: int = int(os.getenv("RESPONSE_MAX_RETRIES", "1"))
response_min_answer_length: int = int(os.getenv("RESPONSE_MIN_ANSWER_LENGTH", "40"))
response_document_dump_shingle_words: int = int(os.getenv("RESPONSE_DOCUMENT_DUMP_SHINGLE_WORDS", "12"))
```
Also append the matching commented defaults to `.env.example`.

### 3. `app/prompts/response_prompt.txt` (new)
Static template with `{{intent}}`, `{{topic}}`, `{{user_message}}`,
`{{knowledge_instructions}}`, `{{retrieved_context}}`, `{{structure_instructions}}`
placeholders — content per spec Section 9 (critical "never copy" / "never refuse"
rules, simplification rules, `OUTPUT FORMAT: {"answer": "..."}` only).

### 4. `app/services/response_generator.py` (new package + file)
The "mechanism" layer (mirrors `app/rag/retriever.py`'s role relative to
`knowledge_node.py`). Owns everything content-related; never raises — always returns a
valid dict so `response_node.py` stays thin.

Contents:
- Constants: `RAG_INSTRUCTIONS`, `LLM_INSTRUCTIONS`, `CONCEPT_STRUCTURE_INSTRUCTIONS`,
  `DIRECT_STRUCTURE_INSTRUCTIONS`, `BANNED_PHRASES` (spec Section 6.3),
  `ANSWER_TYPE_BY_INTENT` (spec Section 6.5), two corrective-reprompt suffixes (spec
  Section 9.6), `INFRA_FAILURE_FALLBACK_ANSWER` (spec Section 8.6).
- `_format_retrieved_context(retrieved_docs)` — spec Section 6.2, verbatim.
- `_build_prompt(understanding, knowledge, user_message, extra_suffix="")` — template
  substitution.
- `_strip_code_fences(text)` / `_parse_answer(raw_text) -> str` — same pattern as
  `understanding_node._strip_code_fences` + `json.loads`, extracting `answer`.
- `_shingles(text, n)` / `_is_document_dump(answer, retrieved_docs)` — spec Section 6.4,
  using `settings.response_document_dump_shingle_words`.
- `_contains_banned_phrase(answer) -> bool`.
- `_count_violations(answer, retrieved_docs) -> int` (min-length + banned-phrase +
  document-dump, each contributing to the tie-break in `_select_fallback`).
- `_select_fallback(attempts, llm_call_failed) -> tuple[str, str]` — spec Section 8.6,
  verbatim logic.
- `generate_response(understanding, knowledge, user_message, llm=None) -> dict` — the
  entry point. For each of `1 + settings.response_max_retries` attempts: build the
  (possibly corrective) prompt, call `llm.invoke(...)`, catch any exception per-attempt
  (never propagate), parse+validate the answer against both guards, stop early on a
  clean pass. After the loop, call `_select_fallback` if no attempt passed cleanly.
  Returns `{"answer", "source", "answer_type", "topic", "intent", "confidence",
  "grounded_chunk_ids", "error"}` (no `generation_time_ms` — timed by the node).

### 5. `app/nodes/response_node.py` (new)
Thin graph-wiring layer (mirrors `knowledge_node.py`):
- `ResponseOutput(BaseModel)` with the two `model_validator`s from spec Section 8.4,
  importing `BANNED_PHRASES` from `app.services.response_generator`.
- `response_node(state, llm=None) -> dict` — builds default `ChatOpenAI` (model=
  `settings.response_model`, temperature=`settings.response_temperature`) if none
  passed, times the call, invokes `generate_response(...)`, validates through
  `ResponseOutput`, logs, returns `{"response": validated}`. Wrapped in a defensive
  top-level `try/except Exception` as a last-resort safety net (logs + returns the
  infra-failure fallback shape) since `generate_response` is designed to never raise but
  the node's own contract (FR-12) is "must never raise under any input."
- `build_response_graph()` — extends `understanding_node -> knowledge_node ->
  response_node`, terminating at `END`, mirroring `build_knowledge_graph()`.

### 6. `app/models.py` (edit)
Add an API-layer Pydantic model for the `/respond` endpoint. Named `AnswerResponse`
(not `ResponseResponse`) to avoid the naming stutter with Starlette's `Response` /
the state `Response` TypedDict, while still mirroring `UnderstandResponse`/
`KnowledgeResponse` field-for-field.

### 7. `app/main.py` (edit)
- Add `response_graph` global, build it in `lifespan` via `build_response_graph()`.
- Add `POST /respond` endpoint mirroring `/knowledge`'s shape (session history →
  `_history_to_chat_turns` → graph invoke → `AnswerResponse(**result["response"])`).

### 8. `tests/test_response_node.py` (new)
Mirror `test_knowledge_node.py`'s `FakeRetriever`/`FakeLLM` style (reuse the
`FakeLLM` pattern from `test_understanding_node.py`, scripted multi-call responses).
Cover: rag happy path (`grounded_chunk_ids` populated, `confidence` passthrough), llm
fallback happy path (`grounded_chunk_ids == []`), `answer_type` derived correctly for
each of the 8 intents, banned-phrase first attempt → corrective retry → clean second
attempt, document-dump first attempt → corrective retry → clean second attempt, both
attempts fail a guard → `error == "quality_guard_exhausted"` with a non-empty answer,
both LLM calls raise → `error == "llm_call_failure"` with the templated fallback text,
does-not-mutate-input-state, `source`/`confidence` exactly equal `knowledge.source`/
`knowledge.confidence` (FR-13).

## Verification

- `cd /home/user/NEW_manasi && venv/bin/pytest tests/test_response_node.py -v` — all new
  tests pass without any live OpenAI call (fake LLM only, matching existing test
  convention).
- `venv/bin/pytest tests/ -v` — confirm Phase 1/2 tests still pass unmodified (no
  regressions from the `GraphState`/`config.py` edits).
- Manually exercise `build_response_graph()` end-to-end with a real `ChatOpenAI` call for
  one rag-sourced and one llm-fallback question and eyeball that the answer is not a
  verbatim copy of `data/manascience_therapies.md` content and contains no banned phrase.
- Start the app (`uvicorn app.main:app`) and `curl -X POST localhost:8000/respond` with a
  sample message to confirm the endpoint wires through correctly.
