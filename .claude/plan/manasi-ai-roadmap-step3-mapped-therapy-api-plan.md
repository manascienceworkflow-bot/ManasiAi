# Implementation Plan — Roadmap Step 3: Mapped Therapy API Endpoint

**Spec:** `.claude/spec/manasi-ai-roadmap-step3-mapped-therapy-api-spec.md`
**Branch:** `feature/domain-type-passthrough`

---

## Context

The Domain → Therapy Mapping pipeline (`load_roadmap` → `filter_by_severity` →
`get_mappings` → `map_domains_to_therapies`) is fully implemented and tested as
pure Python functions in `app/roadmap/`, but there is **no HTTP route that returns
the mapped therapies**. The only existing roadmap route, `POST /roadmap/submit`,
stops after the severity filter and persists the result — it never calls the
therapy mapper.

This plan adds the **only frontend integration point** for mapped therapies:
`POST /roadmap/mapped-therapies`. It builds **only an API layer and a serialization
layer** on top of the finished pipeline. No mapping/business logic is created or
changed. The frontend gets flat, stable JSON — never Python objects, tuples,
`frozen` Pydantic models, Excel row indices, or diagnostics (unless explicitly
requested).

**Verified against the code** (signatures/imports all confirmed present):
- `domain_key(value)` — `app/roadmap/therapy_mapper.py:77` (the join key helper)
- `map_domains_to_therapies(filtered, bundle, *, strict=False)` — `therapy_mapper.py:137`
- `get_mappings(force_reload=False)` — `app/roadmap/mapping_loader.py:414` (module-cached)
- Exceptions live in their module files: `RoadmapValidationError` (`roadmap_loader.py:9`),
  `MappingLoadError` (`mapping_loader.py:46`), `TherapyMappingError` (`therapy_mapper.py:51`)
- `FilteredRoadmapResult.filtered_scores[]` each have `.domain` and `.score`; `.is_empty` property exists
- `tests/test_roadmap_routes.py` already establishes the `TestClient` + env-stub + fake-Supabase
  bootstrap to reuse verbatim.

---

## Files to change

### Frozen — MUST NOT touch (7 files)
`roadmap_loader.py`, `severity_filter.py`, `mapping_loader.py`, `therapy_mapper.py`,
`models.py`, `mapping_models.py`, `therapy_models.py`. A git diff on these must stay empty.

### Create
1. **`app/roadmap/serializers.py`** — the serialization layer.
2. **`tests/test_roadmap_serializers.py`** — serializer unit tests.
3. **`tests/test_roadmap_mapped_therapies.py`** — route + service integration tests.

**Scope: CORE ONLY** (user-confirmed). Do **not** build the `?include_diagnostics=true`
flag or the `docs/roadmap-mapped-therapies-frontend.md` guide in this pass — they remain
future extensions per spec §10.5 / §13.

### Modify (additive only — existing functions untouched)
5. **`app/roadmap/services.py`** — add `map_roadmap_therapies(...)`.
6. **`app/roadmap/routes.py`** — add the `POST /mapped-therapies` route.

`app/main.py` and `requirements.txt` are **unchanged** — the roadmap router is
already mounted via `app.include_router(roadmap_router)`, and all deps (FastAPI,
Pydantic, openpyxl) are already pinned.

---

## Step-by-step

### Step 0 — Place the plan where requested
Copy this plan to `.claude/plan/manasi-ai-roadmap-step3-mapped-therapy-api-plan.md`
(the user asked for `.claude/plan/`; plan mode restricts edits to the harness plan
file, so this copy happens as the first execution action).

### Step 1 — `app/roadmap/serializers.py` (new)
Response models (plain `BaseModel`, `list[...]` not `tuple[...]`, contract fields only):
- `TherapyOut { therapy: str, relevance: Optional[str] = None }`
- `MappedDomainOut { domain, domain_type: Optional[str], score: Union[str,float,int], severity: Optional[str], therapies: list[TherapyOut] }`
- `MappedTherapyResponse { user_id: str, classification: Literal["ND","NT"], mapped_domains: list[MappedDomainOut] }`

Function:
- `build_mapped_response(filtered, mapped) -> MappedTherapyResponse`
  - Import `domain_key` from `therapy_mapper`.
  - Index scores: `score_by_key = {domain_key(fs.domain): fs.score for fs in filtered.filtered_scores}`.
  - For each `m` in `mapped.mappings`, emit `MappedDomainOut` pulling `score` via
    `score_by_key.get(domain_key(m.domain))`, `severity`/`domain`/`domain_type` from `m`,
    therapies from `m.therapies`. Preserve mapper order; preserve therapy (Excel) order — no re-sorting.
  - **Score-join miss:** if a key is absent, set `score=None` + `logger.warning("score_join_miss ...")`; never raise.

