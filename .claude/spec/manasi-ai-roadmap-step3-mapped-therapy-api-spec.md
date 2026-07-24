# Manasi AI – Roadmap Pipeline Step 3 – Mapped Therapy API Endpoint Specification

> **Status:** Implementation-ready
> **Author:** Roadmap pipeline team
> **Applies to commit line:** `feature/domain-type-passthrough` (builds on the completed Domain → Therapy Mapping pipeline)
> **Endpoint introduced:** `POST /roadmap/mapped-therapies`

---

## 1. Purpose

The Domain → Therapy Mapping pipeline is **already implemented and tested** as a
set of pure Python functions under `app/roadmap/`. Today those functions
(`load_roadmap` → `filter_by_severity` → `map_domains_to_therapies`, backed by
`load_mappings`) can only be invoked in-process; there is **no HTTP route that
returns the mapped therapies to a caller**. The existing `POST /roadmap/submit`
route runs the loader + severity filter and persists the result, but it never
calls the therapy mapper and never returns therapies.

The purpose of this step is **exclusively** to expose the completed mapping
pipeline through one production REST endpoint that:

1. Receives the assessment JSON from the frontend.
2. Runs the **existing, unmodified** pipeline (loader → severity filter → mapping
   loader → therapy mapper).
3. Serializes the internal Pydantic/`frozen` model graph into a flat, stable JSON
   contract.
4. Returns that JSON as the response.

This endpoint becomes the **single integration point** through which the frontend
dashboard obtains mapped therapies. The frontend must never see Python objects,
tuples, `frozen=True` Pydantic models, Excel row indices, or internal helper
classes.

**This step does not create, redesign, or rewrite any mapping logic.** It builds
only the API layer and the serialization layer on top of the finished pipeline.

---

## 2. Scope

### 2.1 In scope

- A new FastAPI route: `POST /roadmap/mapped-therapies`.
- A new **service orchestrator** function that composes the four existing pipeline
  functions in order and returns a serializable response object.
- A new **serialization layer**: response Pydantic models plus a pure mapper that
  flattens `DomainTherapyResult` (+ the score/severity carried by the severity
  filter) into the public JSON contract.
- Error mapping from the pipeline's existing exception types to HTTP status codes.
- Structured logging around the request lifecycle.
- Unit + integration tests for the route, service, and serializer.

### 2.2 Explicitly out of scope (MUST NOT be touched)

The following files own the business logic and **must not be modified** by this
step:

| File | Reason it is frozen |
|---|---|
| `app/roadmap/roadmap_loader.py` | Owns the frontend wire format + validation |
| `app/roadmap/severity_filter.py` | Owns High/Moderate actionability filtering |
| `app/roadmap/mapping_loader.py` | Owns Excel workbook parsing |
| `app/roadmap/therapy_mapper.py` | Owns the Domain → Therapy join |
| `app/roadmap/models.py` | Loader + filter Pydantic models |
| `app/roadmap/mapping_models.py` | Excel-data Pydantic models |
| `app/roadmap/therapy_models.py` | Therapy-output Pydantic models |

Also out of scope: roadmap generation, PDF generation, dashboard rendering, email
delivery, authentication, and any change to `POST /roadmap/submit` or the
persistence table. These are addressed only in **§20 Future Extensibility** as
non-breaking extensions.

> **Note on `to_list()`:** `DomainTherapyResult.to_list()` already exists in
> `therapy_models.py`. Reusing it is allowed (it is a read-only view, not a logic
> change). However, `to_list()` **does not include `score`**, which the response
> contract in this spec requires. The serialization layer therefore performs an
> additional join against the severity filter's output rather than relying on
> `to_list()` alone. See §8.

---

## 3. Architecture

### 3.1 Layered view

