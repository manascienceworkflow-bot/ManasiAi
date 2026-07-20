# Manasi AI – Therapy Recommendation Aggregation – Product Requirements Specification

> **Status:** Implementation-ready (spec only — do NOT implement from this document)
> **Author:** Roadmap pipeline team
> **Applies to commit line:** `fix/therapy-mapping-data-unavailable` (builds on the completed Mapped Therapy API, `POST /roadmap/mapped-therapies`)
> **Deliverable introduced:** a backend Therapy Aggregation layer + an aggregated therapy view on the mapped-therapies response

---

## 1. Feature Overview

The Domain → Therapy mapping pipeline (`load_roadmap` → `filter_by_severity` →
`map_domains_to_therapies`, serialized by `build_mapped_response`) currently
returns a **domain-centric** response: a list of matched domains, each carrying
its own list of recommended therapies. This shape is defined by
`MappedTherapyResponse` / `MappedDomainOut` in `app/roadmap/serializers.py`.

Because a single therapy (e.g. **MNRI**) is legitimately recommended by several
domains, the *same therapy name appears in multiple domain buckets*. When the
frontend renders one therapy card per therapy occurrence, the user sees the same
therapy card several times.

This feature introduces a **Therapy Aggregation layer** that transposes the
domain-centric result into a **therapy-centric** view: one object per unique
therapy, carrying the list of domains that recommended it and the set of
relevance labels observed across those domains. The frontend renders exactly one
card per therapy, listing the domains under "Recommended For".

### 1.1 Guiding principles (inherited from the pipeline)

The aggregation layer follows the same principles as the rest of `app/roadmap/`:

- **P1 — Pure & deterministic.** Same input → same output, forever. No I/O, no
  clock, no randomness, no global state.
- **P2 — Additive, non-breaking.** The existing `mapped_domains` array is
  preserved verbatim. Aggregation is a *new* field, not a replacement (see §4.2).
- **P3 — Verbatim carry-through.** Therapy display names, domain display names,
  and relevance labels are emitted exactly as they arrived. Case-insensitivity is
  used only for *matching/deduplication keys*, never to rewrite what the user
  sees (mirrors `domain_key()` in `therapy_mapper.py`).
- **P4 — Observe, don't drop.** Malformed items are skipped defensively and
  counted, never allowed to 500 a successful mapping.

---

## 2. Problem Statement

After a user completes the assessment questionnaire, the backend returns affected
domains and their recommended therapies. Example (real domain labels):

| Domain | Recommended therapies |
|---|---|
| Sensory Processing | MNRI, Feldenkrais |
| Body Awareness & Skills | MNRI, Feldenkrais |
| Emotional Regulation | MNRI |
| Academic & Learning | Arrowsmith |

The current wire shape (`mapped_domains`) lists MNRI three times and Feldenkrais
twice, because those therapies each belong to more than one domain. A frontend
that iterates domains → therapies therefore renders:

- MNRI card (from Sensory Processing)
- Feldenkrais card (from Sensory Processing)
- MNRI card (from Body Awareness & Skills) ← duplicate
- Feldenkrais card (from Body Awareness & Skills) ← duplicate
- MNRI card (from Emotional Regulation) ← duplicate
- Arrowsmith card (from Academic & Learning)

**Result:** duplicate therapy cards, a cluttered UI, and no single place that
answers "which domains does MNRI address?". The information needed to de-duplicate
exists in the response, but grouping is currently left to the frontend — and is
not being done consistently.

---

## 3. Goals

### 3.1 In-scope goals

1. Every therapy appears **exactly once** in the aggregated view.
2. Each aggregated therapy carries the **list of all unique domains** that
   recommended it.
3. Each aggregated therapy carries the **set of all unique relevance values**
   observed for it across domains.
4. **Duplicate therapy cards can never be rendered** — the backend ships an
   already-clean, already-grouped list.
5. **All domain information is preserved** — no domain that recommended a therapy
   is lost.
6. **Ordering is preserved** by the therapy's first appearance in the mapped
   results (no alphabetical sort unless explicitly requested later).
7. Aggregation happens **entirely in the backend**. The frontend never groups.

### 3.2 Non-goals

- **NOT** removing or restructuring the existing `mapped_domains` array (it stays;
  see §4.2 additive rollout).
