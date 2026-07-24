# Manasi AI — Roadmap Pipeline **Step 1: Excel Mapping Loader** — Technical Specification

**Module:** `app/roadmap/mapping_loader.py`
**Status:** Specification (implementation pending)
**Scope owner:** Roadmap / Therapy-Mapping pipeline
**Depends on:** `openpyxl==3.1.5` (new dependency — see Appendix A), `app.config.settings`
**Consumed by:** Therapy Mapping module (Step 2+), *not defined here*

---

## Confirmed scope (this revision)

Four decisions are fixed for Step 1 and everything below conforms to them:

1. **A separate module — `app/roadmap/mapping_loader.py`.** `roadmap_loader.py` already owns loading the **frontend JSON payload**; the Excel mapping loader is a distinct concern and gets its own file. The two are never merged. (§4.2)
2. **`openpyxl==3.1.5` is the reader dependency**, added to `requirements.txt`. It is not currently installed as a project dependency. (Appendix A, AC-12)
3. **The loader does exactly three things and nothing more:**
   - Load the ND (`Neurodivergent_map.xlsx`) and NT (`Neurotypical_map.xlsx`) Excel files.
   - Validate the required **worksheet** and the four required **columns**.
   - Load the rows into memory as immutable models.
   (§2.1, §3.1)
4. **No downstream logic in this step** — no domain lookup, no therapy mapping, no filtering, no roadmap generation. Those build *from* this loader's output in later modules. (§2.2, §3.2)

---

## 0. Reader's note — three facts about the real files you must not skip

This spec was written **against the actual workbooks** in `data/roadmap/`, not against the idealized column list in the brief. Three things are true of the real files and every design decision below follows from them. If you implement to the brief instead of to the files, the loader will not load them.

1. **The header is not the first row.** Each sheet opens with a merged title banner (`"Neurodivergent Path - Domain to Modality"`), then two blank rows, and only then the real header row (`Domain | Track | Suggested modalities (in order) | Relevance`). In the current ND file that header sits at **sheet row 4** (0-based index 3). The loader therefore **discovers** the header row; it never assumes row 1.

2. **The column is spelled `Suggested modalities (in order)` — lowercase `m`.** The brief writes `Suggested Modalities`. Column validation is therefore **case- and whitespace-insensitive** (normalized match), never an exact-string equality.

3. **`Domain` and `Track` are sparse by design.** A domain that suggests two modalities occupies two rows; `Domain` and `Track` are filled on the **first** row only and are `None` on the continuation row. This is Excel merged-cell / visual-grouping behaviour. Because this module **must not modify data** (see §3.2), those `None`s are preserved **verbatim**. Forward-filling the domain down its group is a *mapping* concern and is explicitly **out of scope** (§2.2). The loader hands the mapping module the exact shape it will need to forward-fill, plus the original row number so it can.

A fourth, minor fact: the two sheets are named **`Neurodivergent Path`** and **`Neurotypical Path`** — not a shared fixed name — so the loader does not hardcode a single worksheet name (§7.3).

---

## 1. Purpose

Provide a single, self-contained module whose **only** responsibility is to **locate, open, validate, and load** the two Excel mapping workbooks into immutable in-memory datasets, and to return them.

The loader is the **one place** in the codebase that touches the `.xlsx` binary format, mirroring the project's existing "one loader owns the raw format" pattern (`roadmap_loader.py` owns the raw frontend JSON; `cta_loader.py` owns the raw CTA corpus). Every downstream module reads the loader's typed output and never re-opens an Excel file.

This document specifies **Step 1 only**. It contains no therapy lookup, no domain search, no filtering, no roadmap generation, no recommendation logic, no email, no PDF, and no persistence.

---

## 2. Scope

### 2.1 In scope

- Resolving the two file paths under `data/roadmap/`.
- Verifying each file exists, is a regular file, and is readable.
- Opening each workbook safely (corruption / permission / lock handled).
- Selecting the correct worksheet.
- Discovering the header row and validating the four required columns.
- Converting each data row into an immutable `ModalityRow`, **verbatim** (no coercion, no fill, no trimming of meaningful values).
- Returning a `MappingBundle` carrying the ND dataset and the NT dataset.
- Emitting structured logs and raising a typed error on any failure.

### 2.2 Explicitly out of scope (belongs to later modules)