```
┌─────────────────────────────────────────────────────────────┐
│ Frontend Dashboard (React / Webflow)                         │
│   POST /roadmap/mapped-therapies  (JSON in → JSON out)       │
└───────────────────────────────┬─────────────────────────────┘
                                 │ HTTP
┌───────────────────────────────▼─────────────────────────────┐
│ API LAYER  (NEW)                                             │
│   app/roadmap/routes.py :: mapped_therapies()               │
│     • read raw JSON body                                     │
│     • call service orchestrator                             │
│     • translate pipeline exceptions → HTTP status codes     │
│     • return MappedTherapyResponse (FastAPI serializes)     │
└───────────────────────────────┬─────────────────────────────┘
                                 │ Python call
┌───────────────────────────────▼─────────────────────────────┐
│ SERVICE / ORCHESTRATION LAYER  (NEW)                        │
│   app/roadmap/services.py :: map_roadmap_therapies()        │
│     runs the EXISTING pipeline in order, then serializes    │
└───────────────────────────────┬─────────────────────────────┘
                                 │ composes (no changes)
┌───────────────────────────────▼─────────────────────────────┐
│ EXISTING PIPELINE  (UNCHANGED)                              │
│   load_roadmap → filter_by_severity                        │
│   get_mappings (cached) → map_domains_to_therapies         │
└───────────────────────────────┬─────────────────────────────┘
                                 │ Python objects
┌───────────────────────────────▼─────────────────────────────┐
│ SERIALIZATION LAYER  (NEW)                                  │
│   app/roadmap/serializers.py :: build_mapped_response()     │
│     joins FilteredRoadmapResult (score/severity)            │
│     with DomainTherapyResult (therapies/relevance)          │
│     → MappedTherapyResponse (plain, JSON-safe models)       │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Why a separate serializer module

The therapy models are declared `frozen=True` with `tuple[...]` fields and carry
internal-only attributes (`source_row`, `matched_domain`, `dataset_source`,
diagnostics). Serializing them directly would leak internals and couple the wire
contract to internal model shape. A dedicated `serializers.py` gives us one place
that:

- Owns the **public JSON contract** (list-based, no tuples, no row indices).
- Performs the **score join** the therapy mapper does not carry.
- Can evolve the response (add `roadmap`, `pdf_url`, etc.) without ever touching
  pipeline models — see §20.

---

## 4. Processing Flow

```
1. Route receives HTTP POST with a JSON body.
2. Route parses the raw body:  payload = await request.json()
      └─ on JSONDecodeError → 400
3. Route calls services.map_roadmap_therapies(payload).
4. Service — STEP 1: result = load_roadmap(payload)            → RoadmapResult
      └─ RoadmapValidationError → 422 (or 413 if payload_too_large)
5. Service — STEP 2: filtered = filter_by_severity(result)     → FilteredRoadmapResult
      └─ RoadmapValidationError(payload_too_large) → 413
      └─ if filtered.is_empty → still 200 with empty mapped_domains (see §10.4)
6. Service — STEP 3: bundle = get_mappings()                   → MappingBundle (cached)
      └─ MappingLoadError → 500 (mapping_data_unavailable)
7. Service — STEP 4: mapped = map_domains_to_therapies(filtered, bundle)
                                                               → DomainTherapyResult
      └─ TherapyMappingError → 500 (therapy_mapping_failed)
8. Service — STEP 5: response = build_mapped_response(filtered, mapped)
                                                               → MappedTherapyResponse
9. Route returns response; FastAPI emits JSON (200).
```

**Ordering guarantees preserved from the existing pipeline:**

- `filter_by_severity` runs with `strict=False` (production posture) — unknown /
  missing severities are dropped and recorded, never raised.
- `map_domains_to_therapies` runs with `strict=False` — unmatched domains become
  `unmapped` entries, never raised.
- `get_mappings()` (not `load_mappings()`) is used so the Excel workbooks are read
  once and cached at module level; the request path does no disk I/O after warm-up.

---

## 5. Endpoint Design

| | |
|---|---|
| **Method** | `POST` |
| **Path** | `/roadmap/mapped-therapies` |
| **Router** | `app/roadmap/routes.py` → `APIRouter(prefix="/roadmap")` (existing) |
| **Full URL** | `{base}/roadmap/mapped-therapies` |
| **Content-Type (request)** | `application/json` |
| **Content-Type (response)** | `application/json` |
| **Auth** | None at the route (same CORS origin policy as the rest of the API) |
| **Idempotency** | Pure function of the request body. No persistence, no side effects. Safe to retry. |
| **`response_model`** | `MappedTherapyResponse` (FastAPI validates + serializes the outgoing body) |

**Design choices:**

- The route reads the **raw body** (`await request.json()`) and hands it to the
  loader unchanged — exactly like `POST /roadmap/submit`. FastAPI does **no**
  request-schema coercion, keeping `roadmap_loader` the single owner of the wire
  format. (Do **not** declare a Pydantic request model as the body parameter; that
  would duplicate/second-guess the loader's validation.)
- The route **does** declare `response_model=MappedTherapyResponse` so the outgoing
  contract is enforced and documented in OpenAPI.
- This endpoint is **read-only / stateless**: it neither reads nor writes the
  `user_roadmap_results` table. `POST /roadmap/submit` remains the persistence
  endpoint; `POST /roadmap/mapped-therapies` is the compute-and-return endpoint.

---

## 6. Request Schema

The request body is owned by `roadmap_loader`. It accepts **either a bare object
or a one-element array** wrapping it (a multi-element array is rejected). The wire
keys and casing are **exactly** what the loader parses today — this spec does not
change them.

### 6.1 Authoritative wire format (as parsed by `roadmap_loader`)

| Field | Wire key | Type | Required | Notes |
|---|---|---|---|---|
| User id | `user_id` | string | ✅ | Non-empty. |
| Classification | `Classification` | string | ✅ | One of `neurodivergent`, `neurotypical`, `ND`, `NT`. Case-insensitive; normalized to `"ND"` / `"NT"`. |
| Score list | `score` | array | ✅ | Non-empty. Lowercase key. |
| Domain | `score[].domain` | string | ✅ | Non-empty. |
| Domain type | `score[].domain_type` | string | ⬜ | Optional. Carried through verbatim. |
| Raw score | `score[].Score` | string \| number | ✅ | Capital `S`. Stored verbatim (never rounded). Booleans rejected. |
| Severity | `score[].Severity` | string | ⬜ | Optional. Drives the severity filter. |

> ⚠️ **Casing is authoritative and must not be "fixed" in this step.** The keys are
> `user_id`, `Classification`, `score`, `domain`, `domain_type`, `Score`,
> `Severity`. `Classification` and `Score` are capitalized; `score`, `domain`,
> `domain_type` are lowercase. This matches `roadmap_loader._parse_scores` and
> `docs/roadmap-submit-frontend.md`.

### 6.2 Reconciling with the brief's illustrative example

The task brief shows an *illustrative* request using lowercase
`classification` / `score` / `severity`:

```json
{ "user_id": "test001", "classification": "ND",
  "score": [ { "domain": "Sensory Processing", "domain_type": "Spine",
               "score": 85, "severity": "High" } ] }
