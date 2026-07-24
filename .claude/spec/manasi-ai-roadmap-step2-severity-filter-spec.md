# Manasi AI — Roadmap Pipeline **Step 2: Severity Filtering Module** — Technical Specification

**Project:** Manasi AI (ManaScience)
**Component:** `app/roadmap/severity_filter.py` (new)
**Pipeline position:** Step 2 of the Roadmap Assessment Pipeline
**Depends on:** Step 1 — Roadmap Ingestion (`POST /roadmap/submit`, `app/roadmap/roadmap_loader.py`) — **already implemented and shipped** (commit `e860b9c`).
**Author:** Backend Architecture
**Status:** Ready for implementation
**Date:** 2026-07-14

---

## 0. Reader's note — one contract discrepancy you must decide on

The brief for this document shows the frontend payload with **lowercase** keys:

```json
{ "user_id": "...", "classification": "...", "score": [ { "domain": "...", "score": 72, "severity": "High" } ] }
```

The **shipped Step 1 loader** (`app/roadmap/roadmap_loader.py:117-127`) actually requires **mixed-case** keys:

| Brief says | Shipped Step 1 requires | Location |
|---|---|---|
| `classification` | **`Classification`** | `roadmap_loader.py:125` |
| `score` (array) | `score` (array) ✅ same | `roadmap_loader.py:127` |
| `score[].domain` | `score[].domain` ✅ same | `roadmap_loader.py:86` |
| `score[].score` | **`score[].Score`** | `roadmap_loader.py:94` |
| `score[].severity` | **`score[].Severity`** | `roadmap_loader.py:108` |

This spec **does not resolve that discrepancy and does not depend on it.** Step 2 is deliberately specified against the **canonical `RoadmapResult` object that Step 1 emits** — whose attributes are already normalized lowercase (`domain`, `score`, `severity`; `models.py:6-16`) — not against the raw wire JSON. This is not a workaround; it is the correct layering and it is what the existing architecture already mandates (see §4.1, principle **P2**). Consequently:

- If you later fix the wire casing to match the brief, **Step 2 needs no change at all.**
- Step 2 never reads `Classification` / `Score` / `Severity` and never sees raw JSON keys.

**Action for the product owner:** decide separately whether Step 1's wire contract should be lowercased to match `docs/roadmap-submit-frontend.md`. It is out of scope here.

---

## 1. Purpose

Step 2 exists to answer exactly one question, deterministically:

> **Of the domains the assessment scored, which ones are clinically actionable?**

Manasi's downstream pipeline (therapy mapping, roadmap generation — **all out of scope**) must only ever operate on domains the assessment flagged as **High** or **Moderate** severity. Domains scored **Low** represent areas where the user is functioning adequately; carrying them forward would dilute the roadmap, waste downstream LLM/compute budget, and — most importantly — risk recommending intervention for a non-issue.

The Severity Filtering Module is the single, authoritative gate that enforces this. It is a **pure, side-effect-free transformation**:

```
RoadmapResult  ──filter_by_severity()──►  FilteredRoadmapResult
(all domains)                             (High + Moderate only)
```

It performs **no** persistence, **no** network I/O, **no** LLM calls, **no** arithmetic on scores, and **no** mutation of its input. Given the same input it produces byte-identical output, forever.

---

## 2. Scope

### 2.1 In scope

| # | Responsibility |
|---|---|
| 1 | Accept the validated `RoadmapResult` produced by Step 1. |
| 2 | Read its `scores` array. |
| 3 | Normalize each entry's `severity` value (case, whitespace, unicode). |
| 4 | Validate each entry against the severity vocabulary. |
| 5 | Keep entries whose severity ∈ {High, Moderate}. |
| 6 | Drop entries whose severity is Low. |
| 7 | Drop-and-record entries whose severity is missing, null, empty, or unrecognized (§7.4). |
| 8 | Collapse duplicate domains under a deterministic, severity-safe policy (§7.5). |
| 9 | Return a **new** `FilteredRoadmapResult` object plus machine-readable diagnostics. |
| 10 | Emit structured logs for every drop decision. |
| 11 | Expose an optional `GET`-free service function so Step 3+ can consume the filtered set. |

### 2.2 Explicitly out of scope

The module **must not**, and this spec **does not** describe:

| ❌ Not this module | Where it belongs |
|---|---|
| Therapy / intervention mapping | Step 3 (separate spec) |
| Roadmap generation | Step 4 (separate spec) |
| Recommendation engine | Future |
| PDF generation | Future |
| Email / notification | Future |
| Database or Supabase persistence | Step 1's service layer already owns this (`services.py:11`) |
| Any LLM / AI / RAG call | `app/rag/`, `app/nodes/` |
| Re-scoring, rounding, re-ranking, clamping any `score` | **Forbidden project-wide** (principle P1) |
| Mutating the frontend's JSON | **Forbidden** (§3.3) |
| Receiving the HTTP request / parsing raw JSON | **Step 1 — already done** (`routes.py:16`) |
| Deciding severity thresholds from the numeric `score` | Frontend's scoring engine owns this. Backend trusts `severity` verbatim. |

> **Note on "reading and validating JSON":** the brief lists "Reading JSON" and "Validating JSON" as Step 2 responsibilities. In this codebase those two acts are **already performed by Step 1** — `routes.py:23` reads the body, `roadmap_loader.load_roadmap()` validates it, and the project's principle **P2** states the loader is the *only* place the raw wire format may be touched. Duplicating JSON parsing inside the filter would create two owners of the wire contract and guarantee drift. Step 2 therefore inherits parsed, validated data and adds the **one class of validation Step 1 deliberately does not do: severity-vocabulary validation** (`roadmap_loader.py:108` stores severity verbatim with zero checks). §6 specifies exactly which validations belong to which step, so nothing is skipped — it is only placed correctly.

---

## 3. Module Responsibilities

### 3.1 Positive responsibilities (the module MUST)

1. **MUST** be a pure function: same input → same output, no observable side effects other than logging.
2. **MUST** treat its input as immutable (§3.3).
3. **MUST** preserve the **input order** of the surviving domains. It must **not** sort, re-rank, or prioritize — ranking is a downstream concern and re-ranking here would violate P1.
4. **MUST** preserve each surviving entry's `domain`, `score`, and original `severity` **verbatim**, alongside the normalized severity.
5. **MUST** return a *new* object graph; it must never hand back references into the input.
6. **MUST** be deterministic under duplicates, unicode, and mixed casing.
7. **MUST** account for every input entry: `len(kept) + len(dropped) == len(input_scores)` is an invariant the implementation asserts (§20, AC-12).
8. **MUST** be callable without a FastAPI request, without Supabase, and without env vars — so it is unit-testable in isolation and reusable from a CLI, a batch job, or a LangGraph node.

### 3.2 Negative responsibilities (the module MUST NOT)

The function signature makes most of these structurally impossible — it takes no `supabase` client, no `Request`, no LLM handle, and returns a plain model:

```python
def filter_by_severity(result: RoadmapResult, *, strict: bool = False) -> FilteredRoadmapResult
```

There is no seam through which it could persist, email, or call an AI. This is intentional: **the type signature is the enforcement mechanism.** Code review must reject any change that adds a client/session/connection parameter to this module.

### 3.3 The immutability guarantee

> **"The original frontend JSON must never be modified."**

Three layers enforce this:

1. **Step 1 already froze it.** `RoadmapResult.raw` (`models.py:29`) holds the original payload dict. Step 2 **never touches `.raw`** — it reads only `.scores`.
2. **No in-place list ops.** The implementation must build a **new** list. It must never call `result.scores.remove()`, `.pop()`, `del result.scores[i]`, or `result.scores[:] = ...`. A list comprehension / explicit `append` loop only.
3. **Deep-copied entries.** Every surviving entry is rebuilt via `entry.model_copy(deep=True)` before being placed in the output, so that a downstream module mutating a `FilteredDomainScore` cannot reach back and corrupt the `RoadmapResult` that other consumers (e.g. `context_builder.build_context()`, `services.py:52`) still hold.

Verified by acceptance criteria AC-02 and AC-03 (§20).

---

## 4. Architecture

### 4.1 Governing principles (inherited from the existing project)

| ID | Principle | Consequence for Step 2 |
|---|---|---|
| **P1** | Scores and severities are **never** recomputed, rounded, or re-ranked by the backend (`models.py:8-11`). | The filter may **select** and **normalize-for-comparison**, but the values it carries forward are byte-identical to what arrived. It never derives severity from the numeric score. |
| **P2** | The loader is the **only** module that touches the raw wire format (`roadmap_loader.py:118`). | Step 2 consumes `RoadmapResult`, never a `dict`. |
| **P3** | Write path fails **loud**; read path fails **safe** (`services.py:11-17` vs `services.py:45-69`). | Filtering on the submit (write) path may raise. Filtering on a chat (read) path must degrade to "no filtered domains" rather than break a conversation. §10.4. |
| **P4** | Vertical-slice packaging: everything roadmap lives in `app/roadmap/`. | New file goes in `app/roadmap/`, not a global `services/`. |

### 4.2 Placement in the package

```
app/roadmap/
├── __init__.py
├── routes.py            # Step 1 — HTTP boundary               (EXISTS, unchanged)
├── roadmap_loader.py    # Step 1 — raw JSON → RoadmapResult    (EXISTS, unchanged)
├── models.py            # shared Pydantic models               (EXISTS, +3 new models)
├── severity_filter.py   # ★ STEP 2 — THIS MODULE               (NEW)
├── services.py          # orchestration                        (EXISTS, +1 new function)
└── context_builder.py   # RoadmapResult → hidden chat context  (EXISTS, unchanged)
```

**Nothing existing is rewritten.** Step 2 is purely additive: one new module, three new models, one new service function. `routes.py`, `roadmap_loader.py`, and `context_builder.py` are not modified.

### 4.3 Layered view (Clean Architecture)

```
┌──────────────────────────────────────────────────────────────┐
│ FRAMEWORK / DELIVERY   routes.py  (FastAPI, HTTP, status codes)│  ← knows HTTP
├──────────────────────────────────────────────────────────────┤
│ APPLICATION / USE-CASE services.py (orchestrates the steps)   │  ← knows Supabase
├──────────────────────────────────────────────────────────────┤
│ DOMAIN / PURE LOGIC                                           │
│   roadmap_loader.py    (Step 1: parse + validate)             │  ← knows nothing
│   severity_filter.py   (Step 2: THIS MODULE)                  │     external
│   context_builder.py   (render)                               │
├──────────────────────────────────────────────────────────────┤
│ ENTITIES               models.py  (RoadmapResult, ...)        │
└──────────────────────────────────────────────────────────────┘
Dependencies point strictly DOWNWARD. severity_filter.py imports ONLY
`app.roadmap.models` + stdlib (`logging`, `unicodedata`). It imports no
FastAPI, no Supabase, no LangChain, no OpenAI. Enforced by test T-U-30.
```

### 4.4 SOLID

| Principle | How Step 2 satisfies it |
|---|---|
| **S — Single Responsibility** | The module has exactly one reason to change: *the definition of "actionable severity" changes.* It does not parse, persist, render, or rank. Note that even the severity *vocabulary* is factored into a single frozen mapping (`_SEVERITY_RANK`), so a vocabulary change is a one-line diff. |
| **O — Open/Closed** | Adding a new severity level (e.g. `"Severe"`) or changing which levels are actionable requires **only** editing the `_SEVERITY_RANK` / `ACTIONABLE_SEVERITIES` constants (§7.1) — no branch of the filtering algorithm changes, because the algorithm is a set-membership test, not an `if/elif` chain over literals. A hardcoded `if sev == "high" or sev == "moderate"` would violate this and **must not** be written. |
| **L — Liskov** | `FilteredRoadmapResult` is **not** a subclass of `RoadmapResult` (§9.3) — deliberately. A filtered result is *not* substitutable for a complete one (a consumer that reasons about "all domains" would be silently wrong), so inheritance would be a Liskov violation. Composition is used instead. |
| **I — Interface Segregation** | Downstream consumers that only need the surviving domains import `FilteredRoadmapResult`; they are not forced to depend on `RoadmapResult`, the loader, or the diagnostics type. The diagnostics live in a separate model so a consumer can ignore them entirely. |
| **D — Dependency Inversion** | `severity_filter` depends only on the `models` abstraction layer, never on the concrete delivery (FastAPI) or persistence (Supabase) mechanisms. Those depend on *it*. |

