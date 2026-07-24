# Implementation Plan — Manasi AI CTA Data Loader (`cta_loader.py`)

**Source spec:** `.claude/spec/manasi-ai-cta-loader-spec.md` (read in full; verified against current repo state — 15 CTA files exist, no `cta_loader.py`/`test_cta_loader.py` yet, `git status` clean except the new spec file).

## Context

`data/cta/` holds 15 hand-authored Markdown files (one per Call-To-Action, across `therapies/`, `conditions/`, `faq/`, `courses/`, `subscription/`, `about/`, `community/`, `privacy/`, `neuroplasticity/`) that nothing in the codebase currently reads. An earlier, much simpler CTA registry (a flat `key=value` file plus `cta_service.py`/`cta_node.py`) was built and then reverted (`3b08629` → `e4a56ee`) because the data model changed entirely — today's files encode match rules, dozens of grouped trigger examples, aliases, exclusion rules, and fallback rules directly in content, not a side-channel tag. This plan implements the loader spec just written: a pure, deterministic, LLM-free module that scans this directory, parses each file into a typed `CTARecord`, validates it, caches the result in memory, and exposes six read-only accessor functions. It deliberately does **not** implement any matching/decision logic — that's a future, separate CTA Node spec. The intended outcome is a stable foundation that node can be built on later, fully covered by tests today.

