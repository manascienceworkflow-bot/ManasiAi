# Manasi AI — Technical Specification
## CTA Data Loader (`cta_loader.py`)

**Project:** Manasi AI
**Organization:** ManaScience
**Component:** CTA Data Loader — infrastructure module, not a numbered LangGraph pipeline phase
**Status:** Draft for implementation
**Audience:** Python engineer implementing `app/services/cta_loader.py`
**Depends on:** None of the existing LangGraph phases (Phase 1 Understanding, Phase 2 Knowledge, Phase 3 Response, Phase 4 Empathy, Phase 5 Safety) at runtime. This module is a **prerequisite** for a future CTA Matching/Linking Node, whose matching, scoring, and `GraphState` integration responsibilities are deliberately excluded from this document (Section 3.2) and will be specified separately once this loader exists and is stable.
**Data source:** `data/cta/**/*.md` — 15 files at time of writing, spanning `therapies/`, `conditions/`, `faq/`, `courses/`, `subscription/`, `about/`, `community/`, `privacy/`, `neuroplasticity/`.
**Prior art:** An earlier, simpler CTA registry (`data/cta/cta_links.md`, a flat `key=value` file, plus `app/services/cta_service.py` and `app/nodes/cta_node.py`) was implemented and then reverted (commits `3b08629` / `e4a56ee`). That design assumed a single hand-maintained `{key: url}` map driven by a `cta_key` tag on retrieved RAG documents. It has been superseded by the richer, structured per-CTA Markdown corpus this spec describes, which encodes match rules, trigger examples, aliases, and exclusion rules directly in content rather than in a side-channel metadata tag. This spec does not resurrect the old design.

---

## 1. Executive Summary

`data/cta/` currently holds 15 hand-authored Markdown files, one per Call-To-Action, organized into category folders (`therapies/`, `conditions/`, `faq/`, `courses/`, `subscription/`, `about/`, `community/`, `privacy/`, `neuroplasticity/`). Each file is far richer than a simple `topic -> URL` pair: it encodes a status flag, a category/type/priority classification, positive and negative match rules, dozens of grouped trigger-phrase examples, aliases, related topics, exclusion examples, a fallback rule, a display label, and the destination URL. Nothing in the codebase today reads any of this — it is inert content sitting on disk.

This document specifies **`cta_loader.py` only**: a module whose entire job is to find every CTA file, parse it into a well-defined in-memory record, validate that record, cache the full set after the first load, and expose that cached set through a small, read-only API. It deliberately stops there. Deciding *which* CTA (if any) is relevant to a given user turn — comparing trigger examples against a question, weighing confidence, applying exclusion rules, picking a winner among competing categories — is the job of a future **CTA Node**, which does not yet exist and is out of scope here (Section 3.2). This loader's contract is the foundation that node will be built on, in the same way `app/rag/retriever.py` is a foundation `knowledge_node.py` builds on without itself deciding what to do with retrieved documents.

The defining engineering challenge of this module is not the happy path — it is that the 15 source files, while following a consistent *overall* shape, are not byte-for-byte consistent in how several sections are authored (Section 6.2 catalogs every divergence found). A parser that assumes one rigid template will silently mis-parse or reject real files in the corpus today. This spec is implementation-ready specifically because it is grounded in a full read of all 15 existing files, not an idealized example.

---

## 2. Purpose

Give every other part of the Manasi AI system — today nothing, eventually a CTA Node — a single, reliable, in-memory view of "every CTA that exists, and everything its Markdown file says about it," without any of them needing to know that this data lives in a directory of hand-written Markdown files at all. The loader is the only code in the system permitted to know about `data/cta/`'s file layout and Markdown conventions; everything downstream consumes typed `CTARecord` objects.

---

## 3. Scope

### 3.1 In Scope — Responsibilities

The loader SHALL:

* Recursively scan `data/cta/` for CTA Markdown files (Section 7).
* Read and parse every discovered file into a structured `CTARecord` (Sections 8–9).
* Validate each parsed record against a fixed set of structural rules (Section 10).
* Isolate failures per file — one malformed file SHALL NOT prevent any other file from loading (Section 11).
* Hold the full set of successfully parsed records in memory after the first load, so repeated access does not re-read or re-parse disk (Section 13).
* Expose a small set of read-only, non-judgmental accessor functions for other modules to consume (Section 14).
* Log what it loaded, what it skipped, and why (Section 12).

### 3.2 Out of Scope — Non-Responsibilities

The loader SHALL NOT, under any circumstance:

* Match a user's question, message, or conversation history against any CTA's trigger examples, aliases, or match rules.
* Decide which CTA (if any) should be shown for a given turn, or rank/score multiple candidate CTAs against each other.
* Read `state["user_message"]`, `state["chat_history"]`, or any other `GraphState` field — the loader has no concept of a "turn" at all.
* Modify, rewrite, summarize, or otherwise alter a chatbot response.
* Generate a new CTA, a new URL, or new trigger examples — every value the loader exposes must already exist verbatim in a source file.
* Perform fuzzy matching, semantic similarity, or any embedding/LLM call of any kind. The loader is pure, deterministic Python over local text files.
* Write to, rename, or otherwise mutate any file under `data/cta/`. It is a read-only consumer of that directory.

All of the above belong to the future CTA Node (or a later spec for it), exactly as the product context for this work states. A convenience filter like "give me every record whose `category` field equals `Therapy`" (Section 14) is a structural data-access operation, not a matching decision, and is in scope; "give me the record that best matches this question" is a matching decision and is explicitly not.

---

## 4. Functional Requirements

### FR-1: Recursive, Read-Only Discovery
The loader SHALL discover every `*.md` file anywhere under its configured base directory (default `data/cta/`), at any folder depth, without assuming a fixed set of category folder names. It SHALL NOT write to, delete, or rename any file it discovers.

### FR-2: One Record Per File
Each discovered Markdown file SHALL parse into at most one `CTARecord`. The loader SHALL NOT split a single file into multiple records or merge multiple files into one.

### FR-3: Per-File Failure Isolation
A parsing or validation failure in one file SHALL be caught, logged, and recorded as a skipped-file issue (Section 11); it SHALL NOT raise an exception that aborts the scan of the remaining files, and SHALL NOT raise an exception that propagates out of the loader's public entry point under any input, including a missing or empty `data/cta/` directory.

### FR-4: Deterministic, Order-Stable Output
Given an unchanged `data/cta/` directory, two successive loads (or two loads in two different process runs) SHALL produce the same set of records in the same order. File discovery order SHALL be lexicographic by relative path.