```

That illustrative shape is **not** what the current loader parses. Because this
step **must not modify** `roadmap_loader`, the **authoritative** request format is
§6.1 (capitalized `Classification` / `Score` / `Severity`). The frontend must send
the §6.1 keys. If the product later wants case-insensitive keys, that is a
**loader** change (out of scope here) and must be specced separately so we don't
silently fork the wire format.

> **Implementer action:** Every example in this document (§17) uses the §6.1
> authoritative keys, not the brief's illustrative lowercase keys.

---

## 7. Response Schema

The response is a **new, flat, list-based** contract owned by `serializers.py`.
All fields are JSON primitives, objects, or arrays — **no tuples, no `source_row`,
no `matched_domain`, no diagnostics** (unless explicitly requested; see §10.5).

### 7.1 Top level — `MappedTherapyResponse`

| Field | Type | Nullable | Source |
|---|---|---|---|
| `user_id` | string | no | `filtered.user_id` |
| `classification` | `"ND" \| "NT"` | no | `filtered.classification` |
| `mapped_domains` | array of `MappedDomain` | no (may be empty) | join of filtered scores × mappings |

### 7.2 `MappedDomain`

| Field | Type | Nullable | Source |
|---|---|---|---|
| `domain` | string | no | `DomainTherapyMapping.domain` |
| `domain_type` | string | yes | carried from `score[].domain_type` |
| `score` | string \| number | no | joined from `FilteredDomainScore.score` (verbatim) |
| `severity` | string | yes | `DomainTherapyMapping.severity` (original severity string) |
| `therapies` | array of `Therapy` | no (may be empty) | `DomainTherapyMapping.therapies` |

### 7.3 `Therapy`

| Field | Type | Nullable | Source |
|---|---|---|---|
| `therapy` | string | no | `TherapyRef.therapy` |
| `relevance` | string | yes | `TherapyRef.relevance` (e.g. `"Primary"`, `"Secondary"`) |

### 7.4 Field-preservation checklist (per the brief)

The response **preserves** every field the brief requires:
`user_id` ✅ · `classification` ✅ · `domain` ✅ · `domain_type` ✅ ·
`score` ✅ (via the serializer's join) · `severity` ✅ · `therapies` ✅ ·
`relevance` ✅.

### 7.5 New Pydantic response models (serialization layer)

```python
# app/roadmap/serializers.py  (NEW FILE)
from typing import Literal, Optional, Union
from pydantic import BaseModel


class TherapyOut(BaseModel):
    therapy: str
    relevance: Optional[str] = None


class MappedDomainOut(BaseModel):
    domain: str
    domain_type: Optional[str] = None
    score: Union[str, float, int]
    severity: Optional[str] = None
    therapies: list[TherapyOut]


class MappedTherapyResponse(BaseModel):
    user_id: str
    classification: Literal["ND", "NT"]
    mapped_domains: list[MappedDomainOut]
```

> These response models are **not** `frozen`, use **`list[...]` not `tuple[...]`**,
> and expose **only** contract fields. They are distinct from the pipeline's
> `therapy_models.py` so the wire contract can evolve independently.

---

## 8. Serialization Strategy

### 8.1 The problem the serializer solves

The therapy mapper's output (`DomainTherapyResult`) carries `domain`,
`domain_type`, `severity`, and `therapies` — but **not `score`**. The brief's
response requires `score`. The `score` value lives on
`FilteredRoadmapResult.filtered_scores[].score`. The serializer therefore **joins**
the two upstream objects.

### 8.2 The join

Both the filter output and the mapper output describe the **same set of
actionable domains in the same order** (the mapper iterates the filtered scores).
The safe, order-independent join key is the therapy mapper's own matching helper:

```python
from app.roadmap.therapy_mapper import domain_key
```

Algorithm (`build_mapped_response`):

```python
def build_mapped_response(filtered, mapped) -> MappedTherapyResponse:
    # Index filtered scores by the mapper's normalized domain key.
    score_by_key = {domain_key(fs.domain): fs.score for fs in filtered.filtered_scores}

    mapped_domains = []
    for m in mapped.mappings:                 # DomainTherapyMapping (matched only)
        key = domain_key(m.domain)
        mapped_domains.append(MappedDomainOut(
            domain=m.domain,
            domain_type=m.domain_type,
            score=score_by_key.get(key),      # verbatim; see §8.4 for miss policy
            severity=m.severity,
            therapies=[TherapyOut(therapy=t.therapy, relevance=t.relevance)
                       for t in m.therapies],
        ))

    return MappedTherapyResponse(
        user_id=mapped.user_id,
        classification=mapped.classification,
        mapped_domains=mapped_domains,
    )