- ❌ Mapping a domain to therapies / modalities.
- ❌ Searching or matching domains.
- ❌ Forward-filling sparse `Domain`/`Track` cells across a group.
- ❌ Filtering by severity, relevance, or track.
- ❌ Roadmap generation / recommendation ranking.
- ❌ Email or PDF generation.
- ❌ Database or cache persistence.
- ❌ Editing, rounding, re-casing, or re-ordering any cell value.

The immutability guarantee (§3.3) is the hard boundary between this module and all of the above.

---

## 3. Module Responsibilities

### 3.1 Positive responsibilities — the module MUST

| # | Responsibility |
|---|----------------|
| R1 | Resolve the ND and NT file paths from a configurable base directory. |
| R2 | Verify each file exists and is a regular, readable file. |
| R3 | Open each workbook in read-only, data-only mode. |
| R4 | Select the target worksheet per file. |
| R5 | Discover the header row and resolve the four required columns to their positions. |
| R6 | Validate columns: all four present, none duplicated. |
| R7 | Read every data row into a `ModalityRow`, preserving values verbatim. |
| R8 | Skip fully-blank rows and stop cleanly at end-of-data (blank-row sentinel). |
| R9 | Return one `MappingBundle` (ND + NT datasets). |
| R10 | Log every milestone and raise one typed error class on any failure. |

### 3.2 Negative responsibilities — the module MUST NOT

- Modify, coerce, round, re-case, re-order, or fill any cell value.
- Interpret domain/track/relevance semantics.
- Perform any mapping, filtering, ranking, or recommendation.
- Touch the network, the database, the filesystem beyond reading the two inputs, or any global state.
- Depend on any downstream module (no imports from therapy-mapping / roadmap-generation packages).

### 3.3 The immutability guarantee

Every value that reaches a `ModalityRow` field arrives **exactly as `openpyxl` returned it** — same type, same case, same whitespace, same `None`. The models are frozen (Pydantic `model_config = ConfigDict(frozen=True)` / immutable dataclass). The **only** transformation the loader performs on a value is for *matching header cells* (a local, throwaway normalization used to find columns — see §7.2); that normalized form is never written into the returned data. This is the same discipline as `RoadmapDomainScore` ("stored verbatim … never recomputed", `models.py`).

---

## 4. Architecture

### 4.1 Governing principles (inherited from the project)

- **Single Responsibility.** The module loads Excel and nothing else.
- **One owner of the raw format.** All `.xlsx` knowledge lives here; downstream speaks only in typed models.
- **Pure & deterministic.** Same files in → same datasets out. No side effects beyond logging.
- **Fail loud, fail typed.** Any problem raises `MappingLoadError` carrying a machine-readable `code`; the loader never returns a partial or "best-effort" dataset.
- **Open/Closed.** Required columns, the base directory, and file identities are declared as data (constants/config), so adding a column or a third path is a one-line change.

### 4.2 Placement in the package

```
app/roadmap/
├── __init__.py
├── models.py              # existing roadmap models (unchanged)
├── mapping_models.py      # NEW — ModalityRow, MappingDataset, MappingBundle
├── mapping_loader.py      # NEW — this module
├── roadmap_loader.py      # existing — frontend PAYLOAD loader (unrelated)
├── severity_filter.py     # existing — Step 2
└── ...
```

> **Naming note.** `roadmap_loader.py` already exists and loads the **frontend JSON payload**. This Excel loader is a *different* concern and takes a distinct name (`mapping_loader.py`) to avoid any confusion between "load the user's submission" and "load the mapping reference data".

New models live in `mapping_models.py` to keep the loader file focused on behaviour, matching the `models.py` + logic-module split already used across the package.

### 4.3 Layered view

```
        Caller (Therapy Mapping module, tests, warm-up hook)
                          │  load_mappings()
                          ▼
   ┌───────────────────────────────────────────────┐
   │ mapping_loader.py  (orchestration + validation)│
   │   load_mappings → _load_one → _read_sheet      │
   └───────────────────────────────────────────────┘
             │ reads                    ▲ returns
             ▼                          │
   data/roadmap/*.xlsx          MappingBundle (frozen)
        (openpyxl, read-only)   mapping_models.py
```

### 4.4 SOLID quick-map

