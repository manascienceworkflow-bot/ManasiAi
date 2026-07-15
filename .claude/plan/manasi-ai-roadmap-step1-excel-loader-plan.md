# Plan — Roadmap Step 1: Excel Mapping Loader

## Context

The Roadmap / Therapy-Mapping pipeline needs a module that turns the two Excel mapping
workbooks in `data/roadmap/` into typed, in-memory data. Today **nothing** reads these
files — `grep` for `openpyxl|.xlsx|mapping_loader` is empty, and `requirements.txt` has no
Excel reader. The existing `app/roadmap/roadmap_loader.py` loads the **frontend JSON
payload** (a different concern) and must not be conflated with this.

The full design is already written at
`.claude/spec/manasi-ai-roadmap-step1-excel-loader-spec.md`. This plan executes **Step 1
only**: load + validate + hold in memory. **No** domain lookup, therapy mapping, filtering,
or roadmap generation — those build *from* this loader's output in later modules.

Three facts about the real files drive the design (verified by opening them):
1. The header is **not** row 1 — a title banner (row 1) + 2 blank rows sit above it; the real
   header is at sheet row 4. → header row is **discovered**, never assumed.
2. The column reads `Suggested modalities (in order)` (lowercase *m*) vs the brief's
   `Modalities`. → column matching is **case/whitespace-insensitive**.
3. `Domain`/`Track` are **sparse** (merged cells: filled on the first modality row, `None` on
   continuation rows). → preserved **verbatim** as `None`; forward-fill is out of scope.

Also: read-only mode reports ND `max_row = 1,048,576` (trailing empties) → stream with a
blank-row sentinel so memory/time stay bounded.

**Confirmed design choice (user):** lazy module-level cache + a `settings.roadmap_mapping_dir`
config entry, mirroring `cta_loader.py` — but **no** eager import-time warm-up (this loader
raises on bad files; a crash-at-import would break app startup).

## Files to create / modify

### 1. `requirements.txt` (modify)
Add `openpyxl==3.1.5` (version confirmed available in the venv). One line, near the other
data deps.

### 2. `app/config.py` (modify)
Add one path setting next to `cta_data_dir` (line ~60), same idiom:
```python
roadmap_mapping_dir: Path = BASE_DIR / os.getenv("ROADMAP_MAPPING_DIR", "data/roadmap")
```
No change to `Settings.validate()` (path dirs aren't validated at startup — consistent with
existing loaders).

### 3. `app/roadmap/mapping_models.py` (create)
Three **frozen** Pydantic models (`model_config = ConfigDict(frozen=True)`), matching the
verbatim/immutable discipline of `RoadmapDomainScore` in `models.py`:
- `ModalityRow` — `domain/track/relevance: Optional[str] = None`, `modality: str`,
  `source_row: int` (1-based sheet row for provenance).
- `MappingDataset` — `source: Literal["ND","NT"]`, `path: str`, `sheet_name: str`,
  `header_row: int`, `rows: tuple[ModalityRow, ...]`, `warnings: tuple[str, ...] = ()`, plus a
  `row_count` property.
- `MappingBundle` — `neurodivergent: MappingDataset`, `neurotypical: MappingDataset`.

### 4. `app/roadmap/mapping_loader.py` (create — the module)
Logger `logging.getLogger("app.roadmap.mapping_loader")`. Public surface:

```python
class MappingLoadError(Exception):   # code / message / source / field
    ...

REQUIRED_COLUMNS = ("Domain", "Track", "Suggested modalities (in order)", "Relevance")

def load_mappings(base_dir=None, *, strict=True) -> MappingBundle: ...   # dual-mode
def get_mappings(force_reload=False) -> MappingBundle: ...               # lazy cache accessor
def reload_mappings() -> MappingBundle: ...                              # test/hot-reload
```

Internals (mirroring `cta_loader` structure, adapted to xlsx):
- **Dual-mode / cache**: module-level `_CACHE`. `load_mappings(base_dir=None)` resolves
  `settings.roadmap_mapping_dir` and fills/returns `_CACHE`; an explicit `base_dir` always does
  a fresh scan and never touches `_CACHE` (this is what lets tests point at `tmp_path`). **No**
  bare `load_mappings()` at module bottom.