- **NOT** ranking, scoring, or sorting therapies (order = first appearance only).
- **NOT** changing the mapping logic, the Excel loader, the severity filter, or
  any `frozen` model. Those files are frozen exactly as in the Step-3 spec (§4.3).
- **NOT** merging therapies by fuzzy/semantic similarity — dedup is by
  case-insensitive exact name match only (§8).
- **NOT** localization, PDF generation, persistence, or auth.

---

## 4. Scope

### 4.1 In scope

- A new **pure aggregation function**, e.g.
  `aggregate_therapies(mapped: MappedTherapyResponse) -> list[AggregatedTherapyOut]`
  (or operating on `DomainTherapyResult` — see §7 for the input-source decision),
  living in a **new module** `app/roadmap/therapy_aggregator.py`.
- New response Pydantic models: `AggregatedTherapyOut` and the container field on
  the existing response.
- Wiring the aggregation into the serialization step so the aggregated list is
  emitted on the `POST /roadmap/mapped-therapies` response.
- Unit + integration tests (§13).

### 4.2 Additive rollout (non-breaking)

The aggregated view is added as a **new field** `aggregated_therapies` on
`MappedTherapyResponse`, alongside the untouched `mapped_domains`. Existing
frontend consumers of `mapped_domains` keep working unchanged; the new frontend
therapy-card UI reads `aggregated_therapies`. A later, separately-approved change
MAY deprecate `mapped_domains` once all consumers migrate — that deprecation is
**out of scope here**.

### 4.3 Explicitly frozen (MUST NOT be modified)

| File | Reason it is frozen |
|---|---|
| `app/roadmap/roadmap_loader.py` | Owns the frontend wire format + validation |
| `app/roadmap/severity_filter.py` | Owns High/Moderate actionability filtering |
| `app/roadmap/mapping_loader.py` | Owns Excel workbook parsing |
| `app/roadmap/therapy_mapper.py` | Owns the Domain → Therapy join + `domain_key()` |
| `app/roadmap/models.py` | Loader + filter Pydantic models |
| `app/roadmap/mapping_models.py` | Excel-data Pydantic models |
| `app/roadmap/therapy_models.py` | Therapy-output Pydantic models |

The aggregator MAY **import** `domain_key` from `therapy_mapper.py` for
consistency, but MUST NOT modify it. The existing `MappedTherapyResponse` /
`MappedDomainOut` / `TherapyOut` in `serializers.py` are **extended** (a new field
+ new models), not restructured.

---

## 5. Functional Requirements

### 5.1 Input

The aggregator consumes the mapped therapy result — a list of matched domains,
each with an ordered list of `{therapy, relevance}` therapies. Conceptually:

```
Domain
 ├── Sensory Processing
 │      ├── MNRI          (relevance: Primary)
 │      └── Feldenkrais   (relevance: Secondary)
 ├── Body Awareness & Skills
 │      ├── MNRI          (relevance: Secondary)
 │      └── Feldenkrais   (relevance: Secondary)
 └── Emotional Regulation
        └── MNRI          (relevance: Primary)
```

### 5.2 Aggregation rules

- **FR-1.** If the same therapy (by case-insensitive name key) appears under
  multiple domains, produce **exactly one** aggregated therapy object.
- **FR-2.** That object's `domains` array is the union of every domain that
  recommended the therapy, **in first-seen order**, with no duplicates.
- **FR-3.** That object's `relevance` array is the set of all relevance values
  observed for the therapy, **in first-seen order**, with no duplicates, and with
  `null`/empty relevance values excluded from the array (a therapy with no
  relevance label anywhere yields an empty `relevance: []`).
- **FR-4.** The aggregated `therapy` display name is the **first-seen spelling**
  of that therapy name (verbatim), even if later occurrences differ in casing.

### 5.3 Duplicate rules (therapy identity)

- **FR-5.** Two therapy occurrences are the **same therapy** iff their names are
  equal after the canonical key transform. The canonical key = NFKC-normalize →
  collapse internal whitespace → `casefold()` (the same normalization family used
  by `domain_key()`, minus the ordinal-prefix strip which does not apply to
  therapy names). Therefore `MNRI`, `mnri`, `Mnri`, and `  MNRI  ` all collapse to
  one therapy.
- **FR-6.** The key is used **only** for grouping. The emitted `therapy` string is
  the first-seen verbatim spelling (FR-4), never the lowercased key.