- **S** — one class of work: Excel → typed rows.
- **O** — `REQUIRED_COLUMNS`, `_FILES`, and `base_dir` are data; extension needs no logic edit.
- **L** — ND and NT datasets are the same type; either is substitutable everywhere a `MappingDataset` is expected.
- **I** — the public surface is one function returning one object; callers depend on nothing else.
- **D** — the loader depends on the `openpyxl` abstraction and an injected `base_dir`, not on hardcoded absolute paths.

### 4.5 Reusability

`load_mappings(base_dir=...)` accepts an injected directory, so the same code loads production data, a test fixtures folder, or a future locale-specific mapping set without modification.

---

## 5. Processing Flow

```
Backend / caller starts
        │
        ▼
load_mappings(base_dir=None, strict=True)
        │
        ├─ resolve base_dir  (arg → settings → data/roadmap default)          [R1]
        │
        ├─ for each of { ND: Neurodivergent_map.xlsx, NT: Neurotypical_map.xlsx }:
        │        │
        │        ▼   _load_one(path, source, expected_sheet)
        │   ┌──────────────────────────────────────────────┐
        │   │ 1. exists? regular file? readable?            │ [R2] → file_not_found /
        │   │                                               │        not_a_file /
        │   │                                               │        permission_denied
        │   │ 2. open workbook (read_only, data_only)       │ [R3] → workbook_unreadable
        │   │ 3. select worksheet                           │ [R4] → missing_worksheet
        │   │ 4. discover header row (scan first N rows)    │ [R5] → header_not_found /
        │   │                                               │        empty_worksheet
        │   │ 5. resolve + validate 4 required columns      │ [R6] → missing_column /
        │   │                                               │        duplicate_column
        │   │ 6. iterate data rows → ModalityRow (verbatim) │ [R7] → invalid_cell_type*
        │   │    skip blank rows; stop at blank sentinel    │ [R8]
        │   │ 7. no data rows at all?                        │      → no_data_rows
        │   │ 8. close workbook (finally)                   │
        │   └──────────────────────────────────────────────┘
        │        │ MappingDataset
        │        ▼
        └─ assemble MappingBundle(neurodivergent=…, neurotypical=…)          [R9]
                 │
                 ▼
           return bundle   (log: "mapping load complete: ND=%d NT=%d rows")  [R10]
```

`* invalid_cell_type` is raised only in `strict=True` and only for a *required* cell whose type is nonsensical (e.g. a modality that is a formula-error object). See §7.5.

---

## 6. Input Files

| Identity | Filename | Sheet (observed) | Notes |
|----------|----------|------------------|-------|
| ND | `Neurodivergent_map.xlsx` | `Neurodivergent Path` | Larger; read-only reports max_row = 1,048,576 (trailing empties). |
| NT | `Neurotypical_map.xlsx` | `Neurotypical Path` | ~20 data rows. |

Base directory resolution order (first hit wins):

1. `base_dir` argument, if provided.
2. `settings.ROADMAP_MAPPING_DIR`, if configured.
3. Default: `<repo>/data/roadmap/`.

**Observed layout of each sheet** (indices 0-based):

```
row 0 : ["Neurodivergent Path - Domain to Modality", None, None, None]   ← title banner
row 1 : [None, None, None, None]                                          ← blank
row 2 : [None, None, None, None]                                          ← blank
row 3 : ["Domain", "Track", "Suggested modalities (in order)", "Relevance"] ← HEADER
row 4 : ["A. Sensory Processing", "Spine", "MNRI", "Primary"]             ← data
row 5 : [None, None, "Feldenkrais", "Secondary"]                          ← data (sparse)
row 6 : ["B. Auditory & Language", "Spine", "Tomatis", "Primary"]
...
```

The sparse continuation rows (row 5 above) are the merged-cell pattern from §0.3.

---

## 7. Validation Rules

### 7.1 File-level (per file, before opening)

| Code | Condition |
|------|-----------|
| `file_not_found` | Path does not exist. |
| `not_a_file` | Path exists but is a directory / symlink target missing / not a regular file, or extension is not `.xlsx`. |
| `permission_denied` | Path exists but is not readable (`os.access` false, or `PermissionError` on open). |

### 7.2 Column resolution & the normalization used for matching

Header cells are matched to required columns by a **local normalization** applied to the header text only:

```
_norm(s) = collapse_internal_whitespace(str(s).strip()).casefold()
# "Suggested modalities  (in order)" → "suggested modalities (in order)"
```

