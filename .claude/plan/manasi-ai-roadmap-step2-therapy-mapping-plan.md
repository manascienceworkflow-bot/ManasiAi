# Implementation Plan — Roadmap Step 2: Domain → Therapy Mapping Module

## Context

The Roadmap Assessment Pipeline already has: an Excel mapping loader (`app/roadmap/mapping_loader.py` → `MappingBundle`, shipped in commit `1362802`) and a severity filter (`app/roadmap/severity_filter.py` → `FilteredRoadmapResult`, shipped). The next module joins those two already-loaded inputs and answers one question per actionable domain: **which therapies does the mapping table list, and in what order?**

The full technical spec is written at `.claude/spec/manasi-ai-roadmap-step2-therapy-mapping-spec.md`. This plan implements exactly that spec — a pure, side-effect-free `map_domains_to_therapies(filtered, bundle, *, strict=False)` function plus its output models and tests. It does **no** Excel I/O, severity filtering, dedup, ranking, `Track` grouping, roadmap generation, or mutation of its inputs.

The one non-obvious piece of real behavior the module must own (the loader explicitly defers it — see `mapping_models.py:19-31`): the Excel **Domain column is merged**, so continuation rows arrive as `domain=None`, and Excel domains are **ordinal-prefixed** (`"A. Sensory Processing"`) while incoming domains are bare (`"Sensory Processing"`). Matching therefore requires (a) forward-filling the domain down the rows into a read-only local index, and (b) a normalization key that strips the ordinal prefix and folds case/whitespace.

## Files to create

| File | Purpose |
|---|---|
| `app/roadmap/therapy_models.py` | Frozen pydantic output models (mirrors `mapping_models.py` style). |
| `app/roadmap/therapy_mapper.py` | `map_domains_to_therapies()`, `TherapyMappingError`, internal index/normalization helpers (mirrors `severity_filter.py` / `mapping_loader.py` style). |
| `tests/test_therapy_mapper.py` | Unit / integration / validation / failure / performance tests. |

No changes to `app/roadmap/__init__.py` (it is empty; the roadmap package does not re-export modules). No new dependencies, no config, no data files. **No wiring into `services.py`/`routes.py`** — see "Integration note" below.

## 1. `app/roadmap/therapy_models.py`

Five frozen models (`model_config = ConfigDict(frozen=True)`, exactly as `mapping_models.py`), per spec §8.1:

- `TherapyRef` — `therapy: str` (= `ModalityRow.modality`), `relevance: Optional[str] = None`, `source_row: int`.
- `DomainTherapyMapping` — `domain: str` (incoming, verbatim), `severity: Optional[str] = None` (incoming, verbatim), `matched_domain: str` (Excel label that matched, e.g. `"A. Sensory Processing"`), `therapies: tuple[TherapyRef, ...]`.
- `UnmappedDomain` — `domain`, `severity`, `reason: Literal["domain_not_found","empty_dataset"]`.
- `TherapyMappingDiagnostics` — `classification`, `dataset_source: Literal["ND","NT"]`, `total_domains`, `total_mapped`, `total_unmapped`, `total_therapies`, `warnings: tuple[str, ...] = ()`.
- `DomainTherapyResult` — `user_id`, `classification`, `mappings: tuple[DomainTherapyMapping, ...]`, `unmapped: tuple[UnmappedDomain, ...]`, `diagnostics`, plus a `to_list()` method returning the brief's exact `[{domain, severity, therapies:[{therapy, relevance}]}]` JSON shape (matched domains only).

## 2. `app/roadmap/therapy_mapper.py`

Follow the house pattern from `mapping_loader.py` / `severity_filter.py`: module docstring stating the single responsibility and what it must NOT do; `logger = logging.getLogger("app.roadmap.therapy_mapper")`; user-controlled values logged with `%r` (log-injection safe, as `severity_filter.py` does).

**Error class** — `TherapyMappingError(code, message, classification=None, domain=None)`, mirroring `MappingLoadError` (`mapping_loader.py:46`). Codes: `unknown_classification`, `empty_dataset`, `domain_not_found`, `internal_error` (spec §11).

**Normalization key** — `domain_key(value)` (throwaway, never written to output): `None`/non-str → `None`; NFKC normalize (as `severity_filter._normalize`); strip leading ordinal prefix via regex `^\s*[A-Za-z0-9]+[.)]\s+`; collapse whitespace (`" ".join(split())`); `casefold()`. (Spec §9.3.)

**Read-only index builder** — walk `dataset.rows` once in file order, carrying the last non-blank `domain` forward; group each row's `(modality, relevance, source_row)` under the current domain key; a row before any domain header is an orphan → warn + skip. Rows are appended **by reference** into a new local structure — the frozen `ModalityRow`s are never mutated. Optionally memoize per dataset keyed on `id(dataset)` (bundle is immutable), per spec §9.2/§13.5.