### 5.4 Domain rules

- **FR-7.** A therapy's `domains` array MUST contain every unique domain that
  recommended it and MUST NOT contain the same domain twice.
- **FR-8.** Domain de-duplication within a single therapy uses a **case-insensitive
  domain key** (`domain_key()` from `therapy_mapper.py`) so a domain that recurs
  is not listed twice; the **first-seen verbatim domain display name** is emitted.

### 5.5 Relevance rules

- **FR-9.** Collect all **unique** relevance values across the therapy's domains
  (e.g. `Primary`, `Secondary`, `Complementary`), in first-seen order, no
  duplicates.
- **FR-10.** Relevance de-duplication is by exact string after trimming
  surrounding whitespace; unknown/free-text relevance values are preserved
  verbatim (the aggregator does not validate against a fixed vocabulary — see
  §11 EC-8).

### 5.6 Ordering rules

- **FR-11.** Aggregated therapies are ordered by **first appearance** in the
  mapped results — i.e. walk domains in response order, and within each domain
  walk therapies in mapping-table order (the order `therapy_mapper` already
  preserves). The first time a therapy key is seen fixes its position.
- **FR-12.** No alphabetical or relevance-based sort is applied. Any future sort is
  a separate, explicitly-requested enhancement (§14).

### 5.7 Backend / frontend responsibilities

- **FR-13.** Aggregation MUST run in the backend; the response is already-clean.
- **FR-14.** The frontend MUST NOT perform therapy grouping, de-duplication, or
  relevance merging. It renders the `aggregated_therapies` list one card each.

---

## 6. Data Flow

```
Frontend assessment JSON
        │
        ▼
POST /roadmap/mapped-therapies (routes.py)
        │
        ▼
map_roadmap_therapies (services.py)        [FROZEN pipeline]
   load_roadmap → filter_by_severity
   → load_mappings → map_domains_to_therapies
        │  DomainTherapyResult
        ▼
build_mapped_response (serializers.py)      [EXTENDED]
   ├── mapped_domains  (existing, unchanged)
   └── aggregate_therapies(...)  ─────────▶ therapy_aggregator.py   [NEW, pure]
                                                  │  list[AggregatedTherapyOut]
        │                                         ▼
        ▼
MappedTherapyResponse { user_id, classification,
                        mapped_domains, aggregated_therapies }
        │
        ▼
Frontend renders one card per aggregated therapy
```

The aggregator sits **between** the mapper's output and the wire response. It adds
no I/O and never touches Excel, the DB, or the network. It is called once per
request, after the domain-centric list is built.

---

## 7. Backend Architecture

### 7.1 Input source decision

Two candidate inputs exist:

1. `DomainTherapyResult` (mapper output, richer: has `source_row`, `matched_domain`).
2. `MappedTherapyResponse` / `list[MappedDomainOut]` (post-serialization, wire-shaped).

**Decision:** aggregate from the **already-serialized `mapped_domains`**
(`list[MappedDomainOut]`). Rationale:

- The aggregated view needs only `domain`, `therapy`, `relevance` — all present on
  `MappedDomainOut` / `TherapyOut`.
- Aggregating from the serialized list guarantees the two views (`mapped_domains`
  and `aggregated_therapies`) are **derived from identical data**, so they can
  never disagree.
- Keeps the aggregator decoupled from internal `frozen` models and `source_row`
  provenance, matching P2/P3.

The function signature is therefore:

```python
def aggregate_therapies(domains: list[MappedDomainOut]) -> list[AggregatedTherapyOut]: ...
```

`build_mapped_response` builds `mapped_domains` first (as today), then calls
`aggregate_therapies(mapped_domains)` and attaches the result.

### 7.2 New module: `app/roadmap/therapy_aggregator.py`

Pure, importable, no side effects. Owns:

- `therapy_key(name)` — the canonical therapy-identity key (FR-5). MAY reuse the
  NFKC+casefold logic; does **not** strip ordinal prefixes.
- `aggregate_therapies(domains)` — the O(n) grouping (§8).

### 7.3 New response models (in `serializers.py`)