### 4.5 Reusability

Because the filter is pure and framework-free, the same function is directly callable from:

- the `POST /roadmap/submit` route (Step 1's existing write path),
- any future LangGraph node in `app/nodes/`,
- the chat read path (`services.get_roadmap_context_text`),
- a batch/CLI re-processing script in `scripts/`,
- unit tests, with no fixtures, no env vars, and no fakes.

---

## 5. Detailed Processing Flow

### 5.1 The pipeline, stage by stage

```
┌─────────────┐
│  FRONTEND   │  Q1 scoring engine produces the final assessment JSON
└──────┬──────┘
       │  HTTP POST /roadmap/submit
       │  Content-Type: application/json
       ▼
╔══════════════════════════════════════════════════════════════╗
║ STAGE 0 — RECEIVE          routes.py:23   [STEP 1 — DONE]     ║
║   payload = await request.json()                              ║
║   Unparseable body → 400 invalid_json. Nothing else happens.  ║
╚══════════════════════════════════════════════════════════════╝
       │  payload: dict | list
       ▼
╔══════════════════════════════════════════════════════════════╗
║ STAGE 1 — VALIDATE + NORMALIZE   roadmap_loader.py:117        ║
║                                            [STEP 1 — DONE]    ║
║   _unwrap()      list-of-one → object; empty/multi → reject   ║
║   _require()     user_id, Classification, score present       ║
║   _parse_scores()each entry is an object w/ domain + Score    ║
║   Severity is read but NOT validated — stored verbatim.       ║
║   Any violation → RoadmapValidationError → HTTP 422           ║
╚══════════════════════════════════════════════════════════════╝
       │  RoadmapResult (canonical, immutable, all domains)
       │  .scores = [RoadmapDomainScore(domain, score, severity), ...]
       ▼
╔══════════════════════════════════════════════════════════════╗
║ ★ STAGE 2 — SEVERITY FILTER      severity_filter.py           ║
║                                            [STEP 2 — THIS SPEC]║
║                                                               ║
║  2a. GUARD          empty scores?  → empty result, no error   ║
║                     len > MAX_DOMAINS? → payload_too_large    ║
║                                                               ║
║  2b. ITERATE        for i, entry in enumerate(result.scores): ║
║                       (single pass, input order preserved)    ║
║                                                               ║
║  2c. NORMALIZE      raw = entry.severity                      ║
║                       None/non-str      → key = None          ║
║                       NFKC → strip → collapse ws → casefold   ║
║                       ""                → key = None          ║
║                                                               ║
║  2d. CLASSIFY       key in ACTIONABLE   → KEEP                ║
║                     key in EXCLUDED     → DROP (low_severity) ║
║                     key is None         → DROP (missing_sev)  ║
║                     key unrecognized    → DROP (unknown_sev)  ║
║                       (strict=True → raise instead of drop)   ║
║                                                               ║
║  2e. DEDUPE         same normalized domain seen before?       ║
║                       → keep the HIGHER-ranked severity;      ║
║                         tie → first occurrence wins;          ║
║                       → loser recorded as DROP (duplicate)    ║
║                                                               ║
║  2f. COPY           entry.model_copy(deep=True) → new object  ║
║                                                               ║
║  2g. ASSEMBLE       FilteredRoadmapResult(kept, diagnostics)  ║
║                     assert kept + dropped == len(input)       ║
╚══════════════════════════════════════════════════════════════╝
       │  FilteredRoadmapResult (High + Moderate only)
       ▼
   ┌───────────────────────────────────────────────┐
   │  RETURNED TO CALLER.  Step 2 ends here.       │
   │  Steps 3+ (therapy mapping, roadmap gen) are  │
   │  OUT OF SCOPE for this document.              │
   └───────────────────────────────────────────────┘
```

### 5.2 Stage-by-stage narrative

**Stage 0 — Receive.** Already built. `routes.py:23` reads the raw body. This spec changes nothing here. If the body is not valid JSON, the request dies with a `400` and Step 2 is never reached — which is why "Invalid JSON" is *not* a Step 2 edge case in the sense of Step 2 code running; it is covered in §11 as an inherited, pre-Step-2 outcome.

**Stage 1 — Validate + normalize.** Already built. `load_roadmap()` guarantees, by the time Step 2 runs, that: the payload was an object (or a one-element list), `user_id` is a non-empty string, `classification` mapped to `ND`/`NT`, `score` was a **non-empty list**, and **every** entry is an object with a non-empty string `domain` and a present, non-boolean `Score` of type `str|int|float`. `severity` is the **only** field that reaches Step 2 unvalidated. This is precisely the gap Step 2 fills.

> **Design consequence:** several edge cases from the brief ("missing score array", "domain missing", "score missing", "invalid JSON", "malformed request") are **structurally unreachable inside Step 2** — Step 1 rejects them with a 422 first. §11 documents each one with its actual guard location, so that the behaviour is defined end-to-end even though the code path lives one layer up. Step 2 still asserts these invariants defensively (§6.2) so that a *programmatic* caller who hand-builds a malformed `RoadmapResult` gets a loud failure rather than silent corruption.

**Stage 2a — Guard.** Two cheap O(1) checks before the loop. An empty `scores` list is **not an error** at this layer (see §11, EC-01) — it returns an empty filtered set. A list longer than `MAX_DOMAINS` (default 500) is rejected as a resource guard (§15.3).

**Stage 2b — Iterate.** Exactly one pass, in input order. No sorting. No nested loops. No lookahead. `O(n)`.

**Stage 2c — Normalize.** The severity string is reduced to a canonical *comparison key*. This is a **read-only derivation**: the original `severity` string is carried into the output untouched (P1). Normalization is four steps, in this order, and the order matters:

1. **Unicode NFKC** — folds compatibility forms so that `"Ｈｉｇｈ"` (fullwidth) and `"High"` compare equal, and prevents homoglyph-based bypass (§15.2).
2. **Strip** — removes leading/trailing whitespace, including `\t`, `\n`, `\r`, and non-breaking space ` `.
3. **Collapse internal whitespace** — `"Mod  erate"` does **not** become `"moderate"` (that would be guessing); but `"Very  High"` collapses to `"very high"` so multi-word future vocabularies compare cleanly. Implemented as `" ".join(s.split())`.
4. **Casefold** — `str.casefold()`, not `str.lower()`. Casefold is the correct Unicode-aware operation for caseless matching. This is what makes `High` / `HIGH` / `high` / `HiGh` all match.

**Stage 2d — Classify.** A set-membership test against frozen constants. Four mutually exclusive, exhaustive outcomes. No `if/elif` ladder over string literals (that would break Open/Closed).

**Stage 2e — Dedupe.** See §7.5 for the full rationale. Summary: **the higher severity always wins.** Never silently discard the more severe signal for a domain.

**Stage 2f — Copy.** Deep copy, so the output shares no mutable state with the input.

**Stage 2g — Assemble.** Build the result object and assert the accounting invariant.

---

## 6. Validation Rules

### 6.1 Ownership matrix — which layer validates what

Every validation in the system, and its single owner. **No rule is owned twice.**

| # | Rule | Owner | On failure | Error code | HTTP |
|---|---|---|---|---|---|
| V-01 | Body is syntactically valid JSON | Step 1 · `routes.py:23` | reject | `invalid_json` (plain detail) | 400 |
| V-02 | Payload is an object, or a one-element list | Step 1 · `_unwrap` | raise | `payload_not_object` | 422 |
| V-03 | Payload list has ≤ 1 element | Step 1 · `_unwrap` | raise | `ambiguous_batch` | 422 |
| V-04 | `user_id` present, non-empty string | Step 1 · `load_roadmap` | raise | `missing_field` | 422 |
| V-05 | `classification` present + in vocabulary | Step 1 · `_normalize_classification` | raise | `invalid_classification` | 422 |
| V-06 | `score` array present and non-empty | Step 1 · `_parse_scores` | raise | `empty_scores` | 422 |
| V-07 | Each `score[i]` is an object | Step 1 · `_parse_scores` | raise | `invalid_score_entry` | 422 |
| V-08 | Each `score[i].domain` is a non-empty string | Step 1 · `_parse_scores` | raise | `invalid_score_entry` | 422 |
| V-09 | Each `score[i].score` is present, `str\|int\|float`, not `bool` | Step 1 · `_parse_scores` | raise | `invalid_score_entry` | 422 |
| **V-10** | **`scores` list length ≤ `MAX_DOMAINS`** | **Step 2** | raise | `payload_too_large` | **413** |
| **V-11** | **Each severity is a `str` or `None`** | **Step 2** | drop / raise | `invalid_severity_type` | 422 (strict) |
| **V-12** | **Each severity, normalized, is in the known vocabulary** | **Step 2** | drop / raise | `unknown_severity` | 422 (strict) |
| **V-13** | **Each severity is present and non-blank** | **Step 2** | drop / raise | `missing_severity` | 422 (strict) |
| **V-14** | **Input is a `RoadmapResult`** (programmatic contract) | **Step 2** | raise | `TypeError` | 500 |
| **V-15** | **Accounting: kept + dropped == input count** | **Step 2** | raise | `AssertionError` | 500 |

**Rules V-10 through V-15 are the entirety of Step 2's validation surface.** Everything above them is inherited, already implemented, and already tested.

### 6.2 Defensive invariant checks (V-14)

`filter_by_severity` is a public function in a Python codebase with no runtime type enforcement. A future caller could hand it a `dict`, a `None`, or a hand-rolled `RoadmapResult` with a `scores=None`. The module therefore opens with:

```python
if not isinstance(result, RoadmapResult):
    raise TypeError(
        f"filter_by_severity expects a RoadmapResult (the output of Step 1's "
        f"load_roadmap); got {type(result).__name__}. Do not pass raw JSON — "
        f"parsing the wire format is Step 1's job (spec P2)."
    )
```

This is a **programmer error**, not a user error. It is a `TypeError`, not a `RoadmapValidationError`, and it must surface as a `500` — because a `422` would tell the frontend to fix a payload that was, in fact, fine.

### 6.3 The `strict` flag — why it exists

`filter_by_severity(result, *, strict: bool = False)`.

- **`strict=False` (default, production):** an unrecognized/missing severity causes the domain to be **dropped and recorded**, not to fail the request. Rationale: the frontend's scoring engine is the source of truth for severity and may legitimately evolve its vocabulary ahead of a backend deploy. A user who completed a 40-minute assessment must not receive a 422 because one domain came back as `"Borderline"`. The domain is excluded (it is not provably actionable), the drop is logged at `WARNING`, and it is surfaced in `diagnostics.warnings` so the frontend/observability can see it. **Fail-open on the domain, never on the request.**
- **`strict=True` (CI, contract tests, batch validation):** the same condition raises `RoadmapValidationError("unknown_severity", ...)`. This is how the contract test suite proves the frontend and backend vocabularies agree, and how a future admin/backfill script can refuse to process garbage silently.

> **This is the single most consequential decision in this spec.** The alternative — hard-rejecting unknown severities in production — trades a real, user-facing outage risk for a theoretical data-quality benefit that the `WARNING` log and `diagnostics.warnings` already deliver. If the product owner disagrees, the change is flipping one default; the code path already exists and is tested (T-U-18).

---

## 7. Filtering Rules

### 7.1 The vocabulary — the single source of truth

```python
# app/roadmap/severity_filter.py

# Rank is used for two things: (a) membership, (b) duplicate resolution
# (higher rank wins). Adding a level = adding one line here. Nothing else
# in this module changes. (Open/Closed — see §4.4.)
_SEVERITY_RANK: dict[str, int] = {
    "low":      1,
    "moderate": 2,
    "high":     3,
}

# The ONLY definition of "actionable". Downstream steps import THIS,
# never a hardcoded literal.
ACTIONABLE_SEVERITIES: frozenset[str] = frozenset({"high", "moderate"})

# Known-but-excluded. Distinguished from "unknown" so the two produce
# different drop reasons, different log levels, and different diagnostics.
EXCLUDED_SEVERITIES: frozenset[str] = frozenset(_SEVERITY_RANK) - ACTIONABLE_SEVERITIES
# → frozenset({"low"})

MAX_DOMAINS: int = 500
```

**Invariant asserted at import time:** `ACTIONABLE_SEVERITIES <= _SEVERITY_RANK.keys()` — you cannot mark a severity actionable without ranking it.

### 7.2 The decision table

For each entry, exactly one row applies. This table is **total** (every possible input value matches exactly one row) and is the normative definition of the module's behaviour.

| # | Normalized severity key | Decision | Drop reason | Log level | In `diagnostics.warnings`? |
|---|---|---|---|---|---|
| 1 | `"high"` | **KEEP** | — | `DEBUG` | no |
| 2 | `"moderate"` | **KEEP** | — | `DEBUG` | no |
| 3 | `"low"` | **DROP** | `low_severity` | `DEBUG` | no — this is normal, expected, non-anomalous |
| 4 | `None` (severity was `None`, or not a `str`, or blank/whitespace-only after normalization) | **DROP** | `missing_severity` | `WARNING` | **yes** |
| 5 | any other non-empty key (`"borderline"`, `"severe"`, `"hgh"`, `"n/a"`, `"1"`, …) | **DROP** | `unknown_severity` | `WARNING` | **yes** |
| 6 | duplicate of a domain already kept, and this entry does not out-rank it | **DROP** | `duplicate_domain` | `WARNING` | **yes** |

Rows 4 and 5 raise `RoadmapValidationError` instead of dropping when `strict=True`.

> **Why is Low dropped at `DEBUG` and not `WARNING`?** Dropping a Low domain is the module *doing its job*. Logging it at `WARNING` would flood the logs with the single most common event in the system and desensitize on-call to real warnings. Rows 4–6 are genuine data anomalies and deserve `WARNING`.

### 7.3 Case, whitespace, and unicode

All handled by the normalization in Stage 2c. Concretely, **every one of these keeps the domain**:

```
"High"  "HIGH"  "high"  "hIgH"  "  High  "  "High\n"  "\tHigh"  "High "
"Ｈｉｇｈ"  (fullwidth NFKC)     "ＭＯＤＥＲＡＴＥ"     "Moderate"  "MODERATE"  "moderate"
```

And **every one of these drops the domain** (as `unknown_severity`, because guessing is unsafe):

```
"Hgh"  "Hi gh"  "High-ish"  "High "  → no wait: "High " KEEPS (trailing ws stripped).
"Hi gh"  "H1gh"  "elevated"  "3"  "severe"  "borderline"  "n/a"  "-"  "null"
```

> **The module never fuzzy-matches, never spell-corrects, and never infers severity from the numeric `score`.** `{"domain": "X", "score": 95, "severity": "Hgh"}` is dropped, not silently promoted to High, even though 95 "obviously" looks high. Inferring would be *the backend recomputing severity* — a direct P1 violation and a patient-safety hazard. It is dropped, logged at `WARNING`, and surfaced in `diagnostics.warnings` so a human notices the typo.

### 7.4 Missing / null / blank severity

`RoadmapDomainScore.severity` is `Optional[str]` (`models.py:15`) and Step 1 stores it verbatim without validation — so `None` genuinely reaches Step 2. Policy: **drop, warn, record.**

Rationale: a domain with no severity is a domain the scoring engine did not classify. It is **not provably actionable**. Including it would push an unclassified domain into therapy mapping. Excluding it is the conservative, fail-safe choice, and the `WARNING` + `diagnostics.warnings` entry ensures the gap is visible rather than silent. (`strict=True` turns this into a hard failure for contract tests.)

### 7.5 Duplicate domains — the resolution policy

Two distinct sub-cases from the brief:

**(a) "Multiple identical objects"** — byte-identical entries, e.g. `Attention/72/High` twice. Collapsed to one. No information is lost. Recorded as `duplicate_domain`, logged at `WARNING` (a well-behaved frontend should not emit these).

**(b) "Duplicate domains"** — the *same domain* with **conflicting** data, e.g. `Attention/72/High` and `Attention/40/Low`. This is the dangerous case, and a naive "keep first" or "keep last" is **wrong**: whichever you pick, a payload-ordering change could silently drop a High-severity domain out of a clinical roadmap.

**Policy: highest severity wins. Ties resolve to first occurrence (stable).**

```
Rank: high(3) > moderate(2) > low(1) > [unrecognized/missing: rank 0, never wins]

Attention/High  +  Attention/Low       → Attention/High  kept   (High out-ranks Low)
Attention/Low   +  Attention/High      → Attention/High  kept   (order-independent ✔)
Attention/High  +  Attention/Moderate  → Attention/High  kept
Attention/High  +  Attention/High      → first occurrence kept  (tie → stable)
Attention/Low   +  Attention/Low       → BOTH dropped (low_severity), no dup warning
                                          — they never entered the kept set
```

This makes the output **invariant under input reordering** for the duplicate case, which is a property the naive policies do not have, and it is the only policy that can never discard a more-severe signal.

**Domain identity** for deduplication is the **normalized domain**: `NFKC → strip → collapse internal whitespace → casefold`. So `"Attention & Concentration"`, `"attention & concentration"`, and `"  Attention  &  Concentration "` are the **same** domain. The **first-seen original spelling** is what appears in the output (P1: values carried verbatim).

> **Note:** the deduplication key is the *domain*, not the whole entry. Domain identity is deliberately case/whitespace-insensitive because the frontend's domain labels are free-form strings (`roadmap_loader.py:86`) and a stray capitalization must not produce two "Attention" rows in a clinical roadmap.

### 7.6 Extra / unexpected attributes

Step 1's `RoadmapDomainScore` is a Pydantic model with three declared fields; Pydantic v2's default is to **ignore** undeclared keys, so extra attributes inside a `score[i]` object (`{"domain": ..., "Score": ..., "Severity": ..., "confidence": 0.9, "notes": "..."}`) are already dropped at Step 1's boundary. They never reach Step 2. Top-level extra fields are preserved in `RoadmapResult.raw` (`models.py:29`) and Step 2 never reads `.raw`.

**Net effect: extra fields are inert. They cannot change the filter's output.** This is asserted by T-U-25.

### 7.7 The worked example from the brief

Input severities: `High, Moderate, Low, High, Low` (5 distinct domains).

```
i=0  "High"      → normalize "high"      → in ACTIONABLE  → KEEP
i=1  "Moderate"  → normalize "moderate"  → in ACTIONABLE  → KEEP
i=2  "Low"       → normalize "low"       → in EXCLUDED    → DROP (low_severity)
i=3  "High"      → normalize "high"      → in ACTIONABLE  → KEEP
i=4  "Low"       → normalize "low"       → in EXCLUDED    → DROP (low_severity)

Output (input order preserved):  High, Moderate, High     ✔ matches the brief exactly
Accounting: 3 kept + 2 dropped == 5 input                 ✔ invariant holds
```

---

## 8. Input Schema

### 8.1 Formal input — `RoadmapResult` (existing, `app/roadmap/models.py:18`)

Step 2's input is **not** JSON. It is the canonical object Step 1 emits.

```python
class RoadmapResult(BaseModel):
    user_id: str                          # non-empty, guaranteed by Step 1 (V-04)
    classification_raw: str               # e.g. "neurodivergent" — as received
    classification: Literal["ND", "NT"]   # normalized by Step 1 (V-05)
    scores: list[RoadmapDomainScore]      # non-empty, guaranteed by Step 1 (V-06)
    raw: dict                             # the original payload — STEP 2 NEVER READS THIS

class RoadmapDomainScore(BaseModel):
    domain: str                           # non-empty, stripped, guaranteed by Step 1 (V-08)
    score: str | float | int              # verbatim; may be 72 or "72%" (V-09)
    severity: Optional[str] = None        # ★ VERBATIM AND UNVALIDATED — Step 2's whole job
```

| Field | Step 2 reads it? | Step 2 validates it? | Notes |
|---|---|---|---|
| `user_id` | yes — for logging only | no (Step 1 did) | Never used in a filtering decision. |
| `classification` | yes — carried to output | no (Step 1 did) | **Does not affect filtering.** An `NT` user's Moderate domain is kept exactly as an `ND` user's is. Classification-conditional filtering is *not* in this spec. |
| `classification_raw` | yes — carried to output | no | Passthrough. |
| `scores` | **yes — the subject of the module** | **yes — length (V-10)** | |
| `scores[].domain` | yes — dedup key + output | no (Step 1 did) | Normalized *for comparison only*; original spelling preserved. |
| `scores[].score` | yes — output passthrough | **no — deliberately** | Never inspected. Never compared to a threshold. Never used to infer severity. (P1) |
| `scores[].severity` | **yes — the filtering key** | **yes (V-11/12/13)** | |
| `raw` | **NO — never touched** | — | Immutability guarantee (§3.3). |

### 8.2 Illustrative wire payload (for context only — parsed by Step 1, not Step 2)

Using the **shipped** Step 1 casing (see §0):

```json
{
  "user_id": "u_8f21c",
  "Classification": "neurodivergent",
  "score": [
    { "domain": "Attention & Concentration", "Score": 72, "Severity": "High" },
    { "domain": "Memory & Processing",       "Score": 42, "Severity": "Low" },
    { "domain": "Executive Function",        "Score": 61, "Severity": "Moderate" }
  ]
}
```

→ Step 1 → `RoadmapResult(user_id="u_8f21c", classification="ND", scores=[3 entries])` → **Step 2 starts here.**

---

## 9. Output Schema

### 9.1 New models (to be added to `app/roadmap/models.py`)

```python
from typing import Literal, Optional
from pydantic import BaseModel


class FilteredDomainScore(BaseModel):
    """One domain that SURVIVED the Step 2 severity filter, i.e. its severity is
    High or Moderate. `domain`, `score`, and `severity` are carried VERBATIM from
    the frontend (spec P1) -- `severity_key` is the normalized comparison key the
    filter derived, exposed so downstream steps can branch on a canonical value
    without re-implementing normalization."""

    domain: str                     # verbatim, original spelling
    score: str | float | int        # verbatim, NEVER recomputed
    severity: Optional[str]         # verbatim, original casing (e.g. "HIGH")
    severity_key: Literal["high", "moderate"]   # normalized; only actionable values exist here
    severity_rank: int              # 3 = high, 2 = moderate. For downstream ordering ONLY.


class DroppedDomain(BaseModel):
    """One domain the Step 2 filter EXCLUDED, with the machine-readable reason.
    Retained for diagnostics/observability -- NOT for downstream therapy mapping.
    Every input entry appears in exactly one of `kept` or `dropped` (AC-12)."""

    domain: str
    severity: Optional[str]         # verbatim, as received (may be None)
    reason: Literal[
        "low_severity",             # known-good, deliberately excluded — the normal case
        "missing_severity",         # None / blank / non-string
        "unknown_severity",         # non-empty but outside the vocabulary
        "duplicate_domain",         # same domain kept elsewhere at >= severity
    ]
    index: int                      # position in the ORIGINAL scores array


class FilterDiagnostics(BaseModel):
    """Counts + human-readable warnings about what Step 2 threw away. Exists so a
    caller can observe data-quality problems WITHOUT the filter having to fail the
    request (spec §6.3). `warnings` is empty on a clean payload."""

    total_received: int
    total_kept: int
    total_dropped: int
    dropped_low: int
    dropped_missing_severity: int
    dropped_unknown_severity: int
    dropped_duplicate: int
    warnings: list[str] = []        # human-readable, one per anomalous drop


class FilteredRoadmapResult(BaseModel):
    """The output of Step 2. Carries ONLY the actionable (High/Moderate) domains.

    Deliberately NOT a subclass of RoadmapResult (Liskov, spec §4.4): a filtered
    result is not substitutable for a complete one, and a downstream module that
    treated it as 'all the user's domains' would be silently, dangerously wrong.

    This object is what Step 3 (therapy mapping -- OUT OF SCOPE HERE) will consume."""

    user_id: str
    classification: Literal["ND", "NT"]
    classification_raw: str
    filtered_scores: list[FilteredDomainScore]   # High + Moderate, in INPUT order
    dropped: list[DroppedDomain]                 # everything else, for observability
    diagnostics: FilterDiagnostics

    @property
    def is_empty(self) -> bool:
        """True when NO domain was actionable. A legitimate, non-error outcome:
        the user scored Low everywhere. Callers MUST handle this (spec EC-08)."""
        return len(self.filtered_scores) == 0
```

### 9.2 Example output for the §7.7 worked example

```json
{
  "user_id": "u_8f21c",
  "classification": "ND",
  "classification_raw": "neurodivergent",
  "filtered_scores": [
    { "domain": "Attention & Concentration", "score": 72, "severity": "High",     "severity_key": "high",     "severity_rank": 3 },
    { "domain": "Executive Function",        "score": 61, "severity": "Moderate", "severity_key": "moderate", "severity_rank": 2 }
  ],
  "dropped": [
    { "domain": "Memory & Processing", "severity": "Low", "reason": "low_severity", "index": 1 }
  ],
  "diagnostics": {
    "total_received": 3,
    "total_kept": 2,
    "total_dropped": 1,
    "dropped_low": 1,
    "dropped_missing_severity": 0,
    "dropped_unknown_severity": 0,
    "dropped_duplicate": 0,
    "warnings": []
  }
}
```

### 9.3 Why `dropped` is returned at all

It is tempting to return only the survivors. The dropped list earns its place for three reasons:

1. **Auditability.** In a clinical-adjacent product, "why was this user's Memory domain not in their roadmap?" must be answerable from a single object without re-running the pipeline.
2. **The accounting invariant (V-15/AC-12).** `kept + dropped == received` is only checkable if both are materialized. It is the cheapest possible guard against a filter bug that silently eats a domain.
3. **Observability without coupling.** The route can surface counts to the frontend and the logs without the filter needing a logger injection or a metrics client (Dependency Inversion).

It is **explicitly not** an input to therapy mapping. That is stated in the `DroppedDomain` docstring so the next engineer cannot miss it.

---

## 10. Error Handling

### 10.1 Exception taxonomy

Step 2 **reuses the existing `RoadmapValidationError`** (`roadmap_loader.py:9`) rather than inventing a parallel exception type. It already carries `code` / `message` / `field`, and `routes.py:29` already maps it to a structured 422. Introducing a second exception class would force a second `except` clause in every route and split the error contract — a needless breach of Single Responsibility at the boundary.

```python
from app.roadmap.roadmap_loader import RoadmapValidationError
```

> **Coupling note:** importing an exception class from `roadmap_loader` into `severity_filter` is a domain→domain dependency within the same layer — acceptable, and preferable to duplicating the type. If a future refactor wants zero coupling, lift `RoadmapValidationError` into `app/roadmap/errors.py` and have both import it. That is a 3-line change and is **not** required for this spec.

### 10.2 Every error Step 2 can produce

| Condition | Exception | `code` | `field` | HTTP | Rationale |
|---|---|---|---|---|---|
| `result` is not a `RoadmapResult` | `TypeError` | — | — | **500** | Programmer error, not user error. A 422 would blame a blameless payload. |
| `len(scores) > MAX_DOMAINS` | `RoadmapValidationError` | `payload_too_large` | `score` | **413** | Resource guard (§15.3). 413 is the semantically correct code; the route adds this mapping. |
| Severity missing/null/blank, **`strict=True`** | `RoadmapValidationError` | `missing_severity` | `score[i].Severity` | 422 | Contract-test path only. Never fires in production defaults. |
| Severity unrecognized, **`strict=True`** | `RoadmapValidationError` | `unknown_severity` | `score[i].Severity` | 422 | Contract-test path only. |
| Severity is a non-string (e.g. `3`, `["High"]`), **`strict=True`** | `RoadmapValidationError` | `invalid_severity_type` | `score[i].Severity` | 422 | Contract-test path only. |
| Accounting invariant violated | `AssertionError` | — | — | **500** | Internal bug. Must be loud. Must never be caught and swallowed. |

**With `strict=False` (production default), Step 2 raises exactly two things: `TypeError` (bug) and `payload_too_large`. Nothing a well-formed frontend can send will make it raise.**

### 10.3 Route mapping (`app/roadmap/routes.py`)

`routes.py:29-40` already handles `RoadmapValidationError → 422` and `Exception → 503`. Step 2 requires **one** addition — mapping `payload_too_large` to a 413 rather than a 422:

```python
except RoadmapValidationError as exc:
    logger.info("roadmap submit rejected: code=%s field=%s", exc.code, exc.field)
    status = 413 if exc.code == "payload_too_large" else 422
    raise HTTPException(
        status_code=status,
        detail={"status": "rejected",
                "error": {"code": exc.code, "message": exc.message, "field": exc.field}},
    ) from exc
```

The error envelope shape is **unchanged**, so the frontend's existing error handling (`docs/roadmap-submit-frontend.md`) continues to work without modification.

### 10.4 Fail-loud vs fail-safe (principle P3)

| Call site | Posture | Behaviour on failure |
|---|---|---|
| **Write path** — `POST /roadmap/submit` | **Fail LOUD** | Exceptions propagate to the route → 413/422/500. A submission that we cannot filter is a submission we do not silently accept. |
| **Read path** — a future chat turn / context build | **Fail SAFE** | The caller wraps `filter_by_severity` in `try/except Exception`, logs `WARNING`, and proceeds with an empty filtered set. **A filtering bug must never break a live conversation with a user.** This mirrors `services.get_roadmap_context_text` (`services.py:45-69`) exactly. |

The **filter itself never chooses** which posture applies — it always raises. The *caller* decides. This keeps the pure function pure and puts the policy at the layer that knows the context.

### 10.5 What is explicitly NOT an error

These are normal outcomes and must return `200`:

- **All domains are Low** → empty `filtered_scores`, `is_empty == True`, HTTP 200. (§11 EC-08)
- **One domain has an unknown severity** (default mode) → dropped, warned, HTTP 200.
- **Duplicate domains present** → deduplicated, warned, HTTP 200.

---

## 11. Edge Cases

Every edge case named in the brief, with its guard, owner, and exact behaviour. **This table is normative.**

| ID | Edge case | Guard location | Behaviour | HTTP |
|---|---|---|---|---|
| **EC-01** | **Empty `score` array** (`"score": []`) | Step 1 · `_parse_scores` (`roadmap_loader.py:79`) | **Rejected by Step 1** as `empty_scores`. Step 2 never runs. *If* a programmatic caller constructs a `RoadmapResult` with `scores=[]` and calls Step 2 directly, Step 2 returns an **empty `FilteredRoadmapResult`, not an error** — an empty input trivially filters to an empty output. | 422 (via API) / 200 (direct) |
| **EC-02** | **Missing `score` array** (key absent) | Step 1 · `_require` | Rejected as `missing_field`, field `score`. | 422 |
| **EC-03** | **`score` is not an array** (`"score": "high"`) | Step 1 · `_parse_scores` | Rejected as `empty_scores`. | 422 |
| **EC-04** | **Missing severity** (key absent → `severity is None`) | **Step 2** · Stage 2c/2d row 4 | **Domain DROPPED**, reason `missing_severity`, `WARNING` logged, added to `diagnostics.warnings`. Request succeeds. | 200 |
| **EC-05** | **Null severity** (`"Severity": null`) | **Step 2** | Identical to EC-04 — Step 1 stores `None` for both (`roadmap_loader.py:108`). Indistinguishable, and correctly so. | 200 |
| **EC-06** | **Blank / whitespace-only severity** (`"   "`, `"\t\n"`) | **Step 2** · normalization → `""` → key `None` | Identical to EC-04. `missing_severity`. | 200 |
| **EC-07** | **Invalid / unknown severity** (`"Severe"`, `"Borderline"`, `"Hgh"`, `"3"`, `"N/A"`) | **Step 2** · Stage 2d row 5 | **Domain DROPPED**, reason `unknown_severity`, `WARNING`, in `diagnostics.warnings`. **Never guessed at, never spell-corrected, never inferred from `score`.** | 200 |
| **EC-08** | **All domains are Low** → nothing survives | **Step 2** | **NOT an error.** Returns `filtered_scores: []`, `is_empty == True`, `diagnostics.dropped_low == n`. Logged at `INFO`. The caller must handle an empty actionable set. | **200** |
| **EC-09** | **Duplicate domains, conflicting severity** (`Attention/High` + `Attention/Low`) | **Step 2** · Stage 2e | **Higher severity wins** — `Attention/High` kept, the Low entry dropped as `duplicate_domain` (note: *not* `low_severity` — it lost the dedup, which is the more specific reason). `WARNING`. **Order-independent.** | 200 |
| **EC-10** | **Duplicate domains, identical entries** (byte-identical) | **Step 2** · Stage 2e | Collapsed to **one**. First occurrence kept (stable tie-break). Second dropped as `duplicate_domain`. `WARNING`. | 200 |
| **EC-11** | **Duplicate domains, both Low** | **Step 2** | **Both dropped as `low_severity`.** Neither ever entered the kept set, so no duplicate warning is raised — reporting a "duplicate" for two entries that were both excluded anyway would be noise. | 200 |
| **EC-12** | **Duplicate domains differing only in case/whitespace** (`"Attention"` / `"  attention "`) | **Step 2** · normalized dedup key | Treated as the **same domain**. Deduplicated per EC-09. The **first-seen original spelling** appears in the output. | 200 |
| **EC-13** | **`score` (numeric) missing** from an entry | Step 1 · `_parse_scores` (`roadmap_loader.py:94`) | Rejected as `invalid_score_entry`, field `score[i].Score`. Step 2 never runs. | 422 |
| **EC-14** | **`domain` missing / empty / not a string** | Step 1 · `_parse_scores` (`roadmap_loader.py:86`) | Rejected as `invalid_score_entry`, field `score[i].domain`. | 422 |
| **EC-15** | **`score` entry is not an object** (`"score": ["High"]`) | Step 1 · `_parse_scores` (`roadmap_loader.py:81`) | Rejected as `invalid_score_entry`. | 422 |
| **EC-16** | **Invalid JSON** (syntactically broken body) | Step 0 · `routes.py:23` | `400`, detail `"Request body is not valid JSON."` Step 1 and Step 2 never run. | 400 |
| **EC-17** | **Malformed request** — payload is a scalar, `null`, or a multi-element list | Step 1 · `_unwrap` (`roadmap_loader.py:39-52`) | `payload_not_object` or `ambiguous_batch`. | 422 |
| **EC-18** | **Case sensitivity** — `High` / `HIGH` / `high` / `HiGh` | **Step 2** · `casefold()` | **All KEPT.** Same for `Moderate`/`MODERATE`/`moderate` and `Low`/`LOW`/`low` (all dropped). | 200 |
| **EC-19** | **Whitespace around severity** — `" High "`, `"High\n"`, `"\tHigh"`, `"High "` (NBSP) | **Step 2** · NFKC + `strip()` | **All KEPT.** NBSP is folded to a normal space by NFKC, then stripped. | 200 |
| **EC-20** | **Unicode / fullwidth severity** — `"Ｈｉｇｈ"` | **Step 2** · NFKC | **KEPT.** Also closes a homoglyph bypass (§15.2). | 200 |
| **EC-21** | **Severity is a non-string type** (`"Severity": 3`, `["High"]`, `{"v":"High"}`) | **Step 2** · Stage 2c | Step 1 coerces via `str(severity)` (`roadmap_loader.py:108`), so Step 2 sees `"3"` / `"['High']"` — which normalize to unrecognized keys → **DROPPED as `unknown_severity`**. Never silently coerced into a valid level. | 200 |
| **EC-22** | **Severity is boolean** (`"Severity": true`) | **Step 2** | Step 1 → `"True"` → unrecognized → **DROPPED as `unknown_severity`**. | 200 |
| **EC-23** | **Unexpected / extra attributes inside a `score[i]`** | Step 1 · Pydantic default `extra="ignore"` | **Silently ignored at Step 1's boundary.** They never reach Step 2 and **cannot** affect the filter's output. Asserted by T-U-25. | 200 |
| **EC-24** | **Extra top-level fields** (`"foo": "bar"`) | Step 1 | Preserved in `RoadmapResult.raw`. Step 2 **never reads `.raw`**. Inert. | 200 |
| **EC-25** | **Large payload** — 10 000 domains | **Step 2** · V-10 `MAX_DOMAINS` | **REJECTED** as `payload_too_large`. See §15.3 for why a cap is necessary and why 500. | **413** |
| **EC-26** | **Large payload within the cap** — 500 domains | **Step 2** | Processed normally. Single O(n) pass; measured well under the 5 ms budget (§14.1 / AC-09). | 200 |
| **EC-27** | **A single domain, High** | **Step 2** | Kept. `filtered_scores` has 1 entry. | 200 |
| **EC-28** | **Every domain High** | **Step 2** | All kept, input order preserved, zero drops. | 200 |
| **EC-29** | **Mixed anomalies in one payload** (a High, a Low, a null-severity, an unknown, a duplicate) | **Step 2** | Each entry independently resolved by the §7.2 decision table. Decisions **do not interact** (except dedup, which is explicitly stateful). Accounting invariant still holds. | 200 |
| **EC-30** | **Input mutated by a downstream consumer** | **Step 2** · `model_copy(deep=True)` | Impossible to corrupt the source `RoadmapResult`. Asserted by AC-02/AC-03. | — |

---

## 12. Sequence Flow

```
Frontend        routes.py        roadmap_loader     severity_filter        services       (Step 3+)
   │                │                   │                  │                   │          OUT OF SCOPE
   │  POST          │                   │                  │                   │
   │  /roadmap/     │                   │                  │                   │
   │  submit        │                   │                  │                   │
   ├───────────────►│                   │                  │                   │
   │                │                   │                  │                   │
   │                │ await request.json()                 │                   │
   │                ├──┐                │                  │                   │
   │                │  │ ✗ bad JSON ────┼──────────────────┼───────────────────┼─► 400
   │                │◄─┘                │                  │                   │
   │                │                   │                  │                   │
   │                │ submit_roadmap(payload, supabase)    │                   │
   │                ├──────────────────────────────────────┼──────────────────►│
   │                │                   │                  │                   │
   │                │                   │  load_roadmap(payload)   [STEP 1]    │
   │                │                   │◄─────────────────┼───────────────────┤
   │                │                   ├──┐               │                   │
   │                │                   │  │ _unwrap       │                   │
   │                │                   │  │ _require      │                   │
   │                │                   │  │ _parse_scores │                   │
   │                │                   │◄─┘               │                   │
   │                │  ✗ RoadmapValidationError            │                   │
   │                │◄──────────────────┤ ─────────────────┼───────────────────┼─► 422
   │                │                   │                  │                   │
   │                │                   │  RoadmapResult   │                   │
   │                │                   ├─────────────────────────────────────►│
   │                │                   │                  │                   │
   │                │                   │   filter_by_severity(result)  ★STEP 2│
   │                │                   │                  │◄──────────────────┤
   │                │                   │                  ├──┐                │
   │                │                   │                  │  │ guard: len ≤ 500│
   │                │                   │                  │  │ for each entry:│
   │                │                   │                  │  │   normalize    │
   │                │                   │                  │  │   classify     │
   │                │                   │                  │  │   dedupe       │
   │                │                   │                  │  │   deep-copy    │
   │                │                   │                  │  │ assert kept+   │
   │                │                   │                  │  │   dropped == n │
   │                │                   │                  │◄─┘                │
   │                │  ✗ payload_too_large                 │                   │
   │                │◄─────────────────────────────────────┤───────────────────┼─► 413
   │                │                   │                  │                   │
   │                │                   │  FilteredRoadmapResult               │
   │                │                   │                  ├──────────────────►│
   │                │                   │                  │                   │
   │                │                   │                  │  ┌────────────────┴──────────────┐
   │                │                   │                  │  │ persist (Step 1's existing    │
   │                │                   │                  │  │ Supabase upsert — unchanged)  │
   │                │                   │                  │  └────────────────┬──────────────┘
   │                │                   │                  │                   │
   │                │           ack + filter counts        │                   │
   │                │◄─────────────────────────────────────────────────────────┤
   │  200 OK        │                   │                  │                   │
   │◄───────────────┤                   │                  │                   │
   │                │                   │                  │                   │
   │                │                   │       ┌──────────┴───────────────────┴──────────────┐
   │                │                   │       │  STEP 2 ENDS HERE.                          │
   │                │                   │       │  FilteredRoadmapResult is the handoff       │
   │                │                   │       │  artifact for Step 3 (therapy mapping),     │
   │                │                   │       │  which is OUT OF SCOPE for this document.   │
   │                │                   │       └─────────────────────────────────────────────┘
```

---

## 13. API Behaviour

### 13.1 Does Step 2 add a new endpoint?

**No.** Step 2 is a pure library module. It adds **zero** routes. It runs inside the **existing** `POST /roadmap/submit`. Adding a `POST /roadmap/filter` endpoint would expose an internal pipeline stage as a public API — a coupling we would have to support forever, for no consumer that exists.

### 13.2 Change to the existing `POST /roadmap/submit` response

The response model gains **three optional, additive fields**. Existing frontend code that reads `status` / `context_ready` is **unaffected** — no field is removed or renamed.

```python
class RoadmapSubmitResponse(BaseModel):
    status: Literal["accepted"]
    user_id: str
    classification: Literal["ND", "NT"]
    domains_received: int
    context_ready: bool
    # ── NEW (Step 2), all additive ──
    domains_actionable: int = 0        # count of High + Moderate survivors
    domains_filtered_out: int = 0      # count dropped for any reason
    filter_warnings: list[str] = []    # data-quality warnings; [] on a clean payload
```

**The response deliberately does NOT echo the filtered domains themselves.** The frontend already holds every domain and every severity — it computed them. Returning them would be redundant payload and would tempt the frontend to re-derive the roadmap client-side. It gets **counts and warnings**; the filtered set stays server-side as the input to Step 3.

### 13.3 Success example — `200 OK`

Input: 3 domains (High, Low, Moderate).

```json
{
  "status": "accepted",
  "user_id": "u_8f21c",
  "classification": "ND",
  "domains_received": 3,
  "context_ready": true,
  "domains_actionable": 2,
  "domains_filtered_out": 1,
  "filter_warnings": []
}
```

### 13.4 Success with data-quality warnings — `200 OK`

Input: `Attention/High`, `Memory/null-severity`, `Executive/"Severe"`.

```json
{
  "status": "accepted",
  "user_id": "u_8f21c",
  "classification": "ND",
  "domains_received": 3,
  "context_ready": true,
  "domains_actionable": 1,
  "domains_filtered_out": 2,
  "filter_warnings": [
    "score[1] 'Memory & Processing': severity is missing or null; domain excluded from the actionable set.",
    "score[2] 'Executive Function': severity 'Severe' is not a recognized level (expected High/Moderate/Low); domain excluded from the actionable set."
  ]
}
```

**Still a 200.** The submission is accepted; the anomalies are reported, not fatal (§6.3).

### 13.5 All-Low outcome — `200 OK`

```json
{
  "status": "accepted", "user_id": "u_8f21c", "classification": "NT",
  "domains_received": 4, "context_ready": true,
  "domains_actionable": 0, "domains_filtered_out": 4, "filter_warnings": []
}
```

`domains_actionable: 0` is a **valid, successful** result — the user is functioning adequately across every assessed domain. **Not a 404. Not a 422.** The frontend should handle it as "no actionable domains", not as a failure. (EC-08)

### 13.6 Error — `413 Payload Too Large` (new)

```json
{
  "detail": {
    "status": "rejected",
    "error": {
      "code": "payload_too_large",
      "message": "score array carries 10000 domains; the maximum is 500.",
      "field": "score"
    }
  }
}
```

### 13.7 Full status-code table for `POST /roadmap/submit` after Step 2

| HTTP | `error.code` | Raised by | New in Step 2? |
|---|---|---|---|
| `200` | — | success (including 0 actionable domains) | — |
| `400` | (plain detail) | Step 0 — body is not valid JSON | no |
| `413` | `payload_too_large` | **Step 2 — V-10** | **yes** |
| `422` | `payload_not_object`, `ambiguous_batch`, `missing_field`, `invalid_classification`, `empty_scores`, `invalid_score_entry` | Step 1 | no |
| `422` | `missing_severity`, `unknown_severity`, `invalid_severity_type` | **Step 2 — `strict=True` only. Never fires in production.** | **yes (dormant)** |
| `500` | — | `TypeError` / `AssertionError` — internal bug | yes |
| `503` | `persistence_unavailable` | Step 1's Supabase upsert | no |

### 13.8 Idempotency

`filter_by_severity` is a pure function — trivially idempotent. Re-submitting the same payload produces an identical `FilteredRoadmapResult` and, via Step 1's existing upsert (`services.py:20`), the same stored row. Last write wins, as today. Step 2 changes nothing about this.

---

## 14. Logging Strategy

### 14.1 Conventions (inherited — match the existing codebase exactly)

- `logger = logging.getLogger("app.roadmap.severity_filter")` — dotted module path, matching `roadmap_loader.py:6` and `services.py:5`.
- **`%`-style lazy formatting always. Never f-strings in a log call.** The codebase is consistent on this (`roadmap_loader.py:141`, `services.py:30`) and it matters: an f-string is formatted even when the level is disabled, which is exactly the per-domain hot path we are logging in.
- No `basicConfig` here — the module never configures logging, only emits.

### 14.2 What is logged, and at what level

| Level | Event | Example |
|---|---|---|
| `DEBUG` | Per-domain **keep** decision | `filter keep: user_id=%s idx=%d domain=%s severity=%s` |
| `DEBUG` | Per-domain **Low** drop (expected, high-volume — must not be `WARNING`) | `filter drop(low): user_id=%s idx=%d domain=%s` |
| `INFO` | One **summary line per submission** — the workhorse line | `filter complete: user_id=%s received=%d kept=%d dropped=%d (low=%d missing=%d unknown=%d dup=%d)` |
| `INFO` | Zero actionable domains (notable, not alarming) | `filter complete: user_id=%s NO actionable domains (all %d were low/excluded)` |
| `WARNING` | Missing / null / blank severity | `filter drop(missing_severity): user_id=%s idx=%d domain=%s` |
| `WARNING` | Unknown severity — **the value is logged, because a typo in the frontend's vocabulary is exactly what this line exists to catch** | `filter drop(unknown_severity): user_id=%s idx=%d domain=%s severity=%r` |
| `WARNING` | Duplicate domain resolved | `filter dedupe: user_id=%s domain=%s kept severity=%s (rank %d), dropped idx=%d severity=%s (rank %d)` |
| `ERROR` | `payload_too_large` | `filter rejected: user_id=%s domains=%d exceeds MAX_DOMAINS=%d` |

### 14.3 What must NEVER be logged

- **The numeric `score` values.** They are the most sensitive datum in the payload (a person's cognitive assessment result) and they are **never needed** to debug a filter that does not read them. Logging domain + severity is sufficient to diagnose every failure mode in §11. This is a deliberate PII-minimization decision, not an oversight.
- The full `RoadmapResult` or `raw` payload.
- Any assessment answers or free-text.

`user_id` **is** logged, consistent with the existing roadmap modules (`roadmap_loader.py:141`, `services.py:30`), because correlating a submission across the pipeline is impossible without it. It is an opaque identifier, not a name or email.

### 14.4 Log volume

The `INFO` summary is **one line per submission**. Per-domain lines are `DEBUG`, off in production. A 500-domain payload therefore produces **1** production log line, not 500.

---

## 15. Security Considerations

### 15.1 Threat model

Step 2 is a pure, in-process transformation with **no** database access, **no** network egress, **no** filesystem access, **no** deserialization of untrusted formats (`pickle`/`yaml`/`eval`), and **no** shell or subprocess use. Its attack surface is limited to what a malicious payload can do **to the filtering process itself**.

| Threat | Applicable? | Mitigation |
|---|---|---|
| SQL / NoSQL injection | **No** | Step 2 never touches a database. Persistence is Step 1's, via the Supabase client's parameterized API (`services.py:20`). |
| Command injection | **No** | No shell, no `subprocess`, no `os.system`. |
| Deserialization RCE | **No** | Input is an already-parsed Pydantic model. No `pickle`/`eval`/`exec`. |
| Prompt injection | **No** (here) | Step 2 makes **zero LLM calls**. A malicious `domain` string like `"Ignore previous instructions"` passes through Step 2 inertly. **It becomes a real concern the moment a downstream step feeds `domain` into a prompt** — see §15.5. |
| Resource exhaustion / DoS | **Yes** | §15.3 — `MAX_DOMAINS` cap. |
| Algorithmic complexity attack | **Yes** | §15.4 — the algorithm is provably O(n). |
| Homoglyph / unicode bypass | **Yes** | §15.2 — NFKC normalization. |
| Log injection | **Yes** | §15.6 — `%r` on attacker-controlled values. |
| PII leakage via logs | **Yes** | §14.3 — scores are never logged. |

### 15.2 Input sanitization — and its precise limits

**Normalization is for comparison, never for storage.** Step 2 canonicalizes severity and domain strings *only* to derive comparison keys. The values written into `FilteredDomainScore` are the **verbatim originals** (P1). Step 2 does not, and must not, HTML-escape, SQL-escape, strip tags from, or otherwise "clean" the `domain` string — escaping is the responsibility of whichever layer *renders* the value, and pre-escaping here would corrupt the data for every other consumer.

The one sanitization Step 2 **does** perform is **Unicode NFKC normalization** on the comparison key. This is a genuine security control, not just ergonomics:

> Without NFKC, an attacker (or a buggy client) could submit severity `"Ｈｉｇｈ"` (U+FF28 fullwidth H…) which `casefold()` alone does **not** map to `"high"`. It would be classified `unknown_severity` and dropped. Conversely, a crafted string could be made to *look* like `"Low"` in a log or an admin UI while normalizing to something else. NFKC collapses these compatibility forms to a single canonical representation, so **what the filter compares is what a human reading the log sees.**

### 15.3 `MAX_DOMAINS` — resource exhaustion guard (V-10)

The real assessment has **on the order of 5–15 domains.** There is no legitimate payload with 10 000.

Without a cap, a client could `POST` a `score` array with a million entries. Step 1 would happily build a million `RoadmapDomainScore` Pydantic objects (the expensive part), and Step 2 would then deep-copy the survivors — memory and CPU proportional to attacker input, with **no authentication in front of it** (the project has no auth; `manasi-ai-roadmap-api-integration.md` §2 confirms this). That is a trivially exploitable DoS on an unauthenticated endpoint.

**`MAX_DOMAINS = 500`** — two orders of magnitude above any plausible real assessment, so it can never reject a legitimate user, while bounding the worst case to a few milliseconds and a few hundred KB.

> **Known limitation, stated plainly:** the cap is enforced in **Step 2**, which runs *after* Step 1 has already parsed and modelled all N entries. It therefore bounds Step 2's cost but **not** Step 1's. A complete fix requires a body-size limit at the ASGI/reverse-proxy layer (e.g. uvicorn `--limit-max-request-size`, or an nginx `client_max_body_size`), which is **infrastructure, not application code, and is out of scope for this spec.** The `MAX_DOMAINS` check is a correct and useful defense-in-depth layer; it is not, on its own, complete DoS protection. This should be raised as a separate infrastructure ticket. Do not let this document's existence create the impression the endpoint is fully hardened.

### 15.4 Algorithmic complexity

The algorithm is a **single pass with O(1) work per entry**: NFKC + casefold (linear in the string's length, which is bounded by the severity vocabulary in practice), a frozenset lookup, and a dict lookup for dedup. **Total: O(n) time, O(k) extra space** where k = surviving domains. There is no sort, no nested loop, no regex, and no backtracking construct — so there is **no** quadratic blowup and **no** ReDoS surface. An attacker cannot make the filter slow by choosing pathological input; they can only make it *longer*, which `MAX_DOMAINS` bounds.

### 15.5 Prompt injection — a handoff warning for Step 3 (out of scope, stated anyway)

`domain` is a **free-form, attacker-controlled string** (`roadmap_loader.py:86` requires only that it be non-empty). Step 2 passes it through verbatim, as it must.

> **The moment a downstream step interpolates `domain` into an LLM prompt, it becomes a prompt-injection vector.** Step 2 is not the place to fix this (escaping here would corrupt the data for non-LLM consumers), but the risk is created by data that flows *through* Step 2, so it is recorded here for whoever writes Step 3: **treat `FilteredDomainScore.domain` as untrusted input at any prompt boundary.** This is noted, not solved, by this document.

### 15.6 Log injection

Attacker-controlled values (`severity`, `domain`) appear in `WARNING` logs. A crafted value containing `\n` could forge a fake log line. Mitigation: unknown/anomalous values are logged with **`%r`** (`repr`), which escapes newlines and control characters, rather than `%s`. See §14.2's `unknown_severity` line.

### 15.7 Authorization

**There is none, anywhere in this project** — no auth routes, no middleware, no `Depends()` security. `user_id` is supplied by the client in the request body, unverified. This means **any client can submit a roadmap for any `user_id`.**

Step 2 does not change this, and **cannot** fix it (a pure filtering function is the wrong layer for authorization). It is recorded here because a security section that omitted it would be misleading. **Adding authentication is a separate, project-wide concern and a prerequisite for any production launch handling real assessment data.** It should be tracked as its own ticket.

---

## 16. Future Integration Points

Step 2's output is the designed handoff artifact for later stages. **None of these are built or specified here.**

| Consumer | How it will consume Step 2 | Status |
|---|---|---|
| **Step 3 — Therapy Mapping** | `for d in filtered.filtered_scores: map_domain_to_therapies(d.domain, d.severity_key)`. Iterates **only** `filtered_scores`, **never** `dropped`. | **Out of scope — separate spec** |
| **Step 4 — Roadmap Generation** | Consumes Step 3's output. | Out of scope |
| **Recommendation engine** | Future. | Out of scope |
| **PDF / Email** | Future. | Out of scope |
| **Chat context** (`context_builder.py`) | *Could* be switched to render only the actionable domains, so Manasi's hidden context is not diluted by Low domains. **A deliberate follow-up decision, not part of Step 2.** `context_builder` is unchanged by this spec. | Deferred |
| **Persistence** | Step 1's existing Supabase upsert *could* store `filtered_scores` alongside `result`. Not required for Step 2 and **not** done here. | Deferred |

### Extension points already built in

- **New severity level** (e.g. `"Severe"` → rank 4, actionable): add one line to `_SEVERITY_RANK`, add to `ACTIONABLE_SEVERITIES`. **No algorithm change.** (Open/Closed — §4.4.)
- **Classification-conditional filtering** (e.g. NT users need Moderate+ but ND users need High only): the signature already carries `classification`; add a strategy parameter. The `strict` keyword-only parameter establishes the pattern for extending the signature without breaking existing callers.
- **Score-threshold filtering** (e.g. also require `score >= 50`): would be a **new, separate predicate composed with** this one — **not** an edit to the severity filter (Single Responsibility). Note it would collide with P1 if it *derived* severity; requiring a threshold *in addition* to severity is fine.

---

## 17. Testing Strategy

### 17.1 Framework and conventions (match the existing suite exactly)

- **pytest** (`pytest==9.1.0`), tests flat in `tests/`, named `test_<module>.py`.
- Each file prepends the repo root to `sys.path` itself — there is no `conftest.py` (see `tests/test_roadmap_loader.py:1-4`). **Follow this**; do not introduce a `conftest.py` as a drive-by change.
- **Hand-rolled fakes, no `unittest.mock`** — the codebase uses `FakeSupabase`/`FakeQuery` (`tests/test_roadmap_routes.py:30-59`) and `FakeLLM`. Reuse `FakeSupabase` for the integration tests.
- Route tests must stub `SUPABASE_URL`/`SUPABASE_KEY` **before** importing the router, because `app/db.py:13` raises at import time without them (`tests/test_roadmap_routes.py:10-15`).

### 17.2 New test files

| File | Covers | Needs Supabase fake? |
|---|---|---|
| `tests/test_severity_filter.py` | **The pure filter — the bulk of the suite (§18).** | **No** — pure function, zero fixtures. |
| `tests/test_roadmap_routes.py` | **Extend** the existing file with the Step 2 integration cases (§19). | Yes (existing `FakeSupabase`). |
| `tests/test_roadmap_services.py` | **Extend** — service wires loader → filter correctly. | Yes. |

### 17.3 Coverage bar

- **100 % line and branch coverage of `severity_filter.py`.** It is ~90 lines of pure, dependency-free logic with a small, total decision table. There is no excuse for an uncovered branch, and this is a gate on merge.
- Every row of the §7.2 decision table has ≥1 dedicated test.
- Every edge case EC-01 … EC-30 in §11 maps to ≥1 test (the table in §18/§19 gives the mapping).

### 17.4 Property-based testing (recommended, not mandatory)

Two invariants are worth a `hypothesis` property test if the team is willing to add the dependency (**it is not currently in `requirements.txt`; adding it is a judgement call, and the suite is complete without it**):

- **P-01 Accounting:** for any generated `RoadmapResult`, `len(kept) + len(dropped) == len(input.scores)`.
- **P-02 Purity/immutability:** for any input, `deepcopy(input) == input` after the call.
- **P-03 Dedup order-independence:** for any input containing duplicate domains, filtering a *permutation* of the scores yields the same **set** of kept `(domain, severity_key)` pairs.

---

## 18. Unit Test Scenarios

`tests/test_severity_filter.py`. All pure — **no fakes, no env vars, no I/O**.

### Fixture helper

```python
def _result(*entries, user_id="u_test", classification="ND"):
    """Build a RoadmapResult directly, bypassing the wire format. Step 2's input
    is the loader's OUTPUT, so unit tests construct that object, not raw JSON."""
    return RoadmapResult(
        user_id=user_id,
        classification_raw="neurodivergent" if classification == "ND" else "neurotypical",
        classification=classification,
        scores=[RoadmapDomainScore(**e) for e in entries],
        raw={},
    )
```

### Core filtering

| ID | Scenario | Expected | EC |
|---|---|---|---|
| T-U-01 | **The brief's worked example**: High, Moderate, Low, High, Low | exactly `[High, Moderate, High]`, in input order; `dropped_low == 2` | §7.7 |
| T-U-02 | Single High domain | kept | EC-27 |
| T-U-03 | Single Moderate domain | kept | — |
| T-U-04 | Single Low domain | dropped; `is_empty is True`; **no exception** | EC-08 |
| T-U-05 | All domains High | all kept, order preserved, zero drops | EC-28 |
| T-U-06 | All domains Low | `filtered_scores == []`, `is_empty is True`, HTTP-layer 200 | EC-08 |
| T-U-07 | Input order is preserved (High, Moderate, High with distinct domains) | output domain sequence == input domain sequence for survivors; **not sorted by rank** | §3.1.3 |

### Case / whitespace / unicode

| ID | Scenario | Expected | EC |
|---|---|---|---|
| T-U-08 | `parametrize` over `High, HIGH, high, HiGh, hIGH` | **all kept** | EC-18 |
| T-U-09 | `parametrize` over `Moderate, MODERATE, moderate, MoDeRaTe` | **all kept** | EC-18 |
| T-U-10 | `parametrize` over `Low, LOW, low, LoW` | **all dropped**, reason `low_severity` | EC-18 |
| T-U-11 | `parametrize` over `" High "`, `"High\n"`, `"\tHigh"`, `"High "`, `"\r\nHigh \t"` | **all kept** | EC-19 |
| T-U-12 | Fullwidth `"Ｈｉｇｈ"` (NFKC) | **kept** | EC-20 |
| T-U-13 | Fullwidth `"ＭＯＤＥＲＡＴＥ"` | **kept** | EC-20 |
| T-U-14 | `severity_key` on a kept entry is always lowercase `"high"`/`"moderate"`, while `severity` retains the original casing (e.g. `"HIGH"`) | both assertions hold | §9.1 |

### Missing / null / unknown severity

| ID | Scenario | Expected | EC |
|---|---|---|---|
| T-U-15 | `severity=None` | dropped, `missing_severity`, 1 warning | EC-04/05 |
| T-U-16 | `severity=""` and `severity="   "` and `"\t\n"` | dropped, `missing_severity` | EC-06 |
| T-U-17 | `parametrize` over `"Severe", "Borderline", "Hgh", "N/A", "-", "3", "null", "elevated", "Hi gh"` | **all dropped**, `unknown_severity`, one warning each | EC-07 |
| T-U-18 | `strict=True` + unknown severity | **raises** `RoadmapValidationError(code="unknown_severity")`, `field == "score[0].Severity"` | §6.3 |
| T-U-19 | `strict=True` + `severity=None` | **raises** `RoadmapValidationError(code="missing_severity")` | §6.3 |
| T-U-20 | `strict=False` (default) + unknown severity | **does NOT raise**; domain dropped | §6.3 |
| T-U-21 | **A high `score` with a typo'd severity (`score=95, severity="Hgh"`) is DROPPED — not promoted** | dropped as `unknown_severity`; explicitly asserts the filter never infers severity from `score` (P1) | §7.3 |

### Duplicates

| ID | Scenario | Expected | EC |
|---|---|---|---|
| T-U-22 | `Attention/72/High` + `Attention/40/Low` | **High kept**, Low dropped as `duplicate_domain`; 1 survivor | EC-09 |
| T-U-23 | **Reverse order**: `Attention/40/Low` + `Attention/72/High` | **High still kept** — asserts order-independence | EC-09 |
| T-U-24 | Byte-identical duplicate entries | collapsed to **one**; second dropped as `duplicate_domain` | EC-10 |
| T-U-25 | `Attention/High` + `attention/Moderate` + `"  ATTENTION  "/Low` | treated as **one** domain; High kept with its **original spelling** `"Attention"` | EC-12 |
| T-U-26 | Two Low entries for the same domain | **both** dropped as `low_severity`; `dropped_duplicate == 0` (no dup warning) | EC-11 |
| T-U-27 | `Attention/High` + `Attention/High` (tie) | first occurrence kept (stable) | EC-10 |
| T-U-28 | Three distinct domains, no duplicates | `dropped_duplicate == 0` | — |

### Immutability & purity — **the highest-value tests in this suite**

| ID | Scenario | Expected | EC |
|---|---|---|---|
| T-U-29 | Deep-copy the input `RoadmapResult`, run the filter, assert the input `== ` its pre-call copy | **input is bit-identical after the call** | AC-02 |
| T-U-30 | Mutate a returned `FilteredDomainScore.domain` after the call | the source `RoadmapResult.scores[i].domain` is **unchanged** (deep-copy proof) | EC-30 / AC-03 |
| T-U-31 | `RoadmapResult.raw` is untouched | `result.raw` is `==` and `is` the same object it was | §3.3 |
| T-U-32 | `len(result.scores)` is unchanged after filtering | the input list was never mutated in place | §3.3 |
| T-U-33 | Calling the filter **twice** on the same input yields **equal** outputs (determinism) | `f(x) == f(x)` | AC-01 |

### Guards, accounting, and architecture

| ID | Scenario | Expected | EC |
|---|---|---|---|
| T-U-34 | `scores` list of length 501 | **raises** `RoadmapValidationError(code="payload_too_large")` | EC-25 |
| T-U-35 | `scores` list of length exactly 500 | **succeeds** (boundary — the cap is inclusive) | EC-26 |
| T-U-36 | Pass a `dict` / `None` / a string instead of a `RoadmapResult` | **raises `TypeError`** (not `RoadmapValidationError`) | V-14 |
| T-U-37 | Empty `scores=[]` constructed directly | returns empty result, **no exception** | EC-01 |
| T-U-38 | For every scenario above: `total_kept + total_dropped == total_received` | invariant holds universally | AC-12 |
| T-U-39 | `diagnostics` counts sum correctly: `dropped_low + dropped_missing + dropped_unknown + dropped_duplicate == total_dropped` | holds | §9.1 |
| T-U-40 | **Architecture guard:** `severity_filter.py`'s imports contain no `fastapi`, `supabase`, `langchain`, `openai`, or `app.db` | assert by inspecting `inspect.getsource(...)` / the module's `__dict__` | §4.3 |
| T-U-41 | Mixed-anomaly payload (High + Low + null + unknown + duplicate in one input) | each entry resolved independently per §7.2; accounting holds | EC-29 |
| T-U-42 | `classification` (ND vs NT) does **not** change which domains survive | identical `filtered_scores` for both | §8.1 |
| T-U-43 | A `score` of `"72%"` (string) survives verbatim | `filtered_scores[0].score == "72%"` — not coerced to `72` | P1 |

---

## 19. Integration Test Scenarios

Extending `tests/test_roadmap_routes.py` (reusing its existing `FakeSupabase` and its env-stub-before-import pattern) and `tests/test_roadmap_services.py`.

| ID | Scenario | Expected |
|---|---|---|
| T-I-01 | `POST /roadmap/submit` with the brief's 3-domain payload (High, Low, Moderate) | `200`; `domains_received == 3`; `domains_actionable == 2`; `domains_filtered_out == 1`; `filter_warnings == []` |
| T-I-02 | Payload where **every** domain is Low | `200`, **not** an error; `domains_actionable == 0`; `context_ready` still `true` |
| T-I-03 | Payload with one null `Severity` | `200`; `domains_filtered_out` includes it; `filter_warnings` has exactly 1 entry naming the domain |
| T-I-04 | Payload with an unknown severity (`"Severe"`) | `200`; 1 `filter_warnings` entry quoting `'Severe'`; the domain is excluded |
| T-I-05 | Payload with 501 domains | **`413`**; `detail.error.code == "payload_too_large"`; **`FakeSupabase` records ZERO writes** — a rejected payload must not be persisted |
| T-I-06 | Payload with duplicate domains, conflicting severities | `200`; the higher-severity entry is the one that survives; 1 dedupe warning |
| T-I-07 | Existing Step-1 failure modes still behave identically (missing `user_id`, bad `Classification`, empty `score`, non-object entry) | **`422` with the same `error.code`s as before Step 2 — proves Step 2 is non-regressive** |
| T-I-08 | Invalid JSON body | `400` — unchanged; Step 2 never runs |
| T-I-09 | The **existing** response fields (`status`, `user_id`, `classification`, `domains_received`, `context_ready`) are all still present and correct | **backward compatibility of the response contract** |
| T-I-10 | Supabase raises during the upsert, *after* a successful filter | `503`, `persistence_unavailable` — the existing fail-loud write posture is preserved |
| T-I-11 | `services.submit_roadmap` calls `load_roadmap` **then** `filter_by_severity`, in that order, and the filter receives the loader's exact output | wiring assertion (spy on a hand-rolled fake, per house style) |
| T-I-12 | A one-element-list-wrapped payload (Step 1's `_unwrap` path) still filters correctly | `200`, filtering applied normally — proves the two steps compose |
| T-I-13 | Extra/unexpected attributes inside a `score[i]` object | `200`; identical filtered output to the same payload without them — **extras cannot influence the filter** (EC-23) |
| T-I-14 | Extra top-level fields | `200`; inert; `raw` preserves them (EC-24) |

---

## 20. Acceptance Criteria

Step 2 is **DONE** when every one of these is demonstrably true.

### Correctness

- **AC-01 — Determinism.** For any input, repeated calls to `filter_by_severity` return equal results. *(T-U-33)*
- **AC-02 — The frontend JSON is never modified.** The input `RoadmapResult` — including `.raw` and `.scores` — is bit-identical before and after the call. *(T-U-29, T-U-31, T-U-32)*
- **AC-03 — No shared mutable state.** Mutating the output cannot affect the input. *(T-U-30)*
- **AC-04 — The brief's example passes exactly.** `High, Moderate, Low, High, Low` → `High, Moderate, High`. Nothing else. *(T-U-01)*
- **AC-05 — Only High and Moderate survive.** No Low, no unknown, no missing-severity domain ever appears in `filtered_scores`. *(T-U-01 … T-U-21)*
- **AC-06 — Case, whitespace, and unicode insensitivity.** Every variant in EC-18/19/20 resolves correctly. *(T-U-08 … T-U-13)*
- **AC-07 — Duplicate resolution is order-independent and severity-safe.** The higher severity always wins, regardless of input order. *(T-U-22, T-U-23)*
- **AC-08 — Scores are never recomputed.** No arithmetic is performed on any `score`; a severity is never inferred from a score, even when the score "obviously" implies one. *(T-U-21, T-U-43)*

### Robustness

- **AC-09 — Performance.** A 500-domain payload filters in **< 5 ms** on the dev baseline. (The real payload is 5–15 domains; a single O(n) pass with no allocation per non-survivor makes this comfortable, but the assertion is the guard against someone later introducing an accidental O(n²) dedup.) *(T-U-35)*
- **AC-10 — Every edge case EC-01 … EC-30 has a defined, documented, tested behaviour.** No input reaches an undefined path.
- **AC-11 — No unhandled exception can escape.** With `strict=False`, the only exceptions Step 2 raises are `TypeError` (programmer error) and `payload_too_large`. Every other input is filtered, not fatal. *(T-U-20, T-U-36, T-U-41)*
- **AC-12 — Accounting invariant.** `total_kept + total_dropped == total_received`, for every input, asserted in code and in tests. *(T-U-38, T-U-39)*
- **AC-13 — Empty actionable set is a success, not an error.** *(T-U-04, T-U-06, T-I-02)*

### Architecture

- **AC-14 — Purity.** `severity_filter.py` imports **only** `app.roadmap.models`, `app.roadmap.roadmap_loader` (for the exception type), `logging`, and `unicodedata`. No FastAPI, no Supabase, no LangChain, no OpenAI, no `app.db`. *(T-U-40)*
- **AC-15 — Zero forbidden side effects.** The module performs no persistence, no network call, no LLM call, no PDF, no email. Verifiable by inspection of the import list (AC-14) and the function signature, which accepts no client of any kind.
- **AC-16 — Open/Closed.** Adding a severity level requires editing **only** `_SEVERITY_RANK` and `ACTIONABLE_SEVERITIES`. Demonstrated by a review-time diff walkthrough; no `if severity == "high"` literal appears anywhere in the algorithm.
- **AC-17 — Non-regression.** All **existing** roadmap tests (`test_roadmap_loader.py`, `test_roadmap_routes.py`, `test_roadmap_services.py`, `test_roadmap_context_builder.py`) pass **unmodified**. Step 2 breaks nothing. *(T-I-07, T-I-09)*
- **AC-18 — Scope discipline.** The diff touches exactly: `app/roadmap/severity_filter.py` (new), `app/roadmap/models.py` (+3 models, +3 response fields), `app/roadmap/services.py` (+1 call), `app/roadmap/routes.py` (+1 status-code mapping), and the test files. **`roadmap_loader.py` and `context_builder.py` are not modified.**

### Quality

- **AC-19 — Coverage.** 100 % line and branch coverage of `severity_filter.py`.
- **AC-20 — Logging.** One `INFO` summary line per submission; every anomalous drop produces a `WARNING`; **no numeric `score` value ever appears in any log line.** *(§14.3)*

---

## Appendix A — Reference implementation sketch

Normative for structure and behaviour; the implementer may refine naming and comments.

```python
"""Step 2 of the Roadmap Assessment Pipeline: severity filtering.

Keeps ONLY the domains the frontend's scoring engine flagged High or Moderate --
these are the "actionable" domains that downstream steps (therapy mapping,
roadmap generation) operate on. Low, missing, and unrecognized severities are
excluded and recorded.

PURE. No persistence, no network, no LLM, no mutation of the input. Given the
same RoadmapResult it returns the same FilteredRoadmapResult, forever.

See .claude/spec/manasi-ai-roadmap-step2-severity-filter-spec.md
"""

import logging
import unicodedata
from typing import Optional

from app.roadmap.models import (
    DroppedDomain,
    FilterDiagnostics,
    FilteredDomainScore,
    FilteredRoadmapResult,
    RoadmapResult,
)
from app.roadmap.roadmap_loader import RoadmapValidationError

logger = logging.getLogger("app.roadmap.severity_filter")

# The ONE definition of the severity vocabulary. Adding a level is a one-line
# change here; the algorithm below never branches on a literal (spec §4.4, O/C).
_SEVERITY_RANK: dict[str, int] = {"low": 1, "moderate": 2, "high": 3}

ACTIONABLE_SEVERITIES: frozenset[str] = frozenset({"high", "moderate"})
EXCLUDED_SEVERITIES: frozenset[str] = frozenset(_SEVERITY_RANK) - ACTIONABLE_SEVERITIES

MAX_DOMAINS: int = 500  # resource guard; real assessments carry 5-15 (spec §15.3)

assert ACTIONABLE_SEVERITIES <= _SEVERITY_RANK.keys(), \
    "every actionable severity must also be ranked"


def _normalize(value: object) -> Optional[str]:
    """Derive a canonical comparison key. Returns None for absent/blank input.

    NFKC first (folds fullwidth/compatibility forms -- both an ergonomics win and
    a homoglyph-bypass guard, spec §15.2), then strip, then collapse internal
    whitespace, then casefold (the Unicode-correct caseless match, not .lower()).

    This is a READ-ONLY derivation: the caller carries the ORIGINAL string into
    the output verbatim (spec P1)."""
    if not isinstance(value, str):
        return None
    key = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    return key or None


def filter_by_severity(
    result: RoadmapResult, *, strict: bool = False
) -> FilteredRoadmapResult:
    """Keep only High/Moderate domains. See the spec's §7.2 decision table.

    strict=False (production): an unrecognized or missing severity DROPS that
      domain, warns, and records it -- it never fails the request. A user who
      completed a 40-minute assessment must not get a 422 because one domain came
      back "Borderline" (spec §6.3).
    strict=True (contract tests / batch): the same condition raises.
    """
    if not isinstance(result, RoadmapResult):
        raise TypeError(
            f"filter_by_severity expects a RoadmapResult (the output of Step 1's "
            f"load_roadmap); got {type(result).__name__}. Do not pass raw JSON -- "
            f"parsing the wire format is Step 1's job (spec P2)."
        )

    entries = result.scores
    if len(entries) > MAX_DOMAINS:
        logger.error(
            "filter rejected: user_id=%s domains=%d exceeds MAX_DOMAINS=%d",
            result.user_id, len(entries), MAX_DOMAINS,
        )
        raise RoadmapValidationError(
            "payload_too_large",
            f"score array carries {len(entries)} domains; the maximum is {MAX_DOMAINS}.",
            "score",
        )

    kept: list[FilteredDomainScore] = []
    dropped: list[DroppedDomain] = []
    warnings: list[str] = []
    by_domain: dict[str, int] = {}   # normalized domain -> index into `kept`
    origin: dict[str, int] = {}      # normalized domain -> ORIGINAL index of the incumbent

    for i, entry in enumerate(entries):
        key = _normalize(entry.severity)

        # --- rows 4 & 5 of the decision table: not a usable severity ----------
        if key is None or key not in _SEVERITY_RANK:
            missing = key is None
            code = "missing_severity" if missing else "unknown_severity"
            msg = (
                f"score[{i}] {entry.domain!r}: severity is missing or null; "
                f"domain excluded from the actionable set."
                if missing else
                f"score[{i}] {entry.domain!r}: severity {entry.severity!r} is not a "
                f"recognized level (expected High/Moderate/Low); domain excluded "
                f"from the actionable set."
            )
            if strict:
                raise RoadmapValidationError(code, msg, f"score[{i}].Severity")
            logger.warning(
                "filter drop(%s): user_id=%s idx=%d domain=%s severity=%r",
                code, result.user_id, i, entry.domain, entry.severity,
            )
            dropped.append(DroppedDomain(
                domain=entry.domain, severity=entry.severity, reason=code, index=i))
            warnings.append(msg)
            continue

        # --- row 3: known-good, deliberately excluded (the normal case) -------
        if key in EXCLUDED_SEVERITIES:
            logger.debug(
                "filter drop(low): user_id=%s idx=%d domain=%s",
                result.user_id, i, entry.domain,
            )
            dropped.append(DroppedDomain(
                domain=entry.domain, severity=entry.severity,
                reason="low_severity", index=i))
            continue

        # --- rows 1 & 2: actionable. now resolve duplicates (row 6) -----------
        rank = _SEVERITY_RANK[key]
        domain_key = _normalize(entry.domain) or entry.domain.casefold()

        if domain_key in by_domain:
            incumbent = kept[by_domain[domain_key]]
            # HIGHER SEVERITY ALWAYS WINS; ties keep the first occurrence. This
            # makes the outcome invariant under input reordering and guarantees a
            # more-severe signal is never discarded (spec §7.5).
            if rank > incumbent.severity_rank:
                slot = by_domain[domain_key]
                kept[slot] = FilteredDomainScore(
                    domain=entry.domain, score=entry.score, severity=entry.severity,
                    severity_key=key, severity_rank=rank,
                )
                # The incumbent lost -- record it at ITS original index, not i.
                dropped.append(DroppedDomain(
                    domain=incumbent.domain, severity=incumbent.severity,
                    reason="duplicate_domain", index=origin[domain_key]))
                origin[domain_key] = i
            else:
                dropped.append(DroppedDomain(
                    domain=entry.domain, severity=entry.severity,
                    reason="duplicate_domain", index=i))
            msg = (f"score[{i}] {entry.domain!r}: duplicate domain; kept the "
                   f"highest-severity entry.")
            logger.warning(
                "filter dedupe: user_id=%s domain=%s (idx=%d severity=%r)",
                result.user_id, entry.domain, i, entry.severity,
            )
            warnings.append(msg)
            continue

        logger.debug(
            "filter keep: user_id=%s idx=%d domain=%s severity=%s",
            result.user_id, i, entry.domain, key,
        )
        by_domain[domain_key] = len(kept)
        origin[domain_key] = i
        # Deep-copied by construction: a NEW model built from the entry's values,
        # so nothing downstream can reach back into the caller's RoadmapResult.
        kept.append(FilteredDomainScore(
            domain=entry.domain, score=entry.score, severity=entry.severity,
            severity_key=key, severity_rank=rank,
        ))

    # Every input entry landed in exactly one bucket. A violation is a bug in the
    # decision table above, and it must be LOUD (spec V-15 / AC-12).
    assert len(kept) + len(dropped) == len(entries), (
        f"filter accounting violated: {len(kept)} kept + {len(dropped)} dropped "
        f"!= {len(entries)} received"
    )

    diagnostics = FilterDiagnostics(
        total_received=len(entries),
        total_kept=len(kept),
        total_dropped=len(dropped),
        dropped_low=sum(d.reason == "low_severity" for d in dropped),
        dropped_missing_severity=sum(d.reason == "missing_severity" for d in dropped),
        dropped_unknown_severity=sum(d.reason == "unknown_severity" for d in dropped),
        dropped_duplicate=sum(d.reason == "duplicate_domain" for d in dropped),
        warnings=warnings,
    )

    if not kept:
        logger.info(
            "filter complete: user_id=%s NO actionable domains (all %d were low/excluded)",
            result.user_id, len(entries),
        )
    else:
        logger.info(
            "filter complete: user_id=%s received=%d kept=%d dropped=%d "
            "(low=%d missing=%d unknown=%d dup=%d)",
            result.user_id, diagnostics.total_received, diagnostics.total_kept,
            diagnostics.total_dropped, diagnostics.dropped_low,
            diagnostics.dropped_missing_severity, diagnostics.dropped_unknown_severity,
            diagnostics.dropped_duplicate,
        )

    return FilteredRoadmapResult(
        user_id=result.user_id,
        classification=result.classification,
        classification_raw=result.classification_raw,
        filtered_scores=kept,
        dropped=dropped,
        diagnostics=diagnostics,
    )
```

### Service wiring (`app/roadmap/services.py`)

```python
def submit_roadmap(payload, supabase) -> dict:
    result = load_roadmap(payload)                 # Step 1 (existing)
    filtered = filter_by_severity(result)          # ★ Step 2 (new) -- fail LOUD (P3)

    supabase.table(ROADMAP_TABLE).upsert({...}).execute()   # existing, unchanged

    return {
        "status": "accepted",
        "user_id": result.user_id,
        "classification": result.classification,
        "domains_received": len(result.scores),
        "context_ready": True,
        # ── Step 2 additions ──
        "domains_actionable": filtered.diagnostics.total_kept,
        "domains_filtered_out": filtered.diagnostics.total_dropped,
        "filter_warnings": filtered.diagnostics.warnings,
    }
```

The filter runs **before** the upsert: a payload we cannot filter is a payload we do not persist (T-I-05).

---

## Appendix B — Implementation checklist

- [ ] Add `FilteredDomainScore`, `DroppedDomain`, `FilterDiagnostics`, `FilteredRoadmapResult` to `app/roadmap/models.py`.
- [ ] Add the 3 additive fields to `RoadmapSubmitResponse`.
- [ ] Create `app/roadmap/severity_filter.py` (Appendix A).
- [ ] Wire `filter_by_severity` into `services.submit_roadmap`, **before** the upsert.
- [ ] Add the `payload_too_large → 413` mapping in `routes.py`.
- [ ] Create `tests/test_severity_filter.py` — all 43 unit scenarios (§18).
- [ ] Extend `tests/test_roadmap_routes.py` and `tests/test_roadmap_services.py` — 14 integration scenarios (§19).
- [ ] Confirm 100 % branch coverage of `severity_filter.py`.
- [ ] Confirm all pre-existing roadmap tests pass **unmodified** (AC-17).
- [ ] Do **not** modify `roadmap_loader.py` or `context_builder.py` (AC-18).

---

## Appendix C — Open questions for the product owner

These are **decisions, not blockers** — the spec commits to a defensible default for each, stated in the referenced section. Flag any you disagree with before implementation starts.

1. **§0 — Wire-format casing.** Step 1 requires `Classification`/`Score`/`Severity`; the brief shows lowercase. Step 2 is immune either way. Do you want Step 1's contract lowercased (a separate change)?
2. **§6.3 — `strict=False` default.** An unknown severity drops the domain and warns, rather than rejecting the submission. This is the spec's most consequential choice. Confirm.
3. **§7.5 — Duplicate policy.** Highest severity wins, ties → first. Confirm this over keep-first/keep-last.
4. **§7.4 — Missing severity drops the domain.** The conservative choice. An alternative — treating a missing severity as actionable "just in case" — would push unclassified domains into therapy mapping, which is worse. Confirm.
5. **§15.3 — `MAX_DOMAINS = 500`**, and the acknowledgement that a complete DoS fix needs an infrastructure-level body-size limit (separate ticket).
6. **§15.7 — No authentication exists anywhere in the project.** Any client can submit a roadmap for any `user_id`. Out of scope for Step 2, but a prerequisite for a production launch. Needs its own ticket.
7. **§16 — `context_builder`.** Should Manasi's hidden chat context be narrowed to the actionable domains only? Deferred, not done here.