Required columns (declared once, as data):

```python
REQUIRED_COLUMNS = ("Domain", "Track", "Suggested modalities (in order)", "Relevance")
```

Matching is `_norm(header_cell) == _norm(required)`. This is why the file's lowercase `modalities` still matches the brief's `Modalities`.

| Code | Condition |
|------|-----------|
| `header_not_found` | No row within the first `HEADER_SCAN_LIMIT` (default 20) non-empty-ish rows contains all four required columns (after normalization). |
| `missing_column` | Header row found but one or more required columns absent. Error names the missing column(s). |
| `duplicate_column` | Two header cells normalize to the same required column (ambiguous — which one is the data?). |

**Unexpected / extra columns are NOT an error.** They are logged at `INFO` (`extra columns ignored: [...]`) and simply not read. This keeps the loader forward-compatible with files that gain annotation columns.

### 7.3 Worksheet selection

Order (first hit wins), per file:

1. The file's **expected sheet name** if present (`Neurodivergent Path` / `Neurotypical Path`), matched case-insensitively.
2. If the workbook has exactly **one** sheet, use it.
3. Otherwise → `missing_worksheet` (names the sheets that *are* present).

| Code | Condition |
|------|-----------|
| `missing_worksheet` | Expected sheet absent and workbook has ≠ 1 sheet. |
| `empty_worksheet` | Selected sheet has zero non-empty rows. |

### 7.4 Row rules

- A **fully-blank** row (every cell in the four required columns is `None` or blank-string) is **skipped**, not stored, and not counted.
- A row is a **content row** if its *modality* cell (the `Suggested modalities (in order)` column) is non-blank. Content rows are stored.
- `Domain`, `Track`, and `Relevance` may be `None` on a content row (the sparse pattern) — this is **valid** and preserved verbatim.
- End-of-data is detected by a **blank-row sentinel**: after the last content row, `MAX_TRAILING_BLANK_ROWS` (default 50) consecutive blank rows terminate the scan. This is what stops the ND read-only iterator from walking to row 1,048,576 (see §10, "Large workbook").

| Code | Condition |
|------|-----------|
| `no_data_rows` | Header found and valid, but zero content rows before the sentinel/end. |

### 7.5 Cell type handling