```

### 8.3 What is intentionally dropped

- `TherapyRef.source_row` — Excel row index (internal).
- `DomainTherapyMapping.matched_domain` — internal join detail.
- `DomainTherapyResult.unmapped` — domains with no therapies (not part of the
  matched-domain contract; surfaced only via the optional debug view, §10.5).
- `DomainTherapyResult.diagnostics` and `filtered.diagnostics` / `filtered.dropped`
  — internal counters (optional debug view only, §10.5).
- All tuples become JSON arrays; all `frozen` models become plain output models.

### 8.4 Score-join miss policy

Under normal operation every matched domain has a corresponding filtered score, so
`score_by_key.get(key)` always resolves. Defensive rule: if a key does **not**
resolve (should be impossible unless upstream changes), the serializer sets
`score` to `null` and emits a **WARNING** log (`score_join_miss`) with the domain
name. It does **not** raise — a missing score must never turn a successful mapping
into a 500.

### 8.5 Ordering

`mapped_domains` preserves the therapy mapper's output order (which follows the
frontend's submitted score order for actionable domains). `therapies` preserves the
Excel "Suggested modalities (in order)" order. No re-sorting is performed.

---

## 9. Error Handling

Errors reuse the pipeline's existing exception types. The route is the single
translation point from exception → HTTP status. The error body shape mirrors the
existing `POST /roadmap/submit` convention:

```json
{ "status": "rejected" | "error",
  "error": { "code": "<machine_code>", "message": "<human message>", "field": "<optional>" } }
```

| HTTP | When | Raised by | `code` | Notes |
|---|---|---|---|---|
| **400** | Body is not valid JSON | `request.json()` throws | `invalid_json` | `detail` may be a plain string, matching current `/submit`. |
| **413** | Score array exceeds `MAX_DOMAINS` (500) | `RoadmapValidationError("payload_too_large")` from loader or filter | `payload_too_large` | Size problem, not a schema problem. |
| **422** | Schema/validation failure (missing `user_id`, bad `Classification`, empty `score`, boolean `Score`, multi-element array, etc.) | `RoadmapValidationError` (any code ≠ `payload_too_large`) | passthrough `exc.code` | `field` names the offending field. |
| **404** | *Not applicable to this endpoint.* | — | — | This endpoint takes no path/entity id; there is nothing to "not find". Documented for completeness — see §9.1. |
| **500** | Excel mapping data cannot be loaded | `MappingLoadError` | `mapping_data_unavailable` | Server-side data/config fault, not the caller's fault. |
| **500** | Therapy join fails unexpectedly | `TherapyMappingError` | `therapy_mapping_failed` | Should not occur with `strict=False`; caught defensively. |
| **500** | Any other uncaught exception | `Exception` | `internal_error` | Generic guard; logs full detail server-side, returns a generic message. |

### 9.1 Why 404 is not used here

The brief lists 404. This endpoint is a **stateless compute** call keyed entirely
on the request body — there is no resource lookup by id, so no "resource not found"
condition exists. A 404 is therefore **never** returned by this route. It is
reserved for a future GET-by-user variant (see §20) where a missing stored roadmap
would map to 404. Documenting this explicitly prevents a future implementer from
inventing a spurious 404 path.

### 9.2 Route exception-handling skeleton

```python
@router.post("/mapped-therapies", response_model=MappedTherapyResponse)
async def mapped_therapies(request: Request) -> MappedTherapyResponse:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON.") from exc

    try:
        return map_roadmap_therapies(payload)
    except RoadmapValidationError as exc:
        status_code = 413 if exc.code == "payload_too_large" else 422
        logger.info("mapped-therapies rejected: code=%s field=%s", exc.code, exc.field)
        raise HTTPException(status_code=status_code, detail={
            "status": "rejected",
            "error": {"code": exc.code, "message": exc.message, "field": exc.field},
        }) from exc
    except MappingLoadError as exc:
        logger.error("mapped-therapies mapping data error: code=%s source=%s", exc.code, exc.source)
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "error": {"code": "mapping_data_unavailable", "message": "Therapy mapping data is temporarily unavailable."},
        }) from exc
    except TherapyMappingError as exc:
        logger.error("mapped-therapies mapping failed: code=%s domain=%s", exc.code, exc.domain)
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "error": {"code": "therapy_mapping_failed", "message": "Could not map domains to therapies."},
        }) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("mapped-therapies unexpected error")
        raise HTTPException(status_code=500, detail={
            "status": "error",
            "error": {"code": "internal_error", "message": "An unexpected error occurred."},
        }) from exc
