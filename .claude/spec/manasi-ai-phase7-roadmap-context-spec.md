# Manasi AI — Software Specification Document (SSD)
## Phase 7: Roadmap Result Ingestion & Manasi Context Injection

**Project:** Manasi AI
**Organization:** ManaScience
**Component:** Roadmap module (`app/roadmap/`) — ingest the frontend roadmap-assessment score JSON and expose it to Manasi as read-only conversation context
**Status:** Draft for implementation
**Audience:** Backend (Python / FastAPI) engineer building `app/roadmap/`
**Depends on:** `app/main.py` (FastAPI app, CORS config, Supabase client, `session_histories`), `app/graph/state.py` (`GraphState`), and the existing pipeline nodes (Phases 1–6). Introduces **no** new LLM calls, **no** RAG dependency, and **no** scoring logic.
**Does NOT depend on:** any therapy/recommendation logic, PDF generation, or email — those are explicitly future phases (Section 13).

**Pipeline position:**

```
User
  -> Chat with Manasi
  -> Trigger Roadmap
  -> Q0 Assessment        (frontend)
  -> Classify ND / NT     (frontend)
  -> Q1 Assessment        (frontend)
  -> Frontend Scoring Engine  -> Structured Score JSON   (frontend — COMPLETE)
  ------------------------------------------------------------ backend boundary
  -> POST /roadmap/submit     (this spec)
  -> Roadmap Loader           (this spec)
  -> RoadmapResult            (this spec)
  -> Context Builder          (this spec)
  -> Manasi (Understanding -> ... -> CTA)  reads roadmap context, read-only
  -> Response
```

---

## 1. Executive Summary

The ManaScience frontend already runs the full roadmap assessment (Q0 → ND/NT classification → Q1 → scoring engine) and produces a **complete, structured score JSON**. That work is done; this phase does not touch it.

This phase builds the **backend receiving end**. It adds one API route, `POST /roadmap/submit`, that accepts the frontend score JSON, validates it, converts it into a single canonical internal object — `RoadmapResult` — persists it against the user's session, and makes it available to Manasi as **read-only conversation context** on subsequent chat turns.

The scope is deliberately narrow. The backend **stores and surfaces** the assessment; it does not interpret, re-score, diagnose, or recommend. Manasi gains the ability to *acknowledge* that an assessment was completed and to *answer factual follow-up questions* grounded in the stored scores ("what was my score in the communication domain?", "was I classified as ND or NT?"). Manasi must not recommend therapies, re-rank domains, or state a clinical conclusion — those behaviours are reserved for later phases whose extension points this document reserves but does not implement (Section 13).

The design follows the established house pattern already used by the CTA subsystem: a thin **route** (transport + HTTP concerns), a **loader** that isolates raw frontend JSON from the rest of the backend, a single canonical **model** every downstream consumer speaks, a **context builder** that renders the model into a Manasi-consumable block, and a **service** layer that orchestrates persistence and retrieval. Everything is deterministic, LLM-free, and non-mutating with respect to any score.

---

## 2. Purpose & Guiding Principles

| # | Principle | Consequence in this spec |
|---|---|---|
| P1 | **The frontend owns scoring.** | The backend never computes, adjusts, rounds, re-weights, or re-derives any score, classification, or domain value. It stores what it receives verbatim. |
| P2 | **Isolate the wire format.** | Raw frontend JSON never leaks past the Roadmap Loader. Every other module speaks only `RoadmapResult`. |
| P3 | **One canonical object.** | Exactly one internal model, `RoadmapResult`, represents a completed assessment everywhere in the backend. |
| P4 | **Context, not cognition.** | Manasi *reads* the assessment. It does not diagnose, recommend, or recompute. |
| P5 | **Fail loud on ingest, fail safe on read.** | `/roadmap/submit` rejects malformed payloads with precise 4xx errors. The chat path treats "no roadmap on file" as a normal, silent condition — never an error. |
| P6 | **No new heavy dependencies.** | Reuses FastAPI, Pydantic, and the existing Supabase client. No new services, no LLM, no network calls in the ingest path. |

---

## 3. Scope

### 3.1 In Scope

The Roadmap module SHALL:

1. Expose `POST /roadmap/submit` to receive the frontend roadmap score JSON.
2. Validate the payload structurally and semantically (Section 9) and return precise success/error responses (Section 8).
3. Parse the validated payload into a canonical `RoadmapResult` object via the Roadmap Loader (Section 6).
4. Persist the `RoadmapResult` against the user's session so it survives across chat turns (Section 7.3).
5. Build a deterministic, read-only Manasi context block from a `RoadmapResult` via the Context Builder (Section 7).
6. Inject that context into the Manasi pipeline (`GraphState`) so downstream nodes can reference it (Section 7.4).
7. Preserve every score, answer, classification, and metadata value byte-for-byte from ingest through to context (P1, P3).