### FR-5: Required-Field Enforcement
A file missing any of the required sections or scalar fields listed in Section 10.1, or whose `CTA` field is not a syntactically valid absolute HTTP(S) URL, SHALL be rejected (skipped) in its entirety. The loader SHALL NOT construct a partial or best-effort `CTARecord` for a file that fails required-field validation — a CTA with a missing or malformed link is worse than no CTA at all (mirroring the destination registry's existing exact-match, never-guess philosophy from the prior `cta_service.py` design).

### FR-6: Tolerant Handling of Optional Sections and Authoring Variance
A file missing an *optional* section (`Aliases`, `Related Topics`, `Do NOT display this CTA if`) SHALL load successfully with that field defaulted to an empty list. A file whose `Do NOT Trigger` or `Fallback Rule` section is authored with extra prose, nested sub-labels, or duplicated headings (Section 6.2 catalogs every such case actually present in the corpus today) SHALL still load successfully (Section 8.6).

### FR-7: Load Once, Serve From Memory
The full corpus SHALL be parsed at most once per explicit load operation. Public accessor functions (Section 14) SHALL read from the in-memory cache and SHALL NOT trigger a disk scan on every call. An explicit `reload_cta_data()` SHALL be the only way to force a fresh scan.

### FR-8: Statelessness With Respect to Conversations
The loader SHALL hold no per-conversation, per-session, or per-turn state of any kind. Its only persistent state is the process-lifetime cache of parsed CTA content (Section 13), which is identical for every caller and every turn.

### FR-9: Structured, Typed Output Only
Every successfully loaded CTA SHALL be exposed as a `CTARecord` (Section 9.1) — a Pydantic model with named, typed fields. The loader SHALL NOT expose raw file contents or untyped dictionaries as its primary public contract (the full original text is retained internally as an audit field, Section 9.1, but typed fields are the contract).

### FR-10: No Hidden Network or LLM Dependency
The loader SHALL depend only on the local filesystem and the Python standard library plus Pydantic. It SHALL NOT import `langchain`, `langgraph`, any chat-model client, or any embeddings client.

---

## 5. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Reliability** | `load_cta_data()` MUST always return a valid `CTALoadResult` (Section 9.2). It MUST NOT raise an unhandled exception for any input directory state — missing, empty, unreadable, or containing arbitrarily malformed files (FR-3). |
| **Determinism** | Given identical file contents, the loader MUST produce byte-identical `CTARecord` output on every run, with no randomness, sampling, or model-version dependency of any kind (FR-4) — the same determinism guarantee this codebase's deterministic validators (`medical_validator.py`, `boundary_validator.py`) already hold. |
| **Latency** | A full cold scan of the current 15-file corpus MUST complete in well under 50ms; see Section 15 for targets as the corpus grows. |
| **Testability** | The loader MUST be unit-testable with zero mocking infrastructure — no fake LLM, no fake network client, only synthetic Markdown fixtures on a real or temp filesystem (Section 18). |
| **Observability** | Every load SHOULD log a single summary line (files scanned / loaded / skipped / elapsed time) plus one line per skipped file with a machine-readable reason (Section 12). |
| **Isolation** | The loader's only inbound dependency SHOULD be `app.config.settings` (for the base directory path) and the standard library; it MUST NOT import from `app/nodes/`, `app/graph/`, or any `services/*_service.py` module that depends on an LLM client, keeping it safely importable from any future node without pulling in unrelated machinery. |
| **Forward-compatibility** | Adding a new optional scalar field to future CTA files MUST NOT require a code change to avoid the file being rejected (Section 17). |

---

## 6. The Data Source: `data/cta/`

### 6.1 Directory Layout (as it exists today)

```
data/
└── cta/
    ├── about/
    │   └── about.md
    ├── community/
    │   └── community_hub.md
    ├── conditions/
    │   ├── adhd.md
    │   ├── anxiety.md
    │   ├── depression.md
    │   └── general.md
    ├── courses/
    │   └── courses.md
    ├── faq/
    │   └── faq.md
    ├── neuroplasticity/
    │   └── neuroplasticity.md
    ├── privacy/
    │   └── privacy_guidelines.md
    ├── subscription/
    │   └── subscription.md
    └── therapies/
        ├── arrowsmith.md
        ├── general.md
        ├── mnri.md
        └── neurofeedback.md
```

The folder name (e.g. `therapies`) is **organizational only**. It is not guaranteed to equal, or even resemble, the in-file `Category:` value — the `therapies/` folder's files all declare `Category: Therapy` (singular), and `neuroplasticity/neuroplasticity.md` declares `Category: Neuroplasticity` while sitting in a folder of the same name only by coincidence of there being one file in it. The loader MUST treat the folder name purely as a `category_dir` provenance field (Section 9.1) for debugging/grouping, and MUST NOT use it as a substitute for, or cross-check against, the file's actual `Category:` field.

### 6.2 The Markdown Convention — As Actually Written

Every file follows this overall shape:

```
# <Title> CTA

Status: Active

Category: <value>

CTA Type: <value>

Priority: <value>

Match Rule:
[Display this CTA ONLY when:]
- <condition>
- <condition>

[Do NOT display this CTA if:
- <condition>
- <condition>]

Description:

<one or more sentences>

Trigger Examples:                     (sometimes "Trigger Conditions:")

## <Subsection Title>
- <example phrase>
- <example phrase>

## <Subsection Title>
- <example phrase>
...

[Aliases:
- <alias>
...]

[Related Topics:
- <topic>
...]

Do NOT Trigger:
<prose and/or sub-labels and/or bullets — highly variable, see below>

Fallback Rule:
<prose and/or an "Instead:" sub-label and/or bullets — highly variable>

Output Label:

<single line>

CTA:

<single absolute URL>
```

`[...]` marks sections that are absent in at least one real file today. This is the **only** part of the corpus genuinely free-form enough to need special handling, and every variant below has been confirmed against the actual files (not hypothesized):

| Divergence | Where it actually occurs |
|---|---|
| `Match Rule:` body has no `Display this CTA ONLY when:` preamble — bullets start immediately | `therapies/general.md`, `therapies/mnri.md` |
| `Do NOT display this CTA if:` section is entirely absent | `therapies/general.md`, `therapies/mnri.md` |
| `Aliases:` and `Related Topics:` sections are entirely absent | `therapies/general.md` |
| `Trigger Examples:` heading is spelled `Trigger Conditions:` | `therapies/general.md` |
| `Aliases:` body is grouped into `##` subsections (like `Trigger Examples`) instead of one flat bullet list | `therapies/mnri.md` (`## Alternate Names`, `## Common Misspellings`) |
| `Do NOT Trigger:` body is flat bullets only, no prose, no sub-labels | `about.md`, `community_hub.md`, `courses.md`, `faq.md`, `neuroplasticity.md`, `privacy_guidelines.md`, `subscription.md` |
| `Do NOT Trigger:` body opens with a prose sentence, then an `Examples:` sub-label, then bullets | `therapies/general.md` |
| `Do NOT Trigger:` body has two or more named sub-groups (e.g. `General condition questions:`, `Questions about other specific conditions:`), each its own prose line followed by bullets, with no `Examples:` label at all | `conditions/adhd.md`, `conditions/anxiety.md`, `conditions/depression.md`, `therapies/neurofeedback.md` |
| `Do NOT Trigger:` content is split across **two separate top-level headings** in the same file — `Do NOT Trigger:` and, later, `Do NOT Trigger for:` | `conditions/general.md` |
| `Do NOT Trigger:` body alternates prose / `Examples:` / bullets / more prose / more bullets, three times over | `therapies/mnri.md` |
| `Fallback Rule:` body is prose only, no bullets, no sub-label | `about.md`, `community_hub.md`, `courses.md`, `faq.md`, `neuroplasticity.md`, `privacy_guidelines.md`, `subscription.md`, `conditions/general.md`, `therapies/general.md` |
| `Fallback Rule:` body is prose, then an `Instead:` sub-label, then bullets | `conditions/adhd.md`, `conditions/anxiety.md`, `conditions/depression.md`, `therapies/neurofeedback.md` |
| `Fallback Rule:` body is prose, then bullets directly with no `Instead:` label | `therapies/mnri.md` |
| `Priority:` value carries an extra qualifier suffix (`Specific Therapy - MNRI` rather than the plain `Specific Therapy` used elsewhere) | `therapies/mnri.md` |

None of this is a defect to "fix" — it is how 15 files written by hand over time actually look, and the loader's job is to be tolerant of it without silently losing information. Section 8 specifies a parsing strategy designed around exactly this table.

---

## 7. Folder Traversal Strategy

* **Base directory:** `settings.cta_data_dir`, a new `Settings` field added in `app/config.py` following the existing `os.getenv(...)`-backed pattern (`vectorstore_dir`, `chroma_persist_dir`):

  ```python
  cta_data_dir: Path = BASE_DIR / os.getenv("CTA_DATA_DIR", "data/cta")
  ```

  `load_cta_data()` SHALL accept an optional `base_dir: Path` override (defaulting to `settings.cta_data_dir`) purely so tests can point it at a temporary fixture directory without touching global settings.

* **Discovery:** `sorted(base_dir.rglob("*.md"))` — recursive, any depth, so a future re-organization of category folders (or a new nested sub-category) requires no loader change. Sorting is by relative POSIX path string, giving FR-4's order determinism.

* **Filtering:** Only files whose name ends in `.md` (case-sensitive) are considered. Hidden files/directories (any path component starting with `.`) are skipped — relevant for editor swap files, not for anything currently in the corpus. Directories themselves are never treated as records.

* **Identity derivation:** For a discovered file at `base_dir / "therapies" / "mnri.md"`:
  * `source_path` = `"therapies/mnri.md"` (POSIX-style, relative to `base_dir`).
  * `category_dir` = `"therapies"` (first path component).
  * `cta_id` = `"therapies/mnri"` (relative path with the `.md` suffix removed) — stable, human-readable, and guaranteed unique by construction (two files cannot share a path), which is why no separate UUID or hash is needed.

* **Missing/unreadable base directory:** Treated as "zero files found," not an error (Section 11) — `rglob` over a nonexistent path raises in some Python versions, so the loader SHALL check `base_dir.is_dir()` first and short-circuit to an empty scan with a logged `ERROR` if it is not a directory.

---

## 8. Markdown Parsing Strategy

### 8.1 Design Principle: A Label-Driven Splitter, Not a Markdown AST

The corpus mixes real Markdown syntax (`#`/`##` headings, `- ` bullets) with a plain-text "`Label:` then content" convention that is not itself Markdown. A generic Markdown-to-AST library (e.g. `markdown-it-py`) would parse the headings and bullets correctly but would have no special understanding of `Status:`/`Match Rule:`/`Fallback Rule:` as field boundaries — that convention has to be hand-coded regardless of what parses the surrounding syntax. Given that, this spec uses a single hand-rolled, line-based splitter for the whole file: it is no more code than gluing a generic Markdown parser to a custom label-recognizer would be, it has zero new dependencies, and it matches this codebase's established preference for small, auditable, pure-Python parsing logic over pulling in a library (`medical_validator.py`, `hallucination_validator.py`, and the old `cta_service.py`'s `_parse_line` are all this same style).

