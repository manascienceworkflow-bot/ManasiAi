# Manasi AI — Roadmap API Integration Specification

**Project:** Manasi AI (ManaScience)
**Author:** Backend Architecture
**Audience:** Backend + Frontend engineers integrating the Roadmap Assessment feature
**Scope:** Receive the frontend's final scoring JSON and make it available to Manasi as **hidden, in-memory context**. No database. No Supabase. No therapy/PDF/email.
**Date:** 2026-07-11

---

## 1. Summary

The frontend already runs the whole assessment (Q0 → ND/NT classification → Q1 →
scoring engine) and produces one final scoring JSON. The backend's only job this
phase is:

> Receive that JSON at one endpoint → validate it → turn it into a short text
> context block → hold it **in server memory** keyed by `user_id` → inject it
> (hidden) into Manasi's `/chat` prompt on subsequent turns.

**Why in-memory, not a database:** the brief forbids persistence, but the
context must survive from the `/roadmap/submit` call to later `/chat` calls (they
are separate HTTP requests). The existing backend already solves exactly this
with a module-level dict — `session_histories: dict[str, list]` in
`app/main.py:39`. We reuse that pattern with a second dict. This is **not**
database storage; it is process-lifetime session state that is lost on restart,
which is acceptable and intended for this phase.

---

## 2. Existing Route Inventory (analysis)

Every route currently defined in the backend, and whether it plays a part here.

| Method | Route | Status | Relevant to Roadmap? |
|---|---|---|---|
| `GET` | `/health` | Exists | No — no change. |
| `POST` | `/chat` | Exists (`app/main.py:83`) | **Yes — needs a small modification** (§5). Uses the RAG `chat_chain`; this is the surface where roadmap context is injected. |
| `GET` | `/chat/{session_id}/history` | Exists | No — unrelated (chat history). |
| `DELETE` | `/chat/{session_id}` | Exists | Optional — could also clear roadmap context (§6, nice-to-have). |
| `POST` | `/understand` | Exists | No — per-node debug endpoint. |
| `POST` | `/knowledge` | Exists | No — per-node debug endpoint. |
| `POST` | `/respond` | Exists | No — per-node debug endpoint. |
| `POST` | `/humanize` | Exists | No — per-node debug endpoint. |
| `POST` | `/safety` | Exists | No — per-node debug endpoint. |
| `POST` | `/cta` | Exists | No — per-node debug endpoint. |
| `POST` | `/roadmap/submit` | **Exists, needs modification** (`app/roadmap/routes.py:15`) | **Yes — the entry point.** Currently persists to Supabase and uses a different field casing; must be switched to in-memory + the contract in §4. See §7. |

**Authentication:** there is **no authentication** anywhere in the project — no
auth routes, no middleware, no `Depends()` security, no token checks. `user_id`
is supplied by the client in the request body (the same way `session_id` is
passed to `/chat`). This spec follows that existing convention: the roadmap
endpoint requires **no auth header**. (Adding auth is a separate, future concern
for the whole API, not this feature.)

### Verdict

- **One route is needed:** `POST /roadmap/submit`. It **already exists** but must
  be reworked to the no-persistence, in-memory design and the §4 contract.
- **One route needs modification:** `POST /chat` — read roadmap context from the
  in-memory store and inject it into the chain (a few lines).
- **No brand-new routes** are required. Reuse the existing `app/roadmap/` module
  (`roadmap_loader.py`, `context_builder.py`) — only the persistence layer and
  field casing change.

---

## 3. Required Routes — full specification

### 3.1 `POST /roadmap/submit` — receive the scoring JSON

| Field | Value |
|---|---|
| **Method** | `POST` |
| **URL** | `/roadmap/submit` |
| **Purpose** | Receive the frontend's final scoring JSON, validate it, build a hidden Manasi context block, and hold it in memory keyed by `user_id`. **This is the route the frontend calls after Q1 scoring completes.** |
| **Auth** | None (project has no auth). |
| **Request body** | The scoring JSON — see §4. |
| **Response body** | Acknowledgement — see §3.1.2. |
| **Backend function it calls** | `app.roadmap.services.submit_roadmap(payload)`, which calls `roadmap_loader.load_roadmap()` → `context_builder.build_context()` → `roadmap_store.save_context(user_id, text)`. **No Supabase.** |

#### 3.1.1 Validation requirements

| Rule | On failure → `code` (HTTP 422) |
|---|---|
| Body is valid JSON | (HTTP 400 `invalid_json`) |
| `user_id` present, non-empty string | `missing_field` (field: `user_id`) |
| `classification` present and ∈ {Neurodivergent, Neurotypical} (case-insensitive) | `invalid_classification` |
| `scores` present, non-empty array | `empty_scores` |
| each `scores[i].domain` present, non-empty string | `invalid_score_entry` |
| each `scores[i].score` present and numeric | `invalid_score_entry` |
| `scores[i].severity` — optional; stored verbatim | (not validated) |