```

> `map_domains_to_therapies` / `filter_by_severity` also raise `TypeError` on
> wrong-typed arguments. That is a programming error, not a caller error; it falls
> through to the generic `Exception → 500` guard, which is correct.

---

## 10. Validation Rules

### 10.1 Delegated validation (owned by the pipeline — do not re-implement)

| Rule | Enforced by | On violation |
|---|---|---|
| `user_id` present & non-empty | `roadmap_loader` | 422 |
| `Classification` ∈ {neurodivergent, neurotypical, ND, NT} | `roadmap_loader` | 422 |
| `score` present & non-empty list | `roadmap_loader` | 422 |
| `score[].domain` present & non-empty | `roadmap_loader` | 422 |
| `score[].Score` present, non-boolean | `roadmap_loader` | 422 |
| Body is bare object or one-element array only | `roadmap_loader` | 422 |
| ≤ `MAX_DOMAINS` (500) domains | `roadmap_loader` / `severity_filter` | 413 |

### 10.2 Severity filtering (owned by `severity_filter`, `strict=False`)

- Keeps only `high` / `moderate` domains.
- `low`, missing, unknown, and duplicate severities are **dropped and recorded** —
  never an error.

### 10.3 Therapy mapping (owned by `therapy_mapper`, `strict=False`)

- Unmatched domains → recorded as `unmapped` — never an error.
- Empty dataset for the classification → recorded — never an error.

### 10.4 Empty-result rule (API-layer decision)

If, after filtering + mapping, there are **no matched domains** (e.g. every domain
was `low` severity, or none matched a therapy), the endpoint returns **HTTP 200**
with `mapped_domains: []`. An empty actionable set is a **valid** result, not an
error. The frontend renders an appropriate empty state.

### 10.5 Optional diagnostics (must be explicitly requested)

By default the response contains **no** diagnostics, dropped-domain records, or
unmapped-domain records. A caller may opt in with a query flag
`?include_diagnostics=true`, which adds a top-level `diagnostics` object:

```json
"diagnostics": {
  "domains_received": 3,
  "domains_actionable": 2,
  "domains_filtered_out": 1,
  "domains_mapped": 2,
  "domains_unmapped": 0,
  "filter_warnings": [],
  "unmapped": [ { "domain": "…", "reason": "domain_not_found" } ]
}
```

This is derived from `filtered.diagnostics` and `mapped.diagnostics`/`mapped.unmapped`
inside the serializer — still no `source_row` / `matched_domain` leakage. When the
flag is absent or `false`, `diagnostics` is omitted entirely.

---

## 11. Logging Requirements

Use the module logger pattern already in the codebase
(`logging.getLogger("app.roadmap.routes")` / `"app.roadmap.services")`). **Never
log full payloads or PII beyond `user_id`.**

| Point | Level | Message fields |
|---|---|---|
| Request accepted (start) | `INFO` | `user_id`, `domains_received` (post-parse, from loader) |
| Success | `INFO` | `user_id`, `classification`, `domains_actionable`, `domains_mapped`, `domains_unmapped` |
| Validation rejection | `INFO` | `code`, `field` (no payload) |
| Payload too large | `INFO` | `code=payload_too_large`, `domains_received` |
| Mapping data unavailable | `ERROR` | `code`, `source` |
| Therapy mapping failed | `ERROR` | `code`, `domain`, `classification` |
| Score-join miss (defensive) | `WARNING` | `domain` (the key that missed) |
| Unexpected error | `ERROR` (`logger.exception`) | stack trace, `user_id` if available |

**Correlation:** if an `X-Request-ID` header is present, include it in every log
line for that request. (Optional; add only if the platform already propagates one.)

---

## 12. Folder Structure

```
app/
  roadmap/
    __init__.py
    roadmap_loader.py        # UNCHANGED
    severity_filter.py       # UNCHANGED
    mapping_loader.py        # UNCHANGED
    therapy_mapper.py        # UNCHANGED
    models.py                # UNCHANGED
    mapping_models.py        # UNCHANGED
    therapy_models.py        # UNCHANGED  (to_list stays as-is)
    context_builder.py       # UNCHANGED
    services.py              # MODIFIED — add map_roadmap_therapies()
    routes.py                # MODIFIED — add POST /roadmap/mapped-therapies
    serializers.py           # NEW — response models + build_mapped_response()
tests/
  test_roadmap_serializers.py         # NEW — unit tests for the serializer
  test_roadmap_mapped_therapies.py    # NEW — route + service integration tests