```python
class AggregatedTherapyOut(BaseModel):
    therapy: str                 # first-seen verbatim spelling
    domains: list[str]           # unique, first-seen order
    relevance: list[str] = []    # unique, first-seen order; empty if none

class MappedTherapyResponse(BaseModel):
    user_id: str
    classification: Literal["ND", "NT"]
    mapped_domains: list[MappedDomainOut]          # unchanged
    aggregated_therapies: list[AggregatedTherapyOut]  # NEW
```

`aggregated_therapies` MAY be empty (all-Low / all-unmatched outcome) — that is a
**success**, not an error, exactly like `mapped_domains: []`.

---

## 8. Aggregation Algorithm

Single pass, insertion-ordered accumulator. `O(n)` in the total number of
`(domain, therapy)` pairs; memory proportional to the number of *unique*
therapies × their domains/relevance sets.

```
aggregate_therapies(domains):
    order        = []              # list of therapy_keys in first-seen order
    by_key       = {}              # therapy_key -> accumulator

    for domain in domains:                     # response order (FR-11)
        d_name = domain.domain
        if not d_name:            # malformed / missing domain name → skip (EC-6)
            continue
        d_key = domain_key(d_name)

        for t in (domain.therapies or []):     # mapping-table order; None-safe (EC-7)
            if t is None or not t.therapy:      # malformed / empty therapy → skip (EC-5)
                continue
            k = therapy_key(t.therapy)          # NFKC + collapse ws + casefold (FR-5)
            if k is None:                       # non-str / empty key → skip
                continue

            if k not in by_key:
                by_key[k] = {
                    "therapy":       t.therapy,     # first-seen verbatim (FR-4)
                    "domain_keys":   set(),         # dedup set for domains
                    "domains":       [],            # ordered, unique
                    "relevance_seen":set(),         # dedup set for relevance
                    "relevance":     [],            # ordered, unique
                }
                order.append(k)

            acc = by_key[k]

            if d_key not in acc["domain_keys"]:     # FR-7/FR-8
                acc["domain_keys"].add(d_key)
                acc["domains"].append(d_name)       # verbatim first-seen

            rel = (t.relevance or "").strip()       # FR-3/FR-9/FR-10
            if rel and rel not in acc["relevance_seen"]:
                acc["relevance_seen"].add(rel)
                acc["relevance"].append(rel)

    return [ AggregatedTherapyOut(
                 therapy=acc["therapy"],
                 domains=acc["domains"],
                 relevance=acc["relevance"],
             )
             for k in order
             for acc in [by_key[k]] ]
```

### 8.1 Complexity

- **Time:** each `(domain, therapy)` pair is processed once; set membership checks
  are O(1) average → **O(n)** overall.
- **Space:** one accumulator per unique therapy; the `domain_keys` /
  `relevance_seen` sets are transient dedup helpers (not emitted). **Minimal
  overhead**, proportional to unique output size.
- **Determinism:** dict/list insertion order + first-seen rule ⇒ identical input
  yields byte-identical output every time.

---

## 9. API Request/Response Examples

### 9.1 Request (unchanged)

`POST /roadmap/mapped-therapies` — the existing assessment JSON body. No new
request fields.

### 9.2 Response (extended)

Given the §2 example, the response gains an `aggregated_therapies` array:

```json
{
  "user_id": "user-123",
  "classification": "ND",
  "mapped_domains": [
    {
      "domain": "Sensory Processing",
      "domain_type": "Spine",
      "score": 8.0,
      "severity": "High",
      "therapies": [
        { "therapy": "MNRI",        "relevance": "Primary" },
        { "therapy": "Feldenkrais", "relevance": "Secondary" }
      ]
    },
    {
      "domain": "Body Awareness & Skills",
      "domain_type": "Spine",
      "score": 6.0,
      "severity": "Moderate",
      "therapies": [
        { "therapy": "MNRI",        "relevance": "Secondary" },
        { "therapy": "Feldenkrais", "relevance": "Secondary" }
      ]
    },
    {
      "domain": "Emotional Regulation",
      "domain_type": "Spine",
      "score": 7.0,
      "severity": "High",
      "therapies": [
        { "therapy": "MNRI", "relevance": "Primary" }
      ]
    },
    {
      "domain": "Academic & Learning",
      "domain_type": "Complementary",
      "score": 5.0,
      "severity": "Moderate",
      "therapies": [
        { "therapy": "Arrowsmith", "relevance": "Primary" }
      ]
    }
  ],
  "aggregated_therapies": [
    {
      "therapy": "MNRI",
      "domains": [
        "Sensory Processing",
        "Body Awareness & Skills",
        "Emotional Regulation"
      ],
      "relevance": ["Primary", "Secondary"]
    },
    {
      "therapy": "Feldenkrais",
      "domains": [
        "Sensory Processing",
        "Body Awareness & Skills"
      ],
      "relevance": ["Secondary"]
    },
    {
      "therapy": "Arrowsmith",
      "domains": ["Academic & Learning"],
      "relevance": ["Primary"]
    }
  ]
}
```