### 8.2 Known Top-Level Labels

```python
KNOWN_LABELS = [
    "Status", "Category", "CTA Type", "Priority", "Match Rule",
    "Do NOT display this CTA if", "Description",
    "Trigger Examples", "Trigger Conditions",
    "Aliases", "Related Topics",
    "Do NOT Trigger", "Do NOT Trigger for",
    "Fallback Rule", "Output Label", "CTA",
]

# Multiple labels that mean the same logical field (Section 6.2) are merged,
# in file order, under the canonical name on the right.
LABEL_ALIASES = {
    "Trigger Conditions": "Trigger Examples",
    "Do NOT Trigger for": "Do NOT Trigger",
}

REQUIRED_LABELS = [
    "Status", "Category", "CTA Type", "Priority", "Match Rule",
    "Description", "Trigger Examples", "Do NOT Trigger",
    "Fallback Rule", "Output Label", "CTA",
]
# Optional: "Do NOT display this CTA if", "Aliases", "Related Topics".
```

A line is a **label line** iff, after stripping, it matches `^([A-Za-z][A-Za-z /]+):(.*)$` *and* the captured label (trimmed) is an exact, case-sensitive member of `KNOWN_LABELS`. This is deliberately a closed allow-list, not a generic "any line ending in a colon" heuristic — `"Display this CTA ONLY when:"`, `"Examples:"`, `"Instead:"`, and the various named sub-groups (`"General condition questions:"`) all end in a colon too, and must NOT be treated as new top-level sections; they are content belonging to the section they appear inside (Section 8.6 handles them explicitly). Using an open-ended colon heuristic would mis-split exactly the files this spec exists to handle correctly.

Critically, this single regex handles **both** authoring styles in the corpus in one pass: scalar fields write their value inline (`"Status: Active"` → label `"Status"`, captured remainder `" Active"`), while structural fields leave the remainder empty and put their content on subsequent lines (`"Match Rule:"` → captured remainder `""`). Both cases populate the same `body_lines` accumulator; no special-casing by field type is needed in the splitter itself.

### 8.3 Title Extraction

The first non-blank line of the file MUST match `^#\s+(.+)$`; the captured group, verbatim, becomes `title` (e.g. `"MNRI Therapy CTA"` — the spec does not strip the trailing `" CTA"` convention, since it is presentational, not data the loader needs to interpret). A missing or malformed H1 is a required-field failure (Section 10.1) — the whole file is rejected.

### 8.4 The Splitter

```python
import re
from collections import defaultdict

_LABEL_LINE = re.compile(r"^([A-Za-z][A-Za-z /]+):(.*)$")


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    """Splits the file body (everything after the H1 title) into a dict of
    canonical-label -> list of raw body-line-lists, one list per occurrence
    of that label in the file (Section 8.6 merges multi-occurrence labels).
    Lines that appear before the first recognized label are discarded."""
    sections: dict[str, list[list[str]]] = defaultdict(list)
    current_label: str | None = None
    current_body: list[str] = []

    def _flush() -> None:
        if current_label is not None:
            sections[current_label].append(current_body)

    for line in lines:
        match = _LABEL_LINE.match(line.strip())
        candidate = match.group(1).strip() if match else None
        if candidate in KNOWN_LABELS:
            _flush()
            current_label = LABEL_ALIASES.get(candidate, candidate)
            remainder = match.group(2).strip()
            current_body = [remainder] if remainder else []
        elif current_label is not None:
            current_body.append(line)
    _flush()

    # Merge same-label occurrences (e.g. "Do NOT Trigger" + "Do NOT Trigger for")
    # in file order, separated by a blank line, per FR-6.
    return {
        label: [ln for body in bodies for ln in (body + [""])][:-1]
        for label, bodies in sections.items()
    }
```