The backend **never recomputes, rounds, re-ranks, or clamps** any score — values
are stored exactly as received. Severity vocabulary and score range (0–100) are
**recommended** for the frontend but not hard-enforced, so the backend never
rejects a value the scoring engine considered valid.

#### 3.1.2 Response body (200)

```json
{
  "status": "accepted",
  "user_id": "users_id",
  "classification": "Neurodivergent",
  "domains_received": 2,
  "context_ready": true
}
```

`context_ready: true` means the context is now in memory and Manasi will see it on
the next `/chat` turn. No scores are echoed back (the frontend already has them).

---

## 4. Frontend Contract (exact JSON schema)

The frontend sends **exactly** this shape (a single object):

```json
{
  "user_id": "users_id",
  "classification": "Neurodivergent",
  "scores": [
    { "domain": "Attention", "score": 82, "severity": "High" },
    { "domain": "Memory",    "score": 64, "severity": "Moderate" }
  ]
}
```

| Field | Required | Type | Allowed values / rules |
|---|---|---|---|
| `user_id` | ✅ | string | Non-empty. Must be the **same** identifier passed as `session_id` to `/chat`, so Manasi can match the context to the conversation. |
| `classification` | ✅ | string | `"Neurodivergent"` or `"Neurotypical"` (case-insensitive; `"ND"`/`"NT"` also accepted). |
| `scores` | ✅ | array | Non-empty. One entry per assessed domain. |
| `scores[].domain` | ✅ | string | Non-empty, e.g. `"Attention"`, `"Memory"`. Free-form label from the scoring engine. |
| `scores[].score` | ✅ | number | The domain score. Recommended range `0–100`. Stored verbatim, never recomputed. |
| `scores[].severity` | ⬜ optional | string | Recommended: `"Low"`, `"Moderate"`, `"High"`. Stored verbatim; other values accepted. |

**Notes for the frontend developer**
- Send a **single JSON object**, not an array-wrapped one.
- `Content-Type: application/json` is required.
- Unknown extra fields are ignored (kept internally, never surfaced to the user).
- Re-submitting for the same `user_id` **replaces** that user's context (last
  submission wins).

---

## 5. Does `/chat` need modification?

**Yes — a small one.** `/chat` is where the hidden context reaches Manasi. It
must read the user's roadmap context from the in-memory store and pass it into
the RAG chain, which already has a `{roadmap_context}` slot in its system prompt
(`app/rag/chain.py`).

Change (conceptual):

```python
# app/main.py, inside /chat, before chat_chain.invoke(...)
roadmap_context = roadmap_store.get_context(request.session_id)   # "" if none

result = chat_chain.invoke({
    "input": request.message,
    "chat_history": langchain_history,
    "roadmap_context": roadmap_context,     # hidden; never shown to the user
})
```

- `roadmap_store.get_context()` returns `""` when the user has no roadmap on file,
  so chat behaves exactly as today for users who never took the assessment.
- The context is injected into the **system prompt** only — it is never returned
  in the `/chat` response body, so the user never sees the raw JSON.
- No other route (`/understand`, `/respond`, etc.) needs to change.

---

## 6. Backend Processing Flow

```
Frontend (after Q1 scoring)
   │  POST /roadmap/submit   { user_id, classification, scores[] }
   ▼
app/roadmap/routes.py  (submit)
   │  raw JSON
   ▼
roadmap_loader.load_roadmap(payload)        ── validate + normalize (the ONLY
   │  RoadmapResult                             place raw JSON is touched; no
   │                                            arithmetic on scores)
   ▼
context_builder.build_context(result)       ── render hidden text block
   │  summary_text  (+ "do not recommend therapies" guardrail line)
   ▼
roadmap_store.save_context(user_id, text)   ── IN-MEMORY dict, NOT a database
   │
   ▼
200  { status: "accepted", context_ready: true }

           ······ later, on any chat turn ······

Frontend  POST /chat  { message, session_id == user_id }
   ▼
app/main.py (/chat)
   │  roadmap_store.get_context(session_id)  →  hidden context ("" if none)
   ▼
chat_chain.invoke({ input, chat_history, roadmap_context })   ── app/rag/chain.py
   ▼
Manasi answers, silently aware of the roadmap; JSON never shown to the user
```

### Components (reuse existing `app/roadmap/` module, no new architecture)

| Component | File | Responsibility |
|---|---|---|
| Route | `app/roadmap/routes.py` | `POST /roadmap/submit`; map validation errors → 422. |
| Loader | `app/roadmap/roadmap_loader.py` | Validate + normalize raw JSON → `RoadmapResult`. Pure. |
| Context Builder | `app/roadmap/context_builder.py` | `RoadmapResult` → hidden text block. Pure. |
| **Store (new, tiny)** | `app/roadmap/store.py` | Module-level `dict[str, str]` + `save_context()` / `get_context()`. **In-memory only**, mirroring `session_histories`. |
| Service | `app/roadmap/services.py` | Orchestrate loader → builder → store; return ack. |
| Chat injection | `app/rag/chain.py` + `app/main.py` `/chat` | Existing `{roadmap_context}` slot; read from store and pass in. |