Note: MNRI appears **once**, with all three domains merged and both relevance
labels collected in first-seen order. `mapped_domains` is untouched.

### 9.3 Empty outcome

```json
{
  "user_id": "user-123",
  "classification": "NT",
  "mapped_domains": [],
  "aggregated_therapies": []
}
```

HTTP 200 — a legitimate all-Low / all-unmatched result, not an error.

---

## 10. Frontend Rendering Flow

The frontend reads **only** `aggregated_therapies` for the therapy-card UI:

```
for therapy in response.aggregated_therapies:
    render TherapyCard:
        title:  therapy.therapy
        badges: therapy.relevance            (optional chips: Primary / Secondary …)
        section "Recommended For":
            for d in therapy.domains:
                • d
```

Rendered for the §9.2 example:

```
┌─────────────────────────────────────┐
│ MNRI                [Primary][Secondary]
│ Recommended For:                     │
│  • Sensory Processing                │
│  • Body Awareness & Skills           │
│  • Emotional Regulation              │
├─────────────────────────────────────┤
│ Feldenkrais              [Secondary] │
│ Recommended For:                     │
│  • Sensory Processing                │
│  • Body Awareness & Skills           │
├─────────────────────────────────────┤
│ Arrowsmith                 [Primary] │
│ Recommended For:                     │
│  • Academic & Learning               │
└─────────────────────────────────────┘
```

The frontend performs **no** grouping, de-duplication, or relevance merging.

---

## 11. Edge Cases