(No `build_diagnostics` / `include_diagnostics` in this pass — core only.)

### Step 2 — `app/roadmap/services.py` (add function)
```python
from app.roadmap.mapping_loader import get_mappings
from app.roadmap.therapy_mapper import map_domains_to_therapies
from app.roadmap.serializers import build_mapped_response, MappedTherapyResponse

def map_roadmap_therapies(payload) -> MappedTherapyResponse:
    result   = load_roadmap(payload)                      # Step 1
    filtered = filter_by_severity(result)                 # Step 2 (strict=False)
    bundle   = get_mappings()                              # cached Excel load
    mapped   = map_domains_to_therapies(filtered, bundle) # Step 3 (strict=False)
    return build_mapped_response(filtered, mapped)
```
Stateless — no Supabase read/write. `load_roadmap` + `filter_by_severity` already imported in this module.
Add a start/success `INFO` log (`user_id`, `classification`, actionable/mapped/unmapped counts) — `user_id` only, no payload.

### Step 3 — `app/roadmap/routes.py` (add route)
Reuse the `/submit` raw-body pattern. Add imports: `map_roadmap_therapies`,
`MappedTherapyResponse`, `MappingLoadError` (from `mapping_loader`), `TherapyMappingError`
(from `therapy_mapper`).
```python
@router.post("/mapped-therapies", response_model=MappedTherapyResponse)
async def mapped_therapies(request: Request):
    try: payload = await request.json()
    except Exception: -> HTTP 400 "Request body is not valid JSON."
    try:
        return map_roadmap_therapies(payload)
    except RoadmapValidationError as e:   -> 413 if e.code=="payload_too_large" else 422; envelope {status:"rejected", error:{code,message,field}}
    except MappingLoadError as e:         -> 500 code "mapping_data_unavailable"
    except TherapyMappingError as e:      -> 500 code "therapy_mapping_failed"
    except HTTPException: raise
    except Exception:                     -> 500 code "internal_error" (logger.exception)
```
Do **not** declare a Pydantic request-body model (loader owns the wire format). Keep the existing
`/submit` route untouched.

### Step 4 — Tests
- **`tests/test_roadmap_serializers.py`** (unit, build models directly, no I/O): spec §14 cases
  **minus the diagnostics case (U9)** — score join verbatim (`85`, `"72%"`, `88.5`),
  `domain_type`/`severity` passthrough, internal fields dropped, empty mappings,
  score-join-miss → `None`+warning, tuples→lists, ND vs NT dataset.
- **`tests/test_roadmap_mapped_therapies.py`** (integration, `TestClient`): reuse the
  `test_roadmap_routes.py` bootstrap (env stubs + fake Supabase + mount `router` on a `FastAPI()`);
  monkeypatch `get_mappings` → fixture `MappingBundle`. Spec §15 cases **minus the diagnostics
  cases (I13/I14)**: happy path, array-wrap, multi-element→422, missing `user_id`→422,
  bad `Classification`→422, empty `score`→422, boolean `Score`→422, >500→413, bad JSON→400,
  all-low→200 empty, unmatched domain→200, `MappingLoadError`→500, contract-only keys,
  idempotency, `/submit` regression.

(No Step 5 — the frontend doc is out of scope for this pass.)

---

## Key decisions baked in (from the spec)
- **Wire format is authoritative & capitalized** (`Classification`/`Score`/`Severity`) because the
  loader is frozen — the brief's lowercase example is illustrative only. All examples use the real keys.
- **`score` is joined in the serializer** (the mapper output doesn't carry it; `to_list()` drops it).
- **Empty actionable set → 200 with `mapped_domains: []`**, not an error.
- **No 404** on this stateless endpoint (reserved for a future GET-by-user variant).
- `strict=False` throughout (production posture); `get_mappings()` (cached), not `load_mappings()`.

---

## Verification
1. `cd /home/user/NEW_manasi && source venv/bin/activate` (Python 3.12).
2. `pytest tests/test_roadmap_serializers.py tests/test_roadmap_mapped_therapies.py -v` — new tests pass.
3. `pytest tests/ -q` — full suite green (existing loader/filter/mapper/routes/services unchanged).
4. `git diff --stat` on the 7 frozen files — must show **no** changes.
5. Manual smoke: `uvicorn app.main:app` then
   `curl -X POST localhost:8000/roadmap/mapped-therapies -H 'Content-Type: application/json' -d '{"user_id":"test001","Classification":"ND","score":[{"domain":"Sensory Processing","domain_type":"Spine","Score":85,"Severity":"High"}]}'`
   → 200 with `mapped_domains[].therapies[].relevance`. Confirm the endpoint appears in `/docs` with
   `MappedTherapyResponse`. Bad JSON → 400; missing `user_id` → 422.
