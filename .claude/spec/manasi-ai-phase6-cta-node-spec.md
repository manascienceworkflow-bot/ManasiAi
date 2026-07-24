# Manasi AI — Technical Specification
## Phase 6: CTA Node (`cta_node.py` / `cta_service.py`)

**Project:** Manasi AI
**Organization:** ManaScience
**Component:** CTA Node — sixth and final LangGraph pipeline phase
**Status:** Draft for implementation
**Audience:** Python engineer implementing `app/services/cta_service.py` and `app/nodes/cta_node.py`
**Depends on:** `app/services/cta_loader.py` (Sections 13–14 of `manasi-ai-cta-loader-spec.md`) as its **only** source of CTA data, plus the production pipeline through Phase 5 (`app/nodes/safety_node.py`). Does not depend on `app/rag/`, any LLM client, or any other `services/*_service.py` module.
**Pipeline position:**

```
User
  -> Understanding Node   (Phase 1)
  -> Knowledge Node       (Phase 2)
  -> Response Node        (Phase 3)
  -> Empathy Node         (Phase 4)
  -> Safety Node          (Phase 5)
  -> CTA Node              (Phase 6 -- this spec)
  -> Final Output
```

**Prior art:** An earlier CTA design (`data/cta/cta_links.md`, `app/services/cta_service.py`, `app/nodes/cta_node.py`) ran the CTA decision immediately after `knowledge_node` and resolved a CTA from a `cta_key` tag baked into RAG-chunk metadata. It was implemented and reverted (`3b08629` → `e4a56ee`) when the data model moved to the richer per-CTA Markdown corpus under `data/cta/`. That corpus is now served by `app/services/cta_loader.py` (already implemented; see `manasi-ai-cta-loader-spec.md`), whose Section 3.2 explicitly defers all matching/decision logic to "a future CTA Node." This document is that node. It does not resurrect the old design's data source (`cta_links.md`) or its metadata-tag matching strategy, but it does reuse the old design's *shape* — a `cta_service.py` matcher plus a thin `cta_node.py` GraphState adapter, each Section 12 below makes the borrowed and the changed parts explicit.

---

## 1. Executive Summary

`app/services/cta_loader.py` already loads, parses, and validates every CTA Markdown file under `data/cta/` into typed `CTARecord` objects, and exposes them through six read-only accessor functions (`get_all_ctas`, `get_cta_by_id`, `get_ctas_by_category`, `get_ctas_by_status`, plus `load_cta_data`/`reload_cta_data`). Nothing today calls any of them — the loader is a complete, tested foundation with zero consumers.

This spec adds the consumer: a deterministic, LLM-free **CTA Node** that runs last in the pipeline, after `safety_node`. For each turn it asks one question — *should a Call-To-Action be attached to this response, and if so, which one* — by scoring the user's message and the Understanding Node's `topic` against every `Active` CTA's `aliases`, `trigger_examples`, and `related_topics`, excluding any CTA whose `exclusion_conditions`/`do_not_trigger_examples` also match, resolving ties between categories and between competing specific CTAs by documented, auditable rules, and falling back to a category's general/library CTA only when literal phrase matching finds nothing at all. It returns **at most one** CTA, never rewrites the chatbot's answer, and never raises.

