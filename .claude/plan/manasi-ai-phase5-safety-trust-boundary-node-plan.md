# Implementation Plan — Manasi AI Phase 5: Safety, Trust & Boundary Node

**Source spec:** `.claude/spec/manasi-ai-phase5-safety-trust-boundary-node-spec.md` (1401 lines, read in full)

## Context

Phases 1–4 are implemented and working: `understanding_node -> knowledge_node -> response_node -> empathy_node`. None of them ask "is this safe to actually deliver?" — Phase 4's own prompt explicitly defers disclaimers/safety checks to a future phase. This plan implements that phase: `safety_node`, the fifth and final node, run immediately after `empathy_node` and immediately before `END`. It can override or replace anything Phases 3–4 produced (medical-overreach language, off-domain answers, fabricated ManaScience-specific claims, overclaiming certainty) and short-circuits to a fixed, non-generative response template when the user's message contains self-harm/suicide language.

User decisions confirmed before finalizing this plan:
- **Leave the pre-existing, unrelated typo** in `app/graph/state.py`'s `RetrievedDocument.content_type` literals (`practit_info`/`websitioner_info`/`therapye_content`) untouched — it's the user's own uncommitted WIP and doesn't block this work.
- **Run a live OpenAI smoke test** after pytest passes (an `OPENAI_API_KEY` is already present in `.env`, venv has `pytest`/`langgraph`/`langchain-openai` installed).