docs/
  roadmap-mapped-therapies-frontend.md  # NEW (optional) — frontend integration guide
.claude/spec/
  manasi-ai-roadmap-step3-mapped-therapy-api-spec.md   # THIS FILE
```

---

## 13. Files to Create or Modify

### 13.1 Create

1. **`app/roadmap/serializers.py`**
   - `TherapyOut`, `MappedDomainOut`, `MappedTherapyResponse` (§7.5).
   - `build_mapped_response(filtered, mapped) -> MappedTherapyResponse` (§8.2).
   - Optional `build_diagnostics(filtered, mapped) -> dict` for §10.5.
   - Imports `domain_key` from `therapy_mapper` for the join key.

2. **`tests/test_roadmap_serializers.py`** — unit tests (§14).

3. **`tests/test_roadmap_mapped_therapies.py`** — integration tests (§15).

4. *(Optional)* **`docs/roadmap-mapped-therapies-frontend.md`** — frontend guide,
   mirroring the existing `roadmap-submit-frontend.md`.

### 13.2 Modify

5. **`app/roadmap/services.py`** — **add** (do not alter existing functions):

   ```python
   from app.roadmap.mapping_loader import get_mappings
   from app.roadmap.therapy_mapper import map_domains_to_therapies
   from app.roadmap.serializers import build_mapped_response, MappedTherapyResponse

   def map_roadmap_therapies(payload, *, include_diagnostics: bool = False) -> MappedTherapyResponse:
       """Run the completed Domain→Therapy pipeline on a frontend payload and
       return the serialized response. Composes existing functions only; adds no
       business logic. Stateless — no persistence."""
       result   = load_roadmap(payload)                       # Step 1
       filtered = filter_by_severity(result)                  # Step 2 (strict=False)
       bundle   = get_mappings()                              # cached Excel load
       mapped   = map_domains_to_therapies(filtered, bundle)  # Step 3 (strict=False)
       return build_mapped_response(filtered, mapped, include_diagnostics=include_diagnostics)
   ```

6. **`app/roadmap/routes.py`** — **add** the `POST /mapped-therapies` route (§9.2)
   plus imports for `map_roadmap_therapies`, `MappedTherapyResponse`,
   `MappingLoadError`, `TherapyMappingError`, `MappedTherapyResponse`. The existing
   `POST /submit` route is untouched.

> No change to `app/main.py` is needed — the roadmap router is already included via
> `app.include_router(roadmap_router)`. No new dependency is added to
> `requirements.txt` (FastAPI, Pydantic, openpyxl already pinned).

---

## 14. Unit Test Plan

Framework: **pytest 9.1.0** (flat `tests/`, self-bootstrapping `sys.path`, one file
per module — matches the existing convention). No network, no real Excel I/O; build
upstream models directly.

### 14.1 `test_roadmap_serializers.py` — `build_mapped_response`

| # | Case | Assertion |
|---|---|---|
| U1 | Single matched domain, two therapies | Response has 1 `mapped_domain`, 2 `therapies` in Excel order; `relevance` preserved. |
| U2 | `score` join | `mapped_domains[i].score` equals the `FilteredDomainScore.score` verbatim (test with `85`, `"72%"`, `88.5`). |
| U3 | `domain_type` passthrough | `domain_type` preserved when present; `null` when absent. |
| U4 | `severity` preserved | Original severity string (e.g. `"High"`) surfaces, not the normalized `severity_key`. |
| U5 | Internal fields dropped | Response JSON contains no `source_row`, `matched_domain`, `severity_key`, `severity_rank`. |
| U6 | Empty mappings | `mapped_domains == []`; top-level `user_id`/`classification` still present. |
| U7 | Score-join miss (defensive) | A mapping whose domain key is absent from filtered scores → `score is None`, WARNING logged, no exception. |
| U8 | Tuples → lists | `therapies` and `mapped_domains` serialize as JSON arrays (assert `isinstance(list)` after `model_dump`). |
| U9 | `include_diagnostics=True` | Adds `diagnostics` with correct counts + `unmapped`; absent when `False`. |
| U10 | `frozen` inputs unmutated | Passing `frozen=True` therapy models does not raise and does not mutate them. |

### 14.2 `services.map_roadmap_therapies` — with a stubbed mapping bundle

| # | Case | Assertion |
|---|---|---|
| U11 | Happy path (monkeypatch `get_mappings` → fixture bundle) | Returns `MappedTherapyResponse` with expected domains/therapies. |
| U12 | Pipeline order | Assert `load_roadmap` → `filter_by_severity` → `get_mappings` → `map_domains_to_therapies` invoked in order (spy/mocks). |
| U13 | Low-severity-only payload | Returns 200-shaped response with `mapped_domains == []`. |
| U14 | ND vs NT dataset selection | ND payload uses ND dataset; NT uses NT (verify via fixture rows). |

---

## 15. Integration Test Plan

Use FastAPI's `TestClient` (Starlette) against the real router with the mapping
loader pointed at **test fixture workbooks** (or `get_mappings` monkeypatched to a
fixture `MappingBundle`). These exercise the full HTTP path including status codes
and JSON bodies.

| # | Request | Expected |
|---|---|---|
| I1 | Valid ND payload (bare object), domains that match | `200`; body matches §18 shape; `mapped_domains` non-empty; therapies + relevance present. |
| I2 | Valid payload wrapped in one-element array | `200`; identical result to I1. |
| I3 | Multi-element array | `422`; `error.code` from loader; `field` set. |
| I4 | Missing `user_id` | `422`; `error.field == "user_id"`. |
| I5 | Invalid `Classification` (`"xyz"`) | `422`. |
| I6 | Empty `score` list | `422`. |
| I7 | Boolean `Score` | `422`. |
| I8 | `> 500` domains | `413`; `error.code == "payload_too_large"`. |
| I9 | Body is not JSON (`"{"`) | `400`. |
| I10 | All domains `low` severity | `200`; `mapped_domains == []`. |
| I11 | Domain not in mapping table | `200`; that domain absent from `mapped_domains` (or in `diagnostics.unmapped` when flag on). |
| I12 | `get_mappings` raises `MappingLoadError` | `500`; `error.code == "mapping_data_unavailable"`. |
| I13 | `?include_diagnostics=true` | `200`; `diagnostics` object present with correct counts. |
| I14 | `include_diagnostics` absent | `200`; no `diagnostics` key. |
| I15 | Response contract | Assert JSON contains **only** contract keys; no `source_row`/`matched_domain`; all arrays are JSON arrays. |
| I16 | Idempotency | Same request twice → byte-identical body; no state change. |
| I17 | Existing `POST /roadmap/submit` regression | Still `200`/`422` as before — new route did not alter it. |

---

## 16. Acceptance Criteria

The step is **done** when all of the following hold:

1. `POST /roadmap/mapped-therapies` exists and is reachable via the already-included
   roadmap router.
2. The endpoint runs the **existing** pipeline unchanged: `load_roadmap` →
   `filter_by_severity` → `get_mappings` → `map_domains_to_therapies`. Git diff
   shows **zero** changes to the seven frozen files in §2.2.
3. A valid request returns **200** with the exact §7 contract, preserving
   `user_id`, `classification`, `domain`, `domain_type`, `score`, `severity`,
   `therapies`, and `relevance`.
4. The response contains **no** Python objects, tuples, Pydantic-internal fields,
   `source_row`, `matched_domain`, or diagnostics (unless `?include_diagnostics=true`).
5. Error mapping matches §9: 400 (bad JSON), 413 (too large), 422 (validation),
   500 (mapping-data / mapping-failed / internal). No 404 path exists.
6. An all-filtered-out or all-unmatched payload returns **200** with
   `mapped_domains: []` (not an error).
7. All unit tests (§14) and integration tests (§15) pass under `pytest`.
8. Existing test suites (loader, filter, mapping loader, therapy mapper, routes,
   services, context builder) still pass unchanged.
9. Logging emits the §11 events with `user_id` only (no payload/PII leakage).
10. OpenAPI (`/docs`) shows the new endpoint with `MappedTherapyResponse` as the
    documented response model.

---

## 17. Example Request

`POST /roadmap/mapped-therapies`
`Content-Type: application/json`

Using the **authoritative** wire keys (§6.1):

```json
{
  "user_id": "test001",
  "Classification": "ND",
  "score": [
    {
      "domain": "Sensory Processing",
      "domain_type": "Spine",
      "Score": 85,
      "Severity": "High"
    }
  ]
}
```

The one-element-array form is equally valid:

```json
[
  {
    "user_id": "test001",
    "Classification": "neurodivergent",
    "score": [
      { "domain": "Sensory Processing", "domain_type": "Spine", "Score": 85, "Severity": "High" }
    ]
  }
]
```

---

## 18. Example Successful Response

`200 OK` · `Content-Type: application/json`

```json
{
  "user_id": "test001",
  "classification": "ND",
  "mapped_domains": [
    {
      "domain": "Sensory Processing",
      "domain_type": "Spine",
      "score": 85,
      "severity": "High",
      "therapies": [
        { "therapy": "MNRI",        "relevance": "Primary" },
        { "therapy": "Feldenkrais", "relevance": "Secondary" }
      ]
    }
  ]
}
```

Empty actionable set (all `low` / unmatched) — still `200`:

```json
{ "user_id": "test001", "classification": "ND", "mapped_domains": [] }
```

With `?include_diagnostics=true`:

```json
{
  "user_id": "test001",
  "classification": "ND",
  "mapped_domains": [ { "domain": "Sensory Processing", "domain_type": "Spine", "score": 85, "severity": "High", "therapies": [ { "therapy": "MNRI", "relevance": "Primary" } ] } ],
  "diagnostics": {
    "domains_received": 2,
    "domains_actionable": 1,
    "domains_filtered_out": 1,
    "domains_mapped": 1,
    "domains_unmapped": 0,
    "filter_warnings": [],
    "unmapped": []
  }
}
```

---

## 19. Example Error Responses

**400 — body is not valid JSON**
```json
{ "detail": "Request body is not valid JSON." }
```

**413 — payload too large**
```json
{ "detail": { "status": "rejected",
              "error": { "code": "payload_too_large",
                         "message": "Too many domains in score array.", "field": "score" } } }