The defining design decision this spec makes — because the loader deliberately left it unmade (`manasi-ai-cta-loader-spec.md` Section 3.2, Section 9.3) — is *what a "match" means*. Section 9 derives that definition directly from the 15 files actually on disk today (catalogued in Section 9.1's category table), not from an idealized schema, in the same spirit as the loader spec being "grounded in a full read of all 15 existing files."

---

## 2. Purpose

Give the pipeline's final step a single, reliable answer to "CTA Found or CTA Not Found, and if found, exactly which one" — using only the Understanding Node's output, the user's raw message, and the CTA Loader's in-memory `CTARecord` set. Every other node's output up through `safety_node` is treated as read-only, untouched input; the CTA Node's only write is its own `cta` field.

---

## 3. Scope

### 3.1 In Scope — Responsibilities

The CTA Node SHALL:

* Call `app.services.cta_loader`'s public accessors only (`get_ctas_by_status`, transitively `get_all_ctas`/`get_cta_by_id` if ever needed) to obtain CTA data.
* Score the candidate pool against `state["user_message"]` and `state["understanding"]["topic"]` (Section 9).
* Apply each candidate's own `exclusion_conditions` and `do_not_trigger_examples` before it can ever be selected (Section 9.4).
* Resolve competition between categories and between same-category candidates via one documented, deterministic procedure (Section 9.5–9.6).
* Fall back to a category's general/library CTA, driven by `state["understanding"]["intent"]`, only when no candidate scores a literal phrase match at all (Section 9.7).
* Return exactly one CTA or none — never a list, never more than one (Section 9.8, FR-7).
* Pass `state["safety"]["safe_response"]` through unmodified, byte-for-byte, as `cta.response` (FR-2).
* Never raise out of its public entry point, for any input including an empty or unavailable loader result (Section 11).

### 3.2 Out of Scope — Non-Responsibilities

The CTA Node SHALL NOT, under any circumstance:

* Read any file under `data/cta/`, or any other Markdown file, directly. Every fact about a CTA SHALL come from a `CTARecord` returned by `cta_loader`.
* Perform RAG retrieval, or read `state["knowledge"]` at all.
* Generate, rewrite, summarize, append to, or otherwise alter `state["safety"]["safe_response"]`. The only string transformation it may apply to chatbot-facing text is none — `cta.response == state["safety"]["safe_response"]`, always.
* Perform any Safety, medical-boundary, or hallucination check — that is `safety_node`'s job, already done by the time this node runs.
* Call an LLM, an embeddings model, or any network service. Matching is pure, deterministic Python over in-memory `CTARecord` data (mirroring the loader's own FR-10).
* Cache CTA data itself. `cta_loader` already caches; re-caching in this node would create a second, potentially stale, copy of the same data.
* Manage conversation memory, session state, or any per-conversation state of any kind. Like every other node in this pipeline, it is a pure function of its declared inputs for the current turn.
* Return more than one CTA, or a ranked list of candidates, to its caller.

---

## 4. Pipeline Position & Inputs

### 4.1 Inputs, As They Actually Exist In `GraphState`

| Input | Source | Notes |
|---|---|---|
| User message | `state["user_message"]` | Raw string, unmodified since Understanding Node read it. |
| Intent | `state["understanding"]["intent"]` | One of the 8 `Literal` values already defined in `app/graph/state.py`'s `Understanding` TypedDict (Section 4.2). |
| Topic | `state["understanding"]["topic"]` | Free-text string, e.g. `"MNRI"`, `"ADHD"`, `"neuroplasticity"`. |
| Final chatbot response | `state["safety"]["safe_response"]` | The Safety Node's output — **not** `state["empathy"]["final_answer"]`. By the time this node runs, Safety is the authoritative final-answer field; reading Empathy's pre-Safety text would risk attaching a CTA to content Safety may have modified or escalated. |
| CTA data | `app.services.cta_loader.get_ctas_by_status("Active")` | Not a `GraphState` field — a direct call to the loader's public API (Section 12.1). |

### 4.2 Clarifying a Discrepancy: There Is No `category` Field on `Understanding`

The product brief that motivated this spec lists "Understanding Node output: intent, topic, category" as an input. Reading `app/graph/state.py`'s actual `Understanding` TypedDict shows it carries `intent`, `topic`, `search_query`, and `emotional_state` — there is no `category` field anywhere in the Understanding Node's contract, today or in any of its spec history (Phases 1–5).

"Category" in the CTA domain (`"Therapy"`, `"Condition"`, `"FAQ"`, …) is a property of a **`CTARecord`**, not of the user's turn. This spec resolves the discrepancy by treating category resolution as something the CTA Node *derives*, as a side effect of matching (Section 9.5) — never as a value it reads from upstream state. No change to `Understanding` or to any earlier phase is needed or proposed.

### 4.3 Why Safety's Output, Not Empathy's

`safety_node` (Phase 5) is the pipeline's last content gate: it can modify `final_answer` (`safety_status: "modified"`) or replace it entirely with a crisis/redirect template (`safety_status: "escalated"`). The CTA Node runs after it specifically so that a CTA is only ever attached to content that has already cleared every safety check — attaching a CTA to a pre-Safety answer would risk shipping a CTA alongside text Safety was about to rewrite or block.

---

## 5. Outputs

### 5.1 Internal — `GraphState["cta"]` (Rich, Audit-Capable)

Every other phase's `GraphState` entry carries full audit fields (timing, error, the upstream values it consumed) in addition to its "headline" result — `Safety` carries `validation_time_ms`, `error`, `original_final_answer`, etc. alongside `safe_response`. The CTA Node's internal output follows the same convention (full type in Section 10.1):

```json
{
    "cta_found": true,
    "cta_id": "therapies/mnri",
    "cta_url": "https://manascience.webflow.io/post/mnri",
    "cta_trigger": "Learn More About MNRI",
    "cta_category": "Therapy",
    "match_reason": "specific_match",
    "matched_phrase": "what is mnri",
    "response": "<state[\"safety\"][\"safe_response\"], verbatim>",
    "lookup_time_ms": 0.41,
    "error": null
}
```

or, when nothing matches:

```json
{
    "cta_found": false,
    "cta_id": null,
    "cta_url": null,
    "cta_trigger": null,
    "cta_category": null,
    "match_reason": "no_match",
    "matched_phrase": null,
    "response": "<state[\"safety\"][\"safe_response\"], verbatim>",
    "lookup_time_ms": 0.18,
    "error": null
}
```

### 5.2 External — The Minimal Pipeline Contract

The brief's required "Final Output" shape is a strict subset of Section 5.1, produced by `build_cta_response()` (Section 12.1) for any future consumer (a unified end-of-pipeline endpoint, a frontend payload) that wants exactly this and nothing more:

```json
{
    "response": "...",
    "cta_found": true,
    "cta": {
        "url": "https://manascience.webflow.io/post/mnri",
        "trigger": "Learn More About MNRI",
        "category": "Therapy"
    }
}
```

```json
{
    "response": "...",
    "cta_found": false,
    "cta": null
}
```

`cta.trigger` is `CTARecord.output_label` — the human-facing call-to-action label a UI renders as the clickable prompt (e.g. `"Learn More About MNRI"`, `"Explore the Therapy Library"`), not the internal matched search phrase. The matched phrase is audit-only and lives in the internal shape (`matched_phrase`, Section 5.1) precisely because a frontend has no use for it and Section 3.2 forbids this node from inventing user-facing text — `output_label` already exists verbatim in the source Markdown, the node only ever copies it through.

---

## 6. Functional Requirements

**FR-1: Loader-Only Data Access.** The CTA Node and its service layer SHALL obtain every fact about every CTA exclusively through `app.services.cta_loader`'s public functions. No file I/O, no `Path`/`open()` call against `data/cta/`, appears anywhere in `cta_service.py` or `cta_node.py`.

**FR-2: Response Immutability.** `cta.response` SHALL be identical, character-for-character, to `state["safety"]["safe_response"]` on every code path, including every error/fallback path (Section 11).

**FR-3: At Most One CTA.** The node's public entry points SHALL return either exactly one `CTARecord`-derived result or none. No function in the public interface (Section 12) returns a `list[CTARecord]` or a ranked candidate set as its result.

**FR-4: Active-Only Candidates.** Only `CTARecord`s with `status == "Active"` SHALL ever be eligible for selection. The CTA Node is the layer that decides "Active" is the operative status value — `cta_loader` deliberately does not hard-code this (loader spec Section 9.3) — via `get_ctas_by_status("Active")` (Section 12.1).

**FR-5: Exclusion Always Wins.** A `CTARecord` whose `exclusion_conditions` or `do_not_trigger_examples` matches the search text (Section 9.4) SHALL NOT be selected through any code path — neither direct phrase matching (Section 9.3) nor the intent-driven category fallback (Section 9.7) — regardless of how strongly its own `trigger_examples`/`aliases` also match.

**FR-6: Deterministic, Order-Stable Resolution.** Given an unchanged CTA corpus and identical inputs, two calls to `find_cta()` SHALL return the same winner. Every tie-break (category vs. category, candidate vs. candidate) resolves via a documented total order (Sections 9.5–9.6), never via set/dict iteration order or randomness.

**FR-7: General Fallback Is a Fallback, Not a Default.** A category's general/library CTA (Section 9.2) SHALL be selected only when (a) it is itself the highest-scoring direct phrase match in its category, or (b) literal phrase matching across the *entire* corpus produced zero candidates and `state["understanding"]["intent"]` carries an affinity to that category (Section 9.7). It SHALL NOT be returned merely because no *specific* CTA in its category matched while some other category's CTA did.

**FR-8: Never Raise.** `cta_node()` SHALL NOT propagate any exception out of its public entry point, for any input — an empty or single-CTA-only loader result, a malformed `understanding` dict, an empty `user_message`, or an unexpected exception anywhere inside `cta_service`. Section 11 defines the fallback behavior.

**FR-9: No Hidden LLM/Network Dependency.** Neither `cta_service.py` nor `cta_node.py` SHALL import `langchain`, `langgraph` (other than `langgraph.graph` inside `build_cta_graph()`, exactly as every other node does it), any chat-model client, or any embeddings client.

**FR-10: Statelessness.** The node SHALL hold no per-conversation or per-session state. Its only "memory" is whatever `cta_loader` already cached (a dependency, not a CTA-Node-owned cache — Section 3.2 forbids the latter).

---

## 7. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Reliability** | `cta_node()` MUST always return `{"cta": {...}}` matching `CTAOutput`'s schema (Section 10.1), for any state, including a loader that returns zero Active CTAs. |
| **Determinism** | Identical `(user_message, understanding, safe_response, loaded CTA corpus)` MUST produce a byte-identical result on every call — no model-version dependency, no randomness (FR-6). |
| **Latency** | A single `find_cta()` call against the current 15-record corpus MUST complete in well under 5ms — it is a handful of substring/set operations over an in-memory list already cached by the loader, with no I/O and no network call (Section 16). |
| **Testability** | Fully unit-testable with zero mocking infrastructure — synthetic `CTARecord` instances (built directly, or via `cta_loader.load_cta_data(base_dir=tmp_path)`) and plain `dict` state, no fake LLM client needed anywhere (Section 17). |
| **Observability** | Every call logs exactly one summary line (Section 14); every tie-break and every fallback path logs at a level a developer can filter on. |
| **Isolation** | `cta_service.py`'s only inbound dependencies are `app.services.cta_loader` and the standard library — it MUST NOT import `app/nodes/`, `app/rag/`, or any LLM-bearing `services/*_service.py` module, matching the loader's own isolation requirement. |
| **Forward-compatibility** | Adding a 16th CTA file, or a new `Category` value never seen before, MUST require zero code changes to load and become matchable (Section 9.5's category resolution degrades gracefully — Section 11.2). |

---

## 8. Decision Flow

```
state["safety"]["safe_response"]  +  state["user_message"]  +  state["understanding"]
                          |
                          v
              get_ctas_by_status("Active")     <- cta_loader, the only data source
                          |
                          v
        For every Active CTARecord: is it excluded?
        (exclusion_conditions / do_not_trigger_examples
         match the user_message + topic?)
                          |
              -----------------------
              |                     |
          excluded              not excluded
              |                     |
        (drop from pool)      score against
                               aliases / trigger_examples
                               / related_topics
                          |
                          v
              Did ANY candidate score > 0?
                          |
            --------------------------------
            |                              |
           yes                             no
            |                              |
   Resolve winning category        intent has an entry in
   (Section 9.5: highest score,    INTENT_CATEGORY_AFFINITY?
   intent-affinity as tie-break)            |
            |                      -------------------
            v                      |                 |
   Within that category,          yes                no
   specific CTA beats            |                 |
   the Library/general CTA   category's general/   cta_found = False
   on score (Section 9.6)    library CTA, if not    match_reason = "no_match"
            |                excluded -> match_reason
            v                = "category_fallback"  |
   cta_found = True               |                 |
   match_reason =                 v                 |
   "specific_match"          cta_found = True        |
            |                match_reason =          |
            |                "category_fallback"     |
            |                or False if excluded /  |
            |                no fallback CTA exists  |
            -------------------------|-----------------
                                      v
                    Build {cta_found, cta_id, cta_url, cta_trigger,
                            cta_category, match_reason, matched_phrase,
                            response=safe_response, lookup_time_ms, error}
                                      |
                                      v
                              CTAOutput.model_validate(...)
                                      |
                                      v
                          return {"cta": {...}}  -> Final Output
```

---

## 9. Matching & Lookup Rules

### 9.1 The Corpus's Actual Category Taxonomy (Grounding For Everything Below)

Read directly from the 15 files under `data/cta/` today:

| `category_dir` | `category` | `cta_type` values present | Has a `Library`-typed CTA? |
|---|---|---|---|
| `about/` | `About` | `Information Page` | No — single CTA |
| `community/` | `Community` | `Information Page` | No — single CTA |
| `conditions/` | `Condition` | `Individual Condition` (×3), `Library` (×1) | **Yes** — `conditions/general.md` |
| `courses/` | `Courses` | `Information Page` | No — single CTA |
| `faq/` | `FAQ` | `Information Page` | No — single CTA |
| `neuroplasticity/` | `Neuroplasticity` | `Information Page` | No — single CTA |
| `privacy/` | `Privacy` | `Information Page` | No — single CTA |
| `subscription/` | `Subscription` | `Information Page` | No — single CTA |
| `therapies/` | `Therapy` | `Individual Therapy` (×2), `Specific Therapy` (×1, MNRI), `Library` (×1) | **Yes** — `therapies/general.md` |

Only `Condition` and `Therapy` have more than one CTA today, which is exactly where "specific vs. general" competition (Section 9.6) and the brief's explicit "Therapy Library" fallback example are real, observable behaviors. Every other category is a single `Information Page` CTA — for those, "the category matched" and "the CTA matched" are the same event; there is no specific/general split to resolve.

### 9.2 Defining "The General CTA For a Category"

```python
def _general_cta_for_category(
    category: str, candidates: list[CTARecord]
) -> Optional[CTARecord]:
    """The category's fallback CTA: its `Library`-typed record if one exists,
    else its sole CTA if the category has exactly one. A category with two-plus
    CTAs and no `Library` type has no defined fallback -- this returns None
    rather than guessing, consistent with Section 3.2's never-guess posture."""
    in_category = [c for c in candidates if c.category == category]
    libraries = [c for c in in_category if c.cta_type == "Library"]
    if libraries:
        return libraries[0]
    if len(in_category) == 1:
        return in_category[0]
    return None
```

This single definition covers both shapes in Section 9.1 without a special case: `Therapy`/`Condition` resolve via their `Library` record; every single-CTA category resolves via the `len == 1` branch.

### 9.3 Normalization and Phrase Matching

```python
import re

_WORD = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _phrase_in_text(phrase_norm: str, text_norm: str, text_tokens: set[str]) -> bool:
    """A normalized phrase matches normalized text if it appears as a substring
    in either direction (handles both a full trigger-example question appearing
    in a longer user message, and a short user message like "mnri" matching a
    short alias), or if every one of the phrase's words is present somewhere in
    the text's token set (handles word-order variation, e.g. a phrase "primitive
    reflexes" against "tell me about primitive reflexes please"). No fuzzy
    matching, no embeddings, no edit distance -- exact normalized containment
    or exact token-subset only, mirroring the loader's own "exact-match, never-
    guess" philosophy (cta_loader spec FR-5)."""
    if not phrase_norm:
        return False
    if phrase_norm in text_norm or text_norm in phrase_norm:
        return True
    phrase_tokens = set(phrase_norm.split())
    return bool(phrase_tokens) and phrase_tokens.issubset(text_tokens)
```

The text searched is always `user_message + " " + understanding["topic"]`, normalized once per call (Section 9.8) — `topic` is included because it is frequently the single most concentrated signal for a follow-up turn (e.g. topic `"MNRI"` matching alias `"MNRI"` even when the literal message is "tell me more about it").

### 9.4 Exclusion Check (Runs Before Any Scoring)

```python
def _is_excluded(record: CTARecord, text_norm: str, text_tokens: set[str]) -> bool:
    for phrase in record.exclusion_conditions + record.do_not_trigger_examples:
        if _phrase_in_text(_normalize(phrase), text_norm, text_tokens):
            return True
    return False
```

A record failing this check is removed from the candidate pool entirely (FR-5) — it cannot be selected by direct scoring (Section 9.3) *or* by the intent-driven fallback (Section 9.7); both paths call this same function.

### 9.5 Scoring a Single Candidate

```python
from dataclasses import dataclass
from typing import Literal, Optional

_ALIAS_WEIGHT = 3
_TRIGGER_WEIGHT = 2
_TOPIC_WEIGHT = 1


@dataclass
class _Hit:
    score: int
    tier: Literal["alias", "trigger", "topic"]
    matched_phrase: str


def _best_hit(
    phrases: list[str], tier: str, weight: int, text_norm: str, text_tokens: set[str]
) -> Optional[_Hit]:
    for phrase in phrases:
        if _phrase_in_text(_normalize(phrase), text_norm, text_tokens):
            return _Hit(score=weight, tier=tier, matched_phrase=phrase)
    return None


def _score_candidate(
    record: CTARecord, text_norm: str, text_tokens: set[str]
) -> Optional[_Hit]:
    """None means "not a candidate at all" -- either excluded, or it matched
    nothing. Aliases outrank trigger examples outrank related topics: aliases
    are short canonical names least likely to false-positive, trigger examples
    are full example questions, related topics are single generic words (e.g.
    "Development", "Learning") that are deliberately the weakest signal so they
    can never alone promote a specific CTA over a more literally-matched one."""
    if _is_excluded(record, text_norm, text_tokens):
        return None
    return (
        _best_hit(record.aliases, "alias", _ALIAS_WEIGHT, text_norm, text_tokens)
        or _best_hit(record.trigger_examples, "trigger", _TRIGGER_WEIGHT, text_norm, text_tokens)
        or _best_hit(record.related_topics, "topic", _TOPIC_WEIGHT, text_norm, text_tokens)
    )
```

### 9.6 Resolving Category Competition and Specific-vs-General Competition

```python
from collections import defaultdict

INTENT_CATEGORY_AFFINITY: dict[str, str] = {
    "therapy_information": "Therapy",
    "course_information": "Courses",
    "personal_concern": "Condition",
    "emotional_support": "Condition",
}
# concept_explanation, research_information, website_information, and
# general_chat carry no affinity entry -- they are resolved purely by
# phrase-match score (Section 9.5), never by a forced category guess.


def _resolve_winner(
    scored: list[tuple[CTARecord, _Hit]], intent: str
) -> tuple[CTARecord, _Hit]:
    by_category: dict[str, list[tuple[CTARecord, _Hit]]] = defaultdict(list)
    for record, hit in scored:
        by_category[record.category].append((record, hit))

    if len(by_category) > 1:
        affinity_category = INTENT_CATEGORY_AFFINITY.get(intent)

        def category_key(category: str) -> tuple[int, str]:
            best = max(hit.score for _, hit in by_category[category])
            bonus = 1 if category == affinity_category else 0
            return (best + bonus, category)

        ranked = sorted(by_category, key=category_key, reverse=True)
        if category_key(ranked[0]) == category_key(ranked[1]):
            logger.warning(
                "cta_service: category tie broken deterministically intent=%s categories=%s",
                intent, ranked,
            )
        category_items = by_category[ranked[0]]
    else:
        category_items = next(iter(by_category.values()))

    specific = [(r, h) for r, h in category_items if r.cta_type != "Library"]
    pool = specific or category_items
    pool.sort(key=lambda rh: (-rh[1].score, rh[0].cta_id))
    if len(pool) > 1 and pool[0][1].score == pool[1][1].score:
        logger.warning(
            "cta_service: multiple CTAs matched with equal score, tie broken by cta_id: %s",
            [r.cta_id for r, _ in pool],
        )
    return pool[0]
```

Two competitions, one mechanism each, exactly per the brief's "priority rules if multiple CTAs match":

1. **Cross-category:** the category with the highest best-candidate score wins; `INTENT_CATEGORY_AFFINITY` contributes a `+1` tie-break bonus, never an override of a clearly higher score. A genuine tie is broken by category name (deterministic, logged).
2. **Within-category:** any non-`Library` candidate beats every `Library` candidate outright (FR-7 — general never beats specific). Remaining ties are broken by score, then by `cta_id` sort order (deterministic, logged) — `cta_id` is guaranteed unique by the loader (Section 10.3 of the loader spec), so this is always a total order.

### 9.7 The Intent-Driven Category Fallback (Genuinely a Fallback)

```python
def find_cta(
    user_message: str, understanding: dict, candidates: list[CTARecord]
) -> Optional["CTAMatch"]:
    search_text = f"{user_message} {understanding.get('topic', '')}"
    text_norm = _normalize(search_text)
    text_tokens = set(text_norm.split())

    scored = [
        (record, hit)
        for record in candidates
        if (hit := _score_candidate(record, text_norm, text_tokens)) is not None
    ]
    if scored:
        winner, hit = _resolve_winner(scored, understanding.get("intent", ""))
        return CTAMatch(cta=winner, match_reason="specific_match", matched_phrase=hit.matched_phrase)

    fallback_category = INTENT_CATEGORY_AFFINITY.get(understanding.get("intent", ""))
    if fallback_category:
        fallback_cta = _general_cta_for_category(fallback_category, candidates)
        if fallback_cta is not None and not _is_excluded(fallback_cta, text_norm, text_tokens):
            return CTAMatch(cta=fallback_cta, match_reason="category_fallback", matched_phrase=None)

    return None
```

This fallback only ever runs when `scored` is empty — i.e. when *zero* candidates anywhere in the entire Active corpus matched any alias, trigger example, or related topic. This is what makes it a true fallback (FR-7) rather than a default: a message like `"What therapies are available?"` never reaches this branch at all, because it is one of `therapies/general.md`'s own `trigger_examples` and scores directly in Section 9.5. The branch exists for messages whose phrasing the corpus's authors didn't anticipate, where `intent == "therapy_information"` is still a strong enough signal to show the Therapy Library rather than nothing — precisely the behavior `therapies/mnri.md`'s and `conditions/general.md`'s own `Fallback Rule:` prose describes in natural language (Section 9.9 explains why that prose is not parsed directly).

### 9.8 Why `related_topics` Can Never, By Itself, Win Cross-Category

Because `_TOPIC_WEIGHT = 1` is strictly lower than both other tiers, and Section 9.6's cross-category resolution compares *best* score per category, a category whose only hit is a generic `related_topics` word (e.g. `"Development"`, shared across `conditions/general.md` and plausibly other files) can never outrank a category with even a single `trigger_examples` or `aliases` hit. This is a deliberate design choice: `related_topics` lists are the least specific field in the corpus by construction (Section 6.2 of the loader spec — single words, not phrases), so they are kept as the weakest possible tie-break signal rather than a primary one.

### 9.9 Why `match_rule_raw` and `fallback_rule` Are Never Parsed at Runtime

`CTARecord.match_rule_raw` (e.g. `"Category = Therapy\nSpecific Therapy = MNRI"`) and `CTARecord.fallback_rule` (free natural-language prose, per the loader spec's Section 8.7 catalog of authoring variance) are **not** machine-parsed by this node. Two reasons:

1. They are free-form prose written for a human reviewer, not a DSL — `mnri.md`'s `Fallback Rule:` body alternates prose and bullets across three paragraphs; building a parser for that text would mean re-deriving, in code, exactly the same decision this spec already makes explicitly and auditably in Sections 9.5–9.7.
2. The loader spec itself anticipates this: Section 8.7 keeps these fields as raw strings specifically so "a future LLM-based matcher" *could* read them as instructions, while explicitly not committing this node to being that LLM-based matcher. This spec is the deterministic alternative — Section 3.2 rules out any LLM call, so `match_rule_raw`/`fallback_rule` are carried through to nowhere except potential future human-facing debugging/display; the *behavior* they describe is what Sections 9.1–9.7 implement directly against structured fields (`category`, `cta_type`, `aliases`, `trigger_examples`, `exclusion_conditions`).

---

## 10. Data Model

### 10.1 `CTAMatch` (Internal, `cta_service.py`)

```python
@dataclass
class CTAMatch:
    cta: CTARecord
    match_reason: Literal["specific_match", "category_fallback"]
    matched_phrase: Optional[str]
```

### 10.2 `CTA` (New `GraphState` TypedDict, `app/graph/state.py`)

```python
class CTA(TypedDict):
    cta_found: bool
    cta_id: Optional[str]
    cta_url: Optional[str]
    cta_trigger: Optional[str]
    cta_category: Optional[str]
    match_reason: Literal["specific_match", "category_fallback", "no_match"]
    matched_phrase: Optional[str]
    response: str
    lookup_time_ms: float
    error: Optional[str]
```

`GraphState` gains one field, appended after `safety` (the established convention — each phase's TypedDict is appended in pipeline order):

```python
class GraphState(TypedDict):
    user_message: str
    chat_history: list[ChatTurn]
    understanding: Optional[Understanding]
    knowledge: Optional[Knowledge]
    response: Optional[Response]
    empathy: Optional[Empathy]
    safety: Optional[Safety]
    cta: Optional[CTA]
```

### 10.3 `CTAOutput` (New Pydantic Model, `app/nodes/cta_node.py`)

```python
class CTAOutput(BaseModel):
    cta_found: bool
    cta_id: Optional[str]
    cta_url: Optional[str]
    cta_trigger: Optional[str]
    cta_category: Optional[str]
    match_reason: Literal["specific_match", "category_fallback", "no_match"]
    matched_phrase: Optional[str]
    response: str
    lookup_time_ms: float
    error: Optional[str]

    @model_validator(mode="after")
    def _validate_found_consistency(self) -> "CTAOutput":
        if self.cta_found:
            if not (self.cta_id and self.cta_url and self.cta_trigger and self.cta_category):
                raise ValueError("cta_found=True requires cta_id, cta_url, cta_trigger, and cta_category")
            if self.match_reason == "no_match":
                raise ValueError("cta_found=True is inconsistent with match_reason=='no_match'")
        else:
            if self.cta_id or self.cta_url or self.cta_trigger or self.cta_category or self.matched_phrase:
                raise ValueError("cta_found=False requires every CTA field to be null")
            if self.match_reason != "no_match":
                raise ValueError("cta_found=False requires match_reason=='no_match'")
        return self
```

This is the same belt-and-suspenders pattern as `SafetyOutput`/`EmpathyOutput`'s `model_validator`s (`app/nodes/safety_node.py`, `app/nodes/empathy_node.py`): by the time `CTAOutput.model_validate(...)` runs, `cta_service.process()` already believes the result is internally consistent, but this is the last gate before it enters `GraphState`. Note this validator deliberately does **not** re-check `response` for emptiness — Section 11.4 explains why.

### 10.4 `CTAResponse` (New Pydantic Model, `app/models.py`)

```python
class CTAResponse(BaseModel):
    cta_found: bool
    cta_id: str | None
    cta_url: str | None
    cta_trigger: str | None
    cta_category: str | None
    match_reason: str
    matched_phrase: str | None
    response: str
    lookup_time_ms: float
    error: str | None
```

Mirrors `SafetyResponse`/`HumanizeResponse`'s existing convention of a FastAPI response model with the exact same field set as the node's TypedDict, for the isolated `/cta` debug endpoint (Section 13.3).

---

## 11. Error Handling

### 11.1 Guiding Principle

Identical to every prior phase's stance (`safety_node`'s `_safe_fallback_result`, the loader's FR-3): a problem inside CTA matching is a reason to return "no CTA," never a reason to break the pipeline or lose the chatbot's already-safety-checked answer.

### 11.2 Issue Catalog

| Scenario | Where it's handled | Effect |
|---|---|---|
| `get_ctas_by_status("Active")` returns `[]` | `cta_service.process()` | Logged `WARNING`; treated as "no candidates," proceeds straight to `find_cta`'s intent-fallback branch (Section 9.7) since `scored` is trivially empty. |
| A `CTARecord.category` value never seen before (corpus grows) | `_resolve_winner` (Section 9.6) | No special handling needed — it is just another key in `by_category`; competes on score like any other category. Not an error. |
| A `CTARecord.cta_type` value other than `"Library"`/known specific types | `_general_cta_for_category` (Section 9.2) | Treated as "specific" (the `!= "Library"` check is the only discriminator) — never crashes, never misclassified as a fallback CTA. |
| `understanding["intent"]` is a value with no entry in `INTENT_CATEGORY_AFFINITY` | `find_cta` (Section 9.7) | `.get(intent)` returns `None`; the fallback branch is skipped cleanly — falls through to "no match." Not an error. |
| `understanding["topic"]` is `""` or missing | `find_cta` (Section 9.7) | `.get("topic", "")` defaults to empty string; matching proceeds on `user_message` alone. Not an error. |
| Two or more CTAs tie on score within the winning category | `_resolve_winner` (Section 9.6) | Logged `WARNING`; resolved deterministically by `cta_id` sort. Not an error — a normal, auditable outcome. |
| Two or more categories tie on best score | `_resolve_winner` (Section 9.6) | Logged `WARNING`; resolved deterministically by category name. Not an error. |
| Any unexpected exception anywhere inside `cta_service.process()` (defensive catch-all) | `cta_node()`'s `try/except` | Logged `ERROR`; `_safe_fallback_result()` (Section 11.3) is returned — bypasses `CTAOutput` validation entirely, cannot itself raise. |

### 11.3 The Fallback Result

```python
def _safe_fallback_result(safe_response: str, start: float) -> dict:
    """Hand-built result that is correct by construction -- bypasses CTAOutput
    validation entirely so this path cannot itself raise. Always cta_found=False:
    an internal error is not evidence a CTA exists, so the conservative outcome
    is no CTA, exactly mirroring safety_node/empathy_node's posture toward their
    own internal failures."""
    return {
        "cta_found": False,
        "cta_id": None,
        "cta_url": None,
        "cta_trigger": None,
        "cta_category": None,
        "match_reason": "no_match",
        "matched_phrase": None,
        "response": safe_response,
        "lookup_time_ms": (time.monotonic() - start) * 1000,
        "error": "cta_lookup_failure",
    }
```

### 11.4 Why `response` Is Never Validated For Emptiness

`safety_node`'s own `SafetyOutput._validate_safe_response_quality` already rejects an empty `safe_response` before it can ever reach `GraphState["safety"]`. By the time `cta_node` runs, a non-empty `safe_response` is an upstream-enforced invariant, not something this node needs to re-guard. More importantly, Section 3.2 forbids this node from ever substituting or rewriting response content — if `safe_response` were ever empty despite that invariant, the correct behavior is to pass the empty string through unchanged (not to fabricate replacement text), so `CTAOutput` intentionally has no rule against it. This is verified directly by `test_empty_safe_response_passed_through_unchanged` (Section 17.1).

---

## 12. Public Interface

### 12.1 `app/services/cta_service.py`

```python
INTENT_CATEGORY_AFFINITY: dict[str, str]   # Section 9.6, module-level constant


def find_cta(
    user_message: str, understanding: dict, candidates: list[CTARecord]
) -> Optional[CTAMatch]:
    """Pure, deterministic, LLM-free matching against an already-fetched
    candidate pool (Section 9.7). Never raises; no match is None, not an
    exception."""


def build_cta_response(safe_response: str, match: Optional[CTAMatch]) -> dict:
    """The single, code-only place the minimal external CTA contract
    ({response, cta_found, cta}) is built (Section 5.2), for any future
    consumer that wants the trimmed shape rather than the full CTAOutput.
    Never mutates safe_response."""


def process(user_message: str, understanding: dict, safe_response: str) -> dict:
    """Top-level orchestration cta_node calls: pulls the Active candidate pool
    from cta_loader.get_ctas_by_status, calls find_cta, and returns a dict
    shaped exactly like CTAOutput minus lookup_time_ms/error (the node layer
    adds those after timing the call) -- mirroring safety_service.validate_response
    / empathy_service.humanize_response's identical division of labor."""
```

No `search(query: str)`, `rank_ctas(...)`, or any function accepting a free-text query beyond `user_message`/`understanding` exists in this module — and no function returns a `list[CTARecord]` as its primary result (FR-3).

### 12.2 `app/nodes/cta_node.py`

```python
class CTAOutput(BaseModel): ...   # Section 10.3


def cta_node(state: GraphState) -> dict:
    """LangGraph node: decide whether state["safety"]["safe_response"] should
    carry a CTA, using only state["user_message"], state["understanding"], and
    app.services.cta_loader.

    Pure function of (state["user_message"], state["understanding"],
    state["safety"]["safe_response"]) -> partial state update; does not mutate
    any input, and never reads state["knowledge"] or state["empathy"]. Returns
    {"cta": {...}}.
    """


def build_cta_graph():
    """Compile the full six-node StateGraph (understanding -> knowledge ->
    response -> empathy -> safety -> cta) -- the complete Manasi AI pipeline."""
```

`cta_node` takes no `llm` parameter — unlike `empathy_node`/`safety_node`/`response_node`, it never needs one (FR-9), so its signature is deliberately narrower than theirs rather than carrying an unused `Optional[Any] = None`.

---

## 13. Integration

### 13.1 `app/graph/state.py` (edited)

Add the `CTA` TypedDict (Section 10.2) after `Safety`, and add `cta: Optional[CTA]` as `GraphState`'s final field.

### 13.2 `app/nodes/cta_node.py` (new)

Section 12.2 in full, following `safety_node.py`'s exact file shape: imports, `logger = logging.getLogger("app.nodes.cta_node")`, `CTAOutput`, `cta_node()`, `_safe_fallback_result()`, `build_cta_graph()`.

### 13.3 `app/main.py` (edited)

Add a `/cta` debug endpoint mirroring `/safety`'s shape exactly, plus wire `cta_node` into a new full-pipeline graph:

```python
from app.models import CTAResponse
from app.nodes.cta_node import build_cta_graph

cta_graph = None

# inside lifespan():
cta_graph = build_cta_graph()

@app.post("/cta", response_model=CTAResponse)
def cta_endpoint(request: ChatRequest):
    if cta_graph is None:
        raise HTTPException(status_code=503, detail="CTA node is still starting up")
    history = session_histories.get(request.session_id, [])
    result = cta_graph.invoke(
        {
            "user_message": request.message,
            "chat_history": _history_to_chat_turns(history),
            "understanding": None,
            "knowledge": None,
            "response": None,
            "empathy": None,
            "safety": None,
            "cta": None,
        }
    )
    return CTAResponse(**result["cta"])
```

`build_safety_graph()` (`app/nodes/safety_node.py`) is left untouched — it remains the five-node graph for isolated Phase 5 testing/deployment, exactly as `build_empathy_graph()` was left untouched when Phase 5 shipped. `build_cta_graph()` is the new six-node, full-pipeline graph.

**Explicitly out of scope for this change set:** a unified end-of-pipeline endpoint that calls `build_cta_response()` to produce the Section 5.2 minimal contract. That endpoint does not exist yet anywhere in `app/main.py` (every current endpoint returns its own phase's rich `*Response` model) and inventing one is a product/API decision beyond "implement the CTA Node," not a CTA-matching concern. `build_cta_response()` (Section 12.1) is implemented and unit-tested now so that endpoint has zero CTA-logic work left to do whenever it is built.

### 13.4 `app/models.py` (edited)

Add `CTAResponse` (Section 10.4).

### 13.5 No `app/config.py` Changes

The CTA Node introduces no new tunable settings — `cta_data_dir` already exists (added by the loader spec) and is owned entirely by `cta_loader`. The scoring weights (Section 9.5) and `INTENT_CATEGORY_AFFINITY` (Section 9.6) are module-level constants in `cta_service.py`, not environment-configurable, consistent with this being a small, fully-specified deterministic algorithm rather than a tunable model — promoting them to `Settings` fields is deferred (Section 19) until real usage shows a need.

---

## 14. Logging

* Logger name: `app.services.cta_service` (matching logic) and `app.nodes.cta_node` (node wrapper) — the same two-logger split every other phase uses.
* **INFO** — exactly one summary line per `cta_node()` call:
  ```python
  logger.info(
      "cta_node ok: cta_found=%s cta_id=%s match_reason=%s error=%s elapsed_ms=%.2f",
      validated["cta_found"], validated["cta_id"], validated["match_reason"],
      validated["error"], validated["lookup_time_ms"],
  )
  ```
  Both the "CTA Found" and "CTA Not Found" outcomes log at `INFO` — "no CTA" is the expected, common-case outcome for many turns, not a warning-worthy event (mirrors the brief's "Return no CTA if none matches" being a normal responsibility, not an error path).
* **DEBUG** — every individual candidate's score, inside `_score_candidate`/`_resolve_winner`, for a developer debugging why a specific message did or didn't match a specific CTA. Not on by default; too high-volume for `INFO`.
* **WARNING** — `cta_service`, at the point each occurs:
  * `"cta_service: zero active CTAs available from loader"` (Section 11.2's first row).
  * `"cta_service: category tie broken deterministically intent=%s categories=%s"` (Section 9.6).
  * `"cta_service: multiple CTAs matched with equal score, tie broken by cta_id: %s"` (Section 9.6).
* **ERROR** — `cta_node`, exactly once, on the defensive catch-all:
  ```python
  logger.error("cta_node_failure: error=%s", exc)
  ```

---

## 15. File Structure

```
app/
    graph/
        state.py                   (edited -- add CTA TypedDict, GraphState.cta)
    models.py                       (edited -- add CTAResponse)
    main.py                         (edited -- add /cta endpoint, cta_graph, build_cta_graph wiring)
    services/
        cta_service.py              (new)
    nodes/
        cta_node.py                 (new)

tests/
    test_cta_node.py                 (new)
```

Untouched: `app/services/cta_loader.py`, `app/config.py`, every file under `data/cta/`, every earlier-phase node/service file (Section 3.2 — this node only ever reads their output, never modifies them).

---

## 16. Performance Considerations

| Metric | Target | Rationale |
|---|---|---|
| `find_cta()` against the current 15-record corpus | < 2ms | Worst case is ~15 records × (≤2 exclusion phrases each on average + ≤3 tiers of ≤20 phrases each) substring/token-subset checks over a short, already-normalized string — no I/O, no network, no LLM (FR-9). |
| `cta_node()` end-to-end (incl. `get_ctas_by_status` call) | < 5ms | `get_ctas_by_status` is an O(n) scan over the loader's already-cached list (loader spec Section 15) — adds negligible overhead on top of `find_cta()`. |
| Projected corpus (≤ 500 CTAs) | < 50ms | Linear in candidate count and average phrase-list length; no per-candidate network or LLM call means this scales the same way the loader's own cold-scan does (loader spec Section 15). |
| Memory footprint | O(1) beyond the loader's own cache | `cta_service` holds no CTA data of its own (FR-1, Section 3.2's no-caching rule) — every call re-reads the loader's existing in-memory list. |

---

## 17. Unit Testing Requirements

`tests/test_cta_node.py`, using `pytest`, following this codebase's established style (`test_safety_node.py`/`test_empathy_node.py`: plain functions, a `make_understanding(...)`/`make_safety(...)`-style state-builder helper per fixture, no mocking framework beyond monkeypatching `cta_loader.get_ctas_by_status` where a controlled candidate set is needed).

### 17.1 Required Test Cases

| Test | Asserts |
|---|---|
| `test_specific_therapy_match_mnri` | `user_message="What is MNRI?"`, intent `"therapy_information"`, against the real or a synthetic MNRI+Therapy-Library pair → `cta_found=True`, `cta_id="therapies/mnri"`, `match_reason="specific_match"`. |
| `test_specific_condition_match_adhd` | `user_message="What is ADHD?"`, intent `"personal_concern"`, against a synthetic ADHD+Condition-Library pair → resolves to the ADHD CTA, not the Condition Library. |
| `test_general_therapy_library_direct_match` | `user_message="What therapies are available?"` (one of `therapies/general.md`'s own trigger examples) → matches the Library CTA directly, `match_reason="specific_match"` (Section 9.7 — this is *not* the fallback path; it is a direct hit on the Library record's own `trigger_examples`). |
| `test_intent_driven_category_fallback_when_nothing_matches` | `user_message="hmm, not sure what to ask"` (matches nothing in any `trigger_examples`/`aliases`/`related_topics`), intent `"therapy_information"` → `cta_found=True`, the Therapy Library CTA, `match_reason="category_fallback"`, `matched_phrase=None`. |
| `test_no_match_when_nothing_scores_and_no_intent_affinity` | Same unmatched message, intent `"general_chat"` (no affinity entry) → `cta_found=False`, `match_reason="no_match"`. |
| `test_no_match_returns_none_not_empty_list` | Any no-match scenario → `find_cta()` returns `None`, never `[]` or any list type. |
| `test_exclusion_blocks_an_otherwise_matching_cta` | A message containing one of a CTA's `do_not_trigger_examples` phrases verbatim, with no other CTA also scoring → `cta_found=False`, confirming FR-5 (exclusion isn't merely deprioritized, it is removed). |
| `test_exclusion_also_blocks_the_category_fallback_path` | A message that scores nothing directly, but happens to literally contain a phrase from the *fallback category's own* `do_not_trigger_examples` → fallback CTA is not returned; `cta_found=False`. |
| `test_specific_beats_general_in_same_category` | A message that scores against both `therapies/mnri.md`'s `aliases` and `therapies/general.md`'s `trigger_examples` in the same call → MNRI wins (FR-7: non-`Library` beats `Library` regardless of relative score). |
| `test_alias_outranks_trigger_example_tier` | Two synthetic same-category, non-Library CTAs, where CTA A matches only via a `related_topics` hit and CTA B matches via an `aliases` hit → B wins. |
| `test_cross_category_tie_broken_by_intent_affinity` | Two synthetic CTAs in different categories with equal raw score, intent affinity pointing at one of the two categories → the affinity category's CTA wins; a `WARNING` is logged. |
| `test_cross_category_genuine_tie_logged_and_deterministic` | Equal score, no intent affinity for either category → resolves to the alphabetically-earlier category every time across repeated calls; `WARNING` logged exactly once per call. |
| `test_duplicate_same_score_candidates_tie_broken_by_cta_id` | Two synthetic CTAs in the same category, same `cta_type` tier, both matching the same phrase with equal score → the lower-sorting `cta_id` wins deterministically across repeated calls; `WARNING` logged; exactly one CTA returned, never both. |
| `test_empty_active_ctas_returns_no_match` | `get_ctas_by_status("Active")` monkeypatched to return `[]` → `process()` returns `cta_found=False` without raising; `WARNING` logged ("zero active CTAs"). |
| `test_unexpected_service_exception_falls_back_safely` | `cta_service.process` monkeypatched to raise → `cta_node()` does not propagate; returns `_safe_fallback_result` with `error="cta_lookup_failure"`, `cta_found=False`, `response` unchanged. |
| `test_empty_safe_response_passed_through_unchanged` | `state["safety"]["safe_response"] = ""` → `cta_node()` does not raise; `result["cta"]["response"] == ""` on every code path (match found, no match, and forced-exception fallback) — proves the node never substitutes or fabricates response content (Section 11.4). |
| `test_response_is_never_modified` | A non-trivial `safe_response` string, with and without a CTA match → `result["cta"]["response"]` is exactly `==` the original string object's content in both cases (FR-2). |
| `test_topic_alone_can_trigger_a_match` | `user_message="tell me more about it"` (matches nothing alone), `understanding["topic"]="MNRI"` → matches `therapies/mnri.md` via its `aliases` list, proving topic is included in the search text (Section 9.3). |
| `test_missing_topic_key_does_not_raise` | `understanding` dict with no `"topic"` key at all → `find_cta` does not raise (`.get("topic", "")` default), resolves on `user_message` alone. |
| `test_build_cta_response_minimal_shape_on_match` | `build_cta_response(safe_response, match)` for a found match → returns exactly `{"response", "cta_found": True, "cta": {"url", "trigger", "category"}}`, no extra keys, `cta["trigger"] == match.cta.output_label`. |
| `test_build_cta_response_minimal_shape_on_no_match` | `build_cta_response(safe_response, None)` → exactly `{"response", "cta_found": False, "cta": None}`. |
| `test_performance_under_corpus_growth` | A synthetic 200-record candidate list (covering a spread of categories/tiers) → `find_cta()` completes in well under the Section 16 target, asserted via a wall-clock bound generous enough not to flake in CI. |
| `test_real_corpus_smoke_no_crash_no_unexpected_match` | Against the real `data/cta/` corpus (via `cta_loader.get_ctas_by_status("Active")`, no monkeypatching) with a battery of representative messages (a clear MNRI question, a clear ADHD question, a generic greeting, an empty string) → no exception, and each clear case resolves to the expected `cta_id`. |

### 17.2 Test Categories Explicitly Requested, Cross-Referenced

| Requested category | Covered by |
|---|---|
| Matching CTA | `test_specific_therapy_match_mnri`, `test_specific_condition_match_adhd`, `test_topic_alone_can_trigger_a_match` |
| No CTA | `test_no_match_when_nothing_scores_and_no_intent_affinity`, `test_no_match_returns_none_not_empty_list` |
| General CTA | `test_general_therapy_library_direct_match`, `test_intent_driven_category_fallback_when_nothing_matches` |
| Therapy CTA | `test_specific_therapy_match_mnri`, `test_specific_beats_general_in_same_category` |
| Condition CTA | `test_specific_condition_match_adhd` |
| Invalid loader | `test_empty_active_ctas_returns_no_match`, `test_unexpected_service_exception_falls_back_safely` |
| Duplicate CTA | `test_duplicate_same_score_candidates_tie_broken_by_cta_id` |
| Empty response | `test_empty_safe_response_passed_through_unchanged` |
| Performance | `test_performance_under_corpus_growth` |
| Edge cases | `test_missing_topic_key_does_not_raise`, `test_exclusion_also_blocks_the_category_fallback_path`, `test_cross_category_genuine_tie_logged_and_deterministic` |

---

## 18. Acceptance Criteria

### 18.1 Definition of Done

This specification is considered fully implemented only when **all** of the following hold:

1. `app/services/cta_service.py` exists, implements exactly `find_cta()`, `build_cta_response()`, and `process()` as public functions (Section 12.1), and contains no file I/O against `data/cta/` anywhere (FR-1) — verified by code review against its `import` lines (no `pathlib`/`open()` usage targeting that directory).
2. `app/nodes/cta_node.py` exists, implements `cta_node()` and `build_cta_graph()` (Section 12.2), and never raises for any input tried in Section 17.1's test suite.
3. `app/graph/state.py` has the `CTA` TypedDict and `GraphState.cta` field (Section 13.1); `app/models.py` has `CTAResponse` (Section 13.4); `app/main.py` wires `build_cta_graph()` and exposes `/cta` (Section 13.3).
4. `state["safety"]["safe_response"]` and `result["cta"]["response"]` are identical on every test in Section 17.1 — no test exists where they differ (FR-2).
5. No test in Section 17.1 ever observes more than one CTA returned from any function (FR-3) — verified directly by `test_no_match_returns_none_not_empty_list` and by every matching test asserting a single `cta_id`, never a collection.
6. The category-fallback path (Section 9.7) only ever activates in tests where literal phrase matching was first confirmed to produce zero candidates (FR-7) — `test_intent_driven_category_fallback_when_nothing_matches` and `test_general_therapy_library_direct_match` together prove the distinction between "fallback" and "direct match on the Library's own content" is real and tested.
7. Every tie-break path (Section 9.6) logs a `WARNING` and resolves deterministically across at least 2 repeated calls in its corresponding test (FR-6).
8. No code path in `cta_service.py` or `cta_node.py` imports `langchain`'s LLM/embeddings clients, `langgraph` (other than inside `build_cta_graph()`), or performs a network call (FR-9) — verified by code review.
9. Every test case in Section 17.1 exists in `tests/test_cta_node.py` and passes.

### 18.2 Worked Examples (For Implementer Sanity-Checking)

* `"What is MNRI?"`, intent `therapy_information`, topic `MNRI` → `therapies/mnri.md` (alias/trigger hit), `specific_match`.
* `"What therapies are available?"`, intent `therapy_information` → `therapies/general.md` (direct trigger-example hit on the Library record itself), `specific_match` — **not** `category_fallback`.
* `"I don't know what to ask"`, intent `therapy_information` → `therapies/general.md` (zero phrase hits anywhere, intent affinity → Therapy → its Library CTA), `category_fallback`.
* `"I don't know what to ask"`, intent `general_chat` → no CTA (zero phrase hits, no affinity entry for `general_chat`).
* `"MNRI"` mentioned alongside a message that also matches `conditions/general.md`'s `related_topics` (e.g. contains the word "development") → MNRI wins; a `related_topics`-only hit can never outscore an `aliases` hit (Section 9.8), regardless of category.

---

## 19. Future Considerations (Explicitly Out of Scope Here)

* **A unified end-of-pipeline endpoint** that calls `build_cta_response()` to emit Section 5.2's minimal `{response, cta_found, cta}` contract as the system's actual "Final Output" to a frontend. Not built in this change set (Section 13.3) — `build_cta_response()` is ready for it.
* **Configurable scoring weights / intent-affinity table.** Currently module-level constants in `cta_service.py` (Section 9.5–9.6). If real usage shows the weighting needs tuning per-deployment, promoting them to `Settings` fields is a self-contained follow-up with no change to the matching algorithm's structure.
* **A genuine `category` field on `Understanding`.** Section 4.2 resolves today's discrepancy by deriving category from `CTARecord` data rather than from upstream state. If a future Understanding Node revision adds a real `category` output, this node's `INTENT_CATEGORY_AFFINITY` mechanism (Section 9.6) would be the natural place to fold it in as an additional (or replacement) tie-break signal — not a redesign of Sections 9.1–9.8's core matching.
* **Synonym/fuzzy matching beyond `aliases`.** Section 9.3 is deliberately exact-containment/token-subset only, no edit distance, no embeddings (FR-9). If false negatives on real traffic show this corpus's `aliases` lists aren't catching enough phrasing variance, the fix per this spec's philosophy is to add more `aliases` entries to the Markdown content (an authoring change), not to add fuzzy matching code.
* **Multiple CTAs per turn.** FR-3's single-CTA rule is treated as a hard product requirement here, mirroring the brief. If a future product decision allows e.g. one primary plus one secondary CTA, that is a new spec, not an extension of this one's `find_cta()` contract.

---

*End of CTA Node Specification.*