### 3.2 Out of Scope (This Phase)

The Roadmap module SHALL NOT:

* Recalculate, alter, round, or re-rank any score or classification.
* Diagnose the user or assign any clinical label beyond the classification the frontend already supplied.
* Recommend, rank, or match therapies, courses, or CTAs based on roadmap data.
* Generate PDFs, send emails, or produce any downloadable/exportable artefact.
* Build the "Roadmap Generator", "Therapy Recommendation Engine", "Admin Review", or any module listed in Section 13.
* Call an LLM, embeddings model, RAG retriever, or any external network service in the ingest path.
* Modify Manasi's answer text based on roadmap data beyond making the context available for grounding.

> **Guardrail restated for implementers:** if a task requires *deciding what the scores mean for the user*, it belongs to a future phase, not here. This phase's job ends at "the scores are received, stored, and visible to Manasi as facts."

---

## 4. Definitions

| Term | Meaning |
|---|---|
| **Roadmap assessment** | The frontend Q0/Q1 flow that classifies a user ND/NT and produces domain + overall scores. |
| **Score JSON** | The structured JSON object emitted by the frontend scoring engine. The raw wire payload. |
| **ND / NT** | Neurodivergent / Neurotypical — the classification label produced by the Q0 stage. |
| **RoadmapResult** | The single canonical backend model representing one completed assessment (Section 5). |
| **Roadmap context** | The rendered, read-only representation of a `RoadmapResult` that Manasi consumes (Section 7). |
| **Domain** | A named assessment dimension (e.g. `communication`, `social`, `sensory`) carrying a numeric score. Domain identifiers are frontend-defined; the backend treats them as opaque keys. |
| **Session / user** | Identified by `user_id`, the same identifier used as `session_id` in the existing `/chat` flow. |

---

## 5. Data Models

Two model layers, mirroring the existing codebase split (`app/models.py` Pydantic request/response models vs. `app/graph/state.py` TypedDict internal state):

* **Pydantic models** — wire validation for the API boundary (request in, response out). Live in `app/roadmap/models.py`.
* **TypedDict** — the internal `RoadmapResult` shape passed into `GraphState`. Also declared in `app/roadmap/models.py` (re-exported), and the `GraphState` addition in `app/graph/state.py`.

### 5.1 Canonical model — `RoadmapResult`

`RoadmapResult` is the object the whole backend uses. Its required top-level fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | `str` | ✅ | Identifies the user/session. Non-empty after trim. Same key used by `/chat`. |
| `roadmap_id` | `str` | ✅ | Unique identifier of this assessment run (frontend-generated). Non-empty. |
| `classification` | `Classification` | ✅ | ND/NT label + optional confidence (Section 5.2). |
| `answers` | `list[Answer]` | ✅ | Ordered user responses across Q0 and Q1 (Section 5.3). May be empty only if `metadata.answers_omitted` is `true`; otherwise ≥ 1. |
| `scores` | `Scores` | ✅ | Domain scores + overall (Section 5.4). |
| `metadata` | `Metadata` | ✅ | Provenance and versioning (Section 5.5). |

### 5.2 `Classification`

| Field | Type | Required | Rules |
|---|---|---|---|
| `label` | `Literal["ND", "NT"]` | ✅ | Case-normalized to upper on ingest; any other value → 422. |
| `confidence` | `float \| None` | ⬜ | If present, `0.0 ≤ confidence ≤ 1.0`. Stored verbatim, never recomputed. |
| `source_stage` | `str \| None` | ⬜ | e.g. `"Q0"`. Free-form provenance from frontend. |

### 5.3 `Answer`

| Field | Type | Required | Rules |
|---|---|---|---|
| `question_id` | `str` | ✅ | Non-empty. Unique within `answers` (Section 9). |
| `stage` | `Literal["Q0", "Q1"]` | ✅ | Which assessment stage the question belongs to. |
| `question_text` | `str \| None` | ⬜ | Optional echo of the prompt shown to the user. |
| `answer_value` | `str \| int \| float \| bool` | ✅ | The user's raw response, stored as received (no coercion beyond JSON-native types). |
| `answer_label` | `str \| None` | ⬜ | Optional human-readable label for `answer_value`. |
| `domain` | `str \| None` | ⬜ | Optional domain the answer contributes to. Opaque key. |

### 5.4 `Scores`