**Public function** — `map_domains_to_therapies(filtered, bundle, *, strict=False) -> DomainTherapyResult`, following the flow in spec §6:
1. Type-guard both args (`TypeError` on mismatch, as `severity_filter.py:76` does).
2. Select dataset by `classification` (ND → `bundle.neurodivergent`, NT → `bundle.neurotypical`; else `TherapyMappingError("unknown_classification")`).
3. Build index; empty index → warn `empty_dataset` (strict → raise).
4. Short-circuit `filtered.is_empty` → empty result, INFO log (not an error).
5. For each `filtered.filtered_scores` **in order**: match via `domain_key`; miss → record `UnmappedDomain` + WARNING (strict → raise `domain_not_found`); hit → emit one `TherapyRef` per row in Excel order, verbatim `relevance` (incl. `None`), **no dedup/sort/ranking**.
6. Build diagnostics; INFO "mapping complete"; return.

Logging events and levels per spec §12 (matched = DEBUG, every miss = WARNING).

## 3. `tests/test_therapy_mapper.py`

Match existing conventions from `tests/test_mapping_loader.py` and `tests/test_severity_filter.py`: plain pytest functions (no classes), `sys.path.append(...parent.parent)` header, small builder helpers, `pytest.raises(TherapyMappingError) as exc; assert exc.value.code == "..."`. There is **no** `conftest.py` and no pytest config file — keep that pattern.

Helpers to add:
- `_bundle(nd_rows=..., nt_rows=...)` → builds `MappingBundle` in-memory from `ModalityRow` tuples (no `.xlsx` opened — that is the loader's own test's job). Use `None` domains to exercise the merged-cell forward-fill.
- `_filtered(*domains, classification="ND")` → builds `FilteredRoadmapResult` directly from `FilteredDomainScore`s (mirrors `test_severity_filter.py:_result`).

Cover the unit cases U1–U12, integration I1–I7, and property invariants from spec §13–§15, notably:
- Forward-fill groups continuation rows (U3); ordinal-prefix + case/whitespace match (U4/U5); therapy order preserved (U6); relevance verbatim incl. `None` (U7); duplicates kept (U8); `domain` verbatim vs `matched_domain` (U9); `to_list()` shape (U10); `Track` not interpreted (U11); orphan row skipped (U12).
- One integration test may call the real `load_mappings(base_dir="data/roadmap")` to prove loader→mapper compose end-to-end (I1/I2).
- `strict` semantics both ways (I5/I6); `is_empty` → empty result, no error (I4); bundle unmutated after call (I7); accounting `total_mapped + total_unmapped == len(filtered_scores)`.
- One performance test: 500-domain input maps well under budget (assert < 250 ms), per spec §13.5. (No `performance` pytest marker exists in the repo — it is just a normally-named function, matching `test_cta_node.py:397`.)
- **Architecture test** (mirrors `test_severity_filter.py:418-424`): read `therapy_mapper.py` source and assert it does not import `openpyxl`, `fastapi`, `supabase`, `app.db`, and does not call `load_mappings`/`get_mappings`/`filter_by_severity` — structurally enforcing "must not load Excel / must not reload mappings / pure & injected" (spec §2.2, P3).
- **Immutability**: assert output models are frozen (raise on mutation) and the input `bundle`/`filtered` are deep-copy-unchanged after the call (mirrors `test_mapping_loader.py:151-156`, `test_severity_filter.py:308-341`).

## Integration note (deferred — not in this change)

`services.submit_roadmap` currently chains `load_roadmap → filter_by_severity → upsert` and does not yet call the Excel loader or this mapper. Because nothing consumes the therapy-mapping output until roadmap generation (a future module), wiring `map_domains_to_therapies(get_mappings(), filtered)` into `services.py` now would compute an unused result. Per the spec's P3 (the module is a pure function whose caller injects both inputs), that wiring belongs to the future roadmap-generation step and is intentionally **out of scope here**. The module ships standalone + fully tested.

## Verification

1. **Run the new tests:** `source venv/bin/activate && python -m pytest tests/test_therapy_mapper.py -v` — all pass.
2. **No regressions:** `python -m pytest tests/test_mapping_loader.py tests/test_severity_filter.py -q`.
3. **End-to-end smoke against real data** — a throwaway REPL/script (not committed):
   ```
   from app.roadmap.mapping_loader import load_mappings
   from app.roadmap.severity_filter import filter_by_severity
   from app.roadmap.roadmap_loader import load_roadmap
   from app.roadmap.therapy_mapper import map_domains_to_therapies
   bundle = load_mappings(base_dir="data/roadmap")
   filtered = filter_by_severity(load_roadmap(<sample ND payload>))
   print(map_domains_to_therapies(filtered, bundle).to_list())
   ```
   Confirm: an ND `"Sensory Processing"` (High) resolves to `[{therapy:"MNRI",relevance:"Primary"},{therapy:"Feldenkrais",relevance:"Secondary"}]` (the merged rows 5–6 of `Neurodivergent_map.xlsx`), matched despite the `"A. "` prefix; order and relevance preserved; an unknown domain lands in `unmapped` without raising.

## Acceptance criteria (from spec §16)

Reads only the passed-in `MappingBundle`/`FilteredRoadmapResult` (never opens `.xlsx`); selects ND/NT correctly; resolves merged Domain via forward-fill and matches despite ordinal prefix/case/whitespace; returns all therapies per matched domain in Excel order with `relevance` verbatim; preserves incoming `domain`/`severity` verbatim; records (never silently drops) unmatched domains; performs no filtering/dedup/ranking/grouping/roadmap-gen and no input mutation; `strict` semantics and all §14–§15 tests pass.