```

**422 — validation failure (missing `user_id`)**
```json
{ "detail": { "status": "rejected",
              "error": { "code": "missing_field",
                         "message": "user_id is required.", "field": "user_id" } } }
```

**422 — invalid classification**
```json
{ "detail": { "status": "rejected",
              "error": { "code": "invalid_classification",
                         "message": "Classification must be one of ND/NT/neurodivergent/neurotypical.",
                         "field": "Classification" } } }
```
> `code`/`message` strings are whatever `roadmap_loader` already raises — the route
> passes `exc.code`, `exc.message`, `exc.field` through verbatim. The shapes above
> are illustrative of the envelope, not new strings introduced by this step.

**500 — mapping data unavailable**
```json
{ "detail": { "status": "error",
              "error": { "code": "mapping_data_unavailable",
                         "message": "Therapy mapping data is temporarily unavailable." } } }
```

**500 — therapy mapping failed**
```json
{ "detail": { "status": "error",
              "error": { "code": "therapy_mapping_failed",
                         "message": "Could not map domains to therapies." } } }
```

---

## 20. Future Extensibility

The contract is deliberately shaped so downstream features are **additive** and
never break the current response. The invariant: **existing keys keep their meaning
and type; new capabilities are new keys or new endpoints.**

### 20.1 Roadmap Generation

- Add an optional top-level `roadmap` object (phases, milestones, sequencing)
  computed by a future `roadmap_generator` that consumes the same
  `DomainTherapyResult`. Because `mapped_domains` is unchanged, a client reading
  only therapies is unaffected.
- Or a sibling endpoint `POST /roadmap/generate` that returns `mapped_domains` +
  `roadmap`. `serializers.py` gains a `build_roadmap_response()` that composes
  `build_mapped_response()`.

### 20.2 PDF Generation

- Add an optional `pdf_url` (or `POST /roadmap/mapped-therapies/pdf` returning
  `application/pdf`). The PDF renderer consumes the **already-serialized**
  `MappedTherapyResponse`, so it never touches pipeline models and the JSON contract
  is untouched.

### 20.3 Dashboard Integration

- The dashboard already treats this endpoint as its single integration point. New
  dashboard needs → optional response fields (`display_order`, `category`, colour
  hints) added to `MappedDomainOut`/`TherapyOut` with safe defaults. Additive fields
  do not break existing consumers.
- A future `GET /roadmap/mapped-therapies/{user_id}` (reading the persisted
  `user_roadmap_results` row, then running the same serializer) would be the place a
  legitimate **404** lives (no stored roadmap for that user) — the reason §9.1
  reserves it.

### 20.4 Email Delivery

- A `POST /roadmap/mapped-therapies/email` (or a `deliver: {email: true}` request
  flag) that runs the same service, renders via the PDF/HTML layer, and dispatches
  asynchronously. Delivery is a **side effect layered on top**; the synchronous JSON
  contract of the core endpoint is unchanged.

### 20.5 Contract-stability rules (for all of the above)

1. Never remove or retype an existing response field.
2. New fields are optional with sensible defaults.
3. New behaviours are new endpoints or opt-in request/query flags
   (like `include_diagnostics`), never changes to the default response.
4. All new features consume `MappedTherapyResponse` (the serialized contract) or the
   upstream pipeline objects — **never** by modifying the seven frozen files in §2.2.

---

### Appendix A — Pipeline function reference (for the implementer, unchanged)

| Function | File | Signature | Returns |
|---|---|---|---|
| `load_roadmap` | `roadmap_loader.py` | `load_roadmap(payload)` | `RoadmapResult` |
| `filter_by_severity` | `severity_filter.py` | `filter_by_severity(result, *, strict=False)` | `FilteredRoadmapResult` |
| `get_mappings` | `mapping_loader.py` | `get_mappings(force_reload=False)` | `MappingBundle` (cached) |
| `map_domains_to_therapies` | `therapy_mapper.py` | `map_domains_to_therapies(filtered, bundle, *, strict=False)` | `DomainTherapyResult` |
| `domain_key` | `therapy_mapper.py` | `domain_key(value)` | `Optional[str]` (join key) |

Exceptions: `RoadmapValidationError(code, message, field=None)`,
`MappingLoadError(code, message, source=None, field=None)`,
`TherapyMappingError(code, message, classification=None, domain=None)`.
