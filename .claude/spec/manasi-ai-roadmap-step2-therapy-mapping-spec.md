# Manasi AI — Roadmap Pipeline **Step 2 – Domain → Therapy Mapping Module** — Technical Specification

**Project:** Manasi AI (ManaScience)
**Component:** `app/roadmap/therapy_mapper.py` (new) + `app/roadmap/therapy_models.py` (new)
**Pipeline position:** Step 2 – Domain to Therapy Mapping (see §0.2 for how this maps onto the shipped code's finer numbering)
**Depends on:**
- Excel Mapping Loader — `app/roadmap/mapping_loader.py` / `mapping_models.py` — **already implemented and shipped** (commit `1362802`). Supplies the in-memory `MappingBundle`.
- Severity Filter — `app/roadmap/severity_filter.py` (the shipped severity-filter module) — **already implemented and shipped**. Supplies the `FilteredRoadmapResult`.
**Author:** Backend Architecture
**Status:** Ready for implementation
**Date:** 2026-07-15

---

## 0. Reader's notes — two things to align on before you read

### 0.1 The module consumes **objects**, not JSON

The brief shows the input as loose JSON:

```json
{ "user_id": "...", "classification": "ND",
  "score": [ { "domain": "Sensory Processing", "score": 82, "severity": "High" } ] }
```

That JSON is illustrative of the *shape* of the filtered assessment, but the actual runtime input to this module is the **`FilteredRoadmapResult` pydantic object** emitted by the severity filter (`app/roadmap/models.py:93`), whose fields are already normalized (`classification`, `filtered_scores[].domain`, `filtered_scores[].severity`). This is the same layering the severity filter already mandates — the module never parses wire JSON, and never re-opens the Excel files. If the wire contract ever changes, this module needs **no** change.

### 0.2 "Step 2" and how it maps onto the shipped code's numbering

This document is titled **Step 2 – Domain → Therapy Mapping**, matching the implementation plan. The brief treats ingestion + severity-filtering + Excel-loading together as "Step 1", so **Domain → Therapy Mapping is Step 2**.

One thing to be aware of when reading the existing code: the *shipped codebase* already uses a finer, per-module numbering in which the severity filter is called "Step 2" and it forward-references this module as "Step 3":

> `manasi-ai-roadmap-step2-severity-filter-spec.md §2.2`: *"Therapy / intervention mapping → Step 3 (separate spec)"*

Those are the **same module** under two numbering schemes — the plan's **Step 2** and the code's internal **"Step 3"** both mean *this* Domain → Therapy Mapping module. The full data flow (numbers below are the code's finer per-module labels):

```
Roadmap ingestion      roadmap_loader.py     raw JSON      → RoadmapResult
Excel mapping loader    mapping_loader.py     .xlsx files   → MappingBundle   (infrastructure)
Severity filter         severity_filter.py    RoadmapResult → FilteredRoadmapResult   } the plan's "Step 1"
──────────────────────────────────────────────────────────────────────────────────────
Domain → Therapy map    therapy_mapper.py     ↑ + MappingBundle → DomainTherapyResult  ← THIS SPEC (plan's Step 2)
Roadmap generation      (future)              out of scope
```

---

## 1. Purpose

Step 2 answers exactly one question, deterministically:

> **For each actionable domain, which therapies does the mapping table list, and in what order?**

It is a **pure, side-effect-free transformation** that joins two already-loaded inputs — the actionable domains (from the severity filter) and the therapy-mapping reference tables (Excel loader) — and returns, per domain, the ordered list of therapies with their relevance labels:

```
FilteredRoadmapResult  ─map_domains_to_therapies()─►  DomainTherapyResult
(High/Moderate domains)          +                    (domain → [ {therapy, relevance}, … ])
MappingBundle (ND + NT tables)
```

It performs **no** Excel I/O, **no** persistence, **no** network, **no** LLM call, **no** ranking, **no** deduplication, **no** roadmap sequencing, and **no** mutation of either input. Given the same two inputs it produces byte-identical output, forever.

---

## 2. Scope

### 2.1 In scope

| # | Responsibility |
|---|---|
| 1 | Accept the `FilteredRoadmapResult` from the severity filter **and** the in-memory `MappingBundle` from the Excel loader. |
| 2 | Select the correct dataset from the bundle by `classification` (ND → `neurodivergent`, NT → `neurotypical`). |
| 3 | Build a **read-only** domain → therapies index over the selected dataset, resolving the merged-cell Domain column by forward-fill (§9.2). |
| 4 | Match each actionable domain against that index using ordinal-prefix- and whitespace/case-insensitive comparison (§9.3). |
| 5 | For each matched domain, return **every** mapped therapy, in **Excel row order**, with its `relevance` preserved verbatim. |
| 6 | Record unmatched domains separately (never silently drop them). |
| 7 | Return a **new** `DomainTherapyResult` object plus machine-readable diagnostics; expose a `to_list()` producing the brief's exact JSON shape. |
| 8 | Emit structured logs for dataset selection and every match / miss decision. |

### 2.2 Explicitly out of scope

The module **must not**, and this spec **does not** describe:

| ❌ Not this module | Where it belongs |
|---|---|
| Loading / reading / reloading any `.xlsx` | Excel Mapping Loader (`mapping_loader.py`) — already done |
| Filtering by severity | The severity filter (`severity_filter.py`) — already done |
| Roadmap generation / sequencing | A future module |
| Grouping Spine vs Complementary therapies | A future module — the `Track` column is carried but **not** interpreted here |
| Removing duplicate therapy rows | A future module — duplicates pass through verbatim |
| Ranking / prioritizing therapies | Future recommendation engine |
| Re-casing, forward-filling into, or otherwise **mutating** the loaded mapping data | Forbidden — the `MappingBundle` is frozen and read-only |
| Recomputing scores, PDF, email, DB persistence | Future / other layers |

---

## 3. Architecture

### 3.1 Position & data flow

```
                 ┌─────────────────────────┐
   .xlsx  ─────► │  mapping_loader.py       │──► MappingBundle ─┐
   (ND / NT)     │  (Excel Mapping Loader)  │   (frozen, cached) │
                 └─────────────────────────┘                    │
                                                                 ▼
 raw JSON ─► roadmap_loader ─► RoadmapResult ─► severity_filter ─► FilteredRoadmapResult ─► ┌──────────────────┐
                                            (severity filter)                               │ therapy_mapper.py│
                                                                                            │   (Step 2, THIS) │
                                                                                            └────────┬─────────┘
                                                                                                     ▼
                                                                                           DomainTherapyResult
                                                                                        (→ future roadmap gen)
```

### 3.2 Design principles (inherited from the roadmap family)

- **P1 — Verbatim carry-through.** Therapy names, relevance labels, and the incoming domain/severity are never re-cased, trimmed-in-place, or coerced in the output. Normalization exists **only** as a throwaway comparison key (§9.3), exactly as the Excel loader's `_norm` does.
- **P2 — Object layering.** The module reads typed objects (`FilteredRoadmapResult`, `MappingBundle`), never wire JSON and never `.xlsx`.
- **P3 — Purity / dependency injection.** Both inputs are **parameters**. The module does **not** call `get_mappings()`, `load_mappings()`, or `filter_by_severity()` itself — the caller (route/service layer) fetches them and passes them in. This keeps the function deterministic and trivially testable, and structurally guarantees it cannot load Excel.
- **P4 — Immutability.** The `MappingBundle` and its `ModalityRow`s are frozen (`mapping_models.py`). The forward-fill index (§9.2) is built into a **new local structure**; the loaded rows are never touched.
- **P5 — Never silently drop.** A domain with no match is recorded in `unmapped` with a reason; a caller can observe every actionable domain's fate.

### 3.3 Public surface

```python
def map_domains_to_therapies(
    filtered: FilteredRoadmapResult,
    bundle: MappingBundle,
    *,
    strict: bool = False,
) -> DomainTherapyResult: ...
```

- `strict=False` (production): an unknown domain / empty dataset is recorded and warned, never raised — a user who completed the assessment must not get a 5xx because one domain label drifted.
- `strict=True` (contract tests / batch): the same conditions raise `TherapyMappingError`.

An optional memoized index builder (§9.2, §13.5) keyed on dataset identity is permitted for performance, since the bundle is immutable.

---

## 4. Folder structure

```
app/roadmap/
├── mapping_loader.py      # (existing) loads .xlsx → MappingBundle
├── mapping_models.py      # (existing) ModalityRow / MappingDataset / MappingBundle
├── severity_filter.py     # (existing) severity filter → FilteredRoadmapResult
├── models.py              # (existing) FilteredRoadmapResult / FilteredDomainScore
├── therapy_mapper.py      # NEW — map_domains_to_therapies(), TherapyMappingError, index builder
└── therapy_models.py      # NEW — TherapyRef / DomainTherapyMapping / UnmappedDomain /
                           #        TherapyMappingDiagnostics / DomainTherapyResult

tests/
└── test_therapy_mapper.py # NEW — unit / integration / validation / failure / performance tests
```

No new dependencies, no config, no data files.

---

## 5. Responsibilities

The module **shall**:

1. Read only the already-loaded `MappingBundle` (never touch a file).
2. Select `bundle.neurodivergent` or `bundle.neurotypical` from `classification`.
3. Resolve the merged Domain column by forward-fill into a read-only index (§9.2).
4. Match each incoming domain name against index keys (prefix/whitespace/case-insensitive, §9.3).
5. Return **every** therapy mapped to a matched domain.
6. Preserve **Excel row order** of therapies.
7. Preserve the `relevance` value verbatim (including `None`).
8. Preserve the incoming `domain` and `severity` verbatim in the output.
9. Record unmatched domains and emit diagnostics + structured logs.

It **shall not** dedupe, rank, group by `Track`, filter severity, generate roadmap flow, or mutate either input.

---

## 6. Processing flow

```
map_domains_to_therapies(filtered, bundle, strict):

  0. Type-guard inputs (FilteredRoadmapResult, MappingBundle) — else TypeError.
  1. log "mapping started" (user_id, classification, domain count).
  2. Select dataset:
        classification == "ND" → bundle.neurodivergent   (log "ND dataset selected")
        classification == "NT" → bundle.neurotypical      (log "NT dataset selected")
        else                   → TherapyMappingError("unknown_classification")  (defensive; §10.1)
  3. index = build_domain_index(dataset)          # read-only forward-fill, §9.2
        if index is empty:  warn "empty_dataset"  (strict → raise)
  4. Short-circuit: if filtered.is_empty →
        return DomainTherapyResult with empty mappings/unmapped  (log "no actionable domains").
  5. For each score in filtered.filtered_scores (IN ORDER):
        key = domain_key(score.domain)                 # §9.3
        hit = index.get(key)
        if hit is None:
            record UnmappedDomain(reason="domain_not_found"|"empty_dataset")
            log "domain not found"; (strict → raise "domain_not_found")
            continue
        therapies = tuple(TherapyRef(therapy=row.modality,
                                     relevance=row.relevance,
                                     source_row=row.source_row)
                          for row in hit.rows)          # Excel order, verbatim, NO dedupe
        append DomainTherapyMapping(domain=score.domain,        # verbatim
                                    severity=score.severity,    # verbatim
                                    matched_domain=hit.display_name,
                                    therapies=therapies)
        log "domain matched" (domain, n therapies)
  6. Build diagnostics (counts + warnings).
  7. log "mapping completed" (mapped, unmapped, total therapies).
  8. return DomainTherapyResult(...)
```

Any unexpected exception is wrapped/logged as **"mapping failed"** and re-raised as `TherapyMappingError("internal_error", …)`.

---

## 7. Input structure

### 7.1 `FilteredRoadmapResult` (from the severity filter — `app/roadmap/models.py:93`)

| Field | Type | Used how |
|---|---|---|
| `user_id` | `str` | Carried to output; log correlation only |
| `classification` | `Literal["ND","NT"]` | **Dataset selector** |
| `classification_raw` | `str` | Carried for provenance |
| `filtered_scores` | `list[FilteredDomainScore]` | The domains to map, **in order** |
| `dropped` / `diagnostics` | — | **Ignored** (the severity filter's concern) |
| `is_empty` (property) | `bool` | Short-circuit (§6.4) |

`FilteredDomainScore`: `domain: str` (verbatim, e.g. `"Sensory Processing"`), `score`, `severity: Optional[str]` (verbatim, e.g. `"High"`), `severity_key`, `severity_rank`. Only `domain` and `severity` are read here.

### 7.2 `MappingBundle` (from Excel loader — `app/roadmap/mapping_models.py:64`)

| Field | Type | Used how |
|---|---|---|
| `neurodivergent` | `MappingDataset` | Selected when `classification=="ND"` |
| `neurotypical` | `MappingDataset` | Selected when `classification=="NT"` |

`MappingDataset.rows: tuple[ModalityRow, …]` — file order, verbatim. Each `ModalityRow`:

| Field | Type | Meaning for this module |
|---|---|---|
| `domain` | `Optional[str]` | **May be `None` on continuation rows** (merged cell) → forward-fill (§9.2). Excel values are ordinal-prefixed, e.g. `"A. Sensory Processing"`. |
| `track` | `Optional[str]` | `"Spine"` / `"Complementary"` — **carried but not interpreted** (out of scope) |
| `modality` | `str` | **The therapy name** — always present |
| `relevance` | `Optional[str]` | `"Primary"` / `"Secondary"` / `"Complementary"` / `None` — carried verbatim |
| `source_row` | `int` | 1-based sheet row — carried as provenance |

> **The single most important input fact:** in the real workbooks the Domain column is *merged*. Row 5 carries `domain="A. Sensory Processing"`; rows 6+ that belong to the same domain carry `domain=None`. The loader **deliberately** preserves that `None` and hands forward-fill to *this* module (`mapping_models.py:19-31`). Resolving it (§9.2) is a **prerequisite for any matching at all** — it is not "roadmap generation" and it is not a mutation of the mapping data.

---

## 8. Output structure

### 8.1 Object model (`app/roadmap/therapy_models.py`, all frozen)

```python
class TherapyRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    therapy: str                    # = ModalityRow.modality, verbatim
    relevance: Optional[str] = None # = ModalityRow.relevance, verbatim (may be None)
    source_row: int                 # provenance

class DomainTherapyMapping(BaseModel):
    model_config = ConfigDict(frozen=True)
    domain: str                     # incoming FilteredDomainScore.domain, verbatim
    severity: Optional[str] = None  # incoming severity, verbatim
    matched_domain: str             # the Excel domain label that matched (e.g. "A. Sensory Processing")
    therapies: tuple[TherapyRef, ...]   # Excel row order; NOT deduped, NOT ranked

class UnmappedDomain(BaseModel):
    model_config = ConfigDict(frozen=True)
    domain: str
    severity: Optional[str] = None
    reason: Literal["domain_not_found", "empty_dataset"]

class TherapyMappingDiagnostics(BaseModel):
    model_config = ConfigDict(frozen=True)
    classification: Literal["ND", "NT"]
    dataset_source: Literal["ND", "NT"]
    total_domains: int
    total_mapped: int
    total_unmapped: int
    total_therapies: int
    warnings: tuple[str, ...] = ()

class DomainTherapyResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    user_id: str
    classification: Literal["ND", "NT"]
    mappings: tuple[DomainTherapyMapping, ...]
    unmapped: tuple[UnmappedDomain, ...]
    diagnostics: TherapyMappingDiagnostics

    def to_list(self) -> list[dict]:
        """The brief's exact JSON shape (matched domains only)."""
        return [
            {
                "domain": m.domain,
                "severity": m.severity,
                "therapies": [
                    {"therapy": t.therapy, "relevance": t.relevance}
                    for t in m.therapies
                ],
            }
            for m in self.mappings
        ]
```

### 8.2 `to_list()` output — matches the brief exactly

```json
[
  {
    "domain": "Sensory Processing",
    "severity": "High",
    "therapies": [
      { "therapy": "MNRI",        "relevance": "Primary"   },
      { "therapy": "Feldenkrais", "relevance": "Secondary" }
    ]
  },
  {
    "domain": "Cognitive Function",
    "severity": "Moderate",
    "therapies": [
      { "therapy": "Arrowsmith", "relevance": "Primary" },
      { "therapy": "Stowell",    "relevance": "Secondary" }
    ]
  }
]
```

(The richer `DomainTherapyResult` — with `matched_domain`, `source_row`, `unmapped`, and diagnostics — is what the downstream roadmap-generation module consumes; `to_list()` is the thin view for logging / API echo.)

---

## 9. Mapping rules

### 9.1 Dataset selection

| `classification` | Dataset | Log |
|---|---|---|
| `"ND"` | `bundle.neurodivergent` | `ND dataset selected` |
| `"NT"` | `bundle.neurotypical` | `NT dataset selected` |
| anything else | — | `TherapyMappingError("unknown_classification")` (defensive; the `Literal` type makes this unreachable in normal flow, §10.1) |

### 9.2 Domain index construction (forward-fill of the merged Domain column) — **read-only**

Build a new local mapping `key → DomainGroup` by walking `dataset.rows` **once, in file order**, carrying the last-seen domain forward:

```
current_key = None ; current_display = None
for row in dataset.rows:                       # rows are frozen; we never write to them
    if row.domain is not None and row.domain.strip() != "":
        current_display = row.domain           # verbatim, e.g. "A. Sensory Processing"
        current_key     = domain_key(row.domain)
        index.setdefault(current_key, DomainGroup(display_name=current_display, rows=[]))
    if current_key is None:
        # a therapy row before any domain header — orphan; warn + skip (§10.6)
        warn("orphan_row", row.source_row); continue
    index[current_key].rows.append(row)         # append to the LOCAL group, in order
```

Notes:
- `DomainGroup.rows` preserves **Excel row order**; duplicates are kept.
- The loaded `ModalityRow`s are appended **by reference** into a new list — no copy, no mutation.
- If two separated blocks share the same domain key, they merge under one key (documented behavior); order is first-seen-row order across both blocks.
- The index may be **memoized per dataset** (keyed on `id(dataset)` or the dataset's identity), since the bundle is immutable — safe and O(1) on repeat calls.

### 9.3 Domain-name matching key (throwaway normalization — never written to output)

`domain_key(value)` derives a canonical comparison key and is used for **both** sides (Excel domain and incoming domain):

1. `None`/non-`str` → `None` (no match).
2. Unicode NFKC normalize (consistent with `severity_filter._normalize`).
3. **Strip a leading ordinal prefix**: regex `^\s*[A-Za-z0-9]+[.)]\s+` → removes `"A. "`, `"1) "`, `"iv. "`, etc. This is what makes Excel's `"A. Sensory Processing"` match the incoming `"Sensory Processing"`.
4. Collapse internal whitespace (`" ".join(split())`).
5. `casefold()` (Unicode-correct caseless match).

Examples (all map to key `sensory processing`): `"A. Sensory Processing"`, `"Sensory Processing"`, `"  sensory   processing "`, `"SENSORY PROCESSING"`.

> The key is **only** a lookup device. Output always carries the incoming `domain` (from `FilteredDomainScore`) and, for provenance, the Excel `matched_domain` — both verbatim.

### 9.4 Therapy assembly (per matched domain)

- Emit **one `TherapyRef` per row** in the domain group, in order.
- `therapy = row.modality` (verbatim), `relevance = row.relevance` (verbatim, may be `None`), `source_row = row.source_row`.
- **No** dedup, **no** sort, **no** `Track` grouping, **no** relevance ranking.

---

## 10. Validation rules (edge cases)

| # | Condition | Behavior (`strict=False`, prod) | Behavior (`strict=True`) |
|---|---|---|---|
| 1 | **Unknown classification** (not ND/NT) | `TherapyMappingError("unknown_classification")` — *both* modes (a bad selector cannot yield any correct answer; the `Literal` type makes it unreachable in practice) | same |
| 2 | **Unknown domain** (no index key match) | record `UnmappedDomain(reason="domain_not_found")`, warn, continue | raise `TherapyMappingError("domain_not_found")` |
| 3 | **Empty mapping** (dataset produced an empty index) | every domain → `UnmappedDomain(reason="empty_dataset")`, warn once | raise `TherapyMappingError("empty_dataset")` |
| 4 | **Empty filtered result** (`filtered.is_empty`) | return empty `mappings`/`unmapped`, INFO log — **not** an error (user scored Low everywhere) | same (not an error) |
| 5 | **Missing therapy** (`modality`) | cannot occur — loader guarantees `modality` is always present (`mapping_models.py:37`); document as invariant | same |
| 6 | **Missing relevance** (`None`/blank) | preserve verbatim → `relevance: null` in output; no warning | same |
| 7 | **Duplicate therapy rows** | keep **all**, in order — dedup is out of scope | same |
| 8 | **Invalid / anomalous row** | already dropped or rejected by the loader; not re-validated here | same |
| 9 | **Null domain in Excel** | expected (merged-cell continuation) — resolved by forward-fill (§9.2), never treated as a miss | same |
| 10 | **Case / whitespace mismatch** | absorbed by `domain_key` (§9.3) | same |
| 11 | **Ordinal-prefix mismatch** (`"A. X"` vs `"X"`) | absorbed by `domain_key` prefix-strip (§9.3) | same |
| 12 | **Orphan therapy row** (before any domain header) | warn `orphan_row`, skip that row | warn + skip (not fatal) |
| 13 | **Wrong input types** | `TypeError` (fail fast — a programming error, not user data) | same |
| 14 | **Duplicate domains in filtered input** | the severity filter already de-duplicated; if two survive, each is mapped independently (documented) | same |

---

## 11. Error handling

Single typed error, mirroring `MappingLoadError` / `RoadmapValidationError`:

```python
class TherapyMappingError(Exception):
    def __init__(self, code: str, message: str,
                 classification: Optional[str] = None,
                 domain: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code            # machine-readable (table below)
        self.message = message
        self.classification = classification
        self.domain = domain
```

| `code` | Raised when | Modes |
|---|---|---|
| `unknown_classification` | selector ∉ {ND, NT} | always |
| `empty_dataset` | selected dataset yields an empty index | strict only |
| `domain_not_found` | an incoming domain matches nothing | strict only |
| `internal_error` | any unexpected exception (wrapped) | always |

`TypeError` is raised (not `TherapyMappingError`) for wrong-typed arguments — that is a caller bug, surfaced loudly. The function **never** returns a partial result on a raised error.

---

## 12. Logging strategy

Logger: `logging.getLogger("app.roadmap.therapy_mapper")`. User-controlled values logged with `%r` (log-injection safe), consistent with `severity_filter.py`.

| Event | Level | Message (fields) |
|---|---|---|
| Mapping started | INFO | `mapping started: user_id=%s classification=%s domains=%d` |
| ND dataset selected | INFO | `ND dataset selected: rows=%d` |
| NT dataset selected | INFO | `NT dataset selected: rows=%d` |
| Index built | DEBUG | `domain index built: keys=%d source=%s` |
| Empty dataset | WARNING | `empty mapping dataset: source=%s` |
| No actionable domains | INFO | `mapping skipped: user_id=%s no actionable domains` |
| Domain matched | DEBUG | `domain matched: user_id=%s domain=%r therapies=%d` |
| Domain not found | WARNING | `domain not found: user_id=%s domain=%r source=%s` |
| Orphan row | WARNING | `orphan therapy row skipped: source=%s row=%d` |
| Mapping completed | INFO | `mapping complete: user_id=%s mapped=%d unmapped=%d therapies=%d` |
| Mapping failed | ERROR | `mapping failed: code=%s domain=%r: %s` |

Rationale for levels: `domain matched` is the high-frequency normal case → DEBUG (keeps on-call signal clean, mirroring `filter keep`); every **miss** is WARNING because an unmatched actionable domain is a genuine data-quality signal.

---

## 13. Testing strategy

`tests/test_therapy_mapper.py`. Fixtures build tiny in-memory `MappingBundle` / `FilteredRoadmapResult` objects — **no `.xlsx` is opened in tests** (that is the loader's own test suite). One integration test may call the real `load_mappings()` against `data/roadmap/` to prove the two modules compose.

| Layer | What it proves |
|---|---|
| Unit | Dataset selection, `domain_key` normalization, forward-fill index, per-domain therapy assembly, order preservation. |
| Integration | Real loader → filter → mapper end-to-end on the shipped workbooks. |
| Validation | Every §10 edge case, both `strict` modes. |
| Failure | `TherapyMappingError` codes; `TypeError` on bad input; no partial result on raise. |
| Performance | Index build is O(rows); 500-domain input maps in well under budget (§13.5). |

### 13.4 Property invariants

- **Order:** for every mapping, `therapies` order == `source_row` ascending within the domain block.
- **Verbatim:** every output `therapy`/`relevance`/`domain`/`severity` is `==` (identity of value) to its source; nothing is re-cased or trimmed.
- **Accounting:** `total_mapped + total_unmapped == len(filtered_scores)`.
- **No dedup:** `sum(len(m.therapies))` == number of matched Excel rows (duplicates included).
- **Purity:** inputs are unchanged after the call (frozen models make this structural).

### 13.5 Performance

- Index build: single O(n) pass over dataset rows (~tens of rows in production).
- Matching: O(1) dict lookup per domain → O(d) total.
- Optional per-dataset memoization of the index (bundle is immutable) makes repeat requests O(d).
- Budget: 500 domains × full ND/NT tables complete in < 50 ms; assert < 250 ms as a guard.

---

## 14. Unit test cases

| # | Name | Given | Then |
|---|---|---|---|
| U1 | `test_selects_nd_dataset` | classification `"ND"` | reads `bundle.neurodivergent` only |
| U2 | `test_selects_nt_dataset` | classification `"NT"` | reads `bundle.neurotypical` only |
| U3 | `test_forward_fill_groups_continuation_rows` | domain row + 2 `domain=None` rows | all 3 therapies grouped under that domain, in order |
| U4 | `test_ordinal_prefix_match` | Excel `"A. Sensory Processing"`, input `"Sensory Processing"` | matched |
| U5 | `test_case_and_whitespace_insensitive` | input `" sensory   PROCESSING "` | matched |
| U6 | `test_preserves_therapy_order` | domain with MNRI then Feldenkrais | output order `[MNRI, Feldenkrais]` |
| U7 | `test_preserves_relevance_verbatim` | relevance `"Secondary"` / `None` | echoed verbatim (incl. `null`) |
| U8 | `test_keeps_duplicate_therapy_rows` | same therapy twice | both present |
| U9 | `test_domain_verbatim_in_output` | input `"Sensory Processing"` | output `domain` is the **input** string, `matched_domain` is `"A. Sensory Processing"` |
| U10 | `test_to_list_shape` | one mapping | exact brief JSON |
| U11 | `test_track_not_interpreted` | Spine + Complementary rows | both returned; no grouping/split |
| U12 | `test_orphan_row_skipped` | therapy row before any header | skipped + warned, others fine |

## 15. Integration test cases

| # | Name | Then |
|---|---|---|
| I1 | `test_end_to_end_nd` | `load_mappings(data/roadmap)` + real ND filtered result → correct therapies for a known domain |
| I2 | `test_end_to_end_nt` | same for NT (incl. a Complementary-track domain) |
| I3 | `test_filter_then_map_compose` | `filter_by_severity(...)` output feeds `map_domains_to_therapies(...)` unchanged |
| I4 | `test_empty_filtered_result` | `is_empty` result → empty mappings, no error |
| I5 | `test_unknown_domain_prod` | fabricated domain → recorded in `unmapped`, request succeeds |
| I6 | `test_unknown_domain_strict` | same input, `strict=True` → raises `domain_not_found` |
| I7 | `test_bundle_unmutated` | bundle identical (deep) before/after the call |

---

## 16. Acceptance criteria

The module is **complete** when:

- ✅ It reads only the passed-in `MappingBundle` (and `FilteredRoadmapResult`) — never opens, reads, or reloads an `.xlsx`.
- ✅ It selects ND/NT correctly from `classification`.
- ✅ It resolves the merged Domain column by forward-fill and finds matching domains despite ordinal prefixes, case, and whitespace differences.
- ✅ It returns **all** therapies for every matched domain, in **Excel order**, with `relevance` preserved verbatim (including `None`).
- ✅ It preserves the incoming `domain` and `severity` verbatim.
- ✅ It records (never silently drops) unmatched domains and emits the §12 logs.
- ✅ It performs **no** severity filtering, **no** dedup, **no** ranking, **no** Spine/Complementary grouping, **no** roadmap generation, and **no** mutation of either input.
- ✅ `strict` semantics, all §10 edge cases, and every §14–§15 test pass.
```