| Field | Type | Required | Rules |
|---|---|---|---|
| `domains` | `dict[str, DomainScore]` | ✅ | ≥ 1 entry. Keys are opaque domain identifiers. |
| `overall` | `OverallScore` | ✅ | Aggregate score object (Section 5.4.2). |
| `scoring_version` | `str \| None` | ⬜ | Version tag of the frontend scoring engine, if provided. |

#### 5.4.1 `DomainScore`

| Field | Type | Required | Rules |
|---|---|---|---|
| `score` | `float` | ✅ | Stored verbatim. Not clamped, not rounded. |
| `max_score` | `float \| None` | ⬜ | If present, used only for display context, never to renormalize. |
| `band` | `str \| None` | ⬜ | Frontend-supplied band/level label (e.g. `"moderate"`). Stored as-is. |
| `label` | `str \| None` | ⬜ | Human-readable domain name if different from the key. |

#### 5.4.2 `OverallScore`

| Field | Type | Required | Rules |
|---|---|---|---|
| `score` | `float` | ✅ | Verbatim aggregate. |
| `max_score` | `float \| None` | ⬜ | Display only. |
| `band` | `str \| None` | ⬜ | Verbatim band label. |

> **Backend never derives `overall` from `domains`.** Both arrive from the frontend and are stored independently. If `overall` is missing, that is a 422 — the backend does not compute it (P1).

### 5.5 `Metadata`

| Field | Type | Required | Rules |
|---|---|---|---|
| `assessment_version` | `str` | ✅ | Version of the assessment instrument. Non-empty. |
| `submitted_at` | `str \| None` | ⬜ | ISO-8601 timestamp from the frontend. If absent, the backend stamps `received_at` (Section 7.3) — it does **not** overwrite `submitted_at`. |
| `locale` | `str \| None` | ⬜ | e.g. `"en-IN"`. |
| `answers_omitted` | `bool` | ⬜ (default `false`) | If `true`, an empty `answers` list is permitted (Section 5.1). |
| `extra` | `dict` | ⬜ | Pass-through bag for any additional frontend metadata. Stored, never interpreted. |

### 5.6 `GraphState` addition

`app/graph/state.py` gains one optional field so nodes can read roadmap context without breaking existing callers:

```python
class RoadmapContext(TypedDict):
    present: bool                    # True iff a RoadmapResult was loaded for this turn
    roadmap_id: Optional[str]
    classification: Optional[str]    # "ND" | "NT"
    classification_confidence: Optional[float]
    summary_text: str                # human-readable block, Section 7.2 (empty string if not present)
    scores: Optional[dict]           # serialized Scores, read-only
    answers: Optional[list]          # serialized list[Answer], read-only
    metadata: Optional[dict]
    assessment_version: Optional[str]

class GraphState(TypedDict):
    user_message: str
    chat_history: list[ChatTurn]
    roadmap: Optional[RoadmapContext]   # <-- NEW, defaults to None / absent
    understanding: Optional[Understanding]
    knowledge: Optional[Knowledge]
    response: Optional[Response]
    empathy: Optional[Empathy]
    safety: Optional[Safety]
    cta: Optional[CTA]
```

Because it is `Optional` and every existing node ignores unknown keys, adding it is backward-compatible: existing `/understand`, `/knowledge`, etc. endpoints continue to work with `roadmap` absent (treated as `None`).

---

## 6. Roadmap Loader

**File:** `app/roadmap/roadmap_loader.py`
**Responsibility:** the *only* place raw frontend JSON is touched. Parses, validates, and returns a `RoadmapResult`. Nothing downstream ever sees the raw dict.

### 6.1 Public surface

```python
class RoadmapValidationError(Exception):
    """Raised when the incoming payload violates a validation rule (Section 9).
    Carries a machine-readable `code`, a human `message`, and an optional
    `field` path. The route maps this to a 422 response (Section 8.3)."""
    def __init__(self, code: str, message: str, field: str | None = None): ...

def load_roadmap(payload: dict) -> RoadmapResult:
    """Parse and validate a raw frontend score JSON into a canonical
    RoadmapResult. Raises RoadmapValidationError on any violation.
    Pure function: no I/O, no persistence, no network."""
```

### 6.2 Algorithm