### 8.5 Scalar and Simple List Fields

| Field | Extraction rule |
|---|---|
| `status`, `category`, `cta_type`, `priority`, `output_label`, `cta_url` | Take all non-blank lines in the section body, strip, join with a single space. (In practice every current file has exactly one non-blank line for each of these; joining rather than indexing `[0]` tolerates an accidental wrapped line without crashing — logged at `WARNING` if more than one non-blank line is found, since it signals unexpected authoring, not a parser bug.) |
| `description` | All non-blank lines in the body, joined with a single space, forming one paragraph. |
| `match_rule_raw` | The full body, verbatim (blank lines preserved), for audit/debugging. |
| `match_conditions` | From the same body: drop a leading line that exactly equals `"Display this CTA ONLY when:"` if present (Section 6.2's preamble case), then collect every remaining line matching `^-\s+(.+)$`, stripped. |
| `exclusion_conditions` | Only when the `"Do NOT display this CTA if"` section is present: every `^-\s+(.+)$` line in its body. Absent section → `[]`. |
| `related_topics` | Every `^-\s+(.+)$` line in the `Related Topics` body. Absent section → `[]`. |

### 8.6 Grouped-Bullet Fields: `Trigger Examples` and `Aliases`

Both fields are, in the corpus today, either (a) one flat bullet list, or (b) one or more `## Subsection Title` headers each followed by their own bullet list (Section 6.2). A single helper handles both shapes identically, since a flat list is just the degenerate case of "one implicit group with no heading":

```python
_SUBHEADING = re.compile(r"^##\s+(.+)$")
_BULLET = re.compile(r"^-\s+(.+)$")


def _parse_grouped_bullets(body_lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Returns (flat_examples, groups). `groups` is {} when the body has no
    ## subheadings at all -- the flat-list case (most Aliases sections,
    Related Topics). Order-preserving; exact-string dedup only, no case
    normalization (the loader never decides two phrases are 'the same')."""
    groups: dict[str, list[str]] = {}
    current_group = "_default"
    flat: list[str] = []
    seen: set[str] = set()

    for line in body_lines:
        stripped = line.strip()
        heading_match = _SUBHEADING.match(stripped)
        bullet_match = _BULLET.match(stripped)
        if heading_match:
            current_group = heading_match.group(1).strip()
            groups.setdefault(current_group, [])
            continue
        if bullet_match:
            example = bullet_match.group(1).strip()
            groups.setdefault(current_group, []).append(example)
            if example not in seen:
                flat.append(example)
                seen.add(example)

    if current_group == "_default" and not groups.get("_default"):
        groups = {}  # no real subheadings were ever seen -- pure flat-list file
    return flat, groups
```

`trigger_examples`/`trigger_groups` and `aliases` (flat list only — `aliases` does not need the group structure exposed, since nothing in this spec's scope cares about "alternate name" vs. "common misspelling" as distinct categories) are both produced by this one function applied to the `Trigger Examples` and `Aliases` section bodies respectively.

### 8.7 The Irregular Fields: `Do NOT Trigger` and `Fallback Rule`

Per Section 6.2's table, these two fields have the widest authoring variance — named sub-groups, an `Examples:`/`Instead:` sub-label, plain prose, or several of these alternating within one file. Modeling every nesting shape precisely would require a different ad hoc parser for each of the five-plus variants already observed, for a payoff no current or anticipated consumer needs: the future CTA Node's plausible uses of this data are "read the human-authored guidance verbatim" and "get a flat list of phrases that should *not* trigger this CTA" — neither needs to know whether a given exclusion phrase came from a sub-group called "General condition questions" or "Examples".

The loader therefore deliberately uses one uniform, simple strategy for both fields, rather than five special cases:

* `*_raw` (`do_not_trigger_raw`, `fallback_rule`): the full section body, verbatim, with leading/trailing blank lines stripped and internal blank-line runs collapsed to a single blank line — preserves every word a human wrote, including sub-labels and prose, for direct display or for a future LLM-based matcher to read as instructions.
* `do_not_trigger_examples`: every line anywhere in the (merged) `Do NOT Trigger` body matching `^-\s+(.+)$`, flattened across any nesting depth, in file order, exact-string deduplicated. `Fallback Rule` gets no equivalent flattened list — its bullets (where present, e.g. `adhd.md`'s `Instead:` block) are routing instructions ("if X, show CTA Y instead"), not example phrases, so flattening them into a bare list would discard the conditional logic that makes them meaningful; `fallback_rule` is consumed as prose only.

This is a deliberate simplification, not an oversight — see Section 6.2 for the concrete evidence that a richer model would be solving a problem no consumer has yet.

### 8.8 Forward-Compatible Extra Fields

Any **scalar** label line encountered that is not in `KNOWN_LABELS` is not an error — instead of being silently dropped, the raw `label: value` pair is captured into `extra_fields: dict[str, str]` on the record (Section 17). This requires no change to `KNOWN_LABELS` detection logic itself (an unrecognized label by definition doesn't trigger a new section split — it stays inside whichever known section precedes it), so true forward-compatibility for genuinely new top-level fields is deferred to a future parser revision; what Section 17 commits to today is only that *recognized-but-unexpected-content* inside an existing section never crashes the parse.

---

## 9. Data Model

### 9.1 `CTARecord`

```python
from typing import Optional
from pydantic import BaseModel, model_validator


class CTARecord(BaseModel):
    cta_id: str                          # "therapies/mnri" -- stable, derived from path
    title: str                           # "MNRI Therapy CTA"
    source_path: str                     # "therapies/mnri.md", relative to cta_data_dir
    category_dir: str                    # "therapies" -- organizational only, Section 6.1

    status: str                          # "Active" (raw string; see Section 9.3)
    category: str                        # "Therapy", "Condition", "FAQ", ...
    cta_type: str                        # "Individual Therapy", "Library", ...
    priority: str                        # "Specific Therapy", "Specific Therapy - MNRI", ...

    match_rule_raw: str
    match_conditions: list[str]
    exclusion_conditions: list[str]      # [] if "Do NOT display this CTA if" absent

    description: str

    trigger_examples: list[str]          # flattened, deduplicated
    trigger_groups: dict[str, list[str]] # {} if the file uses a flat list with no ## groups

    aliases: list[str]                   # [] if "Aliases" section absent
    related_topics: list[str]            # [] if "Related Topics" section absent

    do_not_trigger_raw: str
    do_not_trigger_examples: list[str]

    fallback_rule: str

    output_label: str
    cta_url: str

    extra_fields: dict[str, str]         # forward-compat bucket, Section 8.8 / 17
    raw_text: str                        # full original file contents, for audit/debug

    @model_validator(mode="after")
    def _validate_required_nonempty(self) -> "CTARecord":
        for field_name in (
            "title", "status", "category", "cta_type", "priority",
            "match_rule_raw", "description", "do_not_trigger_raw",
            "fallback_rule", "output_label", "cta_url",
        ):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        if not self.trigger_examples:
            raise ValueError("trigger_examples must contain at least one example")
        return self

    @model_validator(mode="after")
    def _validate_cta_url(self) -> "CTARecord":
        if not (self.cta_url.startswith("http://") or self.cta_url.startswith("https://")):
            raise ValueError(f"cta_url is not an absolute http(s) URL: {self.cta_url!r}")
        return self
```

This is a second, belt-and-suspenders check on top of the parser's own required-field enforcement (Section 10) — identical in spirit to `SafetyOutput`'s `model_validator`-based re-checks in the Phase 5 spec (`manasi-ai-phase5-safety-trust-boundary-node-spec.md`, Section 11.5): by the time `CTARecord.model_validate(...)` runs, the parser believes the file is valid, but constructing the model is the last gate before a record enters the cache.

### 9.2 `CTALoadIssue` and `CTALoadResult`

Plain dataclasses (mirroring the existing `@dataclass` usage in `app/services/empathy_service.py`) — these are observability/diagnostic structures, not part of the long-lived data model, so a lighter-weight type than Pydantic is appropriate:

```python
from dataclasses import dataclass, field


@dataclass
class CTALoadIssue:
    source_path: str       # relative path, or "<directory>" for a scan-level issue
    reason: str             # machine-readable code, see Section 11.2
    detail: str             # human-readable explanation, safe to log


@dataclass
class CTALoadResult:
    records: list[CTARecord]
    issues: list[CTALoadIssue]
    files_scanned: int
    files_loaded: int
    files_skipped: int
    load_time_ms: float
```

### 9.3 Why `status`/`category`/`cta_type`/`priority` Are Plain Strings, Not Enums

The corpus's own values are not drawn from a small fixed vocabulary applied consistently — `cta_type` alone takes "Individual Therapy", "Individual Condition", "Information Page", "Library", and "Specific Therapy" as distinct values across files that are conceptually similar (`mnri.md` uses "Specific Therapy" as its `cta_type` where `neurofeedback.md` and `arrowsmith.md` use "Individual Therapy" for the same conceptual role, with "Specific Therapy" appearing in *their* `priority` field instead). Constraining these to a `Literal[...]` enum would mean every future content addition that doesn't match today's exact vocabulary fails validation for a reason that has nothing to do with the file being wrong — it would be the loader enforcing a taxonomy the content authors were never asked to follow. Per Section 3.2, deciding what these values *mean* and how they relate to each other is the future CTA Node's job; the loader's job is to carry the string through faithfully. `status` is handled the same way for the same reason, even though only `"Active"` exists in the corpus today — a future `"Draft"` or `"Inactive"` value must load successfully, not be rejected by an enum the loader was never asked to gatekeep (Section 14 offers an `is_active`-style convenience filter for the one value that exists today, without hard-coding it as the only legal value).

---

## 10. Validation Rules

### 10.1 Required vs. Optional, Stated Plainly

| Field / Section | Required? | Behavior if missing/empty |
|---|---|---|
| `# Title` (H1) | Required | File rejected — `reason="missing_title"` |
| `Status` | Required | File rejected — `reason="missing_required_field"` |
| `Category` | Required | File rejected |
| `CTA Type` | Required | File rejected |
| `Priority` | Required | File rejected |
| `Match Rule` | Required | File rejected |
| `Do NOT display this CTA if` | Optional | `exclusion_conditions = []` |
| `Description` | Required | File rejected |
| `Trigger Examples` / `Trigger Conditions` | Required, and must yield ≥ 1 example | File rejected — `reason="no_trigger_examples"` |
| `Aliases` | Optional | `aliases = []` |
| `Related Topics` | Optional | `related_topics = []` |
| `Do NOT Trigger` / `Do NOT Trigger for` | Required (body may legitimately contain zero bullets if purely prose, e.g. `conditions/general.md`'s second occurrence — only the *section itself* is required) | File rejected only if the section is entirely absent |
| `Fallback Rule` | Required | File rejected |
| `Output Label` | Required | File rejected |
| `CTA` | Required, and must be an absolute `http://`/`https://` URL | File rejected — `reason="missing_required_field"` or `reason="invalid_cta_url"` |

### 10.2 Structural Invariants (Enforced by `CTARecord`'s Validators, Section 9.1)

* No required scalar/text field is empty after stripping whitespace.
* `cta_url` starts with `http://` or `https://`.
* `trigger_examples` is non-empty.

### 10.3 Corpus-Level Invariants (Enforced by the Loader, Not the Per-Record Model)

* `cta_id` is unique across all loaded records. Because `cta_id` is derived directly from a unique relative filesystem path (Section 7), a collision can only occur via something external and unusual (e.g. a case-insensitive filesystem mapping two differently-cased paths to one, or a symlink loop) — the loader detects it defensively (first-discovered record wins, in sorted-path order; the later one is recorded as a skipped issue with `reason="duplicate_cta_id"`) rather than asserting it can never happen.
* The loader does NOT validate that `category_dir` matches `category`, that `cta_type` values are drawn from any fixed set, or that `priority` values are comparable/orderable — per Section 9.3, none of that is this module's concern.

---

## 11. Error Handling

### 11.1 Guiding Principle

Mirroring the rest of this codebase's "never block the pipeline" guarantees (the old `cta_service.py`'s `load_cta_registry`, and Phase 5's FR-10 never-degrade fallback), `load_cta_data()` MUST NOT raise. A typo in one of fifteen files is a content problem to be noticed and fixed by a human reading the logs (Section 12), not a reason to take down every process that imports this module.

### 11.2 Issue Catalog

| `reason` code | Trigger | Effect |
|---|---|---|
| `base_dir_missing` | `cta_data_dir` does not exist or is not a directory | Scan short-circuits to zero files; logged `ERROR` |
| `file_read_error` | `OSError` or `UnicodeDecodeError` reading an individual file | That file is skipped; scan continues |
| `missing_title` | First non-blank line is not a valid `# ...` H1 | File skipped |
| `missing_required_field` | A label in `REQUIRED_LABELS` (Section 8.2) has no corresponding section, or its body is empty after extraction | File skipped |
| `no_trigger_examples` | `Trigger Examples`/`Trigger Conditions` section is present but yields zero bullets | File skipped |
| `invalid_cta_url` | `CTA` section's value does not start with `http://`/`https://` | File skipped |
| `schema_validation_failed` | `CTARecord.model_validate(...)` raises despite passing the parser's own checks (belt-and-suspenders catch-all) | File skipped |
| `duplicate_cta_id` | Two files resolve to the same `cta_id` (Section 10.3) | Second file skipped |

Every one of these is recorded as a `CTALoadIssue` (Section 9.2) in the returned `CTALoadResult.issues`, in addition to being logged (Section 12) — tests assert against the structured list, operators read the logs.

### 11.3 What "Skipped" Means in Practice

A skipped file does not appear in `CTALoadResult.records`, is not present in the in-memory cache, and is therefore invisible to every accessor function in Section 14 — exactly as if it did not exist on disk. This is the correct behavior per FR-5: a CTA with a missing or malformed link must never reach a caller, ever.

### 11.4 Zero Valid Files Is Not an Error

If every file in `data/cta/` fails to load (or the directory is empty/missing), `load_cta_data()` still returns a normal `CTALoadResult` with `records=[]` — it does not raise, and it does not treat this as fundamentally different from "1 file loaded, 0 skipped" at the type level. It is, however, surfaced distinctly in logging (a single `WARNING`, Section 12) because an empty CTA dataset is operationally noteworthy even though it is not, structurally, a crash.

---

## 12. Logging

* Logger name: `app.services.cta_loader` (matching the `app.services.<module>` convention already used by `empathy_service`, `safety_service`, etc.).
* **INFO** — exactly one summary line per load/reload call:
  ```python
  logger.info(
      "cta_loader ok: scanned=%d loaded=%d skipped=%d elapsed_ms=%.2f",
      result.files_scanned, result.files_loaded, result.files_skipped, result.load_time_ms,
  )
  ```
* **WARNING** — once per skipped file, at the point of the skip:
  ```python
  logger.warning("cta_loader skip: path=%s reason=%s detail=%s", source_path, reason, detail)
  ```
  Also used for the "more than one non-blank line in a scalar field" tolerance case (Section 8.5) and for `duplicate_cta_id`.
* **ERROR** — `base_dir_missing`, and any unexpected exception caught by the per-file try/except in Section 11.1's catch-all (logged with the exception, then converted into a `schema_validation_failed`-style skip rather than propagating).
* **DEBUG** — benign, expected structural variance that Section 6.2 already documents as normal: merging a duplicate top-level label occurrence (`Do NOT Trigger` + `Do NOT Trigger for`), and defaulting an absent optional section to an empty list. These are not anomalies worth a human's attention on every load; they exist so a developer debugging the parser itself can turn on `DEBUG` and see exactly how a specific file's sections were assembled.
* A load that produces zero records (Section 11.4) additionally logs one extra `WARNING`: `"cta_loader: zero CTA records loaded from %s"`.

---

## 13. Caching Strategy

* A module-level cache, populated eagerly at import time, mirroring the existing precedent of `CTA_REGISTRY = load_cta_registry(settings.cta_links_path)` at the bottom of the old `cta_service.py`:

  ```python
  _CACHE: Optional[CTALoadResult] = None

  def _ensure_loaded() -> CTALoadResult:
      global _CACHE
      if _CACHE is None:
          _CACHE = load_cta_data()
      return _CACHE

  _CACHE = load_cta_data()  # eager load at import time
  ```

* **Why eager, not lazy-on-first-call:** the corpus is tiny (15 files today, plausibly low hundreds at any realistic future scale, Section 15) and read-only at runtime, so the cost of loading at import time is negligible and the benefit is that any startup-time configuration problem (a missing `cta_data_dir`, a corrupted file) surfaces immediately in process logs rather than silently on whatever request happens to be the first one to touch CTA data.
* **Invalidation:** there is no automatic file-watching or mtime-based invalidation — this is a deliberate scope decision, not an oversight (Section 17 revisits it). `reload_cta_data()` is the only supported way to pick up on-disk changes within a running process, intended for test suites and any future admin/hot-reload tooling, not for production request handling:

  ```python
  def reload_cta_data(base_dir: Optional[Path] = None) -> CTALoadResult:
      global _CACHE
      _CACHE = load_cta_data(base_dir=base_dir, force_reload=True)
      return _CACHE
  ```
* **Defensive copies:** accessor functions (Section 14) return new `list`/`dict` objects (e.g. `list(_CACHE.records)`) rather than handing out references into `_CACHE` itself, so a caller mutating a returned list cannot corrupt the shared cache for every other caller in the process.

---

## 14. Public APIs

All of the following live in `app/services/cta_loader.py` and are the **only** supported way for other modules to read CTA data:

```python
def load_cta_data(
    base_dir: Optional[Path] = None,
    force_reload: bool = False,
) -> CTALoadResult:
    """Scans `base_dir` (default settings.cta_data_dir) and parses every CTA
    Markdown file into a CTARecord. Never raises (Section 11). Pass
    force_reload=True to bypass the module cache and re-scan disk; otherwise
    repeated calls within a process are cheap (Section 13)."""


def get_all_ctas() -> list[CTARecord]:
    """Every successfully loaded CTA record, in deterministic (sorted-path)
    order. A defensive copy -- callers may not mutate the shared cache."""


def get_cta_by_id(cta_id: str) -> Optional[CTARecord]:
    """Exact-match lookup by cta_id (e.g. "therapies/mnri"). Returns None,
    never raises, when no such record was loaded -- a missing CTA is a
    normal outcome, not an error, identical in spirit to the old
    cta_service.py's get_cta_url contract."""


def get_ctas_by_category(category: str) -> list[CTARecord]:
    """Every loaded record whose `category` field exactly equals `category`
    (case-sensitive, no normalization -- Section 3.2: this is a structural
    filter, not a matching decision). [] if none match."""


def get_ctas_by_status(status: str) -> list[CTARecord]:
    """Every loaded record whose `status` field exactly equals `status`.
    Convenience for "give me only Active CTAs" without hard-coding "Active"
    as the only legal value anywhere in the loader itself (Section 9.3)."""


def reload_cta_data(base_dir: Optional[Path] = None) -> CTALoadResult:
    """Forces a fresh scan and replaces the module cache. Intended for test
    isolation and future hot-reload tooling, not per-request use."""
```

No `search(...)`, `find_best_match(...)`, or `resolve(query: str)`-shaped function exists anywhere in this module, by design (Section 3.2).

---

## 15. Performance Considerations

| Metric | Target | Rationale |
|---|---|---|
| Cold scan, current corpus (15 files, ≈150 KB total) | < 50ms | Pure local file I/O plus regex-based parsing of a few KB per file; no network, no LLM call (FR-10). |
| Cold scan, projected corpus (≤ 500 files, ≤ 5 MB total) | < 250ms | Linear in file count and total bytes; regex-based line scanning does not degrade non-linearly with file size at any realistic single-file length for hand-authored content. |
| `get_cta_by_id` | O(1) | Backed by a `dict[str, CTARecord]` index built once at load time, in addition to the ordered `list[CTARecord]` (Section 9.2's `CTALoadResult.records` plus a private `_by_id` index populated alongside it). |
| `get_ctas_by_category` / `get_ctas_by_status` | O(n) linear scan over the cached list | Acceptable at the current and reasonably foreseeable corpus size (tens to low hundreds of records); building a category index is deferred (Section 17) until there's evidence it's needed, per this codebase's general preference for the simplest thing that works over speculative optimization. |
| Memory footprint | O(total corpus size) | Each `CTARecord` retains `raw_text` (Section 9.1) for audit purposes, so memory scales with total file bytes, not just extracted fields — negligible at any size this corpus is likely to reach as hand-authored Markdown. |

---

## 16. File Structure

```
app/
    config.py                  (edited — add cta_data_dir, Section 7)
    services/
        cta_loader.py           (new)

data/
    cta/                        (existing — read-only input, no changes)

tests/
    test_cta_loader.py          (new)
```

### 16.1 `app/config.py` (edited)
**Responsibility:** Add `cta_data_dir: Path = BASE_DIR / os.getenv("CTA_DATA_DIR", "data/cta")` to `Settings`, following the exact pattern already used for `vectorstore_dir`/`chroma_persist_dir`. Add a corresponding commented-out `# CTA_DATA_DIR=data/cta` line to `.env.example`.

### 16.2 `app/services/cta_loader.py` (new)
**Responsibility:** Everything in this spec — `KNOWN_LABELS`/`LABEL_ALIASES`/`REQUIRED_LABELS` (Section 8.2), the splitter and field-extraction helpers (Section 8.4–8.7), `CTARecord` (Section 9.1), `CTALoadIssue`/`CTALoadResult` (Section 9.2), `load_cta_data`/`get_all_ctas`/`get_cta_by_id`/`get_ctas_by_category`/`get_ctas_by_status`/`reload_cta_data` (Section 14), and the module-level cache (Section 13). A single, self-contained module with no dependency on any other `app/services/*` file.

### 16.3 `tests/test_cta_loader.py` (new)
**Responsibility:** Per Section 18.

Explicitly **not** part of this change set: `app/graph/state.py`, anything under `app/nodes/`, `app/prompts/`, `app/main.py`, or `app/models.py`. Those are where a future CTA Node would integrate this loader's output into the LangGraph pipeline, and are out of scope per Section 3.2.

---

## 17. Future Extensibility

* **CMS migration without a consumer-facing change.** Every parsing function in Section 8 takes already-read text plus a `source_path` string, decoupled from `pathlib`/filesystem I/O (only `load_cta_data`'s outer loop touches the filesystem directly). A future CMS-backed source (e.g. fetching Markdown bodies from a Webflow/CMS API instead of local disk) could reuse `_parse_cta_file(text: str, source_path: str) -> CTARecord` unchanged, swapping only the file-discovery loop for an API-paging loop — `CTARecord`, and therefore every downstream consumer including the future CTA Node, would not need to change at all.
* **New optional scalar fields.** Section 8.8's `extra_fields` bucket means a new top-level `Label: value` line added to future CTA files (e.g. a future `Locale:` or `Experiment:` tag) is captured rather than silently lost, without requiring a `CTARecord` schema change to avoid the file being rejected. Promoting a frequently-used `extra_fields` key into a first-class typed field remains a deliberate, reviewed schema change, not something the loader does automatically.
* **Category/status indexing.** Section 15 defers building a `category -> records` index in favor of a linear scan; if the corpus grows enough for that to matter, it is a purely internal change to `load_cta_data`'s post-processing step with no change to the public API in Section 14.
* **File-watching / mtime-based invalidation.** Section 13 deliberately ships without it. If a future operational need arises for the running process to pick up content edits without a restart, the natural extension point is `_ensure_loaded()` checking the base directory's aggregate mtime before deciding whether to reuse `_CACHE` — a self-contained change to Section 13 alone.
* **A second, structured `trigger_groups`-equivalent for `Do NOT Trigger`.** Section 8.7 explains why this is deliberately not built now. If a future CTA Node turns out to need the sub-group labels (e.g. to explain *why* a phrase was excluded, not just *that* it was), the raw text (`do_not_trigger_raw`) already contains everything needed to add that structure later without re-deriving it from scratch.

---

## 18. Unit Testing Requirements

`tests/test_cta_loader.py`, using `pytest` and the `tmp_path` fixture to build synthetic CTA Markdown files on disk (mirroring this codebase's existing `tests/test_validators.py` style: plain functions, no mocking framework, since there is nothing generative to fake here at all).

### 18.1 Required Test Cases

| Test | Asserts |
|---|---|
| `test_loads_well_formed_minimal_file` | A synthetic file with every required section, flat bullets throughout, no optional sections → loads successfully; `exclusion_conditions == aliases == related_topics == []`. |
| `test_loads_file_with_all_optional_sections_present` | A synthetic file matching `about.md`'s full shape → every field populated as expected. |
| `test_rejects_file_missing_required_field` | One file per required label (Section 10.1), each missing that single label → each rejected with `reason="missing_required_field"`, and every *other* file in the same temp directory still loads. |
| `test_rejects_file_with_invalid_cta_url` | `CTA:` value is `"not-a-url"` → rejected with `reason="invalid_cta_url"`. |
| `test_rejects_file_with_no_title` | File body has no `# ...` H1 line → rejected with `reason="missing_title"`. |
| `test_rejects_file_with_zero_trigger_examples` | `Trigger Examples:` section present but contains zero `- ` lines → rejected with `reason="no_trigger_examples"`. |
| `test_match_rule_without_preamble_parses_bullets` | Body is bullets directly with no `"Display this CTA ONLY when:"` line (mirroring `therapies/general.md`/`mnri.md`) → `match_conditions` still populated correctly. |
| `test_match_rule_with_preamble_strips_preamble_line` | Body includes the preamble line → it does not appear in `match_conditions`. |
| `test_grouped_trigger_examples_flatten_correctly` | Multiple `##` subsections under `Trigger Examples` → `trigger_examples` is the deduplicated flattened union, in order; `trigger_groups` preserves the per-subsection breakdown. |
| `test_flat_aliases_parse_without_groups` | `Aliases:` is a flat bullet list → `aliases` populated, no spurious `_default` key artifact. |
| `test_grouped_aliases_parse_like_mnri` | `Aliases:` uses `## Alternate Names` / `## Common Misspellings` subsections (mirroring `mnri.md`) → both groups' bullets all end up in the flat `aliases` list. |
| `test_do_not_trigger_with_named_subgroups_flattens_bullets` | Body has prose + two named sub-group labels + bullets under each (mirroring `adhd.md`) → `do_not_trigger_examples` contains every bullet from both groups; `do_not_trigger_raw` preserves the full original text including the sub-group labels. |
| `test_duplicate_do_not_trigger_headings_are_merged` | A file with both `Do NOT Trigger:` and `Do NOT Trigger for:` (mirroring `conditions/general.md`) → both bodies are merged into one `do_not_trigger_raw`/`do_not_trigger_examples`, no exception, no silently-dropped second section. |
| `test_fallback_rule_prose_only` | Body is plain prose, no bullets → `fallback_rule` is the prose, non-empty. |
| `test_fallback_rule_with_instead_label_and_bullets` | Body has prose + `Instead:` + bullets (mirroring `adhd.md`) → `fallback_rule` includes all of it as one string. |
| `test_unrecognized_scalar_field_captured_in_extra_fields` | File includes an extra `Locale: en-US`-style line → loads successfully; `extra_fields == {"Locale": "en-US"}`; no other field is affected. |
| `test_recursive_discovery_finds_nested_files` | Files at multiple folder depths under `tmp_path` → all discovered regardless of depth. |
| `test_non_markdown_files_ignored` | A stray `.txt`/`.json` file in the same directory → not parsed, not reported as an issue (it was never a candidate). |
| `test_missing_base_directory_returns_empty_result_no_raise` | `base_dir` points at a path that does not exist → `CTALoadResult(records=[], ...)`, `files_scanned == 0`, no exception, one issue with `reason="base_dir_missing"`. |
| `test_empty_base_directory_returns_empty_result_no_raise` | `base_dir` exists but contains zero `.md` files → empty result, no exception, no false "missing directory" issue logged. |
| `test_duplicate_cta_id_keeps_first_sorted_occurrence` | Construct two paths that collide on `cta_id` (e.g. via a controlled case-folding test fixture) → first-by-sorted-path wins; second recorded with `reason="duplicate_cta_id"`. |
| `test_get_cta_by_id_returns_none_for_unknown_id` | No matching record → `None`, not an exception. |
| `test_get_ctas_by_category_and_status_filter_correctly` | Multiple synthetic records spanning categories/statuses → each accessor returns exactly the matching subset, `[]` when nothing matches. |
| `test_reload_picks_up_on_disk_changes` | Load, then modify a fixture file on disk, then call `reload_cta_data()` → the updated content is reflected; a plain second call to `get_all_ctas()` without `reload_cta_data()` is NOT required to reflect the change (asserts the caching contract from Section 13, not just that reload works). |
| `test_accessor_results_are_defensive_copies` | Mutate a list returned by `get_all_ctas()` → a subsequent call returns an unmutated result. |

### 18.2 Regression Guard Against the Real Corpus

One additional integration-style test, run against the actual `data/cta/` directory (not a synthetic fixture):

```python
def test_real_cta_corpus_loads_with_zero_issues():
    result = load_cta_data(force_reload=True)
    expected_file_count = len(list(settings.cta_data_dir.rglob("*.md")))
    assert result.files_scanned == expected_file_count
    assert result.issues == []
    assert result.files_loaded == expected_file_count
```

This pins the parser against the live, evolving corpus: if a future content edit introduces a structural shape this spec's parsing strategy doesn't yet handle, this test fails in CI immediately, rather than the gap being discovered only once a future CTA Node silently can't see that file. The assertion is computed from the corpus itself (`rglob` count), not a hard-coded `15`, so adding a sixteenth well-formed CTA file does not require updating this test.

---

## 19. Acceptance Criteria

### 19.1 Test Case Categories

| Category | Pass Criteria |
|---|---|
| Schema validity | Every record in `get_all_ctas()` is a valid `CTARecord` per Section 9.1's validators, for both the synthetic fixture suite (Section 18.1) and the real corpus (Section 18.2). |
| Corpus regression | `test_real_cta_corpus_loads_with_zero_issues` (Section 18.2) passes against the current 15-file `data/cta/` tree with zero skipped files and zero issues. |
| Fault isolation | Every "rejects file with X" test in Section 18.1 confirms the *other* synthetic files in the same temp directory still load successfully in the same `load_cta_data()` call. |
| Never-raise guarantee | `load_cta_data()` does not raise for: a missing base directory, an empty base directory, a file with invalid encoding, a file with every required field missing simultaneously, and a directory containing only non-`.md` files. |
| Caching contract | A second call to any accessor function within a process does not re-read the filesystem (verified via a fixture that mutates disk between two non-reload calls and asserts the second call still reflects the pre-mutation state, then confirms `reload_cta_data()` does pick up the change). |
| API surface discipline | No function in `app/services/cta_loader.py` accepts a free-text query, a `user_message`, or any conversation-shaped input — verified by a deliberately blunt test asserting the module's public callables list matches exactly the six functions in Section 14, no more. |

### 19.2 Definition of Done

This specification is considered fully implemented only when **all** of the following hold:

1. `app/services/cta_loader.py` exists and implements every function in Section 14, with no additional public function whose name or signature implies matching, scoring, or selection (Section 3.2).
2. `app/config.py` has a `cta_data_dir` setting following the established `Settings` pattern (Section 16.1).
3. Every test case listed in Section 18.1, plus the corpus regression test in Section 18.2, exists in `tests/test_cta_loader.py` and passes.
4. The real `data/cta/` corpus (15 files at time of writing) loads with `files_loaded == files_scanned` and `issues == []` — every authoring irregularity catalogued in Section 6.2 is provably handled, not just theoretically addressed.
5. No code path in the module imports `langchain`, `langgraph`, or any LLM/embeddings client (FR-10), verified by a static import check or simply by code review against the module's actual `import` lines.
6. Running `load_cta_data()` against the real corpus twice in a row, with no `force_reload`, results in the second call not touching the filesystem (verified via the caching-contract test, Section 19.1).

---

## 20. Future Considerations (Explicitly Out of Scope Here)

* **The CTA Node itself.** Matching a user's question against `trigger_examples`/`aliases`/`match_conditions`, applying `exclusion_conditions`/`do_not_trigger_examples`, resolving ties between multiple plausible categories (e.g. a question that is both about a condition and a therapy), and deciding a final `matched`/`cta_url` outcome for a turn — all of this is a separate spec, to be written once this loader exists and its `CTARecord` contract is stable. That future spec is the natural place to decide whether matching is keyword-based, embedding-based, or LLM-judged; this document takes no position on that question.
* **`GraphState` integration.** Adding a `cta: Optional[CTA]` field to `app/graph/state.py`, wiring a `cta_node.py` into the production graph, and deciding where in the pipeline (relative to `knowledge_node`/`response_node`/`safety_node`) it runs are all future-CTA-Node concerns, not loader concerns.
* **Authoring tooling.** Nothing here proposes a linter, a content-authoring template, or a pre-commit check that would catch a malformed CTA file before it reaches `data/cta/` at all — Section 18.2's regression test is the only safety net today, and it is a CI-time guard, not an authoring-time one.
* **Multi-locale CTA content.** Every file in the corpus today is English-only, as is every fixed string in this spec. A future localized corpus would need a parallel `data/cta/<locale>/` structure and a locale-aware `load_cta_data`, which this spec does not attempt to anticipate beyond the `extra_fields` escape hatch (Section 17).
* **mtime-based or file-watcher-based cache invalidation.** Noted in Section 17 as a plausible extension; not built now because nothing currently requires the running process to observe a content edit without a restart.

---

*End of CTA Data Loader Specification.*
