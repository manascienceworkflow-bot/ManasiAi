# Implementation Plan — Roadmap Step 2: Severity Filtering Module

**Spec:** `.claude/spec/manasi-ai-roadmap-step2-severity-filter-spec.md`
**Status:** ✅ Implemented 2026-07-14. 350/350 tests pass (73 new unit + 9 new route + 5 new service). Verified end-to-end against the real ASGI app.

---

## Context

Step 1 of the Roadmap Assessment Pipeline (ingestion — `POST /roadmap/submit` → `load_roadmap()` → Supabase upsert) is shipped and working. It validates `user_id`, `Classification`, and every `score[]` entry's `domain` and `Score`, but it deliberately stores `Severity` **verbatim and unvalidated** (`app/roadmap/roadmap_loader.py:108`).

That leaves a gap: every downstream stage (therapy mapping, roadmap generation — both out of scope) must operate **only** on the domains the assessment flagged as clinically actionable. Right now nothing enforces that. A `Low`-severity domain — one where the user is functioning adequately — would flow straight into therapy mapping and risk recommending intervention for a non-issue.

Step 2 closes that gap with a single pure function that keeps **only High and Moderate** domains and drops everything else, recording why. It is the first module to validate severity at all.

**Outcome:** `filter_by_severity(RoadmapResult) -> FilteredRoadmapResult`, wired into the existing submit path, returning the actionable domain set plus diagnostics. No new endpoint. No behavior change for any existing caller.

---

## Approach

Purely **additive**. One new module, four new models, three additive response fields, one new status-code mapping. `roadmap_loader.py` and `context_builder.py` are **not touched**.

The filter consumes the canonical `RoadmapResult` that Step 1 emits — **not** raw JSON. This respects the project's existing rule that the loader is the only module allowed to see the wire format (`roadmap_loader.py:118`), and it makes Step 2 immune to the `Classification`/`Score`/`Severity` casing discrepancy noted in §0 of the spec.

---

## Files to change

### 1. `app/roadmap/models.py` — add 4 models, extend 1 (additive only)

Append `FilteredDomainScore`, `DroppedDomain`, `FilterDiagnostics`, `FilteredRoadmapResult` exactly as specified in spec §9.1. Key points:

- `FilteredRoadmapResult` is **not** a subclass of `RoadmapResult` (Liskov — a filtered set is not substitutable for a complete one).
- It carries `filtered_scores`, `dropped`, `diagnostics`, and an `is_empty` property.
- `DroppedDomain.reason` is a `Literal` of the four drop reasons: `low_severity`, `missing_severity`, `unknown_severity`, `duplicate_domain`.

Extend `RoadmapSubmitResponse` with three fields that all have defaults, so no existing caller breaks:

```python
domains_actionable: int = 0
domains_filtered_out: int = 0
filter_warnings: list[str] = []
```

### 2. `app/roadmap/severity_filter.py` — **NEW**, the module itself

Implement per the reference sketch in spec Appendix A. The non-obvious parts, all of which have a stated reason:

- **Vocabulary lives in one frozen mapping** (`_SEVERITY_RANK` + `ACTIONABLE_SEVERITIES`). The algorithm does set-membership lookups, never `if sev == "high"` — that's what makes adding a severity level a one-line change (Open/Closed, spec §4.4).
- **Normalization order matters**: NFKC → strip → collapse internal whitespace → `casefold()`. NFKC is first because it folds fullwidth/compatibility forms, which is both an ergonomics win and a homoglyph-bypass guard (spec §15.2). `casefold()` not `.lower()` — it's the Unicode-correct caseless match.
- Normalization derives a **comparison key only**. The original `severity` and `score` strings are carried into the output byte-for-byte (project rule P1: the backend never recomputes or re-ranks a score).
- **Severity is never inferred from the numeric score.** `{score: 95, severity: "Hgh"}` is dropped as `unknown_severity`, not promoted to High.
- **Duplicate domains: highest severity wins, ties keep first occurrence.** This is the one stateful part of the loop. It makes the result invariant under input reordering and guarantees a more-severe signal is never discarded. Dedup key is the *normalized* domain, so `"Attention"` and `"  attention "` are one domain; the first-seen original spelling is what appears in the output.
- **`MAX_DOMAINS = 500`** guard → `RoadmapValidationError("payload_too_large")`. Real assessments carry 5–15 domains.
- **`strict: bool = False`** keyword-only flag. Default (production): an unknown/missing severity drops the domain, warns, and records it — it never fails the request. `strict=True` raises instead; used by contract tests.
- **Accounting assertion**: `len(kept) + len(dropped) == len(entries)`. A violation is an internal bug and must be loud.
- Reuses the **existing** `RoadmapValidationError` from `roadmap_loader.py:9` rather than inventing a parallel exception type — the route already maps it to a structured 422.
- Imports **only** `logging`, `unicodedata`, `app.roadmap.models`, and that one exception. No FastAPI, no Supabase, no LangChain, no `app.db`.
- Logging follows house style: `logging.getLogger("app.roadmap.severity_filter")`, `%`-style lazy args (never f-strings), one `INFO` summary per submission, `WARNING` per anomaly, `DEBUG` per-domain. **Numeric scores are never logged** (PII minimization, spec §14.3).