1. **Shape guard.** Reject non-object payloads (`RoadmapValidationError("payload_not_object", ...)`).
2. **Required-field presence.** Verify every required top-level field (Section 5.1) exists. Missing → `missing_field` error naming the field.
3. **Pydantic parse.** Feed the payload to the `RoadmapSubmitRequest` Pydantic model (Section 5, `app/roadmap/models.py`). Pydantic enforces types, enums (`ND`/`NT`, `Q0`/`Q1`), and bounds (`confidence ∈ [0,1]`). Convert `pydantic.ValidationError` into a `RoadmapValidationError` with `code="schema_invalid"` and the first error's field path.
4. **Semantic checks** (Section 9.3) that Pydantic can't express: non-empty `domains`, unique `question_id`, `answers` non-empty unless `answers_omitted`, classification normalization.
5. **Normalize.** Upper-case `classification.label`; trim `user_id` and `roadmap_id`. **No numeric normalization** (P1).
6. **Construct** and return the canonical `RoadmapResult`. On success the raw dict is discarded.

### 6.3 Invariants

* `load_roadmap` performs **zero** arithmetic on scores.
* `load_roadmap` never persists, never reads Supabase, never calls the network — it is a pure transform (testable in isolation).
* On any failure it raises `RoadmapValidationError`; it never returns a partial or `None` result.

---

## 7. Manasi Context Builder & Integration

**File:** `app/roadmap/context_builder.py`
**Responsibility:** convert a `RoadmapResult` into a `RoadmapContext` (Section 5.6) suitable for Manasi. Deterministic, value-preserving, LLM-free.

### 7.1 Public surface

```python
def build_context(result: RoadmapResult) -> RoadmapContext:
    """Render a RoadmapResult into the read-only RoadmapContext consumed by
    the Manasi pipeline. Preserves every score, answer, and classification
    verbatim. Never mutates `result`."""

def empty_context() -> RoadmapContext:
    """The canonical 'no roadmap on file' context: present=False, summary_text=''.
    Used on chat turns for users who have not submitted a roadmap."""
```

### 7.2 `summary_text` rendering rules

`summary_text` is a compact, factual, human-readable block Manasi can ground on. It is assembled purely by string templating — **no interpretation, no recommendation language**. Example shape:

```
ROADMAP ASSESSMENT (read-only context — do not recommend therapies)
Roadmap ID: rm_8f21c9
Classification: ND (confidence: 0.82)
Assessment version: v2.3
Overall score: 68 / 100 (band: moderate)
Domain scores:
  - communication: 12 / 20 (band: moderate)
  - social:        9 / 20 (band: low)
  - sensory:       15 / 20 (band: high)
Answers on file: 24 (Q0: 4, Q1: 20)
```

Rendering rules:

* Emit only fields that are present; omit `None`s rather than printing `"None"`.
* Reproduce numeric values exactly as stored (no rounding, no unit conversion).
* Domain order = the frontend's insertion order in `scores.domains` (preserve dict order; do not sort by score — sorting would imply a ranking the backend must not assert).
* The leading guardrail line (`do not recommend therapies`) is a literal constant, included on every render.

### 7.3 Persistence

Roadmap results persist in Supabase, mirroring the existing `user_chat_histories` pattern in `app/main.py`.

* **Table:** `user_roadmap_results`
* **Columns:** `user_id` (text, PK-ish lookup key), `roadmap_id` (text), `result` (jsonb — the serialized `RoadmapResult`), `received_at` (timestamptz, server-stamped via `now()`), `updated_at` (timestamptz).
* **Write strategy:** `upsert` keyed on `user_id`. The latest submitted roadmap for a user is the active one. (Historical retention is a future concern — Section 13, Database Persistence.)
* `received_at` is stamped by the backend at write time; it never overwrites `metadata.submitted_at`.

Persistence functions live in `app/roadmap/services.py` (Section 10), not in the loader or context builder, keeping those two pure.

### 7.4 Injection into Manasi

Two integration points, both additive:

1. **On submit** (`POST /roadmap/submit`): after a successful `load_roadmap` + persist, the service builds the context once and returns a lightweight acknowledgement. It does **not** invoke the chat pipeline.
2. **On chat** (`POST /chat`, existing endpoint): before invoking the pipeline, the service loads the user's active `RoadmapResult` (if any) from Supabase, calls `build_context`, and sets `state["roadmap"]`. If none exists, `state["roadmap"] = empty_context()`. Downstream nodes (Understanding, Response, Empathy) may read `state["roadmap"]["summary_text"]` to ground factual answers.

> **Integration is read-only for existing nodes.** Nodes consult `state["roadmap"]` when the user's message references the assessment; they never write it. The Response/Empathy prompt gains an instruction: *"If roadmap context is present, you may answer factual questions about the user's scores and classification using it verbatim. You must not recommend therapies, courses, or next steps based on it."* Wiring this instruction into the prompt is the only change to existing node behaviour, and it is guarded so that when `present=False` the prompt is unchanged from today.

