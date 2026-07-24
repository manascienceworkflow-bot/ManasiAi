# Implement Phase 6: CTA Node

## Context

`app/services/cta_loader.py` already loads, parses, and validates every CTA Markdown
file under `data/cta/` (15 files today) into typed `CTARecord` objects, with zero
consumers — nothing in the codebase calls it yet. A complete, highly prescriptive
technical spec for the consumer was just written at
`.claude/spec/manasi-ai-phase6-cta-node-spec.md`, following this repo's established
convention (confirmed by the loader itself, and by Phases 1–5) of writing specs
detailed enough to translate into code near-verbatim.

The goal of this work is to implement that spec: a deterministic, LLM-free **CTA
Node** that runs last in the pipeline (after `safety_node`), decides whether to
attach one Call-To-Action to the chatbot's final answer, and never modifies that
answer. This is a pure greenfield addition — no existing `cta_node.py`/`cta_service.py`/
`test_cta_node.py` exists (confirmed via `find`), and no other phase's files need
behavioral changes, only additive edits in the established per-phase pattern.

Verified facts grounding this plan (re-derived from the live repo, not assumed):
- Python 3.12.3, Pydantic 2.13.4 (v2 API — `@model_validator(mode="after")` confirmed in use by `safety_node.py`/`empathy_node.py`).
- No pytest.ini/conftest.py/isort/ruff config exists — pytest uses defaults; no mechanical import-sort tool to defer to.
- Real corpus confirms the spec's worked examples: `data/cta/conditions/adhd.md:34` and `data/cta/conditions/general.md:181` both contain `"What is ADHD?"` verbatim — as a trigger example on `adhd.md` and as an exclusion phrase on `general.md` — so asking "What is ADHD?" is expected to resolve to `conditions/adhd` two ways at once (it scores directly, *and* the Library CTA is independently excluded).

## Approach

Implement file-by-file in dependency order, each new/edited file translating the
spec's already-detailed sections directly into code, reconciling two things the
spec's illustrative code blocks don't fully pin down:

1. **Definition order inside `cta_service.py`.** The spec presents helper functions
   in section-narrative order, not safe top-to-bottom Python order (e.g. `CTAMatch`
   is defined in Section 10.1 but used by `find_cta` in Section 9.7). Reorder so
   every name is defined before first use — no `from __future__ import annotations`
   needed, this codebase doesn't use it anywhere else.