Conventions confirmed directly from the live codebase (not just the spec's prose): `app/nodes/empathy_node.py` / `app/services/empathy_service.py` are the direct structural analogs (thin node + business-logic service, `model_validator`-based Pydantic output model, `_safe_fallback_result(...)` that bypasses Pydantic validation, `build_*_graph()` with sibling-node imports done locally inside the function). `app/config.py` is a flat `Settings` class with one `os.getenv(...)` line per setting. `app/prompts/*.txt` use plain-text `{{placeholder}}` string-replace substitution. All package `__init__.py` files are empty. `tests/test_empathy_node.py` is the test-density/style bar: no `conftest.py`, a `FakeLLM`/`_FakeResponse` class duplicated per test file, inline builder functions, assertions on `len(fake_llm.calls)`, an explicit state-immutability test, an explicit "doesn't read X" test.

---

## Implementation Plan

Files in dependency order: validators (no internal deps) → config → prompt → service → state/models/main edits → node → tests.

### 1. `app/validators/__init__.py` (new)
Empty, matching every other package `__init__.py` in the repo.

### 2. `app/validators/medical_validator.py` (new)
Pure module, zero `app.*` imports. Lift verbatim from **spec Section 8.3**: `MEDICAL_DIAGNOSTIC_PHRASES`, `MEDICATION_INSTRUCTION_PHRASES`, `MEDICAL_BANNED_PHRASES = MEDICAL_DIAGNOSTIC_PHRASES + MEDICATION_INSTRUCTION_PHRASES`, `fails_medical_safety(final_answer: str) -> bool`. Lift verbatim from **Section 8.4**: `MEDICAL_SAFE_REDIRECT_PHRASES` (4-item list — do not reorder; index `[2]` is the conservative default used later).

### 3. `app/validators/boundary_validator.py` (new)
Pure module, no LLM dependency. Lift verbatim from **spec Section 7.3**: `UNSUPPORTED_DOMAIN_KEYWORDS`. Lift verbatim from **Section 7.4**: `BOUNDARY_REDIRECT_TEMPLATE`. New (not given verbatim — derived from Section 7.1's recap list):
```python
SUPPORTED_DOMAIN_TOPICS = [
    "manascience", "neuroplasticity", "primitive reflex", "primitive reflexes",
    "sensory processing", "occupational therapy", "physical therapy",
    "developmental challenge", "developmental challenges", "learning challenge",
    "learning challenges", "practitioner", "course", "research", "family support",
    "therapy", "therapies",
]

def fails_domain_boundary(final_answer: str, topic: str) -> bool:
    """Boolean backstop signal only -- full vs partial handling is safety_service's job."""
    lowered = final_answer.lower()
    return any(kw in lowered for kw in UNSUPPORTED_DOMAIN_KEYWORDS)

def has_supported_domain_content(final_answer: str) -> bool:
    lowered = final_answer.lower()
    return any(kw in lowered for kw in SUPPORTED_DOMAIN_TOPICS)
```
`topic` stays in `fails_domain_boundary`'s signature (matches spec Section 14.5's literal signature) but is intentionally unused in the body — a mixed-domain answer can have an in-domain `topic` while still containing off-domain keywords (Example 20), so `topic` must not suppress the scan.

### 4. `app/validators/hallucination_validator.py` (new)
Lift verbatim from **spec Section 10.2**: `_candidate_entities`, `_is_grounded`, `KNOWN_SAFE_SELF_REFERENCES`, `flagged_entities(final_answer, source, retrieved_docs) -> list[str]`. Lift verbatim from **Section 10.5**: `HALLUCINATION_HONEST_FALLBACK_PHRASES` (3-item list; index `[1]` is the conservative default used later).

### 5. `app/config.py` (edit)
Append after the existing `empathy_*` settings block, before `def validate`:
```python
safety_model: str = os.getenv("SAFETY_MODEL", "gpt-4o-mini")
safety_temperature: float = float(os.getenv("SAFETY_TEMPERATURE", "0.1"))
safety_max_retries: int = int(os.getenv("SAFETY_MAX_RETRIES", "1"))
```
Per spec Section 14.9 / NFR tables. Also append the matching commented block to `.env.example` mirroring the existing `# EMPATHY_*` lines.

### 6. `app/prompts/safety_prompt.txt` (new)
Copy **verbatim** from spec **Section 12.4** (the full `text` fence block) — placeholders `{{grounding_context}}`, `{{violation_instructions}}`, `{{final_answer}}`. Plain text, same substitution style as `empathy_prompt.txt`.

### 7. `app/services/safety_service.py` (new)
Orchestration layer, direct analog of `empathy_service.py`.

**Imports:** `EMPATHY_BANNED_PHRASES` from `app.services.empathy_service`; everything from the three new validator modules. (Verified no import cycle: validators import nothing from `app.services`/`app.nodes`; `empathy_service.py` imports nothing from `safety_service.py` or `app.validators`.)

**Constants — lift verbatim:** `CRISIS_KEYWORDS_HIGH`, `SEVERE_DISTRESS_KEYWORDS_MODERATE` (Section 9.2); `CRISIS_RESPONSE_TEMPLATE_HIGH`, `CRISIS_RESPONSE_TEMPLATE_CHILD` (Section 9.4); `CERTAINTY_OVERCLAIM_PHRASES` (Section 6.3); `VIOLATION_REVIEW_INSTRUCTIONS` (Section 12.3). **New:** `CHILD_REFERENCE_PHRASES = ["my son", "my daughter", "my child", "my kid", "she wants to", "he wants to", "she said", "he said"]`.

**Functions:**
- `detect_crisis(user_message: str) -> str` — verbatim from Section 9.2 (`"high"`/`"moderate"`/`"none"`).
- `_select_crisis_template(user_message: str) -> str` — `CHILD` if any `CHILD_REFERENCE_PHRASES` hit, else `HIGH`.
- `_fails_certainty_overclaim(final_answer) -> bool`, `_fails_identity_violation(final_answer) -> bool` (re-checks `EMPATHY_BANNED_PHRASES`).
- `_run_guards(final_answer, topic, source, retrieved_docs) -> list[str]` — **single shared guard-runner**, called both on the original `final_answer` and on every rewrite candidate (this is what makes the LLM's own `is_clean` claim non-authoritative — the same function re-validates every candidate). Returns the dedup'd subset of `["medical_safety", "domain_boundary", "hallucination_risk", "trust_overclaim", "identity_violation"]`.
- `_is_full_domain_violation(final_answer) -> bool` — `fails_domain_boundary(...) and not has_supported_domain_content(...)`.
- `_format_grounding_context(retrieved_docs, source) -> str` — concatenated `doc["content"]`, truncated to `settings.knowledge_max_context_chars`; literal placeholder text when `source == "llm"`.
- `_violation_instructions_block(violations) -> str` — concatenates `VIOLATION_REVIEW_INSTRUCTIONS[v]`; a generic holistic-review instruction when `violations == []`.
- `_build_prompt(...)`, `_strip_code_fences(...)`, `_parse_safety_review(raw_text) -> tuple[bool, str]` (parses `{"is_clean", "safe_response"}`), `_safe_template_for(violations)` and `_select_fallback(...)` (both **verbatim from Section 11.8**), `_build_llm()`, `_invoke(...)` — all mirroring the equivalent helpers in `empathy_service.py`/`response_generator.py`.
- **`validate_response(empathy: dict, user_message: str, retrieved_docs: list[dict], llm=None) -> dict`** — entry point, never raises. Algorithm:
  1. `crisis_level = detect_crisis(user_message)`. If `"high"` → return immediately: `safety_status="escalated"`, `escalation_level="high"`, `safe_response=_select_crisis_template(user_message)`, `violations_detected=[]`, `disclaimer_added=False`, full passthrough, `error=None`. **Zero LLM calls.**
  2. `violations = _run_guards(final_answer, topic, source, retrieved_docs)`; `needs_moderate_support = (crisis_level == "moderate")`.
  3. **Full-domain shortcut:** if `violations == ["domain_boundary"]` exactly (the *only* violation) **and** `_is_full_domain_violation(final_answer)` **and not** `needs_moderate_support` → skip the LLM entirely, return `safety_status="modified"`, `safe_response=BOUNDARY_REDIRECT_TEMPLATE`, `violations_detected=["domain_boundary"]`, `disclaimer_added=False`, `error=None`. (If domain_boundary co-occurs with another violation, fall through to the normal LLM loop instead — a combined violation needs a targeted rewrite, not a flat redirect.)
  4. Otherwise, run the **attempt loop** (max `1 + settings.safety_max_retries`): build the prompt with current `violations` (empty list → holistic instruction) plus any corrective suffix; invoke the LLM; parse `(is_clean, candidate)`; **re-run `_run_guards` on `candidate`** — this re-check result is authoritative, not `is_clean`. If clean, accept and break. If not, build the corrective suffix from whichever guards just failed and retry.
  5. If a clean attempt was found: `safety_status = "modified"` if (`violations` non-empty or `needs_moderate_support`) else `"approved"`; `error=None`.
  6. If no clean attempt was found: call `_select_fallback(final_answer, violations, llm_call_failed=...)` — if `violations` was non-empty pre-call, this **must** return the safe template (never the unreviewed `final_answer`); if `violations` was empty (pure holistic-pass LLM failure), it's safe to return `final_answer` unchanged with `safety_status="approved"`.
  7. `disclaimer_added = (escalation_level == "moderate") or any(p.lower() in safe_response.lower() for p in MEDICAL_SAFE_REDIRECT_PHRASES)`, forced to `False` whenever `safety_status == "escalated"`.
  8. Return the dict with full passthrough (`emotional_state`, `source`, `answer_type`, `topic`, `intent`, `confidence`, `grounded_chunk_ids` copied unchanged from `empathy`) and `original_final_answer = empathy["final_answer"]`.

### 8. `app/graph/state.py` (edit)
Add the `Safety` TypedDict and `safety: Optional[Safety]` field on `GraphState`, lifted verbatim from **spec Section 13.4**. Strictly additive — diff touches only the bottom of the file; the pre-existing `content_type` typo is left untouched per the user's decision.

### 9. `app/models.py` (edit)
Add `SafetyResponse(BaseModel)` mirroring `HumanizeResponse`'s field set (`str`/`float`/`list[str]`/`bool`-typed), per spec Section 13.7.

### 10. `app/main.py` (edit)
Import `SafetyResponse` and `build_safety_graph`; add a `safety_graph = None` global, build it in `lifespan(...)`; add `POST /safety` mirroring `/humanize`'s exact shape (Section 13.7). **Do not touch** the existing `/chat` endpoint or `build_chain()` — that migration is explicitly deferred (Section 13.8/17).

### 11. `app/nodes/safety_node.py` (new)
Thin wrapper mirroring `empathy_node.py`. `SafetyOutput(BaseModel)` with both `model_validator`s lifted verbatim from **Section 11.5** (imports `MEDICAL_BANNED_PHRASES` from `app.validators.medical_validator`, `EMPATHY_BANNED_PHRASES` from `app.services.empathy_service`). `safety_node(state, llm=None) -> dict` reads `state["empathy"]`, `state["user_message"]`, and `state["knowledge"]["retrieved_docs"]` only when `empathy["source"] == "rag"` and `knowledge` is present; calls `validate_response(...)`, times it, validates via `SafetyOutput`, returns `{"safety": {...}}`. `_safe_fallback_result(empathy, start)` hand-builds a conservative result (bypassing `SafetyOutput`) defaulting to `MEDICAL_SAFE_REDIRECT_PHRASES[2]` / `safety_status="modified"` / `violations_detected=["medical_safety"]` — **never** the unreviewed `final_answer`, since an unexpected internal error is not evidence the content was clean. Logs a distinct `safety_escalation` warning on the `escalated` path (Section 9.6). `build_safety_graph()` compiles the full five-node production graph, lifted verbatim from **Section 13.6**.

---

## Test Plan

### `tests/test_safety_node.py` (new)
Same structure as `test_empathy_node.py` (`FakeLLM`/`_FakeResponse`, inline builders, no `conftest.py`). ~18 cases:
1. Holistic pass, `is_clean: true` → approved, 1 LLM call.
2. Crisis high → escalated, **zero** LLM calls.
3. Crisis high + child-referring language → `CRISIS_RESPONSE_TEMPLATE_CHILD` selected.
4. Severe distress (moderate) → `modified`, `escalation_level="moderate"`, exactly 1 LLM call (not zero).
5. Ordinary `overwhelmed` with no crisis/distress language → `escalation_level="none"`, normal pipeline.
6. Medical diagnosis phrase → `modified`, `violations_detected=["medical_safety"]`, `disclaimer_added=True`.
7. Medical violation: rewrite still fails guard on attempt 1 → retries → succeeds on attempt 2 (`len(llm.calls) == 2`).
8. Medical violation: both attempts fail → fallback to `MEDICAL_SAFE_REDIRECT_PHRASES[2]`, `error="quality_guard_exhausted_safe_fallback"`, and explicitly assert `safe_response != final_answer`.
9. Fully off-domain answer → `BOUNDARY_REDIRECT_TEMPLATE`, **zero** LLM calls.
10. Mixed in-domain/off-domain answer → goes through LLM rewrite, in-domain sentence preserved.
11. `source == "llm"`, named entity present → `hallucination_risk` fires unconditionally (Section 10.3).
12. `source == "rag"`, entity grounded in `retrieved_docs` → no `hallucination_risk` fires.
13. `source == "rag"`, entity NOT in `retrieved_docs` → `hallucination_risk` fires.
14. Certainty-overclaim phrase → `trust_overclaim`, softened rewrite.
15. `EMPATHY_BANNED_PHRASES` phrase in `final_answer` → `identity_violation` fires (defense-in-depth).
16. LLM call fails both attempts, **no guard fired** pre-call → `approved`, `safe_response` unchanged, `error="llm_call_failure"`.
17. LLM call fails both attempts, **guard fired** pre-call → `modified`, safe template (never unreviewed answer), `error="quality_guard_exhausted_safe_fallback"`.
18. State immutability (`empathy`/`knowledge` dicts unchanged after the call) + full metadata passthrough (FR-12) in one approved-path case.

Add 2 `SafetyOutput` Pydantic consistency-rule tests: `escalation_level="high"` with `safety_status="modified"` raises; `safety_status="approved"` with non-empty `violations_detected` raises.

### `tests/test_validators.py` (new)
One file covering all three new pure-function validator modules together (no precedent in this repo for per-module test files — `app/rag/retriever.py` has no standalone test file either, it's only exercised via its node's test file — so this single file matches existing convention while still satisfying NFR 4.1's "independently unit-testable as a pure function"). No `FakeLLM`, no state, just direct calls:
- `fails_medical_safety`: true for a diagnostic phrase, true for a medication phrase, false for clean educational text, case-insensitive.
- `fails_domain_boundary` / `has_supported_domain_content`: true/false on representative in-domain vs. off-domain text.
- `flagged_entities`: `source=="llm"` flags all candidate entities; `source=="rag"` flags only ungrounded ones; `KNOWN_SAFE_SELF_REFERENCES` ("ManaScience", "Manasi") never flagged.

---

## Verification

1. **Unit tests (FakeLLM only, no API calls):**
   ```bash
   cd /home/user/NEW_manasi
   pytest tests/test_validators.py tests/test_safety_node.py -v
   ```
2. **Full regression** — confirm the additive `GraphState`/`config.py` edits don't break Phases 1–4:
   ```bash
   pytest tests/ -v
   ```
3. **File-structure sanity check:**
   ```bash
   git diff --stat app/graph/state.py app/models.py app/main.py app/config.py
   ```
   Should show only additive hunks; the pre-existing `content_type` typo must remain untouched.
4. **Live smoke test** (per user's request — a real `OPENAI_API_KEY` is already in `.env`):
   ```bash
   uvicorn app.main:app --reload &
   curl -s -X POST localhost:8000/safety -H "Content-Type: application/json" \
     -d '{"message": "What is neuroplasticity?", "session_id": "smoke1"}' | python3 -m json.tool
   curl -s -X POST localhost:8000/safety -H "Content-Type: application/json" \
     -d '{"message": "I want to end my life", "session_id": "smoke2"}' | python3 -m json.tool
   curl -s -X POST localhost:8000/safety -H "Content-Type: application/json" \
     -d '{"message": "What is Python programming?", "session_id": "smoke3"}' | python3 -m json.tool
   ```
   Expect: call 1 → `"safety_status": "approved"`; call 2 → `"safety_status": "escalated", "escalation_level": "high"` with the crisis template verbatim, near-instant (no LLM latency); call 3 → `"safety_status": "modified", "violations_detected": ["domain_boundary"]` with `BOUNDARY_REDIRECT_TEMPLATE` text.
5. Stop the server afterward (`kill %1` or `fg`+Ctrl-C).
6. **Save a copy of this plan** to `.claude/plan/manasi-ai-phase5-safety-trust-boundary-node-plan.md`, matching the existing repo convention (`manasi-ai-phase3-response-generation-node-plan.md`), as the first action after exiting plan mode.
