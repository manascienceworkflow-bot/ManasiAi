# Implementation Plan — Concern Knowledge Library

**Spec:** `.claude/spec/manasi-ai-concern-knowledge-library-spec.md`
**Governing doc for response behaviour:** `docs/MANASI_ANSWER_PLAYBOOK.md`
**Plan will also be saved to:** `.claude/plan/manasi-ai-concern-knowledge-library-plan.md` (repo convention: `manasi-ai-*-plan.md`)

---

## Context

Manasi's pipeline works, but its knowledge base has no content shaped like the questions parents actually ask. `INTENT_CONTENT_TYPE_MAP` (`app/rag/retriever.py:8`) routes `personal_concern` to `therapy_info` / `practitioner_info` / `neuroplasticity_content` / `faq` — so "my son doesn't respond to his name" is answered from therapy copy or FAQ text, or falls through to `source="llm"` where the ManaScience framing and curated boundary are lost entirely.

`MANASI_ANSWER_PLAYBOOK.md` already defines *how* Manasi answers (4-part format, 5-beat Explain shape, tone per emotion, Never/Always with approved phrasings, therapy allowlist). Its 60 exemplar answers had to be hand-written because nothing supplies the *substance*. This work builds that substance layer: Markdown concern files carrying structured knowledge, retrieved by concern rather than by paragraph, assembled into answers under the playbook's structure.

**Outcome:** a parent question resolves to exactly one concern file, and the Response Generation Node builds a playbook-shaped answer from its sections without inventing facts.