### 3. `app/roadmap/services.py` — wire it in

In `submit_roadmap`, call the filter **before** the Supabase upsert (a payload we can't filter is a payload we don't persist), then add the three counts to the returned ack dict:

```python
result = load_roadmap(payload)              # Step 1, existing
filtered = filter_by_severity(result)       # Step 2, new — fail LOUD on the write path
supabase.table(ROADMAP_TABLE).upsert({...}).execute()   # existing, unchanged
```

`get_roadmap_context_text` (the read path) is **not** changed — narrowing Manasi's hidden chat context to actionable domains only is a deferred product decision (spec §16), not part of Step 2.

### 4. `app/roadmap/routes.py` — one new status-code mapping

`payload_too_large` is semantically a **413**, not a 422. In the existing `except RoadmapValidationError` block:

```python
status = 413 if exc.code == "payload_too_large" else 422
```

The error envelope shape is unchanged, so the frontend's existing error handling keeps working.

### 5. Tests

**`tests/test_severity_filter.py` — NEW.** ~43 unit scenarios from spec §18. Pure — no fakes, no env vars, no `TestClient`. A `_result(*entries)` helper builds a `RoadmapResult` directly (Step 2's input is the loader's *output*, so tests construct that object, not raw JSON). Groups: core filtering incl. the brief's worked example (High, Moderate, Low, High, Low → High, Moderate, High); case/whitespace/unicode; missing/null/unknown severity; duplicates incl. the order-independence test; **immutability & purity** (the highest-value tests — deep-copy the input, run the filter, assert the input is bit-identical); guards and the accounting invariant.

**`tests/test_roadmap_routes.py` — EXTEND.** 14 integration scenarios from spec §19, reusing the file's existing `FakeSupabase`/`_client` helpers and its env-stub-before-import pattern. Critical ones: a 501-domain payload is a **413 with zero Supabase writes**; all-Low is a **200 with `domains_actionable: 0`**, not an error; and every pre-existing Step-1 failure mode still returns the same `error.code` as before (non-regression).

**`tests/test_roadmap_services.py` — EXTEND.** Assert the service calls loader → filter in that order and threads the counts into the ack.

House test conventions to follow (from `tests/test_roadmap_loader.py:1-4` and `tests/test_roadmap_routes.py:10-15`): each file prepends the repo root to `sys.path` itself, there is **no `conftest.py`**, and fakes are hand-rolled (no `unittest.mock`). Don't introduce a `conftest.py` as a drive-by.

---

## Decisions already committed in the spec

These are defaults I'm implementing; each is a one-line change if you disagree (spec Appendix C):

- **Unknown severity drops the domain, doesn't reject the request** (§6.3). A user who spent 40 minutes on an assessment shouldn't get a 422 because one domain came back `"Borderline"`. The anomaly surfaces as a `WARNING` log + a `filter_warnings` entry.
- **Duplicates: highest severity wins** (§7.5). Keep-first/keep-last could silently drop a High domain if the payload order changed.
- **Missing severity → drop** (§7.4). An unclassified domain is not provably actionable; the conservative choice.

---

## Verification

1. `python -m pytest tests/ -q` — the full suite. **All pre-existing roadmap tests must pass unmodified** (`test_roadmap_loader.py`, `test_roadmap_routes.py`, `test_roadmap_services.py`, `test_roadmap_context_builder.py`).
2. `python -m pytest tests/test_severity_filter.py -q` — the new unit suite, incl. the brief's exact worked example.
3. Branch coverage of `severity_filter.py` should be 100% (`--cov=app.roadmap.severity_filter --cov-branch` if `pytest-cov` is available; it is not currently in `requirements.txt`, so this is a check, not a gate).
4. **End-to-end against a live server**: start `uvicorn app.main:app`, then `POST /roadmap/submit` with the spec's 3-domain example (High / Low / Moderate) and confirm the response reports `domains_received: 3`, `domains_actionable: 2`, `domains_filtered_out: 1`. Then post an all-Low payload and confirm a **200** with `domains_actionable: 0` (not an error), and a payload with a `"Severe"` severity and confirm a 200 with one entry in `filter_warnings`.

---

## Out of scope (do not build)

Therapy mapping, roadmap generation, recommendation engine, PDF, email, any LLM call, any new endpoint, persisting `filtered_scores`, narrowing the chat context, and fixing the Step 1 wire-format casing.