### 7.5 What the Context Builder must NOT do

* Must not compute any derived score (averages, ranks, percentiles).
* Must not add interpretive or clinical language ("this suggests…", "you should try…").
* Must not reorder domains by magnitude.
* Must not drop or truncate scores/answers for brevity — completeness over compactness (P1, P3). If size is a concern, that is a future optimization, flagged not silently applied.

---

## 8. API Design

### 8.1 Route

```
POST /roadmap/submit
Content-Type: application/json
```

Registered in a dedicated `APIRouter` (`app/roadmap/routes.py`) and mounted in `app/main.py` via `app.include_router(roadmap_router)`. CORS is inherited from the existing global middleware (same allowed origins as `/chat`).

### 8.2 Request contract

**Required fields:** `user_id`, `roadmap_id`, `classification.label`, `answers` (unless `metadata.answers_omitted=true`), `scores.domains` (≥1), `scores.overall.score`, `metadata.assessment_version`.

**Optional fields:** `classification.confidence`, `classification.source_stage`, per-answer `question_text`/`answer_label`/`domain`, `domain.max_score`/`band`/`label`, `overall.max_score`/`band`, `scores.scoring_version`, `metadata.submitted_at`/`locale`/`answers_omitted`/`extra`.

**Example request:**

```json
{
  "user_id": "user_1837",
  "roadmap_id": "rm_8f21c9",
  "classification": { "label": "ND", "confidence": 0.82, "source_stage": "Q0" },
  "answers": [
    { "question_id": "q0_1", "stage": "Q0", "answer_value": true, "answer_label": "Yes" },
    { "question_id": "q1_7", "stage": "Q1", "answer_value": 3, "answer_label": "Often", "domain": "communication" }
  ],
  "scores": {
    "domains": {
      "communication": { "score": 12, "max_score": 20, "band": "moderate" },
      "social":        { "score": 9,  "max_score": 20, "band": "low" },
      "sensory":       { "score": 15, "max_score": 20, "band": "high" }
    },
    "overall": { "score": 68, "max_score": 100, "band": "moderate" },
    "scoring_version": "score-engine-2.3.1"
  },
  "metadata": {
    "assessment_version": "v2.3",
    "submitted_at": "2026-07-11T09:14:22Z",
    "locale": "en-IN"
  }
}
```

### 8.3 Response contract

**Success — `200 OK`:**

```json
{
  "status": "accepted",
  "user_id": "user_1837",
  "roadmap_id": "rm_8f21c9",
  "classification": "ND",
  "domains_received": 3,
  "answers_received": 2,
  "context_ready": true,
  "received_at": "2026-07-11T09:14:23Z"
}
```

`context_ready: true` confirms the `RoadmapResult` was persisted and a `RoadmapContext` can be built on the next chat turn. The endpoint returns **no** scores back to the caller (the frontend already has them) — it echoes only identifiers and counts for confirmation.

**Validation failure — `422 Unprocessable Entity`:**

```json
{
  "status": "rejected",
  "error": {
    "code": "missing_field",
    "message": "Required field 'scores.overall.score' is missing.",
    "field": "scores.overall.score"
  }
}
```

**Malformed JSON — `400 Bad Request`** (body not parseable as JSON): standard FastAPI/Starlette error.

**Service unavailable — `503`** (Supabase not reachable at write time): `{"status":"error","error":{"code":"persistence_unavailable","message":"Roadmap store is temporarily unavailable."}}`.

### 8.4 Error code catalogue

| HTTP | `code` | When |
|---|---|---|
| 400 | (Starlette default) | Body is not valid JSON. |
| 422 | `payload_not_object` | Top-level JSON is not an object. |
| 422 | `missing_field` | A required field is absent. `field` names it. |
| 422 | `schema_invalid` | Type/enum/bound violation (from Pydantic). `field` names the first offender. |
| 422 | `empty_domains` | `scores.domains` has zero entries. |
| 422 | `empty_answers` | `answers` empty while `answers_omitted` is not `true`. |
| 422 | `duplicate_question_id` | A `question_id` repeats within `answers`. |
| 422 | `invalid_classification` | `classification.label` not in {ND, NT}. |
| 422 | `confidence_out_of_range` | `classification.confidence` outside `[0,1]`. |
| 503 | `persistence_unavailable` | Supabase write failed. |

---

## 9. Validation Rules

The loader enforces, in order (fail fast, first violation wins):

### 9.1 Structural

* **V1** Payload is a JSON object. → `payload_not_object`.
* **V2** All required top-level fields present (Section 5.1). → `missing_field`.
* **V3** Types/enums/bounds conform to the Pydantic schema. → `schema_invalid`.