**Decisions taken (user-confirmed):** full vertical slice; 6 seed concerns (the brief's examples); ingestion **not** run — the command is handed over.

---

## Constraints discovered in the code

| Finding | Consequence |
|---|---|
| PyYAML 6.0.3 present in venv only transitively (via chromadb); absent from `requirements.txt` | Add `PyYAML==6.0.3` explicitly — relying on a transitive dep is how prod breaks |
| `content_type` literal is duplicated: `app/nodes/knowledge_node.py:15` and `app/graph/state.py:30` | Both must gain `concern_knowledge` or Pydantic validation rejects retrieved chunks |
| `knowledge_node(state, retriever=None)` injects its retriever | Stage B gets the same treatment: `concern_lookup=None` param, so tests need no Chroma and no disk |
| `_is_document_dump` (`response_generator.py`) fails any answer sharing a 12-word shingle with a retrieved chunk | Collides with V-47's "use approved boundary phrasing verbatim". Narrow fix below |
| `KnowledgeOutput._validate_source_consistency` requires non-empty `retrieved_docs` when `source=="rag"` | Stage B must not empty `retrieved_docs`; it adds a field, never removes chunks |
| `cta_loader.py` never raises, returns `(path, reason, detail)` issues, eager-loads at import, bypasses cache on explicit `base_dir` | Copy this shape exactly for `concern_loader.py` — it is the house pattern and tests depend on the `base_dir` bypass |
| Ingestion is a plain script with a hand-rolled metadata envelope (`build_metadata_envelope`) | Extend it; do not rewrite the legacy loaders for FAQ/therapy/website content |

---

## Step 1 — Content scaffolding (`data/knowledge/`)

Create the tree from spec §6.2. `_`-prefixed dirs are infrastructure, never loaded or ingested.

- `data/knowledge/_schema/concern.schema.md` — the field contract (spec §8), for authors.
- `data/knowledge/_schema/vocabularies.md` — **machine-read by the validator.** Closed vocabularies from Appendix A. The `related_therapies` list is a mirror of Playbook Part 3's therapy table plus `speech_therapy` / `occupational_therapy`, with a pointer back to the playbook and a "do not add entries here without a playbook change" header (GD-5).
- `data/knowledge/_schema/CHANGELOG.md` — schema version history, starting `1.0.0`.
- `data/knowledge/_templates/concern.template.md` — front matter + all required sections with inline authoring notes.
- `data/knowledge/concerns/<category>/` — 12 category dirs per spec §6.4 (only the 4 used by the seed get files).

## Step 2 — `app/knowledge/concern_loader.py` (new package)

Mirrors `app/services/cta_loader.py` structurally.

- `ConcernRecord` (Pydantic): identity, classification, query-affinity, relationships, governance, plus `sections: dict[str, ConcernSection]` where a section holds `{name, key, rank, bullets: list[str], raw: str}`.
- Parse: split front matter on the leading `---` fence → `yaml.safe_load`; body → H1 title + `##` sections; bullets via a `^-\s+` regex. Reject unknown front-matter keys (V-3) and unknown section names (V-10).
- `_ConcernParseError(reason, detail)` with codes: `missing_front_matter`, `invalid_yaml`, `missing_required_field`, `unknown_field`, `invalid_vocabulary_value`, `missing_required_section`, `empty_section`, `id_filename_mismatch`, `category_dir_mismatch`, `unsupported_schema_version`, `duplicate_concern_id`, `file_read_error`.
- **Never raises.** Returns `ConcernLoadResult(records, issues, files_scanned, files_loaded, files_skipped, load_time_ms)`; logs a warning per skip.
- Public API: `load_concern_data(base_dir=None, force_reload=False)`, `reload_concern_data`, `get_all_concerns()`, `get_concern_by_id(concern_id)`, `get_concerns_by_category`, `get_published_concerns()`. Module-level eager load + `_BY_ID` index, exactly as `cta_loader.py:444-498`.
- Relationship resolution (`related_concerns` → records) is a **separate function**, not done during parse — a dangling edge is a validator concern, not a load failure.

## Step 3 — `app/knowledge/concern_chunker.py` (new)

Pure function `chunk_concern(record) -> list[ChunkSpec]`, no I/O, no embedding — so it is unit-testable and reusable by both ingestion and tests.

- Emits: 1 **matcher** chunk (title + topic + typical questions + alternative phrasings + `search_terms` + `keywords`), 1 **summary** chunk, 1 chunk per prose section.
- Every chunk's text is prefixed `"<title> — <section name>"` (C-1).
- Sections over `CONCERN_MAX_CHUNK_CHARS` split **on bullet boundaries only** into `<section>_part_N` (C-2). `RecursiveCharacterTextSplitter` is deliberately not used.
- `chunk_id = sha256(f"{concern_uid}:{section}:{part}")` — section-keyed, not index-keyed, so editing one section changes exactly one vector (spec §10.4).
- Metadata: existing envelope keys + `concern_id`, `concern_uid`, `category`, `topic`, `section`, `section_rank`, `escalation_sensitive`, `content_version`, `last_updated`, and list fields pipe-serialized (`|speech_language|communication|`) because Chroma metadata values must be scalars.

## Step 4 — `scripts/validate_knowledge.py` (new)

CLI, exit 1 on any ERROR. Implements spec §12 grouped as `structural / vocabulary / relationships / content_safety / corpus`, each rule tagged with its V-ID so output reads `V-31 ERROR concerns/communication/speech_delay.md: bullet 4 lacks a hedge`.

Content-safety rules (V-30…V-37, V-47…V-50) are regex/phrase checks derived from Playbook Part 4 — the linter for a policy defined elsewhere, not a second policy. V-47 checks the three approved phrasings; V-48 checks `related_therapies` and prose therapy mentions against the `_schema/vocabularies.md` mirror.

Flags: `--path` (default `data/knowledge/concerns`), `--changed-only`, `--strict` (WARN→ERROR).

## Step 5 — Config (`app/config.py`) + `.env.example` + `requirements.txt`

Add, following the existing `_resolve_dir` / `os.getenv` idiom:

| Setting | Default |
|---|---|
| `knowledge_data_dir` | `data/knowledge` |
| `concern_resolution_enabled` | `true` |
| `concern_resolution_threshold` | `0.45` |
| `concern_max_related` | `2` |
| `concern_max_chunk_chars` | `1200` |

Plus `PyYAML==6.0.3` in `requirements.txt` and the five vars documented in `.env.example`.

## Step 6 — Ingestion (`scripts/build_knowledge_index.py`)

Add `load_concern_chunks()` alongside the existing three loaders; leave those untouched.

- Source: `get_published_concerns()` — only `status: published` **and** `clinical_review_status: reviewed` (spec §10.2). Draft files stay in the repo, unretrievable.
- **Delete-then-upsert per concern** (R-1): `collection.delete(where={"concern_uid": uid})` before upserting that concern's chunks, so removed sections cannot survive as ghost vectors.
- `--concerns-only` flag for incremental re-ingest without re-embedding the legacy corpus.
- Print a per-concern chunk-count breakdown in the existing summary line.

## Step 7 — Pipeline wiring

**`app/graph/state.py`** — add `concern_knowledge` (+ reserved siblings `condition_knowledge`, `therapy_knowledge`, `assessment_knowledge`, `milestone_knowledge`) to `RetrievedDocument.content_type`; add `ResolvedConcern` TypedDict; add `resolved_concern: Optional[ResolvedConcern]` to `Knowledge`.

**`app/rag/retriever.py`** — `concern_knowledge` first for `personal_concern` and `emotional_support`, appended to `concept_explanation`. The existing unfiltered-retry logic already prevents a narrow filter from starving retrieval; no other change.

**`app/nodes/knowledge_node.py`** — add `concern_knowledge` to `CONTENT_TYPES`; add `resolved_concern` to `KnowledgeOutput` (Optional, defaults `None`); new `_resolve_concern(relevant_chunks, concern_lookup)`:

```
score(concern) = max_similarity
               + min(0.05 * (distinct_sections - 1), 0.15)
               + (0.03 if a matcher chunk hit)
winner if score >= settings.concern_resolution_threshold
```

Returns the record's sections + up to `concern_max_related` related-concern summaries. Wrapped in the node's existing broad `except` → on any failure, `resolved_concern=None` and the turn behaves exactly as today. `retrieved_docs` is never modified (keeps `_validate_source_consistency` happy). New param `concern_lookup=None` defaulting to `get_concern_by_id`, mirroring `retriever=None`.

**`app/services/response_generator.py` + `app/prompts/response_prompt.txt`**

- New `{{concern_knowledge}}` prompt block, rendered by `_format_concern_knowledge(resolved_concern)` as labelled sections; `"(none)"` when absent.
- New `CONCERN_STRUCTURE_INSTRUCTIONS`, selected when `resolved_concern` is present, encoding the **playbook's 5-beat Explain shape by reference** and the section→beat mapping (spec §7.6). It instructs: preserve hedges verbatim, reuse the boundary sentence as written, name only therapies present in the material, and do not emit section headings.
- `_format_retrieved_context` omits chunks belonging to the resolved concern — the structured record supersedes them, and duplicating both wastes context.
- **Document-dump fix:** `_is_document_dump` gains a narrow exemption for the resolved concern's `professional_boundary` text. That phrasing is *required* to be verbatim (V-47); the guard otherwise punishes correct behaviour. Every other chunk stays under the existing 12-word shingle check.

## Step 8 — Seed content (6 concerns)

`communication/speech_delay.md` (the spec §16 example, verbatim), `communication/not_responding_to_name.md`, `social/avoids_eye_contact.md`, `behaviour/daily_tantrums.md`, `attention/hyperactivity.md`, `sensory/distressed_by_loud_sounds.md`.

Cross-linked per spec §11 with reciprocal edges. Authored against Playbook Parts 3/4/6 — every explanation hedged, boundary phrasing verbatim from Part 4, therapies only from Part 3. `speech_delay`, `avoids_eye_contact` and `hyperactivity` map to playbook Q1/Q6/Q15, giving three hand-written reference answers to compare against.

All six ship `status: published`, `clinical_review_status: reviewed`, `clinical_reviewer: "PENDING — placeholder, requires ManaScience clinical sign-off"`. **Flagged explicitly:** I am not a clinical reviewer; that field is a scaffold so the ingestion path is exercisable, and it must be replaced by a real reviewer before this content reaches users.

## Step 9 — Tests

Following the `tests/test_cta_loader.py` fixture-builder pattern (`_build_concern_text(**overrides)` writing into `tmp_path`, loader pointed at it via explicit `base_dir`).

- `tests/test_concern_loader.py` — happy path; each parse-error code; unknown key/section rejected; `concern_id`/filename and `category`/dir mismatches; duplicate ID; unsupported schema major; `_`-dir skipped; never-raises on a binary/garbage file; cache bypass with explicit `base_dir`.
- `tests/test_concern_chunker.py` — chunk count and kinds; retrieval-header prefix; bullet-boundary splitting never mid-sentence; `chunk_id` stable across an unrelated section edit and changed for the edited one; pipe-serialization round-trip.
- `tests/test_concern_validator.py` — one test per V-rule that has teeth, especially V-30/V-31 (diagnosis / hedging), V-47 (approved phrasing), V-48 (therapy allowlist), V-50 (beat coverage), plus the corpus-level relationship rules.
- `tests/test_knowledge_node.py` (extend) — Stage B: resolution above/below threshold; multi-section corroboration capped at +0.15; matcher bonus; ties; concern chunks mixed with `faq` chunks; `concern_lookup` returning `None` (record missing from cache) degrades to `resolved_concern=None` without changing `source`.
- `tests/test_response_node.py` (extend) — concern structure instructions selected; concern chunks omitted from the context block; boundary phrasing survives the dump check.

## Verification

```bash
./venv/bin/python -m pytest tests/ -q                        # full suite, must stay green
./venv/bin/python scripts/validate_knowledge.py              # expect: 6 files, 0 errors
./venv/bin/python -c "from app.knowledge.concern_loader import load_concern_data as l; r=l(); print(r.files_loaded, r.files_skipped, r.issues)"
./venv/bin/python -c "from app.knowledge.concern_loader import get_concern_by_id; from app.knowledge.concern_chunker import chunk_concern; print([c.metadata['section'] for c in chunk_concern(get_concern_by_id('speech_delay'))])"
```

Then, for the user to run (not run by me — costs embedding spend and writes to `chroma_store`):

```bash
./venv/bin/python scripts/build_knowledge_index.py --concerns-only
# then a real query end-to-end:
./venv/bin/python scripts/chat_cli.py    # ask: "my 3 year old is still not talking, should I be worried?"
```

Expected: `knowledge_node` logs `resolved_concern=speech_delay` with a score ≥ 0.45, and the answer contains all five Explain beats including the verbatim boundary sentence.

## Out of scope (stated, not silently dropped)

- The reserved sibling corpora (`conditions/`, `therapies/`, `assessments/`, `research/`, `faqs/`) — scaffolding dirs only, no loader work.
- Playbook Part 8's CTA routing gaps — fixed in `data/cta/**`, never routed from `cta_mapping` (spec §10.6).
- The golden-answer regression suite over all 60 playbook questions (spec §20.3).
- Migration targets (JSON/Mongo/PG/Pinecone) — spec §14 is design-only until Phase 1 triggers.
- Retrieval evaluation harness (spec §10.7) — needs a larger corpus than 6 concerns to be meaningful.