2. **Two function bodies the spec only gives a docstring for** (`cta_node()`'s body,
   `process()`'s body) — write these by direct analogy to `safety_node()`'s shape
   (`app/nodes/safety_node.py`) and `safety_service.validate_response`'s split of
   labor, per the spec's own cross-references (Sections 12.1/12.2/14).

### Step 1 — `app/services/cta_service.py` (new)

Imports: `logging`, `re`, `collections.defaultdict`, `dataclasses.dataclass`,
`typing.Literal/Optional`, and `from app.services.cta_loader import CTARecord,
get_ctas_by_status`. **No `import time`** — timing is the node's job (Section 12.1).
Logger name `app.services.cta_service`.

Define, top-to-bottom, in this corrected order (spec sections in parens):
`_WORD`/`_normalize()` (9.3) → `_phrase_in_text()` (9.3) → `_is_excluded()` (9.4) →
weight constants + `_Hit` dataclass (9.5) → `_best_hit()` (9.5) → `_score_candidate()`
(9.5) → `_general_cta_for_category()` (9.2) → `INTENT_CATEGORY_AFFINITY` dict (9.6) →
`_resolve_winner()` (9.6) → `CTAMatch` dataclass (10.1) → `find_cta()` (9.7) →
`build_cta_response()` (12.1, body per Section 5.2's exact JSON shape) → `process()`
(12.1, body: call `get_ctas_by_status("Active")`, `logger.warning(...)` if empty per
Section 11.2, call `find_cta`, return the `CTAOutput`-shaped dict *minus*
`lookup_time_ms`/`error`).

Every code block needed already exists almost verbatim in the spec (Sections 9.2–9.7,
12.1) — copy and reorder, don't redesign.

### Step 2 — `app/nodes/cta_node.py` (new)

Mirrors `app/nodes/safety_node.py`'s shape, with one deliberate structural
difference: **no `llm` parameter** anywhere (the spec's FR-9 — fully deterministic).

- `CTAOutput` — spec Section 10.3, verbatim, complete as written.
- `cta_node(state: GraphState) -> dict` — reads `state["user_message"]`,
  `state.get("understanding") or {}` (defensive against missing/None — `cta_service`
  only ever does `.get(...)` on it), `state["safety"]["safe_response"]`; times the
  call into `cta_service.process()`, validates through `CTAOutput`, falls back to
  `_safe_fallback_result()` on any exception, logs one `INFO` summary line per
  Section 14, returns `{"cta": {...}}`.
- `_safe_fallback_result(safe_response, start)` — spec Section 11.3, verbatim.
- `build_cta_graph()` — six-node graph (`understanding → knowledge → response →
  empathy → safety → cta`), function-local imports exactly like
  `safety_node.build_safety_graph()`'s pattern, importing `safety_node` itself as the
  fifth node.

### Step 3 — `app/graph/state.py` (additive edit)

Insert the `CTA` TypedDict (spec Section 10.2) immediately after the `Safety` class
and before `GraphState`; append `cta: Optional[CTA]` as `GraphState`'s new last
field. No import changes (`Literal`/`Optional`/`TypedDict` already imported).

### Step 4 — `app/models.py` (additive edit)

Append `CTAResponse` (spec Section 10.4) after `SafetyResponse`, matching the
existing `str | None` style. No new imports needed.

### Step 5 — `app/main.py` (additive edit)

Five additive changes, mirroring `/safety`'s exact wiring:
1. Add `CTAResponse` to the `app.models` import block — alphabetical-insensitive
   placement: `AnswerResponse, ChatRequest, ChatResponse, CTAResponse,
   HumanizeResponse, ...` (no sort tool exists in-repo to defer to; this ordering is
   the lowercase/visual-alphabetical one a human would write by hand).
2. Add `from app.nodes.cta_node import build_cta_graph` — sorts first among the
   `app.nodes.*` imports (`cta_node` < `empathy_node` < `knowledge_node` <
   `response_node` < `safety_node` < `understanding_node`).
3. Add `cta_graph = None` global, after `safety_graph = None`.
4. In `lifespan()`: add `cta_graph` to the `global` statement, assign
   `cta_graph = build_cta_graph()` after `safety_graph = build_safety_graph()`.
5. Add a `/cta` endpoint after `/safety`, invoking the six-node graph with all
   upstream `GraphState` fields `None` — the same isolated-per-phase pattern every
   prior endpoint uses (no shared production graph exists yet). Name the endpoint
   function **`cta`** (not the spec draft's `cta_endpoint`) to match this file's
   actual established convention — every other endpoint function is named exactly
   after its route segment (`understand`, `knowledge`, `respond`, `humanize`,
   `safety`), none suffixed `_endpoint`.

### Step 6 — `tests/test_cta_node.py` (new)

Mirror `tests/test_safety_node.py`'s exact file shape: `sys.path.append(...)`
boilerplate, `# noqa: E402` imports, plain pytest functions, no test classes. Key
differences from the safety test file: no `FakeLLM`/`json`/`httpx`/`openai` (CTA
matching is LLM-free) — control candidates instead via `monkeypatch`, and via direct
`find_cta()`/`process()` calls at the service level for matching-logic tests (cheaper
and more precise than always going through the full `cta_node()`).

Helpers to write: `make_cta_record(...)` (a `CTARecord` builder defaulting every
required field so a test only overrides what it cares about — `status="Active"`,
non-empty `trigger_examples`, valid `https://` `cta_url`, etc., satisfying
`CTARecord`'s own pydantic validators), `make_understanding(...)`, `make_safety(...)`,
`make_state(...)` (matching the `make_empathy`/`make_state` pattern in
`test_safety_node.py`).

**Critical monkeypatch detail:** `cta_service.py` does `from app.services.cta_loader
import ... get_ctas_by_status` (a direct name import). Tests must patch
`monkeypatch.setattr("app.services.cta_service.get_ctas_by_status", fake_fn)` — the
name as bound in the *consumer's* namespace — not
`app.services.cta_loader.get_ctas_by_status`, which would silently no-op against
`cta_service`'s already-bound reference.

Test functions to implement (27 total — the 23 scenarios named in spec Section 17.1's
table, listed below by name, plus 4 `CTAOutput` validator tests mirroring
`test_safety_node.py`'s `test_safety_output_rejects_*` pattern, which the spec's
Section 10.3 validator logic implies but Section 17.1 doesn't enumerate separately):

`test_specific_therapy_match_mnri`, `test_specific_condition_match_adhd`,
`test_general_therapy_library_direct_match`,
`test_intent_driven_category_fallback_when_nothing_matches`,
`test_no_match_when_nothing_scores_and_no_intent_affinity`,
`test_no_match_returns_none_not_empty_list`,
`test_exclusion_blocks_an_otherwise_matching_cta`,
`test_exclusion_also_blocks_the_category_fallback_path`,
`test_specific_beats_general_in_same_category`,
`test_alias_outranks_trigger_example_tier`,
`test_cross_category_tie_broken_by_intent_affinity`,
`test_cross_category_genuine_tie_logged_and_deterministic`,
`test_duplicate_same_score_candidates_tie_broken_by_cta_id`,
`test_empty_active_ctas_returns_no_match`,
`test_unexpected_service_exception_falls_back_safely`,
`test_empty_safe_response_passed_through_unchanged`,
`test_response_is_never_modified`, `test_topic_alone_can_trigger_a_match`,
`test_missing_topic_key_does_not_raise`,
`test_build_cta_response_minimal_shape_on_match`,
`test_build_cta_response_minimal_shape_on_no_match`,
`test_performance_under_corpus_growth`,
`test_real_corpus_smoke_no_crash_no_unexpected_match` (no monkeypatching — hits the
real, already-loaded corpus), plus
`test_cta_output_rejects_found_true_with_missing_cta_id`,
`test_cta_output_rejects_found_true_with_no_match_reason`,
`test_cta_output_rejects_found_false_with_nonnull_cta_id`,
`test_cta_output_rejects_found_false_with_wrong_match_reason`.

## Critical Files

- `app/services/cta_service.py` (new) — the matching algorithm.
- `app/nodes/cta_node.py` (new) — the LangGraph wrapper.
- `app/graph/state.py` (edit) — `CTA` TypedDict + `GraphState.cta`.
- `app/models.py` (edit) — `CTAResponse`.
- `app/main.py` (edit) — `/cta` endpoint + six-node graph wiring.
- `tests/test_cta_node.py` (new) — 27 tests.

Reused as-is, no changes: `app/services/cta_loader.py` (`CTARecord`,
`get_ctas_by_status`), `app/config.py` (`cta_data_dir` already exists), every
upstream node (`understanding_node`, `knowledge_node`, `response_node`,
`empathy_node`, `safety_node`).

## Verification

1. **Unit tests:** `cd /home/user/NEW_manasi && python -m pytest tests/test_cta_node.py -v`, then the full suite `python -m pytest -q` to confirm zero regressions to Phases 1–5's existing tests.
2. **Real-corpus smoke check** (no LLM, no server — hand-construct `state["understanding"]`/`state["safety"]` and call `cta_node()` directly), confirming against the real files read during planning:
   - `"What is MNRI?"` (intent `therapy_information`, topic `"MNRI"`) → expect `cta_id == "therapies/mnri"`.
   - `"What therapies are available?"` (intent `therapy_information`) → expect `cta_id == "therapies/general"` (a *direct* trigger-example hit on the Library record itself, `match_reason == "specific_match"`, not `"category_fallback"`).
   - `"What is ADHD?"` (intent `personal_concern`, topic `"ADHD"`) → expect `cta_id == "conditions/adhd"` (confirmed doubly correct against the real files: it's a trigger example on `adhd.md` *and* an exclusion phrase on `general.md`).
   - An unmatched generic message with intent `general_chat` → expect `cta_found == False`.
   - This is covered by `test_real_corpus_smoke_no_crash_no_unexpected_match` in the test file, and can be re-run standalone as a quick sanity check.
3. **Static checks:** `grep -n "^import\|^from" app/services/cta_service.py` should show only stdlib + `app.services.cta_loader` (FR-1 isolation); `grep -n "langgraph" app/nodes/cta_node.py` should show it only inside `build_cta_graph()`.
4. **Optional end-to-end:** start the app (`uvicorn app.main:app --port 8000`, requires `OPENAI_API_KEY` since `understanding_node` calls an LLM) and `curl -X POST localhost:8000/cta -d '{"message": "What is MNRI?"}' -H "Content-Type: application/json"` to confirm the full six-node graph and FastAPI wiring work end-to-end, not just the matching logic in isolation.