- `_load_one(path, source, expected_sheet)` per file:
  1. exists / regular `.xlsx` / readable → `file_not_found` / `not_a_file` / `permission_denied`
  2. `openpyxl.load_workbook(path, read_only=True, data_only=True)` in a `try`, closed in
     `finally`; wrap `BadZipFile` / `InvalidFileException` → `workbook_unreadable`
  3. select sheet: expected name (case-insensitive) → else single sheet → else
     `missing_worksheet`; empty → `empty_worksheet`
  4. **discover header**: scan first `HEADER_SCAN_LIMIT` (20) rows for one whose normalized
     cells cover all `REQUIRED_COLUMNS` → else `header_not_found`
  5. resolve columns via `_norm(s) = collapse_ws(str(s).strip()).casefold()`;
     `missing_column` / `duplicate_column`; extra columns → log INFO, ignore
  6. stream data rows → `ModalityRow` **verbatim**; skip fully-blank rows; stop after
     `MAX_TRAILING_BLANK_ROWS` (50) consecutive blanks (the 1M-row guard)
  7. zero content rows → `no_data_rows`
  8. `strict`: a required modality cell that is an error object → `invalid_cell_type`;
     non-strict → drop row into `MappingDataset.warnings`
- Atomic: if ND loads but NT fails, raise — never return a partial bundle.
- Logging per spec §11 (started / header at row / workbook loaded / complete / failed).

### 5. `tests/test_mapping_loader.py` (create)
Follow repo conventions (from exploration):
- Top-of-file bootstrap: `sys.path.append(str(Path(__file__).resolve().parent.parent))` +
  `# noqa: E402` on app imports.
- **Synthetic fixtures generated with openpyxl into `tmp_path`** (mirrors the CTA tests'
  `tmp_path` + builder approach): a `_build_map_xlsx(dir_, name, sheet, rows, *, header_row=4,
  omit_col=None, dup_col=None, ...)` helper that writes a workbook with the banner+blank+header
  layout, then `load_mappings(base_dir=tmp_path)`.
- Assert on the typed exception like `test_roadmap_loader.py`:
  `with pytest.raises(MappingLoadError) as exc: ...; assert exc.value.code == "missing_column"`,
  driven by `@pytest.mark.parametrize` for the failure matrix.
- **One real-file regression test** (mirrors `test_real_cta_corpus_loads...`):
  `load_mappings()` on the actual `data/roadmap/` files asserts ND `rows[0] ==
  ModalityRow(domain="A. Sensory Processing", track="Spine", modality="MNRI",
  relevance="Primary", source_row=5)` and sheet names.
- Cover: header discovery below banner, lowercase-column match, sparse `None` preserved,
  verbatim values, blank-row skip, trailing-blank sentinel, frozen models, extra-column-ignored,
  and each error `code`. (Spec §13–14.)

### 6. Copy plan to `.claude/plan/` (per the request)
As the first implementation action, copy this plan to
`.claude/plan/manasi-ai-roadmap-step1-excel-loader-plan.md` (that dir doesn't exist yet; create
it). Plan mode only permits editing the canonical plan file, so this copy happens once
implementation begins.

## What is explicitly NOT in this step
No forward-fill, no domain→therapy map, no severity/relevance filtering, no ranking, no
roadmap generation, no persistence, no network, no eager import-time load. The loader returns
the two sheets faithfully as rows and stops there.

## Verification
1. `pip install openpyxl==3.1.5` (already present in venv; ensures the pin resolves).
2. `python -c "from app.roadmap.mapping_loader import load_mappings; b = load_mappings();
   print(b.neurodivergent.row_count, b.neurotypical.row_count,
   b.neurodivergent.rows[0])"` — prints non-zero counts and the first ND row loaded verbatim.
3. `pytest tests/test_mapping_loader.py -q` — all unit / validation / failure / integration
   tests pass.
4. Confirm no regression: `pytest -q` (whole suite) still green; `app/roadmap/roadmap_loader.py`
   untouched; app import does not eagerly load Excel (grep the module for a bare
   `load_mappings()` call → none).
5. Prove immutability: assert the source `.xlsx` bytes/mtime are unchanged after a load.