| ID | Scenario | Required behavior |
|---|---|---|
| **EC-1** | Therapy appears in 10+ domains | One therapy object; `domains` holds all 10+ unique domains in first-seen order. No cap, no truncation. |
| **EC-2** | Same therapy, different relevance per domain (Primary, Secondary, Complementary) | `relevance` collects all three, first-seen order, no dupes (FR-9). |
| **EC-3** | A single domain lists the same therapy twice | Emitted once for that domain; the domain appears once under it (FR-7); relevance values from both occurrences merged (FR-9). |
| **EC-4** | Mixed casing (`MNRI`, `mnri`, `Mnri`) across domains | Collapse to one therapy; display the **first-seen** spelling (FR-4/FR-6). |
| **EC-5** | Empty therapy list overall | Return `aggregated_therapies: []`; HTTP 200 (§9.3). |
| **EC-6** | Domain with no name / empty domain string | Skip that domain for aggregation (don't emit a blank domain entry); still process others. |
| **EC-7** | Domain present but `therapies` is null/empty | Contributes no therapies; not an error. Domain simply won't appear under any therapy. |
| **EC-8** | Null / malformed therapy object, or `therapy` name null/empty | Skip that occurrence defensively; never raise. Log at debug/warn with a count (P4). |
| **EC-9** | Unknown / free-text relevance value | Preserved verbatim in `relevance`; the aggregator does not validate a vocabulary (FR-10). |
| **EC-10** | Relevance is null/empty for every occurrence | `relevance: []` (FR-3). Empty strings and whitespace-only are treated as "no relevance". |
| **EC-11** | Therapy name identical except surrounding whitespace (`" MNRI "` vs `"MNRI"`) | Same key ⇒ one therapy (FR-5). |
| **EC-12** | Same domain label recurs (e.g. after ordinal-prefix drift) for one therapy | De-duped by `domain_key` (FR-8); listed once. |

No edge case may cause a `500`. A successfully mapped result must always
serialize, degrading to skips + logged warnings for malformed items.

---

## 12. Acceptance Criteria

- **AC-1.** For any response, no two objects in `aggregated_therapies` share the
  same `therapy_key` (uniqueness).
- **AC-2.** For every therapy in the source `mapped_domains`, exactly one
  aggregated object exists and its `domains` set equals the set of domains that
  recommended it (by `domain_key`). No domain lost, none duplicated.
- **AC-3.** Each aggregated `relevance` list contains every distinct non-empty
  relevance value seen for that therapy, in first-seen order, with no duplicates.
- **AC-4.** Aggregated therapy order matches first-appearance order across
  `mapped_domains` (domain order, then intra-domain therapy order).
- **AC-5.** The emitted `therapy` and `domains` strings are verbatim first-seen
  spellings (never the lowercased key).
- **AC-6.** `mapped_domains` is byte-for-byte identical to the pre-feature
  response (additive, non-breaking).
- **AC-7.** All §11 edge cases behave as specified; none produce a 5xx.
- **AC-8.** The aggregation function is pure: same input → identical output across
  repeated calls and process restarts.
- **AC-9.** `aggregated_therapies: []` is returned (HTTP 200) for an empty /
  all-unmatched result.

---

## 13. Testing Strategy

### 13.1 Unit tests — `tests/test_therapy_aggregator.py` (new)

- **Happy path:** the §2 example → MNRI merged across 3 domains, Feldenkrais
  across 2, Arrowsmith 1; assert order, domains, relevance (AC-2/3/4).
- **Case-insensitivity:** `MNRI`/`mnri`/`Mnri` → one therapy, first-seen spelling
  (EC-4, AC-5).
- **Whitespace key equality:** `" MNRI "` vs `"MNRI"` → one therapy (EC-11).
- **Relevance dedup + order:** Primary/Secondary/Complementary collected once each
  (EC-2, AC-3); all-null relevance → `[]` (EC-10).
- **Domain dedup:** same domain twice for one therapy → listed once (EC-12).
- **Intra-domain duplicate therapy:** EC-3.
- **10+ domains:** no truncation (EC-1).
- **Malformed inputs:** null therapy object, empty therapy name, empty/blank
  domain name, null `therapies` list → skipped, no raise (EC-5–EC-8).
- **Empty input:** `[]` → `[]` (EC-5, AC-9).
- **Determinism:** call twice, assert equal output (AC-8).
- **Complexity guard (optional):** large synthetic input completes within a linear
  time budget.

### 13.2 Serializer tests — extend `tests/test_roadmap_serializers.py`

- `build_mapped_response` output now includes `aggregated_therapies`; assert it is
  derived from `mapped_domains` and consistent with it.
- Assert `mapped_domains` unchanged vs. the pre-feature golden (AC-6).

### 13.3 Route/integration tests — extend `tests/test_roadmap_mapped_therapies.py`

- Full `POST /roadmap/mapped-therapies` run returns both arrays; aggregated view
  has no duplicate therapy names.
- Empty-actionable path → both arrays empty, HTTP 200.

---

## 14. Future Enhancements

1. **Deprecate `mapped_domains`.** Once all frontends read `aggregated_therapies`,
   remove or version-gate the domain-centric array (separate, breaking change).
2. **Relevance ranking / sort.** Optionally sort aggregated therapies by a
   priority derived from relevance (e.g. Primary-first) or by domain count —
   behind an explicit query flag so the default stays first-appearance order.
3. **Per-domain relevance detail.** Emit `domains` as objects
   (`{domain, relevance}`) rather than plain strings, so the card can show why a
   therapy is recommended per domain, while keeping the flat `relevance` union.
4. **Canonical therapy catalog.** Map first-seen spellings to a canonical display
   name / id from a therapy master table (would replace FR-4's first-seen spelling
   with a catalog lookup).
5. **Severity/score propagation.** Attach the max or per-domain severity to each
   aggregated therapy to support prioritized UI ordering.
6. **i18n.** Localize domain and relevance labels at render time; the aggregator
   remains language-neutral.

---

## 15. Summary

This feature adds a **pure, O(n), deterministic backend aggregation layer** that
transposes the existing domain-centric mapped-therapy response into a
**therapy-centric** view — one object per unique therapy, carrying its merged
domains and relevance set — emitted as a **new, additive `aggregated_therapies`
field**. It eliminates duplicate therapy cards, keeps grouping entirely in the
backend, preserves all domain/relevance information and first-appearance ordering,
and leaves every mapping-logic file and the existing `mapped_domains` contract
frozen and unbroken.