### 9.2 Field-level

* **V4** `user_id`, `roadmap_id`, `metadata.assessment_version` non-empty after trim. → `missing_field`.
* **V5** `classification.label ∈ {"ND","NT"}` after upper-casing. → `invalid_classification`.
* **V6** If `classification.confidence` present, `0.0 ≤ x ≤ 1.0`. → `confidence_out_of_range`.

### 9.3 Semantic

* **V7** `scores.domains` has ≥ 1 entry. → `empty_domains`.
* **V8** `scores.overall.score` present and numeric. → `missing_field` / `schema_invalid`.
* **V9** Every `DomainScore.score` is numeric (int or float). → `schema_invalid`.
* **V10** `answers` has ≥ 1 entry unless `metadata.answers_omitted == true`. → `empty_answers`.
* **V11** `question_id` values are unique within `answers`. → `duplicate_question_id`.
* **V12** Each `answer.stage ∈ {"Q0","Q1"}`. → `schema_invalid`.

### 9.4 Non-rules (explicitly NOT validated)

To honour P1, the backend does **not**:

* Check that `overall.score` equals any aggregate of domain scores.
* Check that domain scores fall within `[0, max_score]` (frontend may use its own scale).
* Check that `classification` is "consistent" with the scores.
* Reject unknown extra keys under `metadata.extra` (pass-through bag).

These are frontend responsibilities; the backend trusts and stores.

---

## 10. Folder Structure

```
app/
  roadmap/
    __init__.py
    routes.py            # APIRouter: POST /roadmap/submit — transport + HTTP mapping only
    models.py            # Pydantic request/response models + RoadmapResult / RoadmapContext TypedDicts
    roadmap_loader.py    # load_roadmap(payload) -> RoadmapResult ; RoadmapValidationError (pure, no I/O)
    context_builder.py   # build_context(result) -> RoadmapContext ; empty_context()  (pure, no I/O)
    services.py          # persistence (Supabase upsert/fetch) + orchestration (submit, load-for-chat)
  graph/
    state.py             # + RoadmapContext TypedDict, + GraphState["roadmap"] field  (edit)
  main.py                # include_router(roadmap_router); inject roadmap context in /chat  (edit)
tests/
  roadmap/
    test_roadmap_loader.py
    test_context_builder.py
    test_routes.py
    test_services.py
    fixtures/            # sample valid + invalid score JSON payloads
```

**Separation of concerns:**

| Module | May do | Must NOT do |
|---|---|---|
| `routes.py` | Parse HTTP body, call services, map exceptions → HTTP responses. | Contain validation logic or touch Supabase directly. |
| `roadmap_loader.py` | Validate + build `RoadmapResult`. Pure. | Persist, call network, do arithmetic on scores. |
| `context_builder.py` | Render `RoadmapContext`. Pure. | Persist, interpret, recommend, reorder domains. |
| `services.py` | Orchestrate: load→persist→build; fetch active roadmap for chat. | Redefine validation or rendering (delegates to loader/builder). |
| `models.py` | Declare schemas. | Hold behaviour. |

---

## 11. Error Handling & Resilience

* **Ingest path (`/roadmap/submit`)** — fail loud (P5). Every rejection is a specific 4xx with a `code`, `message`, and `field`. `RoadmapValidationError` from the loader is caught in `routes.py` and mapped to 422 (Section 8.4). Unexpected exceptions → 500 with a generic message (no stack trace leakage).
* **Persistence failure** — a Supabase write error surfaces as 503 `persistence_unavailable`; the submit is **not** silently accepted. The frontend may retry.
* **Chat path (`/chat`)** — fail safe (P5). If loading the roadmap for context throws or returns nothing, the service falls back to `empty_context()` and the chat proceeds normally. A missing roadmap is a normal state, never an error, and must never break an existing chat turn.
* **Idempotency** — re-submitting the same `roadmap_id` for the same `user_id` upserts (overwrites) the active record; it is not an error. Distinct `roadmap_id`s from the same user overwrite the active pointer (last write wins); historical retention is deferred (Section 13).
* **Determinism** — `load_roadmap` and `build_context` are pure and referentially transparent: same input → same output, testable without Supabase or the network.

---

## 12. Sequence & Data-Flow Diagrams

### 12.1 Data-Flow Diagram