---

## 7. What must change vs. the current code

The `/roadmap/submit` route and `app/roadmap/` module already exist but were built
against an earlier brief that **persisted to Supabase** and used a different field
casing. To match **this** spec:

1. **Remove Supabase from the roadmap path.** Replace the `user_roadmap_results`
   upsert/select in `app/roadmap/services.py` with an in-memory
   `app/roadmap/store.py` (dict). `/chat` reads from the store, not Supabase.
   *(Chat history's own Supabase usage is pre-existing and unrelated — leave it.)*
2. **Update the field contract** in `roadmap_loader.py` to §4:
   `classification` (was `Classification`), `scores` (was `score`), `score` (was
   `Score`), `severity` (was `Severity`); accept numeric `score`.
3. **Keep** the loader/context-builder/validation structure, error codes, and the
   hidden-context injection — those already match this design.

*(These are code deltas, not part of the frontend contract. Happy to apply them on request.)*

---

## 8. Future Roadmap Routes (not needed now)

Reserved for later phases — **do not build this phase**:

- `GET /roadmap/{user_id}` — inspect the stored context (debug/admin).
- `DELETE /roadmap/{user_id}` — clear a user's context.
- Durable persistence, roadmap history/versioning, therapy recommendation, PDF,
  email, dashboard — all future, all out of scope here.

---

## 9. Frontend Integration

Everything the frontend developer needs to integrate roadmap submission.

- **Endpoint:** `POST /roadmap/submit`
  (full URL = `<API_BASE_URL>/roadmap/submit`, e.g. `https://api.manascience.in/roadmap/submit`)
- **Method:** `POST`
- **Headers:** `Content-Type: application/json` — **no auth header** required.
- **When to call:** once, immediately after the Q1 scoring engine produces the
  final JSON. Use the **same `user_id`** you pass as `session_id` to `/chat`.
- **What to send:** the §4 JSON.

### Success response — `200 OK`

```json
{
  "status": "accepted",
  "user_id": "users_id",
  "classification": "Neurodivergent",
  "domains_received": 2,
  "context_ready": true
}
```

Treat `status === "accepted"` (or HTTP 200) as success. After this, Manasi
automatically uses the roadmap on subsequent `/chat` calls — no extra step.

### Error responses to handle

| HTTP | `error.code` | Meaning / how to handle |
|---|---|---|
| `400` | `invalid_json` | Body wasn't valid JSON. Fix the payload. |
| `422` | `missing_field` | A required field is missing (`error.field` names it, e.g. `user_id`). |
| `422` | `invalid_classification` | `classification` not Neurodivergent/Neurotypical. |
| `422` | `empty_scores` | `scores` missing or empty. |
| `422` | `invalid_score_entry` | A `scores[]` item lacks a valid `domain`/`score`. |
| `503` | `service_unavailable` | Backend still starting up — retry shortly. |

Error body shape:

```json
{ "detail": { "status": "rejected", "error": { "code": "missing_field", "message": "Required field 'user_id' is missing.", "field": "user_id" } } }
```

### Example — `fetch()`

```js
async function submitRoadmap(scoreJson) {
  const res = await fetch(`${API_BASE_URL}/roadmap/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(scoreJson),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail?.error?.code || `HTTP ${res.status}`);
  }
  return res.json(); // { status: "accepted", context_ready: true, ... }
}

// after Q1 scoring:
await submitRoadmap({
  user_id: currentUserId,               // same id used as session_id in /chat
  classification: "Neurodivergent",
  scores: [
    { domain: "Attention", score: 82, severity: "High" },
    { domain: "Memory",    score: 64, severity: "Moderate" },
  ],
});
```

### Example — Axios

```js
import axios from "axios";

try {
  const { data } = await axios.post(
    `${API_BASE_URL}/roadmap/submit`,
    {
      user_id: currentUserId,
      classification: "Neurodivergent",
      scores: [
        { domain: "Attention", score: 82, severity: "High" },
        { domain: "Memory",    score: 64, severity: "Moderate" },
      ],
    },
    { headers: { "Content-Type": "application/json" } }
  );
  // data.context_ready === true  → Manasi is now roadmap-aware
} catch (e) {
  const code = e.response?.data?.detail?.error?.code || e.message;
  // surface `code` to your error handling
}
```

### Integration checklist

- [ ] Call `POST /roadmap/submit` once, right after Q1 scoring.
- [ ] Send `user_id` identical to the `/chat` `session_id`.
- [ ] Send `classification` + a non-empty `scores` array (`domain` + numeric `score` each).
- [ ] Treat HTTP 200 / `status: "accepted"` as success; no further call needed.
- [ ] Handle 400/422 by reading `detail.error.code` (and `.field`).
- [ ] Do **not** display the roadmap JSON to the user — it's hidden context only.
```