Values are stored **verbatim** — strings, numbers, `None` all pass through. The loader does **not** coerce types. In `strict=True`, the single exception is a *required modality cell* holding an openpyxl error sentinel (e.g. `#REF!` / `ArrayFormula`), which raises `invalid_cell_type` (that row's therapy is unrecoverable). In `strict=False`, such a row is dropped and recorded in `MappingDataset.warnings` instead of failing the whole load. Every other column's odd types are preserved without comment.

---

## 8. Output Structure

All three models are **frozen** (immutable).

```python
# app/roadmap/mapping_models.py
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict


class ModalityRow(BaseModel):
    """One row of a mapping sheet, VERBATIM. `domain`/`track`/`relevance` are
    Optional because the source uses merged cells: on a continuation row they
    arrive as None and are preserved as None (spec §0.3, §3.3). `modality` is
    the only always-present field (a row with no modality is not stored).
    `source_row` is the 1-based sheet row number, so the mapping module can
    forward-fill / cite provenance without this loader having interpreted it."""
    model_config = ConfigDict(frozen=True)

    domain: Optional[str] = None
    track: Optional[str] = None
    modality: str
    relevance: Optional[str] = None
    source_row: int


class MappingDataset(BaseModel):
    """The fully-loaded contents of ONE workbook. No business meaning is
    attached to `rows`; they are in file order, verbatim."""
    model_config = ConfigDict(frozen=True)

    source: Literal["ND", "NT"]
    path: str
    sheet_name: str
    header_row: int              # 1-based sheet row where the header was found
    rows: tuple[ModalityRow, ...]
    warnings: tuple[str, ...] = ()

    @property
    def row_count(self) -> int:
        return len(self.rows)


class MappingBundle(BaseModel):
    """What load_mappings() returns: both datasets, side by side. Deliberately
    NOT a dict keyed by a stringly-typed label — the two paths are named so
    callers get autocompletion and cannot typo the key."""
    model_config = ConfigDict(frozen=True)

    neurodivergent: MappingDataset
    neurotypical: MappingDataset
```

### 8.1 Public API

```python
# app/roadmap/mapping_loader.py
def load_mappings(
    base_dir: str | Path | None = None,
    *,
    strict: bool = True,
) -> MappingBundle: ...
```

- `base_dir` — override the input directory (test fixtures, alternate locale). `None` → resolution order in §6.
- `strict` — `True` (default): any malformed required cell fails the load (§7.5). `False`: such rows are dropped into `MappingDataset.warnings`; only structural problems (missing file/column/sheet) still raise.
- **Returns** a `MappingBundle`. **Raises** `MappingLoadError` (only). Never returns a partial bundle.

```python
class MappingLoadError(Exception):
    """The one and only error the loader raises. `code` is machine-readable
    (§9), `message` is human, `source` is 'ND'/'NT'/None, `field` names the
    column/sheet/path at fault when one applies."""
    def __init__(self, code: str, message: str,
                 source: str | None = None, field: str | None = None): ...
```

This mirrors `RoadmapValidationError` in `roadmap_loader.py` (typed `code` + `message` + `field`).

---

## 9. Error Handling

Every failure path raises `MappingLoadError` with one of these codes. The loader wraps low-level exceptions rather than leaking them.

| `code` | Trigger | Underlying exception wrapped |
|--------|---------|------------------------------|
| `file_not_found` | Missing path. | `FileNotFoundError` |
| `not_a_file` | Not a regular `.xlsx` file. | — |
| `permission_denied` | Unreadable / locked. | `PermissionError` |
| `workbook_unreadable` | Corrupt / not a real xlsx / not a zip. | `zipfile.BadZipFile`, `openpyxl.utils.exceptions.InvalidFileException`, `KeyError` from a broken archive |
| `missing_worksheet` | Expected sheet absent, ≠1 sheet. | — |
| `empty_worksheet` | Sheet has no non-empty rows. | — |
| `header_not_found` | No header row within scan limit. | — |
| `missing_column` | Required column absent. | — |
| `duplicate_column` | Two headers map to one required column. | — |
| `no_data_rows` | Header valid, zero content rows. | — |
| `invalid_cell_type` | (strict) Required modality cell is an error object. | — |

Guarantees:

- **Atomic per bundle.** If ND loads but NT fails, `load_mappings` raises — it never returns a half-built bundle.
- **Resource-safe.** Each workbook is closed in a `finally`, including on the error path.
- **No silent skips of structure.** A dropped *data* row (strict=False) is recorded in `warnings`; a dropped *structural* element never happens — it raises.
- **Never leaks openpyxl types.** Callers depend only on `MappingLoadError` and the frozen models.

---

## 10. Edge Cases — explicit dispositions

| Edge case | Disposition |
|-----------|-------------|
| Missing Excel file | `file_not_found`. |
| Incorrect file name / typo | `file_not_found` (path won't resolve). |
| Path is a directory | `not_a_file`. |
| Wrong extension (`.xls`, `.csv`) | `not_a_file` (only `.xlsx` supported by openpyxl read path). |
| Corrupted workbook / truncated zip | `workbook_unreadable`. |
| Password-protected workbook | `workbook_unreadable` (openpyxl cannot open). |
| Workbook open in Excel / lock file | If the OS denies read → `permission_denied`; if a stale `~$` lock only → normal read succeeds. |
| Missing worksheet | `missing_worksheet`. |
| Empty worksheet | `empty_worksheet`. |
| Header not on row 1 | **Normal** — discovered by scan (§0.1). |
| Header column lowercase / extra spaces | **Normal** — normalized match (§0.2, §7.2). |
| Missing required column | `missing_column`. |
| Duplicate column | `duplicate_column`. |
| Unexpected extra columns | Ignored + logged `INFO` (§7.2). |
| Blank rows between title and header | Skipped by the scan. |
| Sparse `Domain`/`Track` (merged cells) | Preserved as `None` verbatim (§0.3). |
| Fully-blank rows inside data | Skipped, uncounted. |
| Trailing blank rows to 1,048,576 (ND) | **Large workbook** — blank-row sentinel (`MAX_TRAILING_BLANK_ROWS`) stops the scan; `read_only=True` keeps memory O(one row) during iteration (§7.4). |
| Invalid data type in a required cell | strict → `invalid_cell_type`; non-strict → dropped to `warnings`. |
| Permission denied | `permission_denied`. |

**Memory / scalability note.** The workbook is opened with `read_only=True, data_only=True`; rows are streamed and materialized only as `ModalityRow`s that survive the blank/skip rules. Peak memory is O(kept rows), not O(sheet dimension) — this is what makes the 1M-row ND dimension a non-issue.

---

## 11. Logging Strategy

Logger: `logging.getLogger("app.roadmap.mapping_loader")` (matching the project's `"app.<pkg>.<module>"` convention). No print statements. The loader never logs full cell contents at `INFO` (a mapping file is reference data, not PII, but the discipline keeps logs terse).

| Level | Event | Example message |
|-------|-------|-----------------|
| INFO | Loader started | `mapping load started: base_dir=%s strict=%s` |
| DEBUG | File resolved | `resolved %s → %s` |
| DEBUG | Header located | `[ND] header at row %d, columns=%s` |
| INFO | Extra columns ignored | `[ND] extra columns ignored: %s` |
| INFO | Workbook loaded | `[ND] workbook loaded: sheet=%r rows=%d` |
| INFO | Both loaded | `mapping load complete: ND=%d rows, NT=%d rows` |
| WARNING | Non-strict row dropped | `[NT] dropped row %d: %s` |
| WARNING | Validation warning | `[ND] %s` |
| ERROR | Validation / load failed | `mapping load failed: code=%s source=%s field=%s: %s` |

Each `ERROR` is logged immediately before the `MappingLoadError` is raised, so the code and the stack co-locate in logs.

---

## 12. Testing Strategy

Test file: `tests/test_mapping_loader.py` (pytest, matching `tests/test_roadmap_loader.py`). Fixtures live in `tests/fixtures/roadmap/` and are generated **programmatically** with openpyxl in a fixture factory, so each malformed case is explicit and version-controlled as code, not as opaque binaries. One integration test additionally runs against the **real** `data/roadmap/` files.

Five categories, per the brief:

1. **Unit** — column normalization, header discovery, path resolution, blank-row sentinel, verbatim preservation, in isolation.
2. **Integration** — full `load_mappings()` against the real ND + NT files.
3. **Validation** — each required-column / worksheet / header rule.
4. **Failure** — each error `code` in §9.
5. **Performance** — the large-dimension ND file and a synthetic wide/tall sheet load within budget and memory bound.

---

## 13. Unit Test Cases

| ID | Name | Assert |
|----|------|--------|
| U-01 | `test_norm_matches_lowercase_modalities` | `_norm("Suggested modalities (in order)") == _norm("Suggested Modalities (in order)")`. |
| U-02 | `test_norm_collapses_whitespace` | `"Suggested   modalities  (in order)"` matches. |
| U-03 | `test_header_discovered_below_banner` | Header at row 4 (banner+2 blanks above) is found; `header_row == 4`. |
| U-04 | `test_header_scan_limit` | Header beyond `HEADER_SCAN_LIMIT` → `header_not_found`. |
| U-05 | `test_sparse_domain_preserved_as_none` | Continuation row keeps `domain is None`, `modality == "Feldenkrais"`. |
| U-06 | `test_values_verbatim` | Cell `"A. Sensory Processing"` stored byte-identical; no strip/case change. |
| U-07 | `test_blank_row_skipped` | An all-`None` interior row is not in `rows`. |
| U-08 | `test_trailing_blank_sentinel_stops_scan` | Sheet with data then 1,048,000 empty rows loads only the data rows. |
| U-09 | `test_source_row_is_sheet_number` | `source_row` equals the true 1-based sheet row. |
| U-10 | `test_extra_column_ignored_not_error` | Adding a 5th column loads fine; logged, not raised. |
| U-11 | `test_single_sheet_autoselected` | Workbook with one sheet loads even if its name is unexpected. |
| U-12 | `test_models_are_frozen` | Mutating a `ModalityRow` field raises. |
| U-13 | `test_base_dir_injection` | `load_mappings(base_dir=fixtures)` reads fixtures, not `data/roadmap`. |

---

## 14. Integration Test Cases

| ID | Name | Assert |
|----|------|--------|
| I-01 | `test_load_real_files` | `load_mappings()` on the real `data/roadmap/` returns a `MappingBundle`; both datasets non-empty. |
| I-02 | `test_real_nd_columns` | ND dataset's discovered columns == the four required (normalized). |
| I-03 | `test_real_first_row` | ND `rows[0] == ModalityRow(domain="A. Sensory Processing", track="Spine", modality="MNRI", relevance="Primary", source_row=5)`. |
| I-04 | `test_real_sheet_names` | ND `sheet_name == "Neurodivergent Path"`, NT `== "Neurotypical Path"`. |
| I-05 | `test_no_mutation_of_source` | File mtime/bytes unchanged after a load (proves read-only). |
| I-06 | `test_idempotent` | Two loads return equal bundles. |

### 14.1 Failure test cases

| ID | Name | Expect `code` |
|----|------|---------------|
| F-01 | missing file | `file_not_found` |
| F-02 | path is a directory | `not_a_file` |
| F-03 | `.csv` renamed to `.xlsx` / truncated zip | `workbook_unreadable` |
| F-04 | `chmod 000` file (skip if root) | `permission_denied` |
| F-05 | expected sheet renamed, 2 sheets present | `missing_worksheet` |
| F-06 | sheet with only a banner, no header | `header_not_found` |
| F-07 | header missing `Relevance` | `missing_column` |
| F-08 | two `Domain` columns | `duplicate_column` |
| F-09 | header present, no data rows | `no_data_rows` |
| F-10 | empty sheet | `empty_worksheet` |
| F-11 | ND ok but NT missing | raises (no partial bundle) |
| F-12 | (strict) modality cell `#REF!` | `invalid_cell_type` |
| F-13 | (non-strict) same file | loads; row in `warnings` |

### 14.2 Performance test cases

| ID | Name | Budget |
|----|------|--------|
| P-01 | `test_large_dimension_load` | Real ND (1M-row dimension) loads in < 1.5 s. |
| P-02 | `test_memory_bound` | Synthetic 5,000-data-row sheet: peak RSS delta stays O(rows), not O(dimension) (asserts read-only streaming). |
| P-03 | `test_wide_sheet` | 50-column sheet with the 4 required among them loads without slowdown. |

---

## 15. Acceptance Criteria

The module is **done** when all of the following hold:

1. `load_mappings()` with no arguments loads the real ND and NT files and returns a `MappingBundle` with both datasets non-empty. **(I-01)**
2. The four required columns are validated **case- and whitespace-insensitively**, so the file's lowercase `modalities` is accepted. **(U-01, I-02)**
3. The header row is **discovered**, not assumed — a file whose header sits below a title banner and blank rows loads correctly. **(U-03, I-03)**
4. Sparse `Domain`/`Track` cells are returned as `None`, **verbatim**, with no forward-fill. **(U-05, I-03)**
5. Every value is byte-identical to the source cell; the source files are provably unmodified after a load. **(U-06, I-05)**
6. The 1,048,576-row ND dimension loads in bounded time and memory via read-only streaming + blank-row sentinel. **(P-01, P-02)**
7. Each error condition in §9 raises `MappingLoadError` with the correct `code`; no low-level openpyxl/zip exception ever escapes. **(F-01 … F-12)**
8. A failure in either file raises — the loader never returns a partial bundle. **(F-11)**
9. Returned models are frozen; a caller cannot mutate loaded data. **(U-12)**
10. The module imports nothing from therapy-mapping / roadmap-generation packages, performs no mapping/filtering/ranking, and touches no network or database. **(code review + import graph)**
11. All 13 unit, 6 integration, 13 failure, and 3 performance tests pass under `pytest tests/test_mapping_loader.py`.
12. `openpyxl` is added to `requirements.txt` and the loader runs on Python 3.12 (project baseline).

---

## Appendix A — Dependency & config changes

- **`requirements.txt`**: add `openpyxl==3.1.5` (or latest 3.1.x). It is currently **not** installed; the loader cannot run without it.
- **`app/config.py`**: optional `ROADMAP_MAPPING_DIR` setting (defaults to `<repo>/data/roadmap`). If not added, the loader falls back to the computed default; the setting is a convenience for deployment overrides.

## Appendix B — What this module deliberately does NOT return

It does **not** return: a domain→therapy map, a de-duplicated domain list, a forward-filled table, a severity-filtered subset, or anything ranked. It returns the two sheets, faithfully, as rows. The very next module in the pipeline (Therapy Mapping) is the first place any of those appears — and it will build them **from** `MappingBundle`, never by reopening an Excel file.