Conventions confirmed directly from the live repo (not just the spec's prose):
- `app/config.py` is a flat `Settings` class, one `field: type = os.getenv("ENV_VAR", "default")` line per setting (e.g. `vectorstore_dir: Path = BASE_DIR / os.getenv("VECTORSTORE_DIR", "vectorstore")`); `.env.example` mirrors it with a commented-out line per setting.
- `app/services/empathy_service.py`/`safety_service.py` use `logging.getLogger("app.services.<module>")` and `@dataclass` for lightweight non-Pydantic structures.
- `app/validators/*.py` are pure, dependency-free, deterministic modules — the same philosophy the new hand-rolled splitter follows (no new Markdown-AST dependency).
- **Test import convention — confirmed by reading `tests/test_safety_node.py`/`test_empathy_node.py`/`test_validators.py` directly, and confirming there is no `conftest.py`, `pytest.ini`, or `pyproject.toml` anywhere in the repo:** every test file starts with
  ```python
  import sys
  from pathlib import Path
  sys.path.append(str(Path(__file__).resolve().parent.parent))
  # then app.* imports with  # noqa: E402
  ```
  `tests/test_cta_loader.py` must follow this exact shim.
- All `app/**/__init__.py` files are empty — no exports to add.
- The reverted `cta_service.py`/`cta_node.py` (`git show 3b08629:app/services/cta_service.py`) are useful only for the "never raise, never block" defensive philosophy (`except OSError: return {}`) — not reused for data format.

## Implementation Plan

Files in dependency order: config → loader module → tests.

### 1. `app/config.py` (edit)

Add one line to `Settings`, after the existing `chroma_*`/`knowledge_*` block (matching the established pattern exactly):
```python
cta_data_dir: Path = BASE_DIR / os.getenv("CTA_DATA_DIR", "data/cta")
```
No other config changes — this module needs nothing else from `Settings`.

### 2. `.env.example` (edit)

Add a matching commented-out line in the "Optional overrides" block:
```
# CTA_DATA_DIR=data/cta
```

### 3. `app/services/cta_loader.py` (new)

Single self-contained module, zero dependency on any other `app/services/*`, `app/nodes/*`, `app/graph/*`, `langchain`, or `langgraph` (FR-10). Logger: `logging.getLogger("app.services.cta_loader")`.

**Constants** (spec Section 8.2, lifted verbatim):
```python
KNOWN_LABELS = [
    "Status", "Category", "CTA Type", "Priority", "Match Rule",
    "Do NOT display this CTA if", "Description",
    "Trigger Examples", "Trigger Conditions",
    "Aliases", "Related Topics",
    "Do NOT Trigger", "Do NOT Trigger for",
    "Fallback Rule", "Output Label", "CTA",
]
LABEL_ALIASES = {
    "Trigger Conditions": "Trigger Examples",
    "Do NOT Trigger for": "Do NOT Trigger",
}
REQUIRED_LABELS = [
    "Status", "Category", "CTA Type", "Priority", "Match Rule",
    "Description", "Trigger Examples", "Do NOT Trigger",
    "Fallback Rule", "Output Label", "CTA",
]
_PREAMBLE_LINE = "Display this CTA ONLY when:"
```

**Internal error type** (not explicit in the spec — needed to carry spec Section 11.2's distinct `reason` codes out of the parser cleanly, instead of relying solely on Pydantic's generic `ValidationError`):
```python
class _CTAParseError(Exception):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail
```
Raised explicitly at each specific required-field check (`missing_title`, `missing_required_field`, `no_trigger_examples`, `invalid_cta_url`) so the loop in `load_cta_data` can record the *correct* reason code rather than a generic catch-all. `schema_validation_failed` is reserved for the belt-and-suspenders case where `CTARecord.model_validate(...)` itself raises despite the manual checks passing (per spec Section 9.1's "second check" framing).

**Splitter** (spec Section 8.4, lifted verbatim — `_split_sections(lines) -> dict[str, list[str]]`), plus title extraction (Section 8.3) as a small `_extract_title(lines) -> tuple[str, list[str]]` returning the H1 text and the remaining lines, raising `_CTAParseError("missing_title", ...)` if the first non-blank line isn't `# ...`.

**Field extraction helpers**, each a pure function over a section body (`list[str]`) → its target type, per spec Sections 8.5–8.8:
- `_join_scalar(body: list[str], label: str) -> str` — non-blank lines stripped and joined with a space; logs `WARNING` if >1 non-blank line.
- `_extract_bullets(body: list[str]) -> list[str]` — every `^-\s+(.+)$` line, stripped, in order (used for `exclusion_conditions`, `related_topics`, and as the building block inside `_parse_grouped_bullets`).
- `_extract_match_conditions(body: list[str]) -> list[str]` — drops a leading line exactly equal to `_PREAMBLE_LINE` if present, then `_extract_bullets(...)` on the rest.
- `_parse_grouped_bullets(body: list[str]) -> tuple[list[str], dict[str, list[str]]]` — spec Section 8.6, lifted verbatim (handles both flat `Aliases` and `mnri.md`'s grouped `## Alternate Names`/`## Common Misspellings`, and `Trigger Examples`/`Trigger Conditions`).
- `_normalize_raw_block(body: list[str]) -> str` — strip leading/trailing blank lines, collapse runs of blank lines to one, used for `match_rule_raw`, `do_not_trigger_raw`, `fallback_rule`.
- `_do_not_trigger_examples(body: list[str]) -> list[str]` — every `^-\s+(.+)$` line anywhere in the body (already merged across `Do NOT Trigger`/`Do NOT Trigger for` by the splitter per spec Section 8.4's merge step), flattened, in order, exact-string deduplicated.

**Top-level orchestration** — `_parse_cta_file(path: Path, base_dir: Path) -> CTARecord`:
1. Read the file (`path.read_text(encoding="utf-8")`); catch `OSError`/`UnicodeDecodeError` → `_CTAParseError("file_read_error", str(exc))`.
2. `title, remaining_lines = _extract_title(lines)`.
3. `sections = _split_sections(remaining_lines)`.
4. For each label in `REQUIRED_LABELS`: if missing or its joined/normalized body is empty after stripping → `_CTAParseError("missing_required_field", f"missing or empty section: {label}")`.
5. Extract every field per the table above into the `CTARecord` kwargs. `extra_fields`: any **scalar**-looking unrecognized label is not actually produced by `_split_sections` (unrecognized labels by construction stay inside the preceding known section's body, per spec Section 8.8) — so practically, `extra_fields` will be `{}` for every file in the corpus today; the field still exists on `CTARecord` and is wired through as `{}` by default, satisfying FR-9/Section 17's forward-compat contract without needing speculative detection logic beyond what Section 8.8 already describes.
6. `trigger_examples` empty → `_CTAParseError("no_trigger_examples", ...)`.
7. `cta_url` not starting `http://`/`https://` → `_CTAParseError("invalid_cta_url", cta_url)`.
8. Derive `source_path`, `category_dir`, `cta_id` from `path.relative_to(base_dir)` (POSIX-style, suffix-stripped for `cta_id`) per spec Section 7.
9. Construct and return `CTARecord(...)` — let a `pydantic.ValidationError` here propagate to the caller uncaught (caller maps it to `schema_validation_failed`).

**`CTARecord`** (spec Section 9.1, lifted verbatim — all fields, both `@model_validator`s).

**`CTALoadIssue`/`CTALoadResult`** (spec Section 9.2, lifted verbatim, `@dataclass`).

**The scan loop** — `_scan(base_dir: Path) -> CTALoadResult`:
```python
def _scan(base_dir: Path) -> CTALoadResult:
    start = time.monotonic()
    if not base_dir.is_dir():
        logger.error("cta_loader: base_dir_missing path=%s", base_dir)
        return CTALoadResult([], [CTALoadIssue(str(base_dir), "base_dir_missing", "not a directory")], 0, 0, 0, (time.monotonic() - start) * 1000)

    paths = sorted(
        p for p in base_dir.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(base_dir).parts)
    )
    records: list[CTARecord] = []
    issues: list[CTALoadIssue] = []
    seen_ids: set[str] = set()

    for path in paths:
        rel = str(path.relative_to(base_dir).as_posix())
        try:
            record = _parse_cta_file(path, base_dir)
        except _CTAParseError as exc:
            issues.append(CTALoadIssue(rel, exc.reason, exc.detail))
            logger.warning("cta_loader skip: path=%s reason=%s detail=%s", rel, exc.reason, exc.detail)
            continue
        except Exception as exc:  # belt-and-suspenders, FR-3 -- never propagate
            issues.append(CTALoadIssue(rel, "schema_validation_failed", str(exc)))
            logger.error("cta_loader skip: path=%s reason=schema_validation_failed detail=%s", rel, exc)
            continue
        if record.cta_id in seen_ids:
            issues.append(CTALoadIssue(rel, "duplicate_cta_id", record.cta_id))
            logger.warning("cta_loader skip: path=%s reason=duplicate_cta_id detail=%s", rel, record.cta_id)
            continue
        seen_ids.add(record.cta_id)
        records.append(record)

    result = CTALoadResult(records, issues, len(paths), len(records), len(paths) - len(records), (time.monotonic() - start) * 1000)
    logger.info("cta_loader ok: scanned=%d loaded=%d skipped=%d elapsed_ms=%.2f",
                result.files_scanned, result.files_loaded, result.files_skipped, result.load_time_ms)
    if not records:
        logger.warning("cta_loader: zero CTA records loaded from %s", base_dir)
    return result
```

**Caching and public API** (spec Sections 13–14) — one judgment call the spec leaves implicit, made explicit here: `load_cta_data()`'s module-level cache is keyed to "the default directory" (`base_dir is None`, i.e. `settings.cta_data_dir` read fresh at call time, not captured at import). A call with an **explicit** `base_dir` (what every parsing/validation unit test uses, per spec Section 7's "without touching global settings") always does a fresh scan and never reads or writes the module cache — this is what makes those tests independent of caching behavior. Only calls with `base_dir=None` (the real production path, and the dedicated caching tests, which use `monkeypatch.setattr(settings, "cta_data_dir", tmp_path)` instead of passing `base_dir`) participate in `_CACHE`/`_BY_ID`:
```python
_CACHE: Optional[CTALoadResult] = None
_BY_ID: dict[str, CTARecord] = {}

def load_cta_data(base_dir: Optional[Path] = None, force_reload: bool = False) -> CTALoadResult:
    global _CACHE, _BY_ID
    if base_dir is None:
        if _CACHE is not None and not force_reload:
            return _CACHE
        _CACHE = _scan(settings.cta_data_dir)
        _BY_ID = {r.cta_id: r for r in _CACHE.records}
        return _CACHE
    return _scan(base_dir)

def reload_cta_data(base_dir: Optional[Path] = None) -> CTALoadResult:
    return load_cta_data(base_dir=base_dir, force_reload=True)

def get_all_ctas() -> list[CTARecord]:
    return list(load_cta_data().records)

def get_cta_by_id(cta_id: str) -> Optional[CTARecord]:
    load_cta_data()
    return _BY_ID.get(cta_id)

def get_ctas_by_category(category: str) -> list[CTARecord]:
    return [r for r in load_cta_data().records if r.category == category]

def get_ctas_by_status(status: str) -> list[CTARecord]:
    return [r for r in load_cta_data().records if r.status == status]

_CACHE = load_cta_data()  # eager import-time load, per spec Section 13
```
(`get_all_ctas`/`get_ctas_by_category`/`get_ctas_by_status` return fresh lists by construction — satisfies the "defensive copy" requirement without a separate copy step.)

### 4. `tests/test_cta_loader.py` (new)

Same shim as every other test file (`sys.path.append` + `# noqa: E402` imports of `app.config.settings` and everything public from `app.services.cta_loader`). A local helper `_write_cta(dir_, name, **overrides)` builds a syntactically-valid minimal CTA file from a base template with one field overridden/removed per test, avoiding 25 near-duplicate hand-written fixtures.

Maps every spec Section 18.1 case to a concrete test, using `tmp_path`:
1. `test_loads_well_formed_minimal_file`
2. `test_loads_file_with_all_optional_sections_present` (mirrors `about.md`'s shape)
3. `test_rejects_file_missing_required_field` (parametrized over `REQUIRED_LABELS`; asserts the *other* fixture file in the same `tmp_path` still loads)
4. `test_rejects_file_with_invalid_cta_url`
5. `test_rejects_file_with_no_title`
6. `test_rejects_file_with_zero_trigger_examples`
7. `test_match_rule_without_preamble_parses_bullets`
8. `test_match_rule_with_preamble_strips_preamble_line`
9. `test_grouped_trigger_examples_flatten_correctly`
10. `test_flat_aliases_parse_without_groups`
11. `test_grouped_aliases_parse_like_mnri`
12. `test_do_not_trigger_with_named_subgroups_flattens_bullets`
13. `test_duplicate_do_not_trigger_headings_are_merged`
14. `test_fallback_rule_prose_only`
15. `test_fallback_rule_with_instead_label_and_bullets`
16. `test_unrecognized_scalar_field_captured_in_extra_fields` — given the module's actual `extra_fields` mechanism (see step 3, item 5 above) never populates anything from a line inside a known section, this test documents `extra_fields == {}` as the correct, current behavior with an explanatory comment, rather than asserting a capture mechanism that Section 8.8 describes as a future-facing contract, not a today behavior. (Flagging this explicitly as a deviation from a literal reading of the spec's test table — see "Note" below.)
17. `test_recursive_discovery_finds_nested_files`
18. `test_non_markdown_files_ignored`
19. `test_missing_base_directory_returns_empty_result_no_raise`
20. `test_empty_base_directory_returns_empty_result_no_raise`
21. `test_duplicate_cta_id_keeps_first_sorted_occurrence`
22. `test_get_cta_by_id_returns_none_for_unknown_id`
23. `test_get_ctas_by_category_and_status_filter_correctly`
24. `test_reload_picks_up_on_disk_changes` — uses `monkeypatch.setattr(settings, "cta_data_dir", tmp_path)` + `reload_cta_data()` (no `base_dir` arg), per the caching design above.
25. `test_accessor_results_are_defensive_copies`

Plus the Section 18.2 regression test against the real corpus, verbatim:
```python
def test_real_cta_corpus_loads_with_zero_issues():
    result = load_cta_data(base_dir=settings.cta_data_dir, force_reload=True)
    expected = len(list(settings.cta_data_dir.rglob("*.md")))
    assert result.files_scanned == expected
    assert result.issues == []
    assert result.files_loaded == expected
```

**Note on item 16 / Section 8.8:** re-reading the spec's own Section 8.8 carefully, it states the splitter design means a genuinely new top-level label is *not* detected as a section boundary at all — it just stays as plain text inside whichever known section precedes it (e.g., a stray `Locale: en-US` line appearing right after `CTA:`'s value would simply become part of `cta_url`'s joined-scalar text, or get silently dropped if it's the very last line with nothing after it, depending on where it lands). Section 8.8 explicitly says: *"true forward-compatibility for genuinely new top-level fields is deferred to a future parser revision."* So implementing real `extra_fields` capture today would mean inventing a mechanism the spec describes as deliberately not yet built. This plan implements `extra_fields: dict[str, str] = {}` as a typed-but-always-empty field (matching the schema, satisfying any future consumer that reads it expecting a dict) and writes the test to assert today's actual behavior rather than a capture mechanism — flagging this as the one place this plan diverges from a literal reading of the spec's test table, and noting it for confirmation before / during implementation.

---

## Critical Files

| File | Change |
|---|---|
| `app/config.py` | Add `cta_data_dir` setting |
| `.env.example` | Add matching commented override line |
| `app/services/cta_loader.py` | New module (entire implementation above) |
| `tests/test_cta_loader.py` | New test file (25 unit tests + 1 corpus regression test) |

No changes to `app/graph/state.py`, `app/nodes/`, `app/main.py`, `app/models.py`, or `data/cta/` itself — all explicitly out of scope per spec Section 3.2 / Section 16.

## Reused utilities/patterns

- `app.config.settings` pattern for the new `cta_data_dir` field (`app/config.py`'s existing `vectorstore_dir`/`chroma_persist_dir` lines).
- `@dataclass` precedent from `app/services/empathy_service.py` for `CTALoadIssue`/`CTALoadResult`.
- `model_validator(mode="after")` precedent from `app/nodes/safety_node.py`'s `SafetyOutput` for `CTARecord`'s two validators.
- Test shim (`sys.path.append` + `# noqa: E402`) copied verbatim from `tests/test_safety_node.py`.

## Verification

1. `cd /home/user/NEW_manasi && venv/bin/pytest tests/test_cta_loader.py -v` — all 26 tests pass.
2. `venv/bin/pytest tests/ -v` — full existing suite still passes (confirms no import-cycle or naming collision introduced).
3. Manual smoke check against the real corpus:
   ```
   venv/bin/python -c "
   from app.services.cta_loader import get_all_ctas, get_cta_by_id
   records = get_all_ctas()
   print(len(records), 'records loaded')
   print(get_cta_by_id('therapies/mnri').output_label)
   "
   ```
   Expect `15 records loaded` and the MNRI CTA's output label printed with no exceptions/log errors.
4. Confirm `git status` shows only the four intended file changes (plus removal of any `__pycache__` noise).