```
┌───────────┐
│ Frontend  │  Q0 → ND/NT → Q1 → Scoring Engine (COMPLETE)
└─────┬─────┘
      │ Score JSON
      ▼
┌──────────────────────┐
│ POST /roadmap/submit │  (routes.py)
└─────┬────────────────┘
      │ raw dict
      ▼
┌──────────────────┐   validate + parse (pure)
│  Roadmap Loader  │───────────────► RoadmapValidationError ──► 422
└─────┬────────────┘
      │ RoadmapResult (canonical)
      ▼
┌──────────────────┐   upsert user_roadmap_results
│    services.py   │───────────────► Supabase (persist)
└─────┬────────────┘
      │ RoadmapResult
      ▼
┌──────────────────┐
│ Context Builder  │  build_context (pure, value-preserving)
└─────┬────────────┘
      │ RoadmapContext
      ▼
┌──────────────────┐   on next /chat turn: state["roadmap"] = context
│      Manasi      │  Understanding → Knowledge → Response → Empathy → Safety → CTA
│    (pipeline)    │  reads roadmap context READ-ONLY; no therapy recommendation
└─────┬────────────┘
      ▼
   Response
```

### 12.2 Sequence Diagram — Submit

```
Frontend        Route (/roadmap/submit)   Roadmap Loader   Context Builder   services.py   Supabase
   │  score JSON        │                       │                │              │             │
   │───────────────────>│                       │                │              │             │
   │                    │  load_roadmap(payload) │                │              │             │
   │                    │──────────────────────>│                │              │             │
   │                    │   RoadmapResult / raise│                │              │             │
   │                    │<──────────────────────│                │              │             │
   │                    │        (on raise) 422  │                │              │             │
   │                    │  persist(result)       │                │              │             │
   │                    │───────────────────────────────────────────────────> upsert         │
   │                    │                        │                │              │───────────> │
   │                    │                        │                │              │  ok / err   │
   │                    │                        │                │              │<─────────── │
   │                    │  build_context(result) │                │              │             │
   │                    │───────────────────────────────────────>│              │             │
   │                    │            RoadmapContext               │              │             │
   │                    │<───────────────────────────────────────│              │             │
   │   200 accepted     │                        │                │              │             │
   │<───────────────────│                        │                │              │             │
```

### 12.3 Sequence Diagram — Chat consumption

```
Frontend      Route (/chat)     services.py      Supabase      Manasi pipeline
   │  message      │                 │               │                │
   │──────────────>│  fetch active roadmap           │                │
   │               │────────────────>│──────────────>│                │
   │               │                 │  RoadmapResult │                │
   │               │                 │<──────────────│                │
   │               │  build_context / empty_context  │                │
   │               │  state["roadmap"] = context     │                │
   │               │────────────────────────────────────────────────>│  invoke()
   │               │                 │               │  reads roadmap (read-only)
   │               │                 │               │  answer grounded in scores,
   │               │                 │               │  NO therapy recommendation
   │               │<────────────────────────────────────────────────│
   │  answer       │                 │               │                │
   │<──────────────│                 │               │                │
```

---

## 13. Future Expansion Points (Reserved — NOT Implemented)

These are declared as extension seams so this phase's code is forward-compatible. **None** is built now.

| Future phase | Seam reserved in this phase | Explicitly deferred |
|---|---|---|
| **Therapy Recommendation Engine** | `RoadmapResult` is the canonical input a recommender will read; a future `roadmap/recommender.py` will consume it. | All ranking/matching of therapies to scores. |
| **Roadmap Generator** | The stored `scores`/`answers` are complete enough to drive generation later. | Any generation of a plan/roadmap from results. |
| **PDF Generator** | `RoadmapResult` + `summary_text` are render-ready inputs for a future `roadmap/pdf.py`. | Producing any document/file. |
| **Email Service** | Persisted results + `user_id` give a future notifier what it needs. | Sending any email/notification. |
| **Database Persistence (history)** | `user_roadmap_results` schema can gain a history table; `roadmap_id` already uniquely keys each run. | Multi-version retention, querying past assessments. |
| **Admin Review** | Stored `result` jsonb is queryable for a future admin surface. | Any admin UI, moderation, or override flow. |

Guardrail: any PR that adds recommendation, diagnosis, PDF, or email logic to `app/roadmap/` in *this* phase is out of scope and should be rejected in review.

---

## 14. Functional Requirements (traceable)

| ID | Requirement |
|---|---|
| FR-1 | `POST /roadmap/submit` SHALL accept the frontend score JSON and return 200 on success. |
| FR-2 | The Roadmap Loader SHALL validate the payload per Section 9 and raise `RoadmapValidationError` on any violation. |
| FR-3 | The route SHALL map `RoadmapValidationError` to a 422 with `code`/`message`/`field` (Section 8.4). |
| FR-4 | The loader SHALL produce a canonical `RoadmapResult`; no other module SHALL consume the raw payload. |
| FR-5 | The backend SHALL store `RoadmapResult` per `user_id` (upsert) and stamp `received_at` server-side. |
| FR-6 | The Context Builder SHALL render a `RoadmapContext` preserving every score, answer, and classification verbatim. |
| FR-7 | On `/chat`, the backend SHALL inject the user's `RoadmapContext` (or `empty_context()`) into `state["roadmap"]`. |
| FR-8 | Manasi SHALL be able to answer factual follow-up questions using roadmap context, and SHALL NOT recommend therapies. |
| FR-9 | The backend SHALL NOT recalculate, alter, round, or re-rank any score or classification (P1). |
| FR-10 | The ingest path SHALL make no LLM, embeddings, RAG, or external network call. |
| FR-11 | A missing roadmap SHALL never cause a chat turn to fail (fail-safe read). |
| FR-12 | Adding `state["roadmap"]` SHALL be backward-compatible with all existing endpoints. |

---

## 15. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-1 **Performance** | Ingest (validate + persist) SHALL complete in < 300 ms p95 excluding Supabase round-trip; validation/build are pure in-memory ops (target < 20 ms). |
| NFR-2 **Determinism** | `load_roadmap` and `build_context` SHALL be pure functions (same input → same output). |
| NFR-3 **Isolation** | Raw frontend JSON SHALL NOT appear in any module outside `roadmap_loader.py`. |
| NFR-4 **Backward compatibility** | Existing `/chat`, `/understand`, `/knowledge`, `/respond`, `/humanize`, `/safety`, `/cta` SHALL continue to function unchanged when no roadmap exists. |
| NFR-5 **Security** | `user_id` scoping SHALL prevent one user reading another's roadmap; no PII beyond what the frontend supplies is added. CORS inherits the existing allow-list. |
| NFR-6 **Observability** | Each submit SHALL log `user_id`, `roadmap_id`, outcome (accepted/rejected + code), and timing — without logging full answer contents. |
| NFR-7 **Testability** | Loader, builder, and services SHALL be unit-testable without a live Supabase (services mockable). |
| NFR-8 **Data fidelity** | Round-trip (submit → store → build context) SHALL preserve all numeric values with no precision loss or rounding. |

---

## 16. Acceptance Criteria

1. Submitting the Section 8.2 example returns the Section 8.3 success body; a row exists in `user_roadmap_results` for `user_1837` whose `result` jsonb round-trips to an equal `RoadmapResult`.
2. Removing `scores.overall.score` from the payload yields 422 `missing_field` naming `scores.overall.score`; nothing is persisted.
3. A payload with `classification.label: "nd"` is accepted and normalized to `"ND"`; `"maybe"` yields 422 `invalid_classification`.
4. Duplicate `question_id` yields 422 `duplicate_question_id`.
5. After a successful submit, a `/chat` turn asking "what was my communication score?" has `state["roadmap"]["present"] == True` and `summary_text` containing the exact stored value; Manasi answers factually and does **not** recommend a therapy.
6. A `/chat` turn for a user with no submitted roadmap has `state["roadmap"]["present"] == False`, `summary_text == ""`, and completes normally.
7. No score value anywhere in the pipeline differs from the submitted value (fidelity check, NFR-8).
8. `grep` confirms no LLM/RAG/network import in `roadmap_loader.py` or `context_builder.py` (FR-10).

---

## 17. Implementation Checklist

- [ ] `app/roadmap/models.py` — Pydantic `RoadmapSubmitRequest`/response models + `RoadmapResult`, `RoadmapContext` TypedDicts.
- [ ] `app/roadmap/roadmap_loader.py` — `load_roadmap`, `RoadmapValidationError`, Section 9 rules.
- [ ] `app/roadmap/context_builder.py` — `build_context`, `empty_context`, Section 7.2 rendering.
- [ ] `app/roadmap/services.py` — Supabase upsert/fetch + submit/chat orchestration.
- [ ] `app/roadmap/routes.py` — `POST /roadmap/submit`, exception→HTTP mapping.
- [ ] `app/graph/state.py` — add `RoadmapContext` + `GraphState["roadmap"]`.
- [ ] `app/main.py` — `include_router`; inject roadmap context into `/chat`; add guarded prompt instruction.
- [ ] Supabase migration — `user_roadmap_results` table.
- [ ] `tests/roadmap/` — loader, builder, services, routes + fixtures.
- [ ] Verify FR-9/FR-10/NFR-8 with the acceptance checks in Section 16.

---

*End of specification.*
