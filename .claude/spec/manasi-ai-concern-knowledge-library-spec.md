# Manasi AI — Technical Specification
## Concern Knowledge Library (Markdown Knowledge Layer)

**Project:** Manasi AI
**Organization:** ManaScience
**Layer:** Knowledge Content Layer (feeds the existing Knowledge Node / RAG)
**Status:** Draft for implementation
**Audience:** Content architects, clinical content authors, Python/LangGraph engineers
**Governing document for response behaviour:** `docs/MANASI_ANSWER_PLAYBOOK.md`

**Depends on:**
- `docs/MANASI_ANSWER_PLAYBOOK.md` — **authoritative** for answer structure, tone, safety boundaries, approved phrasings, the ManaScience perspective, the referenceable therapy list, and CTA behaviour. This specification does **not** restate those rules; it references them.
- `manasi-ai-phase1-understanding-node-spec.md` (intent / emotion / topic / search_query contract)
- `manasi-ai-phase2-knowledge-node-spec.md` (ChromaDB collection, metadata envelope, retrieval thresholds)
- `manasi-ai-phase3-response-generation-node-spec.md` (how retrieved context becomes an answer)
- `manasi-ai-phase5-safety-trust-boundary-node-spec.md` (medical boundary enforcement)
- `manasi-ai-phase6-cta-node-spec.md` (CTA corpus, `cta_id` format)

**Last Updated:** 2026-07-28

---

## Table of Contents

1. Executive Summary
2. Problem Statement
3. Goals
4. Non-Goals
5. Architecture Overview
6. Folder Structure
7. Markdown Schema
8. Metadata Specification
9. Naming Conventions
10. Retrieval Flow
11. File Relationships and Cross-Linking
12. Validation Rules
13. Versioning Strategy
14. Migration Strategy
15. Example Folder Tree
16. Complete Example Markdown File
17. Contribution Guidelines
18. Engineering Recommendations
19. Risks
20. Future Enhancements
21. Appendix A — Controlled Vocabularies
22. Appendix B — Field → Storage Mapping Matrix

---

## 1. Executive Summary

Manasi's pipeline (Understanding → Knowledge/RAG → Response Generation → Empathy → Safety → CTA) is complete and working, but its knowledge base is currently three general-purpose ManaScience documents (`manascience_faq.md`, `manascience_therapies.md`, `manasi_overview.md`) plus the CTA trigger corpus under `data/cta/`. None of that content is organized around the thing parents actually type: *"My child is not speaking."*

This specification defines the **Concern Knowledge Library** — a Markdown-only, repository-resident knowledge layer where each file captures **exactly one developmental concern** as *structured, reusable knowledge*, never as a finished chatbot answer. A concern file tells the pipeline what a concern is, how parents phrase it, what may explain it developmentally, what to observe, what helps day to day, how ManaScience frames it through neuroplasticity, where the professional boundary lies, and which conditions, therapies, concerns and CTAs it relates to. The Response Generation Node assembles that raw material into a personalized answer; the Empathy Node gives it Manasi's voice; the Safety Node validates the boundary; the CTA Node attaches the next step.

The design has three load-bearing properties:

1. **Machine-readable head, human-readable body.** Every file is YAML front matter (closed-vocabulary metadata, relationships, retrieval hints) followed by fixed, named `##` sections (educational prose in bullet form). The head drives filtering, relationships and migration; the body drives semantic retrieval and response assembly.
2. **Retrieval is two-stage.** Vector search finds the *concern*, not a paragraph. Chunks vote for a `concern_id`; the winning concern's full structured record is then loaded from the Markdown corpus and handed to Response Generation. This keeps answers coherent instead of stitched from unrelated chunk fragments, and it keeps Manasi within `KNOWLEDGE_MAX_CONTEXT_CHARS`.
3. **Storage-neutral information architecture.** The field set, ID scheme and relationship model are defined independently of Markdown. Markdown is the MVP *serialization*, not the architecture. JSON, MongoDB, PostgreSQL, ChromaDB and Pinecone targets are all mechanical projections of the same fields (Section 14, Appendix B) — the migration changes the container, never the content model.

**This library defines what Manasi knows, not how Manasi answers.** `docs/MANASI_ANSWER_PLAYBOOK.md` already defines the answer format, the five-beat Explain shape, tone per emotional state, the non-negotiable safety rules with their approved phrasings, the ManaScience commitments, the therapies Manasi may reference, and how CTAs are attached. That document remains authoritative and unduplicated here. Where this specification touches response behaviour, it *cites* the playbook rather than restating it — and where the two ever appear to disagree, the playbook wins (Section 5.1).

The library is specified to scale to 500+ concerns, 300+ therapies, 150+ conditions, plus research articles, FAQs, blogs and assessment explanations, all inside the same `data/knowledge/` tree, under one shared metadata envelope and one shared validator.

---

## 2. Problem Statement

### 2.1 What is wrong today

* **The corpus does not match the questions.** `INTENT_CONTENT_TYPE_MAP` in `app/rag/retriever.py` routes `personal_concern` to `therapy_info`, `practitioner_info`, `neuroplasticity_content` and `faq`. A parent asking *"my son doesn't respond to his name"* is therefore answered from therapy marketing copy or FAQ text that was never written to explain that behaviour. There is no content type that *is* the concern.
* **The RAG fallback is silently doing the work.** With `RAG_SIMILARITY_THRESHOLD = 0.35` and `RAG_MIN_RELEVANT_CHUNKS = 1`, weak matches either scrape past the threshold (grounding an answer in near-irrelevant material) or fall through to `source = "llm"`, where Manasi answers from generic model knowledge with no ManaScience framing, no neuroplasticity perspective and no curated professional boundary. Neither outcome is ManaScience's answer.
* **Trigger corpora are being misused as knowledge.** `data/cta/**` files (e.g. `data/cta/conditions/autism.md`) contain hundreds of parent phrasings — excellent *matching* signal, zero *explanatory* content. They exist to decide which link to show, not to teach.
* **Knowledge is condition-shaped, not concern-shaped.** Parents do not arrive saying "tell me about ASD"; they arrive with a behaviour. Condition-first content forces the pipeline to leap from an observation to a diagnostic label — precisely the leap Manasi must never make.
* **Nothing is authored against the pipeline's needs.** The Response Generation Node needs explanation material; the Safety Node needs an explicit boundary statement; the CTA Node needs a mapping. Today each node improvises from unstructured prose.
* **The behavioural half of the problem is already solved; the factual half is not.** `docs/MANASI_ANSWER_PLAYBOOK.md` specifies precisely *how* Manasi should answer sixty real concern questions — structure, tone, boundaries, the ManaScience lens — and its exemplar answers demonstrate it working. What it cannot do is supply the *substance* for the 500 concerns it does not enumerate: the explanations, observations and support ideas that fill the Explain body. Every one of its exemplar answers had to be hand-written for exactly that reason. This library is the missing input that makes the playbook's format reproducible at scale rather than one question at a time.

### 2.2 Why Markdown, and why now

The MVP constraint is deliberate and correct: no database, no CMS, no JSON build step. Markdown files in the repo give ManaScience content review through pull requests, diffable clinical edits, no infrastructure to operate, and no schema migration cost while the taxonomy is still moving. The risk of Markdown — that it becomes unstructured, unvalidated prose that cannot be migrated later — is exactly what this specification exists to prevent, through a closed metadata schema, a fixed section set and a hard validation gate.

---

## 3. Goals

| # | Goal | Success criterion |
|---|---|---|
| G-1 | One concern per file, authoritatively | Every published file has exactly one `concern_id`, and a validator rejects multi-concern files (Section 12.4) |
| G-2 | Store reusable knowledge, never chatbot answers | Zero published files contain second-person direct address or assembled response prose; enforced by the style validator (V-27…V-30) |
| G-3 | Optimize for semantic retrieval | Every concern is reachable from ≥ 12 distinct real parent phrasings at similarity ≥ `RAG_SIMILARITY_THRESHOLD` (Section 10.7 evaluation set) |
| G-4 | Give Response Generation structured slots | Every published file provides all 7 required prose sections; the generator never needs a field the schema lacks |
| G-5 | Make the professional boundary mechanical | Every file carries `professional_boundary` and `when_professional_evaluation_may_help`; Safety Node validates against content, not vibes |
| G-6 | Make relationships explicit and navigable | 100 % of `related_*` IDs resolve to existing files or registry entries; no dangling links in `published` content |
| G-7 | Stay maintainable at 500+ concerns | Adding a concern requires touching exactly one new file plus (optionally) reciprocal links; no central registry edit required for concerns |
| G-8 | Migrate without re-authoring | Every field maps to JSON/Mongo/PG/Chroma/Pinecone per Appendix B with no content rewrite |
| G-9 | Version content safely | Content changes are reviewable, attributable, dated, and reversible via Git plus `schema_version` / `content_version` / `status` |
| G-10 | Feed the Answer Playbook's structure without duplicating it | All five Playbook Part 2 Explain beats are sourceable from any published concern file (V-50); this document defines zero answer-format, tone or approved-phrasing rules of its own |

---

## 4. Non-Goals

* **N-1 — Not a diagnostic system.** Concern files never assert what a child *has*. They describe what a behaviour *may* reflect. No decision trees, no scoring, no screening thresholds, no "if 3 of 5 then autism".
* **N-2 — Not a treatment recommender.** Files never prescribe therapy, dosage, duration or provider. `related_therapies` is an *educational pointer*, not a recommendation.
* **N-3 — Not chatbot copy, and not a second answer policy.** No greetings, no empathy lines, no closing questions, no CTA sentences. The Empathy and CTA Nodes own those at runtime, and `MANASI_ANSWER_PLAYBOOK.md` owns them on paper. This specification defines no answer format, no tone rules, no approved phrasings and no CTA routing logic of its own — duplicating any of that would create a second, divergent source of truth (R-15).
* **N-4 — No runtime code in this document.** This is a content and information-architecture specification. Loader, validator and ingestion implementations are separate engineering tickets (Section 18.1).
* **N-5 — Not a replacement for the CTA corpus.** `data/cta/**` keeps owning trigger/exclusion/link rules. Concern files reference CTAs by `cta_id`; they never carry URLs or output labels.
* **N-6 — No database in the MVP.** No JSON build artifacts committed, no CMS, no admin UI. Markdown is the single source of truth.
* **N-7 — Not localized in v1.** English (Indian-English parent vocabulary included). Localization is designed for (Section 20.4) but out of scope.
* **N-8 — Not a change to the pipeline's node contracts.** The library is additive: a new `content_type`, new corpus directories, new ingestion path. Node input/output schemas are untouched except for the additive changes named in Section 10.9.

---

## 5. Architecture Overview

### 5.1 Governing documents and separation of responsibilities

Manasi's behaviour is specified by two documents plus one node that joins them. They must never overlap.

| Document / component | Owns | Answers the question | Never contains |
|---|---|---|---|
| **`docs/MANASI_ANSWER_PLAYBOOK.md`** | Answer structure (Part 2), the ManaScience perspective and referenceable therapy list (Part 3), safety non-negotiables and approved phrasings (Part 4), the reusable template (Part 5), behaviour-not-condition discipline (Part 6), worked exemplars (Part 7), CTA routing reality and gaps (Part 8), escalation (Part 9) | **How Manasi answers** | Per-concern facts, explanations, observation lists, support ideas |
| **Concern Knowledge Library** (this spec) | Structured knowledge per concern: phrasings, possible explanations, development domains, things to observe, everyday support ideas, concern-specific ManaScience framing and boundary, relationships, CTA mapping hints | **What Manasi knows** | Answer format, tone rules, greeting/closing copy, approved phrasing catalogue, CTA routing logic |
| **Response Generation Node** | Selecting and composing knowledge into a draft answer under the playbook's structure | **How the two combine** | Content of its own — it may not invent facts absent from the retrieved knowledge, nor structure absent from the playbook |

```
   MANASI_ANSWER_PLAYBOOK.md              Concern Knowledge Library
   ── how Manasi answers ──               ── what Manasi knows ──
   • 4-part answer format                 • possible explanations
   • 5-beat Explain shape                 • things to observe
   • tone per emotional_state             • everyday support ideas
   • Never / Always rules                 • development domains
   • approved boundary phrasings          • related concerns / conditions
   • referenceable therapy list           • per-concern ManaScience framing
   • CTA behaviour                        • per-concern boundary statement
              │                                        │
              └────────────────┬───────────────────────┘
                               ▼
                   RESPONSE GENERATION NODE
        structure + tone from the playbook, applied to
        facts from the library → draft answer
                               ▼
              Empathy → Safety → CTA (unchanged)
```

**Precedence rules:**

* **GD-1 — The playbook is authoritative on behaviour.** Any statement in this specification touching structure, tone, safety phrasing or CTA behaviour is a *reference*, not a definition. If the two disagree, the playbook governs and this document is corrected.
* **GD-2 — This specification is authoritative on knowledge shape.** The playbook does not define front matter, section names, IDs, relationships, validation or storage. It never should.
* **GD-3 — Single-source rule.** A rule lives in exactly one document. When a concern file needs a boundary sentence, it uses the playbook's approved phrasing verbatim (V-47) rather than an author's paraphrase; when the playbook needs facts about a concern, it draws on the library rather than embedding new claims.
* **GD-4 — The playbook's exemplars are the acceptance test.** A concern file is well-formed if the Response Generation Node can build a playbook-Part-7-quality answer from it without inventing facts. Section 7.6 maps the library's sections onto the playbook's Explain beats so this is checkable, not aspirational.
* **GD-5 — Changes propagate one way.** A playbook change (new tone rule, revised phrasing) may require a library update; a library change never rewrites the playbook. Playbook Part 3's therapy list is the single vocabulary for `related_therapies` (V-48).

### 5.2 Layer position

```
                    ┌──────────────────────────────────────────────┐
                    │  AUTHORING LAYER (humans, Git, PR review)    │
                    │  data/knowledge/**/*.md                      │
                    └───────────────┬──────────────────────────────┘
                                    │  validate (CI gate)
                    ┌───────────────▼──────────────────────────────┐
                    │  LOADER LAYER (parse → typed records)        │
                    │  front matter + sections → ConcernRecord     │
                    │  never raises; skips invalid files w/ reason │
                    └───────┬───────────────────────┬──────────────┘
                            │                       │
              ingest (build)│                       │lookup by concern_id (runtime)
                            │                       │
            ┌───────────────▼─────────┐   ┌─────────▼──────────────┐
            │  VECTOR LAYER (Chroma)  │   │  STRUCTURED LAYER      │
            │  chunk + embed + meta   │   │  in-memory record cache│
            │  collection:            │   │  (mirrors cta_loader)  │
            │  manascience_knowledge  │   │                        │
            └───────────────┬─────────┘   └─────────┬──────────────┘
                            │                       │
                    ┌───────▼───────────────────────▼──────────────┐
                    │  PIPELINE (unchanged node contracts)         │
                    │  Understanding → Knowledge → Response →      │
                    │  Empathy → Safety → CTA                      │
                    └──────────────────────────────────────────────┘
```

### 5.3 The three representations of one concern

| Representation | Lives in | Purpose | Authority |
|---|---|---|---|
| **Markdown file** | `data/knowledge/concerns/<category>/<slug>.md` | Human authoring, review, diffing | **Source of truth** |
| **ConcernRecord** | Loader cache (memory) | Typed, validated access by `concern_id`; supplies structured sections to Response Generation | Derived, rebuilt on load |
| **Chunks** | Chroma collection | Semantic *findability* only | Derived, rebuilt on ingest |

**Rule A-1:** Derived representations are always rebuildable from Markdown alone. Nothing may exist only in the index or only in the cache.

**Rule A-2:** Chunks answer *"which concern is this?"*. The record answers *"what do we know about it?"*. A chunk's text is never handed to Response Generation as the sole context when its parent record is available.

### 5.4 Content types in the unified corpus

The Knowledge Node's `CONTENT_TYPES` literal (`app/nodes/knowledge_node.py`) currently allows nine values. This library adds **`concern_knowledge`** and reserves four more for the sibling corpora that share the tree:

| `content_type` | Corpus root | Status |
|---|---|---|
| `concern_knowledge` | `data/knowledge/concerns/` | **New — this spec** |
| `condition_knowledge` | `data/knowledge/conditions/` | Reserved (same envelope, different body sections) |
| `therapy_knowledge` | `data/knowledge/therapies/` | Reserved |
| `assessment_knowledge` | `data/knowledge/assessments/` | Reserved |
| `milestone_knowledge` | `data/knowledge/milestones/` | Reserved |
| `faq`, `blog`, `research_article`, `therapy_info`, `website_content`, `neuroplasticity_content`, `course`, `practitioner_info`, `pdf_document` | existing | Unchanged |

All corpora share Section 8's **common envelope**; only the `##` body sections differ per corpus. That is what keeps one loader, one validator and one ingestion path viable at 1,000+ files.

---

## 6. Folder Structure

### 6.1 Principles

* **P-1 — One physical file per knowledge unit.** No file contains two concerns; no concern spans two files.
* **P-2 — Directory = category = taxonomy.** A file's parent directory is its `category`; the front matter must agree (V-6). One source of truth for taxonomy, checkable by `ls`.
* **P-3 — Two levels deep, never three.** `corpus/category/file.md`. Deeper nesting produces path churn every time the taxonomy shifts.
* **P-4 — Flat within a category.** Sub-grouping happens through `tags` and relationships, not folders — a concern legitimately belongs to several groupings, and folders can only express one.
* **P-5 — Corpora are siblings, not nested.** `concerns/`, `conditions/`, `therapies/` sit side by side so each can be ingested, validated and versioned independently.
* **P-6 — `data/cta/` is untouched.** The CTA corpus keeps its own root, structure and loader.

### 6.2 Root layout

```
data/
├── cta/                          # EXISTING — CTA trigger corpus (unchanged)
├── roadmap/                      # EXISTING — roadmap workbooks (unchanged)
├── manascience_faq.md            # EXISTING — legacy flat files (unchanged)
├── manascience_therapies.md
├── manasi_overview.md
└── knowledge/                    # NEW — the structured knowledge layer
    ├── _schema/                  # schema contracts, not content (never ingested)
    │   ├── concern.schema.md
    │   ├── vocabularies.md
    │   └── CHANGELOG.md
    ├── _templates/               # authoring templates (never ingested)
    │   └── concern.template.md
    ├── concerns/                 # THIS SPEC
    │   ├── communication/
    │   ├── social/
    │   ├── behaviour/
    │   ├── sensory/
    │   ├── motor/
    │   ├── attention/
    │   ├── learning/
    │   ├── emotional/
    │   ├── sleep/
    │   ├── feeding/
    │   ├── daily_living/
    │   └── milestones/
    ├── conditions/               # reserved, same envelope
    ├── therapies/                # reserved
    ├── assessments/              # reserved
    ├── research/                 # reserved
    └── faqs/                     # reserved
```

### 6.3 Reserved-prefix rule

Any directory whose name begins with `_` (underscore) is **infrastructure, not content**: never loaded, never chunked, never embedded. This is what lets schema docs, templates and authoring notes live beside the content without polluting retrieval. (The CTA loader already ignores dot-prefixed paths; the concern loader extends the rule to `_`.)

### 6.4 Category set (v1)

| Directory | Covers | Representative concerns |
|---|---|---|
| `communication/` | speech, language, understanding, expression | `speech_delay`, `not_responding_to_name`, `echolalia`, `unclear_speech` |
| `social/` | interaction, play, relating | `avoids_eye_contact`, `not_playing_with_peers`, `prefers_being_alone` |
| `behaviour/` | externalized behaviour, regulation | `daily_tantrums`, `hitting_others`, `repetitive_behaviours`, `meltdowns` |
| `sensory/` | sensory reactivity and seeking | `distressed_by_loud_sounds`, `avoids_certain_textures`, `constant_movement_seeking` |
| `motor/` | gross and fine motor | `late_walking`, `poor_pencil_grip`, `clumsiness` |
| `attention/` | attention, activity level, executive function | `hyperactivity`, `cannot_sit_still`, `poor_attention_span` |
| `learning/` | academic and cognitive learning | `difficulty_learning_letters`, `struggles_with_reading` |
| `emotional/` | mood, anxiety, emotional regulation | `separation_distress`, `frequent_crying`, `intense_fears` |
| `sleep/` | sleep onset, maintenance, patterns | `difficulty_falling_asleep`, `frequent_night_waking` |
| `feeding/` | eating, food range, mealtimes | `extremely_restricted_diet`, `refuses_new_foods` |
| `daily_living/` | self-care, adaptive skills | `toilet_training_difficulty`, `dressing_difficulty` |
| `milestones/` | general/global developmental pacing | `not_meeting_milestones`, `regression_of_skills` |

Adding a category is a schema change (Section 13.3), not a content change: it requires a `_schema/vocabularies.md` update and a validator vocabulary bump.

---

## 7. Markdown Schema

### 7.1 File anatomy

```
┌─────────────────────────────────────────┐
│ ---                                     │  ← YAML front matter
│ concern_id: speech_delay                │     machine-readable
│ ...                                     │     closed vocabularies
│ ---                                     │     drives filter + relations + migration
├─────────────────────────────────────────┤
│ # Speech Delay                          │  ← H1: display title (exactly one)
├─────────────────────────────────────────┤
│ ## Summary                              │  ← H2 sections: fixed names, fixed order
│ ## Typical User Questions                │     human-readable
│ ## Possible Explanations                 │     drives embeddings + response assembly
│ ...                                      │
└─────────────────────────────────────────┘
```

**Why YAML front matter rather than the CTA corpus's `Label:` convention.** The CTA loader parses `Label:` lines because that corpus predates any schema discipline, and its parser needs 200 lines of label-alias, merge and normalization logic to survive author variation. Front matter gives typed lists, typed scalars, standard tooling, and a single unambiguous parse for the migration targets in Section 14. The concern corpus starts clean and should not inherit the older convention's cost. The `Label:` corpus is not being migrated as part of this work.

### 7.2 Front-matter rules

* **S-1** The file MUST begin with `---` on line 1; the block MUST close with a `---` line. No content before it.
* **S-2** The block MUST be valid YAML 1.2, UTF-8, LF line endings, 2-space indentation, no tabs.
* **S-3** All keys are `snake_case`, from the closed key set in Section 8. Unknown keys are a validation error (V-3), not a silent pass — this is what prevents schema drift across 500 files.
* **S-4** List fields are always YAML block sequences, never comma strings, even with one element.
* **S-5** String values containing `:`, `#`, `?`, leading `-`, or a leading digit MUST be quoted.
* **S-6** Field order in the file follows Section 8's declaration order. Machines do not care; reviewers reading 500 diffs do.

### 7.3 Body rules

* **S-7** Exactly one `#` H1, immediately after the front matter. It is the human display title and MUST equal `title`.
* **S-8** Sections are `##` headings, spelled exactly as in Section 7.4, in that order. No `###` in v1 — subsection nesting fragments chunking and complicates section-slot mapping.
* **S-9** Every required section MUST be present and non-empty. An absent-but-required section is an error; a genuinely inapplicable section is filled with the explicit sentinel `- Not applicable for this concern.` so reviewers can distinguish "considered and rejected" from "forgotten".
* **S-10** Section bodies are bullet lists (`- `). Each bullet is one self-contained idea, 8–45 words, ending with a period. Bullets are the atomic reuse unit: Response Generation selects and rephrases bullets; it does not parse paragraphs.
* **S-11** No nested bullets in v1 (flat lists chunk and re-assemble predictably).
* **S-12** No tables, images, HTML, code fences, or footnotes in section bodies. `## References` is the only section allowed inline links.
* **S-13** No horizontal rules (`---`) anywhere in the body. A bare `---` collides with front-matter delimiting and with the existing FAQ block splitter in `scripts/build_knowledge_index.py`.
* **S-14** Bold/italic are permitted but discouraged; emphasis does not survive into a generated response and adds diff noise.

### 7.4 Section catalog

**Required (7 knowledge sections + 2 index sections = 9):**

| # | Section | Purpose | Content rules | Size |
|---|---|---|---|---|
| 1 | `## Summary` | Neutral 2–4 sentence definition of the concern as a *behaviour*, for retrieval anchoring and quick grounding | Prose (the one prose exception to S-10). No reassurance, no address to the reader. | 40–90 words |
| 2 | `## Typical User Questions` | Real parent/caregiver phrasings, verbatim style | One question per bullet, first person, as typed. No rewriting into formal English. | 12–30 bullets |
| 3 | `## Alternative User Phrasings` | Non-question forms, colloquialisms, Indian-English variants, regional/family vocabulary | Statements, fragments, and paraphrases. Complements section 2. | 8–25 bullets |
| 4 | `## Possible Explanations` | Developmentally plausible reasons the behaviour occurs | **Every bullet hedged** ("may", "can", "sometimes", "for some children"). Ordered common → less common. Never asserts a cause for *this* child. | 6–15 bullets |
| 5 | `## Things to Observe` | What a family can usefully notice and describe to a professional | Observable, non-technical, non-scoring. Never "if X then Y". | 6–12 bullets |
| 6 | `## Everyday Support Ideas` | Ordinary daily-life strategies any family can try safely | Zero-risk, no equipment, no protocol, no therapy substitution. Framed as "families often find…". | 6–14 bullets |
| 7 | `## ManaScience Perspective` | How ManaScience frames **this specific concern** | Applies the five commitments in **Playbook Part 3** to this concern; never restates them generically. If a bullet would read identically in another concern file, it belongs in the playbook, not here. No product pitch, no pricing, no urgency. | 4–8 bullets |
| 8 | `## Neuroplasticity Explanation` | Why change is possible, in plain language, specific to this concern's domain | Domain-specific, not boilerplate copy-paste — the *general* neuroplasticity frame is Playbook Part 3, commitment 1. No claims of cure, guaranteed outcome or timeline (Playbook Part 4, "Never"). | 4–8 bullets |
| 9 | `## Professional Boundary` | The explicit limit of what Manasi can say about this concern, and **which professional** is the right one | At least one bullet MUST use a **Playbook Part 4 "Always"** approved phrasing verbatim (V-47). The concern-specific contribution is naming the relevant professional (audiologist, speech-language pathologist, occupational therapist, educational psychologist) and what specifically cannot be determined without assessment. | 3–6 bullets |

**Required (conditional):**

| # | Section | Purpose | Content rules | Size |
|---|---|---|---|---|
| 10 | `## When Professional Evaluation May Help` | Non-alarming signals that make an evaluation worth considering | Framed as "worth discussing with a professional", never as "warning signs", never with a numeric cut-off. Any true urgency wording (regression, safety) is flagged `escalation_sensitive: true` in front matter (Section 8.6). | 4–10 bullets |

**Optional (author when they add real value):**

| Section | Purpose |
|---|---|
| `## Common Misunderstandings` | Widespread myths this concern attracts ("boys talk late", "TV causes it") — high-value retrieval surface for reassurance-seeking queries |
| `## What This Concern Is Not` | Explicit disambiguation from adjacent concerns; suppresses cross-concern retrieval confusion |
| `## Age-Specific Notes` | How the concern presents differently across `age_groups`; authored only when presentation genuinely differs by age |
| `## Family Perspective Notes` | How the concern is experienced/reported differently by parent vs grandparent vs teacher |
| `## Cultural and Multilingual Notes` | Bilingual-home effects, cultural expectations around milestones/eye contact/mealtimes |
| `## Questions a Professional May Ask` | Preparation material for an evaluation appointment |
| `## References` | Sources; the only section permitting links. Format: `- Title — Organization (year) — URL` |

**Rule S-15:** New section names require a schema version bump (Section 13.3). Authors may not invent sections.

### 7.5 Section → pipeline consumption

| Section | Primary consumer | Use |
|---|---|---|
| Summary | Knowledge Node, Response Generation | Retrieval anchor; opening grounding |
| Typical User Questions, Alternative User Phrasings | Vector index (matcher chunk) | Query-to-concern matching |
| Possible Explanations | Response Generation | The educational core of the answer |
| Things to Observe | Response Generation | Actionable, non-diagnostic next step |
| Everyday Support Ideas | Response Generation | Practical help |
| ManaScience Perspective, Neuroplasticity Explanation | Response Generation | Framing and hope, grounded in ManaScience positioning |
| Professional Boundary | Safety Node | Boundary language available as grounded content, not improvised |
| When Professional Evaluation May Help | Response Generation, Safety Node | Escalation guidance |
| References | Audit / review | Not surfaced to users in v1 |

**Rule S-16:** Response Generation never emits a section verbatim as a block, and never emits section headings. Sections are raw material for prose (this is what "not chatbot answers" means operationally).

### 7.6 Sections → the Playbook's Explain beats

`MANASI_ANSWER_PLAYBOOK.md` Part 2 defines the five-beat shape of the Explain body for concern questions. The section set above exists **because of** those beats — each beat has a designated source section, so the generator never has to invent material to complete the structure:

| Playbook Explain beat (Part 2) | Sourced from | Notes |
|---|---|---|
| 1. Normalise without dismissing | `## Summary`, `## Common Misunderstandings` | The summary supplies "this is common and has several possible reasons" as *fact*, not as reassurance copy |
| 2. Give the actual explanations (2–4, non-diagnostic) | `## Possible Explanations` | The generator selects 2–4 bullets; the file supplies 6–15 so selection can be age- and phrasing-appropriate |
| 3. Apply the ManaScience lens | `## ManaScience Perspective`, `## Neuroplasticity Explanation`, `development_domains`, `related_therapies` | Beat 3 is what makes the answer ManaScience's; `development_domains` names the areas, the therapy list stays inside Playbook Part 3's allowlist |
| 4. State the boundary (never optional) | `## Professional Boundary` | Approved phrasing already present in the source, so the generator copies rather than composes |
| 5. Point to the next step | `## Things to Observe`, `## When Professional Evaluation May Help`, `## Everyday Support Ideas` | Observation, professional input, or the Personalized Roadmap — the three next-step forms the playbook names |

The remaining playbook elements — Acknowledge, Support, Invite (Part 2), tone selection (Part 4), and the CTA object (Part 8) — draw **nothing** from concern files. They are behavioural, and they stay with the playbook, the Empathy Node and the CTA Node respectively. A concern file that contains material for them is defective (V-33, V-34).

**Rule S-17 (the completeness test):** A concern file is complete when all five beats can be sourced from it for a query in its `age_groups` × `family_perspectives` range, with zero invented facts. This is the operational meaning of GD-4, and it is what the authoring checklist in Section 17.5 checks.

---

## 8. Metadata Specification

The complete front-matter contract. **R** = required, **O** = optional. "Closed" means values must come from Appendix A.

### 8.1 Identity

| Key | Type | R/O | Rules |
|---|---|---|---|
| `schema_version` | string | R | Semver of the *schema*, e.g. `"1.0.0"`. Loader rejects unknown majors. |
| `content_type` | string (closed) | R | Always `concern_knowledge` in this corpus. |
| `concern_id` | string | R | Globally unique `snake_case` slug. MUST equal the filename stem (V-4). Immutable once `published` (Section 13.5). |
| `concern_uid` | string | R | Path-derived cross-corpus identity: `concerns/<category>/<concern_id>`. Mirrors the CTA corpus's `cta_id` path convention so a single ID space spans all corpora. |
| `title` | string | R | Human display title, Title Case, 2–6 words. MUST equal the H1 (V-5). |
| `status` | string (closed) | R | `draft` \| `in_review` \| `published` \| `deprecated`. Only `published` is ingested (Section 10.2). |

### 8.2 Classification

| Key | Type | R/O | Rules |
|---|---|---|---|
| `category` | string (closed) | R | MUST equal the parent directory name (V-6). |
| `topic` | string | R | Short canonical topic label matching Understanding Node `topic` vocabulary, e.g. `"speech delay"`. Lowercase. |
| `subtopics` | list[string] | O | 0–6 finer labels. Free text, lowercase. |
| `development_domains` | list (closed) | R | 1–4 domains from Appendix A.3. Ordered primary-first. |
| `tags` | list[string] | O | 0–10 free-text cross-cutting labels (`early_years`, `school_readiness`, `bilingual`). The escape valve that keeps folders flat (P-4). |

### 8.3 Query-affinity (retrieval hints)

| Key | Type | R/O | Rules |
|---|---|---|---|
| `primary_intents` | list (closed) | R | 1–3 Understanding-Node intents this concern serves. Almost always includes `personal_concern`. Appendix A.1. |
| `common_emotional_states` | list (closed) | R | 1–4 from the Phase 1 emotion enum. Declares which states this concern *typically* arrives with, so content review can sanity-check the material against **Playbook Part 4's tone table** (e.g. an `overwhelmed` concern needs support ideas that break into small steps). It is **not** a tone instruction and **not** a retrieval filter — the runtime tone always comes from the turn's actual `emotional_state`, and a calm parent must still reach the content. Appendix A.2. |
| `age_groups` | list (closed) | R | 1–N from Appendix A.4, or `[any]`. |
| `family_perspectives` | list (closed) | R | 1–N from Appendix A.5. Default `[parent]`. |
| `keywords` | list[string] | R | 8–25 single words / short noun phrases, lowercase, deduplicated. Includes clinical *and* lay terms. |
| `search_terms` | list[string] | R | 5–15 multi-word phrases that resemble Understanding-Node `search_query` output (e.g. `"toddler not talking at 2 years"`). These are what the matcher chunk is built from (Section 10.3). |
| `negative_terms` | list[string] | O | 0–10 phrases that must NOT pull this concern (e.g. `"adult speech therapy"` on a child concern). Used for retrieval QA and future re-ranking; never a hard runtime filter in v1. |

**Rule M-1:** `keywords` and `search_terms` are *retrieval surface*, not content. They may be tuned freely without clinical re-review, as long as they do not assert new claims.

### 8.4 Relationships

| Key | Type | R/O | Rules |
|---|---|---|---|
| `related_concerns` | list[object] | R (may be empty list) | Each: `{id, relation, weight}`. `id` is a `concern_id`. Relations in Appendix A.6. `weight` ∈ [0.0, 1.0]. Max 8. |
| `related_conditions` | list[string] | R (may be empty) | Condition slugs (`autism`, `adhd`, `hearing_impairment`). MUST resolve once `conditions/` exists; until then validated against `_schema/vocabularies.md`. Max 8. |
| `related_therapies` | list[string] | R (may be empty) | Therapy slugs. **Restricted to the approaches listed in Playbook Part 3** ("The therapies Manasi may reference") — MNRI®, Feldenkrais, Arrowsmith, Jill Stowell, Neurofeedback, Access Consciousness, Vision Therapy, Nemechek Protocol, Cellular Hydration, Ayurveda, Naturopathy, SSP, Tomatis, Integrated Listening — plus generic professional disciplines (`speech_therapy`, `occupational_therapy`). Enforced by V-48. Educational pointers only, never a recommendation (N-2, Playbook Part 4 "Never"). Max 8. |
| `cta_mapping` | list[object] | R (may be empty) | Each: `{cta_id, priority}`. `cta_id` MUST exist in the CTA corpus (e.g. `conditions/autism`, `therapies/mnri`). `priority` ∈ `primary` \| `secondary`. Max 1 `primary`. Advisory input to the CTA Node, never an override (Section 10.6). |

**Rule M-2:** Relationships are IDs, never titles or URLs. Display text is resolved from the target file at read time, so a renamed title never leaves stale copies across 500 files.

### 8.5 Safety and governance

| Key | Type | R/O | Rules |
|---|---|---|---|
| `professional_boundary_required` | bool | R | Always `true` in v1. Reserved for future non-clinical content in the same corpus. |
| `escalation_sensitive` | bool | R | `true` when the concern legitimately touches urgent territory (skill regression, self-injury, feeding/growth risk). Signals the Safety Node to apply stricter review; does not change retrieval. |
| `clinical_review_status` | string (closed) | R | `unreviewed` \| `reviewed` \| `revision_needed`. A file may not reach `status: published` unless this is `reviewed` (V-14). |
| `clinical_reviewer` | string | O | Reviewer name/handle. Required when `clinical_review_status: reviewed` (V-15). |
| `content_version` | string | R | Semver of *this file's content*. Bump rules in Section 13.4. |
| `last_updated` | date | R | ISO `YYYY-MM-DD`. MUST be ≥ the previous committed value (V-17). |
| `authors` | list[string] | R | ≥ 1 author. |
| `sources` | list[string] | O | Source identifiers backing the clinical claims; mirrors `## References`. |
| `supersedes` / `superseded_by` | string | O | `concern_id` links for merges/splits (Section 13.6). |

### 8.6 Complete front-matter shape

```yaml
---
schema_version: "1.0.0"
content_type: concern_knowledge
concern_id: speech_delay
concern_uid: concerns/communication/speech_delay
title: Speech Delay
status: published

category: communication
topic: speech delay
subtopics:
  - expressive language
  - late talking
development_domains:
  - speech_language
  - communication
tags:
  - early_years
  - bilingual

primary_intents:
  - personal_concern
  - emotional_support
common_emotional_states:
  - worried
  - confused
age_groups:
  - toddler_1_3y
  - preschool_3_5y
family_perspectives:
  - parent
  - grandparent
keywords: [...]
search_terms: [...]
negative_terms: [...]

related_concerns:
  - id: not_responding_to_name
    relation: co_occurring
    weight: 0.8
related_conditions: [autism, hearing_impairment]
related_therapies: [speech_therapy]
cta_mapping:
  - cta_id: conditions/autism
    priority: secondary

professional_boundary_required: true
escalation_sensitive: false
clinical_review_status: reviewed
clinical_reviewer: "Dr. A. Sharma"
content_version: "1.2.0"
last_updated: 2026-07-28
authors: ["ManaScience Content Team"]
sources: ["asha-late-talkers", "who-milestones"]
---
```

---

## 9. Naming Conventions

### 9.1 Files and directories

| Element | Convention | Example | Rationale |
|---|---|---|---|
| Concern file | `<concern_id>.md`, `snake_case`, `[a-z0-9_]+`, 2–5 words | `speech_delay.md`, `not_responding_to_name.md` | Filename **is** the ID — no lookup table to drift |
| Category directory | `snake_case`, singular-domain noun | `communication/`, `sensory/` | Matches `category` value exactly |
| Corpus directory | `snake_case`, plural | `concerns/`, `therapies/` | Reads as a collection |
| Infrastructure directory | `_` prefix | `_schema/`, `_templates/` | Excluded from load and ingest (Section 6.3) |

### 9.2 Naming a concern

Name after the **observable behaviour**, not the suspected condition or the emotion.

| ✅ Correct | ❌ Wrong | Why |
|---|---|---|
| `not_responding_to_name.md` | `autism_signs.md` | Concerns are behaviours; conditions live in `conditions/` |
| `daily_tantrums.md` | `behaviour_problems.md` | Too broad — a bucket, not a concern |
| `distressed_by_loud_sounds.md` | `sensory.md` | That is a category, not a concern |
| `speech_delay.md` | `speech_delay_and_autism.md` | Violates one-concern-per-file (G-1) |
| `avoids_eye_contact.md` | `my_child_avoids_eye_contact.md` | IDs are not sentences |
| `late_walking.md` | `walking_late_toddler_18_months.md` | Age belongs in `age_groups`, not the ID |

Additional rules:

* **N-1** No abbreviations except universally understood ones (`adhd`, `asd`) — and those belong to `conditions/`, not `concerns/`.
* **N-2** No leading articles, no verbs in first position unless the behaviour is inherently verbal (`avoids_`, `refuses_`, `not_`).
* **N-3** Prefer the parent's word over the clinician's when both are clear (`daily_tantrums`, not `emotional_dysregulation_episodes`).
* **N-4** Maximum 40 characters.

### 9.3 Identifier formats across the system

| Identifier | Format | Example | Owner |
|---|---|---|---|
| `concern_id` | `snake_case` slug | `speech_delay` | This spec |
| `concern_uid` | `concerns/<category>/<id>` | `concerns/communication/speech_delay` | This spec |
| `cta_id` | `<category_dir>/<file_stem>` | `conditions/autism` | CTA loader (existing) |
| `chunk_id` | deterministic hash of `concern_uid` + section key (Section 10.4) | — | Ingestion |
| `source_id` | repo-relative file path | `data/knowledge/concerns/communication/speech_delay.md` | Ingestion |

**Rule N-5:** `source_id` is the **path** here, whereas legacy chunks use a bare filename. Paths are required once file stems repeat across categories, and the value is only ever used for provenance display and re-ingestion targeting.

---

## 10. Retrieval Flow

### 10.1 End-to-end

```
User: "My son is 3 and still not talking, should I be worried?"
   │
   ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 1. UNDERSTANDING NODE (unchanged)                                    │
│    intent: personal_concern                                          │
│    topic: "speech delay"                                             │
│    search_query: "3 year old child not talking speech delay"         │
│    emotional_state: worried                                          │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 2. KNOWLEDGE NODE — STAGE A: vector search                           │
│    filter: content_type ∈ INTENT_CONTENT_TYPE_MAP[personal_concern]  │
│            = [concern_knowledge, therapy_info, neuroplasticity_…, faq]│
│    embed(search_query) → top-K (KNOWLEDGE_TOP_K = 8)                 │
│    drop chunks < RAG_SIMILARITY_THRESHOLD (0.35)                     │
│    (existing unfiltered retry preserved when < RAG_MIN_RELEVANT)     │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 3. KNOWLEDGE NODE — STAGE B: concern resolution (NEW)                │
│    group surviving concern_knowledge chunks by concern_id            │
│    score(concern) = max_sim + 0.05 × (distinct_matching_sections − 1)│
│    winner = argmax, if winner.max_sim ≥ CONCERN_RESOLUTION_THRESHOLD │
│    load ConcernRecord(winner) from the structured cache              │
│    attach up to CONCERN_MAX_RELATED (2) related-concern summaries    │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│ 4. RESPONSE GENERATION — assembles sections into prose               │
│ 5. EMPATHY NODE — Manasi's voice (content-preserving)                │
│ 6. SAFETY NODE — validates against professional_boundary             │
│ 7. CTA NODE — its own matching; cta_mapping is a tiebreak hint only  │
└──────────────────────────────────────────────────────────────────────┘
```

### 10.2 Ingestion eligibility

Only files with `status: published` **and** `clinical_review_status: reviewed` are embedded. `draft` / `in_review` / `deprecated` files live in the repo, are parsed by the loader (so authors can preview and validators can check them), and are never retrievable. This lets content land in `main` before it is clinically signed off, with zero risk of it reaching a parent.

### 10.3 Chunking strategy

Chunking is **structural, not character-based**. A concern file produces:

| Chunk kind | Built from | Why |
|---|---|---|
| **Matcher chunk** (exactly 1) | `title` + `topic` + all `## Typical User Questions` + all `## Alternative User Phrasings` + `search_terms` + `keywords` | Query-to-concern matching. Embedding parent phrasings directly is the single highest-leverage retrieval decision in this design: the user's sentence is compared against *sentences like theirs*, not against clinical prose. |
| **Summary chunk** (exactly 1) | `title` + `## Summary` | Short, high-precision semantic anchor; also the snippet used when surfacing related concerns. |
| **Section chunks** (1 per required/optional prose section) | `title` + section heading + section bullets | Lets a query about *support strategies* land on the support section while still resolving to the same concern. |

Additional rules:

* **C-1 — Retrieval header.** Every chunk's embedded text is prefixed with `"<title> — <section name>"`. Without it, a bullet list of strategies embeds almost identically across concerns.
* **C-2 — Never split a bullet.** If a section exceeds `CONCERN_MAX_CHUNK_CHARS` (default 1200), split on bullet boundaries into `section_part_1..n`, never mid-sentence. `RecursiveCharacterTextSplitter` is **not** used for this corpus.
* **C-3 — Never merge sections.** Cross-section chunks destroy the section attribution that Stage B and Response Generation rely on.
* **C-4 — No `---` separator splitting.** The FAQ block splitter in `scripts/build_knowledge_index.py` must not be applied here (S-13).
* **C-5 — Typical file yields 11–14 chunks.** At 500 concerns ≈ 6,000 chunks — comfortably within a single Chroma collection.

### 10.4 Chunk metadata

Extends the existing envelope (`chunk_id`, `content_type`, `source_id`, `source_title`, `source_url`, `chunk_index`, `ingested_at`) with concern-specific fields. **Chroma metadata values must be scalars** (`str` / `int` / `float` / `bool`) — lists are serialized as pipe-delimited strings with leading and trailing pipes, so substring containment stays a usable filter primitive:

| Key | Type | Example |
|---|---|---|
| `concern_id` | str | `speech_delay` |
| `concern_uid` | str | `concerns/communication/speech_delay` |
| `category` | str | `communication` |
| `topic` | str | `speech delay` |
| `section` | str | `matcher` \| `summary` \| `possible_explanations` \| … |
| `section_rank` | int | Declaration order; a stable tiebreak |
| `development_domains` | str (piped) | `\|speech_language\|communication\|` |
| `age_groups` | str (piped) | `\|toddler_1_3y\|preschool_3_5y\|` |
| `primary_intents` | str (piped) | `\|personal_concern\|emotional_support\|` |
| `family_perspectives` | str (piped) | `\|parent\|grandparent\|` |
| `escalation_sensitive` | bool | `false` |
| `content_version` | str | `1.2.0` |
| `last_updated` | str | `2026-07-28` |

`chunk_id` = stable hash of `concern_uid + ":" + section + ":" + part_index`. **This is deliberately not the existing `source_id:chunk_index` scheme**, which shifts every downstream ID when a section is inserted, orphaning stale vectors on upsert. Section-keyed IDs make re-ingestion genuinely idempotent: edit one section, and exactly one vector changes.

**Rule R-1 (deletion):** Re-ingesting a concern deletes all existing vectors matching its `concern_uid` before upserting, so removed sections cannot survive as ghosts.

### 10.5 Stage B — concern resolution

Operates on **every** retrieved chunk, not only those clearing `RAG_SIMILARITY_THRESHOLD`. This stage applies its own calibrated bars; a corpus authored for exactly this question should not be discarded by a threshold tuned for generic prose.

1. Partition chunks: `concern_knowledge` vs everything else.
2. Group concern chunks by `concern_id`.
3. Score: `max_similarity + 0.05 × (distinct_sections_matched − 1)`, capped at `+0.15`. Multi-section agreement is corroboration, but it must never let a broadly-mediocre concern beat a strongly-matched one.
4. A matcher-chunk hit adds `+0.03` (it is the phrasing surface authored precisely for this).
5. **Two bars, either of which qualifies the leader** — measurement against the live index showed two distinct signals (§10.7a):
   * **Score bar** — `score ≥ CONCERN_RESOLUTION_THRESHOLD` (0.45, above the global 0.35). Direct phrasings clear this comfortably at 0.7–0.9.
   * **Dominance bar** — `score ≥ CONCERN_DOMINANCE_MIN_SCORE` (0.22) **and** the leader owns `≥ CONCERN_DOMINANCE_MIN_CHUNKS` (3) chunks **and** `≥ CONCERN_DOMINANCE_RATIO` (0.6) of all retrieved concern chunks **and** leads the runner-up by `≥ CONCERN_DOMINANCE_MARGIN` (0.03).
6. **Intent gate.** The resolved record's `primary_intents` must contain the turn's intent. This is enforced from the file's own metadata rather than a hardcoded intent list, so a concern that should serve concept questions declares it.
7. On success, hand Response Generation the **structured record** (all sections, typed), plus non-concern chunks as supporting context, plus ≤ 2 related-concern summaries.
8. **Source promotion.** If stage A produced `source: "llm"` but stage B resolved, the turn is promoted to `source: "rag"` grounded in that concern's own chunks — ManaScience content written for the question outranks a generic LLM answer (Phase 2 spec's priority rule).
9. On failure, degrade exactly as before: chunk-based `source: "rag"` if other chunks qualify, else `source: "llm"`. **No new failure mode is introduced.**

**Why two bars.** The two failure modes are shaped oppositely, so a single absolute threshold cannot separate them:

| Query shape | Score | Leader's chunk share | Correct outcome |
|---|---|---|---|
| *"every evening ends in screaming over nothing at all"* (colloquial paraphrase) | 0.24–0.39 — **low** | 0.83–1.00 — **dominant** | resolve |
| *"what is neuroplasticity?"* (cross-topic concept question) | ~0.56 — **high** | 0.17 — **spread across six concerns** | decline |

Concentration, not magnitude, is what distinguishes them. A concept question pulls one `Neuroplasticity Explanation` chunk from *every* concern — correctly, since those sections really are about neuroplasticity — while a parent's phrasing pulls most of one concern's file.

### 10.6 Downstream contracts

Behaviour at each of these nodes is governed by `MANASI_ANSWER_PLAYBOOK.md`; what follows states only what *changes for them* when a concern record is available.

* **Response Generation** receives sections as named slots and composes prose under the playbook's Part 2 structure, using the beat mapping in Section 7.6. It MUST NOT emit section headings, MUST NOT dump a section verbatim, and MUST preserve hedging language from `Possible Explanations` — the playbook's "keep qualifiers exactly as written" rule (Part 4, "Always") applied to sourced content. A hedge stripped here becomes a diagnosis downstream: the highest-severity content failure in the system.
* **Empathy Node** is content-preserving; it adds warmth without dropping factual content (Playbook Part 1: "Phase 4 may not add facts", and the regression fixed in `094a0b0`). Concern content raises fact density, so the existing `EMPATHY_FACT_RETENTION_MIN_RATIO` guard matters more, not less.
* **Safety Node** now validates against boundary language that is already present and already approved, rather than against improvised phrasing — the concern file carries a Playbook Part 4 sentence verbatim (V-47), so Safety's job shifts from repair to confirmation.
* **CTA Node** keeps full authority; the playbook (Part 1, Part 8) is explicit that CTA selection is literal phrase matching over `data/cta/**`, not AI. `cta_mapping` enters only as a tiebreak hint between otherwise equal candidates and never overrides a CTA's own exclusion rules, because the CTA corpus encodes exclusions (e.g. "do not show the Autism CTA when confidence is low") that a concern author cannot see.
* **On the playbook's documented CTA gaps (Part 8).** Gaps 1–3 — word-form mismatches like "anxious" vs "Anxiety", the dyslexia question landing on Neuroplasticity, sleep questions landing on Anxiety — are **CTA corpus defects and must be fixed there**, by adding the missing trigger phrasings. A concern file's `cta_mapping` MUST NOT be used as a workaround: routing a CTA from concern metadata would bypass that CTA's exclusion rules and split routing logic across two corpora. The legitimate contribution this library makes is that its `## Typical User Questions` sections are a well-sourced inventory of real phrasings that CTA authors can mine when closing those gaps.

### 10.7a Measured results (seed corpus, 6 concerns, 76 chunks)

Run against the live index on 2026-07-28, `text-embedding-3-small`:

| Query set | Result |
|---|---|
| The six concerns as phrased in the original brief | 6/6, scores 0.72–0.90 |
| Colloquial paraphrases appearing nowhere in the corpus | 6/6 |
| Playbook Part 7 question wording (Q1, Q6, Q15, Q21, Q26, Q3) | 6/6 |
| **Top-1 concern accuracy** | **18/18 = 100 %** (target: ≥ 90 %) |
| Negative controls (therapy / website / concept questions) | 3/3 correctly declined |

The initial run scored 78 % with a single 0.45 threshold: four colloquial paraphrases were ranked correctly but fell below the bar, and *"what is neuroplasticity?"* resolved to `hyperactivity`. Both were fixed by the two-bar rule plus the intent gate in §10.5 — not by lowering the threshold, which would have made the false positive worse.

### 10.7 Retrieval quality gate

Each concern ships with an evaluation set of ≥ 12 phrasings (in practice, drawn from `## Typical User Questions` plus paraphrases held out of the file). CI-adjacent retrieval tests assert:

| Metric | Target |
|---|---|
| Top-1 concern accuracy | ≥ 90 % |
| Top-3 concern accuracy | ≥ 97 % |
| Wrong-concern-above-threshold rate | ≤ 2 % |
| `negative_terms` false-positive rate | ≤ 5 % |

A regression here is a content bug (thin/overlapping phrasings), not an infrastructure bug, and is fixed by editing the concern file.

### 10.8 Cost and performance

| Item | Estimate |
|---|---|
| Chunks per concern | 11–14 |
| Chunks at 500 concerns | ~6,000 |
| Full-corpus embedding cost (`text-embedding-3-small`) | ≈ $0.05–0.10 per full rebuild |
| Incremental ingest (one concern) | < 2 s |
| Added retrieval latency (Stage B) | < 5 ms (in-memory grouping) |
| Loader cold start, 500 files | < 1.5 s (mirrors CTA loader's eager-load pattern) |

### 10.9 Changes required in existing code (additive only)

| File | Change |
|---|---|
| `app/nodes/knowledge_node.py` | Add `concern_knowledge` (+ reserved siblings) to `CONTENT_TYPES`; add Stage B resolution |
| `app/rag/retriever.py` | Add `concern_knowledge` **first** in `INTENT_CONTENT_TYPE_MAP` for `personal_concern` and `emotional_support`; add it to `concept_explanation` |
| `app/config.py` | `KNOWLEDGE_DATA_DIR`, `CONCERN_RESOLUTION_ENABLED`, `CONCERN_RESOLUTION_THRESHOLD`, `CONCERN_DOMINANCE_MIN_SCORE`, `CONCERN_DOMINANCE_MIN_CHUNKS`, `CONCERN_DOMINANCE_RATIO`, `CONCERN_DOMINANCE_MARGIN`, `CONCERN_MAX_RELATED`, `CONCERN_MAX_CHUNK_CHARS` |
| `scripts/build_knowledge_index.py` | Add a concern loader path; keep legacy loaders untouched |
| `app/graph/state.py` | Optional `resolved_concern` on the knowledge payload |

No node's public contract changes. Every addition degrades to today's behaviour when the corpus is empty.

---

## 11. File Relationships and Cross-Linking

### 11.1 The four relationship axes

```
                    ┌────────────────────┐
      related_      │                    │  related_conditions
      concerns ────►│   CONCERN FILE     │──────────────────────►  conditions/
      (peer graph)  │   speech_delay     │
                    │                    │  related_therapies
                    │                    │──────────────────────►  therapies/
                    └─────────┬──────────┘
                              │ cta_mapping
                              ▼
                        data/cta/**  (existing corpus)
```

### 11.2 Relation semantics

`related_concerns` entries are typed, because "related" alone cannot tell a reader why (Appendix A.6):

| Relation | Meaning | Example |
|---|---|---|
| `co_occurring` | Often observed together; neither causes the other | `speech_delay` ↔ `not_responding_to_name` |
| `differential` | Easily confused; a reader may be in the wrong file | `speech_delay` ↔ `unclear_speech` |
| `broader` | The other is a more general concern | `not_meeting_milestones` |
| `narrower` | The other is a more specific case | `echolalia` under `speech_delay` |
| `precursor` | Typically appears developmentally earlier | `not_babbling` → `speech_delay` |
| `consequence` | May follow when unaddressed | `speech_delay` → `peer_interaction_difficulty` |

### 11.3 Symmetry rules

* **L-1** `co_occurring` and `differential` are **symmetric** — the validator warns (does not fail) on a missing reciprocal edge, and a maintenance report lists all one-sided pairs.
* **L-2** `broader`/`narrower` and `precursor`/`consequence` are **inverse pairs**; the validator warns when an inverse edge is absent.
* **L-3** Cycles are permitted for symmetric relations and **rejected** for hierarchical ones (`broader`/`narrower` must form a DAG, V-24).
* **L-4** Max 8 `related_concerns` per file. More than 8 means the concern is too broad and should be split — this cap is a design smoke alarm, not a storage limit.

### 11.4 Prose cross-linking

Prose may reference another concern using a relative Markdown link: `[not responding to name](../communication/not_responding_to_name.md)`.

* **L-5** Front matter is **authoritative** for the machine-readable graph. Prose links are for human navigation on GitHub.
* **L-6** Every prose link target must exist (V-25) and its `concern_id` must also appear in `related_concerns` (V-26) — this prevents an invisible second, contradictory graph.
* **L-7** Link text is lowercase prose, never the raw slug.
* **L-8** Links are stripped before embedding; only their anchor text is indexed (URLs are pure noise in vector space).

### 11.5 Why the graph improves retrieval

1. **Recall.** When a query resolves to `avoids_eye_contact` but the parent's real concern spans social communication, related summaries give Response Generation the adjacent framing without a second retrieval round-trip.
2. **Disambiguation.** `differential` edges tell Response Generation what to explicitly *not* conflate, which is how the answer stays educational rather than drifting toward a label.
3. **Coverage auditing.** An orphan concern (no inbound edges, few keywords) is a retrieval blind spot; the graph makes it visible before a parent finds it.
4. **Future navigation.** The same graph powers "related topics" UI without any new content work.

---

## 12. Validation Rules

Validation is a **CI gate**: no concern file merges to `main` unless every ERROR-severity rule passes. Severity: **ERROR** blocks merge; **WARN** reports and requires acknowledgement.

Rule IDs are **stable identifiers, not an ordering** — they are never renumbered, so a rule added to an earlier group later in the document's life (V-47…V-50 in §12.4) keeps its ID. Validator output and PR review comments reference these IDs directly.

### 12.1 Structural

| ID | Rule | Severity |
|---|---|---|
| V-1 | File parses as UTF-8 Markdown with a valid, closed YAML front-matter block | ERROR |
| V-2 | All required keys (Section 8) present | ERROR |
| V-3 | No unknown front-matter keys | ERROR |
| V-4 | `concern_id` == filename stem | ERROR |
| V-5 | `title` == H1 text | ERROR |
| V-6 | `category` == parent directory name | ERROR |
| V-7 | `concern_uid` == `concerns/<category>/<concern_id>` | ERROR |
| V-8 | `concern_id` globally unique across the corpus | ERROR |
| V-9 | Exactly one H1; no `###`+ headings | ERROR |
| V-10 | All required `##` sections present, correctly spelled, in declared order | ERROR |
| V-11 | No section body empty (sentinel text counts as filled) | ERROR |
| V-12 | No `---` in the body; no tables/images/HTML/code fences outside `## References` | ERROR |
| V-13 | File ≤ 1,500 lines and ≤ 60 KB | WARN |

### 12.2 Vocabulary and typing

| ID | Rule | Severity |
|---|---|---|
| V-14 | `status: published` requires `clinical_review_status: reviewed` | ERROR |
| V-15 | `clinical_review_status: reviewed` requires `clinical_reviewer` | ERROR |
| V-16 | Every closed-vocabulary value exists in Appendix A | ERROR |
| V-17 | `last_updated` is a valid ISO date, not in the future, ≥ previous committed value | ERROR |
| V-18 | `content_version` and `schema_version` are valid semver | ERROR |
| V-19 | `schema_version` major is supported by the current loader | ERROR |
| V-20 | List cardinalities within Section 8 bounds | ERROR |
| V-21 | `keywords` / `search_terms` deduplicated, lowercase, no punctuation beyond hyphens | WARN |

### 12.3 Relationships

| ID | Rule | Severity |
|---|---|---|
| V-22 | Every `related_concerns.id` resolves to an existing concern file | ERROR |
| V-23 | Every `related_conditions` / `related_therapies` slug exists in `_schema/vocabularies.md` (and, once those corpora exist, as a file) | ERROR |
| V-24 | `broader`/`narrower` edges form a DAG | ERROR |
| V-25 | Every prose Markdown link resolves to an existing file | ERROR |
| V-26 | Every prose-linked concern also appears in `related_concerns` | WARN |
| V-27 | Every `cta_mapping.cta_id` exists in the CTA corpus; ≤ 1 `primary` | ERROR |
| V-28 | Symmetric/inverse relations are reciprocated | WARN |
| V-29 | No self-reference in any `related_*` field | ERROR |

### 12.4 Content-safety and style (the rules that keep this a knowledge base)

These rules are **not a new safety policy**. V-30…V-37 are the mechanical, file-level enforcement of `MANASI_ANSWER_PLAYBOOK.md` Part 4 ("Never" / "Always") and Part 6 (behaviour-not-condition), applied at authoring time so that violations are caught in a diff rather than at runtime by the Safety Node. The playbook remains the definition; this table is the linter. When Part 4 changes, this table follows (GD-5).

| ID | Rule | Severity |
|---|---|---|
| V-30 | **No diagnostic assertion.** Reject patterns asserting a child *has* a condition: `"your child has"`, `"this means your child is"`, `"is autistic"`, `"indicates ADHD"`, `"diagnosed with"` outside `## References` | ERROR |
| V-31 | **Hedging required.** Every bullet in `## Possible Explanations` contains a hedge (`may`, `can`, `might`, `sometimes`, `often`, `for some children`, `in some cases`) | ERROR |
| V-32 | **No treatment prescription.** Reject `"you should start"`, `"we recommend therapy"`, `"the right treatment is"`, dosages, session counts, durations | ERROR |
| V-33 | **No chatbot voice.** Reject second-person direct address to a parent (`"I understand how hard"`, `"Don't worry"`, `"Let me explain"`, `"Great question"`) and any first-person singular | ERROR |
| V-34 | **No CTA/marketing copy.** Reject URLs outside `## References`, `"click here"`, `"sign up"`, `"book a"`, pricing | ERROR |
| V-35 | **No guaranteed outcomes.** Reject `"will cure"`, `"guarantees"`, `"completely resolves"`, `"fixes"` in the neuroplasticity/perspective sections | ERROR |
| V-36 | **No urgency/alarm language.** Reject `"immediately"`, `"urgent"`, `"serious warning sign"`, `"before it's too late"` outside files with `escalation_sensitive: true`, which get manual review instead | ERROR |
| V-37 | **No numeric screening thresholds.** Reject `"if fewer than N words by age M"`-style cut-offs — that is screening, not education | ERROR |
| V-38 | **One concern only.** WARN when a condition name appears > 5 times, or two unrelated `development_domains` dominate the prose, or `## Possible Explanations` reads as two distinct concerns | WARN |
| V-39 | Bullet length 8–45 words | WARN |
| V-40 | `## Summary` is 40–90 words of prose with no bullets | ERROR |
| V-41 | Reading level ≈ grade 8 or below (parent-facing plain language) | WARN |
| V-42 | Required-section bullet counts within Section 7.4 ranges | WARN |
| V-47 | **Approved boundary phrasing.** `## Professional Boundary` contains ≥ 1 bullet using a Playbook Part 4 "Always" phrasing verbatim (*"Only a qualified healthcare professional can determine that."* / *"An evaluation by an appropriate professional may help provide more clarity."* / *"Manasi can provide educational information, but cannot diagnose medical conditions."*), allowing only grammatical adaptation of the leading clause | ERROR |
| V-48 | **Therapy allowlist.** Every `related_therapies` entry and every named approach in prose appears in Playbook Part 3's therapy table or the generic-discipline list (Section 8.4). Naming an approach ManaScience does not cover violates Playbook Part 4's "Never name a ManaScience program… that isn't in the source material" | ERROR |
| V-49 | **No generic ManaScience boilerplate.** `## ManaScience Perspective` bullets are not byte-identical to those in another concern file — generic framing belongs in Playbook Part 3, this section is the concern-specific application (Section 7.4, row 7) | WARN |
| V-50 | **Playbook beat coverage.** All five Explain beats (Section 7.6) are sourceable from the file — mechanically, the beat-source sections are present and non-sentinel | ERROR |

### 12.5 Corpus-level

| ID | Rule | Severity |
|---|---|---|
| V-43 | No two published concerns have > 60 % `keywords` overlap (near-duplicate detector) | WARN |
| V-44 | Every published concern is reachable from ≥ 1 other concern (no orphans) | WARN |
| V-45 | Category directories contain only `.md` files (plus `_`-prefixed infra) | ERROR |
| V-46 | Retrieval evaluation targets (Section 10.7) hold on the published corpus | WARN → ERROR once the corpus exceeds 50 concerns |

### 12.6 When validation runs

| Stage | Scope |
|---|---|
| Pre-commit hook | Changed files only: V-1…V-21, V-29…V-42, V-47…V-50 |
| Pull-request CI | Full corpus: all rules, including relationship + corpus-level |
| Pre-ingestion | Blocking: a file failing any ERROR is never embedded |
| Nightly | V-43…V-46 plus a drift report (orphans, one-sided edges, stale `last_updated` > 365 days) |

---

## 13. Versioning Strategy

### 13.1 Four independent version axes

| Axis | Field / mechanism | Answers |
|---|---|---|
| **Schema** | `schema_version` + `_schema/CHANGELOG.md` | What shape are files in? |
| **Content** | `content_version` + `last_updated` | What did this file say, when? |
| **History** | Git | Who changed what, why, and how do we revert? |
| **Lifecycle** | `status` + `clinical_review_status` | Is it safe to serve? |

### 13.2 Git is the version-control system

No `_v2.md` files, no `archive/` directories, no in-file changelogs. The commit history is the audit trail. Content commits use `content(concerns): <concern_id> — <what changed>`; schema commits use `schema(concerns): …`.

### 13.3 Schema versioning

Semver on the schema itself:

* **MAJOR** — a change that breaks existing files (removing/renaming a required field or section, changing a field's type). Requires a migration pass over the entire corpus **in one commit**, plus a loader that rejects unsupported majors.
* **MINOR** — additive and backward-compatible (new optional field, new optional section, new vocabulary value).
* **PATCH** — clarified documentation, tightened validator messages, no file changes required.

`_schema/CHANGELOG.md` records every bump with date, rationale and migration notes. **Rule VS-1:** a MAJOR bump must ship with a mechanical migration path; "hand-edit 500 files" is not one.

### 13.4 Content versioning

Per-file semver:

| Bump | When | Requires re-review? |
|---|---|---|
| **MAJOR** | Clinical meaning changes — explanations altered, boundary rewritten, scope changed | Yes — reset `clinical_review_status: revision_needed` |
| **MINOR** | New bullets, new phrasings/keywords, new relationships, new optional section | No, unless clinical claims are added |
| **PATCH** | Typos, formatting, link fixes, non-semantic rewording | No |

`last_updated` moves on **every** content change, including PATCH.

### 13.5 ID immutability

`concern_id` is immutable once `status: published`. It appears in `chunk_id` hashes, relationship edges across other files, and (post-migration) database rows. Renaming requires the deprecation flow:

1. New file created with the new ID, `supersedes: <old_id>`.
2. Old file → `status: deprecated`, `superseded_by: <new_id>`.
3. Inbound edges across the corpus are repointed in the same PR (V-22 enforces this).
4. Ingestion deletes the deprecated concern's vectors by `concern_uid` (R-1).
5. The deprecated file is deleted no earlier than one release cycle later.

### 13.6 Splits and merges

* **Split** (a file grew into two concerns): create both new files, mark the original `deprecated` with `superseded_by` pointing at the primary successor, and record the second in `## Common Misunderstandings` or a `related_concerns` `narrower` edge. Redistribute phrasings deliberately — overlapping `search_terms` across the two new files is the classic post-split retrieval regression.
* **Merge**: the surviving file absorbs both phrasing sets; the absorbed file becomes `deprecated` with `superseded_by`. Bump the survivor's content MAJOR.

### 13.7 Index versioning

Chroma metadata carries `content_version` and `last_updated` per chunk, so a stale index is detectable by comparing corpus versions against indexed versions. Full rebuilds are cheap (Section 10.8); incremental re-ingestion by `concern_uid` is the default.

---

## 14. Migration Strategy

### 14.1 Principle

The information architecture is defined by **fields, IDs and relationships** (Sections 8, 9, 11), not by Markdown. Every migration target is a projection of the same model. Migration therefore never touches content — it re-serializes it.

```
Markdown (source of truth)
        │
        │  parse (loader — one implementation, shared by every target)
        ▼
  ConcernRecord  ← the canonical in-memory model
        │
        ├──► JSON files            (1 object per concern)
        ├──► MongoDB               (1 document per concern)
        ├──► PostgreSQL            (normalized: 1 row + child tables)
        ├──► ChromaDB              (chunks + flattened scalar metadata)
        └──► Pinecone              (vectors + native list metadata)
```

**Rule MG-1:** Every target derives from `ConcernRecord`, never from a previous target. No JSON→Mongo→PG chains, which is how field semantics drift silently.

**Rule MG-2:** Markdown remains the source of truth until a full authoring surface (CMS with equivalent review, validation and diffing) exists. A database is a read model first; promoting it to the write model is a separate, explicit decision.

### 14.2 Target: JSON

A direct 1:1 dump — front-matter keys become object keys; each `##` section becomes an array of bullet strings under its snake_case key, plus a `_raw` string for fidelity.

```
{
  "concern_id": "speech_delay",
  "…front matter as-is…",
  "sections": {
    "summary": {"text": "…", "raw": "…"},
    "possible_explanations": {"bullets": ["…", "…"], "raw": "…"}
  }
}
```
Effort: trivial. Risk: none. Use: API payloads, static site builds, snapshot tests.

### 14.3 Target: MongoDB

One document per concern; `concern_id` as `_id`. Front matter maps to top-level fields; sections nest under `sections`; `related_concerns` stays an array of subdocuments. Indexes: `_id`, `category`, `status`, multikey on `development_domains` / `age_groups` / `keywords` / `primary_intents`, text index on `search_terms` + `keywords`, and `related_concerns.id`.
Effort: low. Risk: low. Note: Mongo's flexibility invites schema drift — the validator remains the gate even after migration.

### 14.4 Target: PostgreSQL

Normalized, since the front matter is already relational in shape:

| Table | Contents |
|---|---|
| `concerns` | one row per concern: identity, classification scalars, governance, timestamps |
| `concern_sections` | `(concern_id, section_key, section_rank, body)` |
| `concern_bullets` | `(concern_id, section_key, ordinal, text)` — only if bullet-level querying is needed |
| `concern_keywords` | `(concern_id, keyword, kind)` where `kind` ∈ `keyword` \| `search_term` \| `negative_term` |
| `concern_questions` | `(concern_id, question, kind)` where `kind` ∈ `typical` \| `alternative` |
| `concern_domains`, `concern_age_groups`, `concern_intents`, `concern_perspectives`, `concern_tags` | join tables against enum/lookup tables |
| `concern_relations` | `(source_id, target_id, relation, weight)` — the peer graph |
| `concern_external_relations` | `(concern_id, target_kind, target_slug)` for conditions/therapies |
| `concern_cta_mappings` | `(concern_id, cta_id, priority)` |

Closed vocabularies become PG enums or lookup tables (lookup tables preferred: adding a value stops being a DDL migration). `pg_trgm` on questions/keywords gives useful lexical search alongside vector search.
Effort: medium. Risk: low — the schema is a mechanical read of Section 8, which is why Section 8 is closed-vocabulary in the first place.

### 14.5 Target: ChromaDB (already the runtime target)

Chunks per Section 10.3; metadata per Section 10.4, with lists pipe-serialized because Chroma metadata values must be scalars. Filters use `$in` on scalars and substring matching on piped strings. This is not a future migration — it is how the MVP already runs; the Markdown corpus is simply its build input.

### 14.6 Target: Pinecone

Same chunks, same IDs. Pinecone supports native list-of-string metadata, so piped strings **unpack back into arrays** at write time — the reason those fields are specified as lists in the model and flattened only at the Chroma boundary. Namespaces map to `content_type` (or to `category` for large corpora). `chunk_id` carries across unchanged, so a Chroma→Pinecone move is a re-embed, not a re-model.
Effort: low. Risk: hosted-service cost/latency, not data-model risk.

### 14.7 Migration sequencing

| Phase | Trigger | Action |
|---|---|---|
| 0 (now) | MVP | Markdown + Chroma. No other store. |
| 1 | > 150 concerns, or non-engineers authoring | Add generated JSON as a build artifact (still not committed) for tooling/preview |
| 2 | Editorial workflow needs state (assignments, review queues) | Mongo or PG as a **read model**, synced from Markdown on merge |
| 3 | A real CMS with equivalent review guarantees exists | Promote the database to source of truth; Markdown becomes an export |
| 4 | Scale/latency/multi-tenancy demands it | Swap Chroma → Pinecone; corpus untouched |

**Rule MG-3:** Each phase is independently reversible. No phase requires re-authoring content.

---

## 15. Example Folder Tree

```
data/knowledge/
├── _schema/
│   ├── concern.schema.md
│   ├── vocabularies.md
│   └── CHANGELOG.md
├── _templates/
│   └── concern.template.md
├── concerns/
│   ├── communication/
│   │   ├── speech_delay.md
│   │   ├── not_responding_to_name.md
│   │   ├── unclear_speech.md
│   │   ├── echolalia.md
│   │   ├── not_babbling.md
│   │   ├── limited_vocabulary.md
│   │   └── not_following_instructions.md
│   ├── social/
│   │   ├── avoids_eye_contact.md
│   │   ├── not_playing_with_peers.md
│   │   ├── prefers_being_alone.md
│   │   ├── no_pretend_play.md
│   │   └── not_pointing_or_showing.md
│   ├── behaviour/
│   │   ├── daily_tantrums.md
│   │   ├── meltdowns.md
│   │   ├── hitting_others.md
│   │   ├── repetitive_behaviours.md
│   │   └── difficulty_with_transitions.md
│   ├── sensory/
│   │   ├── distressed_by_loud_sounds.md
│   │   ├── avoids_certain_textures.md
│   │   ├── constant_movement_seeking.md
│   │   └── dislikes_being_touched.md
│   ├── attention/
│   │   ├── hyperactivity.md
│   │   ├── cannot_sit_still.md
│   │   ├── poor_attention_span.md
│   │   └── easily_distracted.md
│   ├── motor/
│   │   ├── late_walking.md
│   │   ├── clumsiness.md
│   │   ├── poor_pencil_grip.md
│   │   └── difficulty_with_stairs.md
│   ├── learning/
│   │   ├── difficulty_learning_letters.md
│   │   ├── struggles_with_reading.md
│   │   └── difficulty_with_numbers.md
│   ├── emotional/
│   │   ├── separation_distress.md
│   │   ├── frequent_crying.md
│   │   └── intense_fears.md
│   ├── sleep/
│   │   ├── difficulty_falling_asleep.md
│   │   └── frequent_night_waking.md
│   ├── feeding/
│   │   ├── extremely_restricted_diet.md
│   │   └── refuses_new_foods.md
│   ├── daily_living/
│   │   ├── toilet_training_difficulty.md
│   │   └── dressing_difficulty.md
│   └── milestones/
│       ├── not_meeting_milestones.md
│       └── regression_of_skills.md
├── conditions/            # reserved — autism.md, adhd.md, …
├── therapies/             # reserved — speech_therapy.md, mnri.md, …
├── assessments/           # reserved
├── research/              # reserved
└── faqs/                  # reserved
```

At 500 concerns this tree averages ~40 files per category directory — still browsable, still greppable, still reviewable in a PR.

---

## 16. Complete Example Markdown File

**Path:** `data/knowledge/concerns/communication/speech_delay.md`

```markdown
---
schema_version: "1.0.0"
content_type: concern_knowledge
concern_id: speech_delay
concern_uid: concerns/communication/speech_delay
title: Speech Delay
status: published

category: communication
topic: speech delay
subtopics:
  - expressive language
  - late talking
  - first words
development_domains:
  - speech_language
  - communication
tags:
  - early_years
  - bilingual
  - milestones

primary_intents:
  - personal_concern
  - emotional_support
common_emotional_states:
  - worried
  - confused
  - overwhelmed
age_groups:
  - toddler_1_3y
  - preschool_3_5y
family_perspectives:
  - parent
  - grandparent
  - caregiver

keywords:
  - speech delay
  - late talker
  - not talking
  - no words
  - few words
  - expressive language
  - language delay
  - first words
  - babbling
  - vocabulary
  - communication delay
  - speech milestones
  - talking late
  - not speaking
  - word count

search_terms:
  - my child is not speaking
  - toddler not talking at 2 years
  - three year old only says a few words
  - child not saying any words yet
  - my son is a late talker
  - when should a child start talking
  - child speech is delayed compared to other children
  - bilingual child not talking yet
  - my daughter stopped saying words she used to say

negative_terms:
  - adult speech therapy
  - stuttering treatment for adults
  - accent reduction

related_concerns:
  - id: not_responding_to_name
    relation: co_occurring
    weight: 0.8
  - id: unclear_speech
    relation: differential
    weight: 0.7
  - id: not_babbling
    relation: precursor
    weight: 0.6
  - id: not_following_instructions
    relation: co_occurring
    weight: 0.5
  - id: not_meeting_milestones
    relation: broader
    weight: 0.5
related_conditions:
  - autism
  - hearing_impairment
  - developmental_language_disorder
  - global_developmental_delay
related_therapies:
  - speech_therapy
  - occupational_therapy
  - mnri
cta_mapping:
  - cta_id: conditions/autism
    priority: secondary
  - cta_id: therapies/general
    priority: primary

professional_boundary_required: true
escalation_sensitive: false
clinical_review_status: reviewed
clinical_reviewer: "ManaScience Clinical Review Panel"
content_version: "1.2.0"
last_updated: 2026-07-28
authors:
  - "ManaScience Content Team"
sources:
  - asha-late-talkers
  - who-early-child-development
  - cdc-milestone-guidance
---

# Speech Delay

## Summary

Speech delay describes a pattern where a child develops spoken words and sentences
later than most children of a similar age. It refers to what a family observes about
talking, not to any diagnosis. Children reach speech milestones across a wide range
of timelines, and the same delay can arise from very different underlying reasons,
which is why an individual assessment matters more than a comparison with other
children.

## Typical User Questions

- My child is not speaking.
- My son is 3 and still not talking.
- Why is my child not talking yet?
- My daughter only says a few words.
- Is my child a late talker?
- When should my child start speaking?
- My child doesn't say any words.
- Why is my child's speech delayed?
- My 2 year old is not talking, should I be worried?
- My child understands everything but doesn't speak.
- My child stopped saying words he used to say.
- Everyone says he will talk when he is ready, is that true?
- My child only points and doesn't use words.
- How many words should a 2 year old say?
- My child speaks less than his cousins of the same age.
- We speak two languages at home, is that why he isn't talking?
- My child talks at home but not at school.
- Is speech delay a sign of autism?

## Alternative User Phrasings

- Late talker.
- Not talking yet.
- Baby not saying words.
- Delayed speech.
- Speech is behind.
- He is very quiet.
- She babbles but no real words.
- Only makes sounds, no words.
- Communicates by pulling my hand.
- Uses gestures instead of words.
- Doctor said wait and watch for speech.
- Speech not clear and very few words.

## Possible Explanations

- Children can develop expressive language on very different timelines, and some
  simply begin talking later while all other development proceeds typically.
- Reduced hearing, including temporary hearing loss from repeated ear infections,
  may make it harder for a child to pick up the sounds of speech.
- Some children may understand far more than they can say, which can indicate that
  expressive language is developing more slowly than comprehension.
- Limited everyday opportunities for back-and-forth interaction can sometimes slow
  how quickly spoken language builds.
- Children growing up with more than one language may distribute their early words
  across languages, which can look like fewer words in any single language.
- Difficulty coordinating the muscles used for speech may make forming words harder
  for some children, even when they have plenty to communicate.
- Speech may develop alongside differences in social communication for some
  children, in which case gestures, eye contact and shared attention are often part
  of the wider picture.
- Extended screen time that replaces interactive conversation may reduce the
  responsive exchanges through which early language typically grows.
- A child who has recently experienced a major change or stressor may temporarily
  communicate less than before.

## Things to Observe

- How the child communicates without words, such as pointing, gestures, leading an
  adult by the hand, or facial expression.
- Whether the child responds consistently to their name and to everyday sounds.
- How much the child appears to understand, such as following simple familiar
  instructions without gestural cues.
- Whether the number of words is slowly growing, staying the same, or reducing.
- Whether the child imitates sounds, actions or words during play.
- How the child communicates with different people and in different settings.
- Whether the child uses sounds and words to start an interaction, not only to
  request something.
- Whether any previously used words have been lost.

## Everyday Support Ideas

- Families often find it helps to narrate everyday routines aloud, describing what
  is happening while dressing, cooking or bathing.
- Pausing after speaking gives a child unhurried space to respond in whatever way
  they can.
- Responding to gestures and sounds as genuine communication tends to encourage
  more attempts, not fewer.
- Repeating a child's attempt back in a slightly fuller form offers a natural model
  without correcting them.
- Face-to-face play at the child's eye level makes mouth movements and expressions
  easier to notice.
- Shared picture books invite naming and pointing without requiring the child to
  perform.
- Reducing background noise from television or music can make speech easier to
  pick out.
- Offering choices between two named objects creates a natural reason to use words.

## ManaScience Perspective

- ManaScience approaches speech delay as a description of where a child is now,
  not as a fixed statement about their potential.
- Understanding what may be making speaking harder tends to be more useful to a
  family than attaching a label early.
- Communication development is viewed as connected to hearing, attention, motor
  coordination and social engagement rather than isolated from them.
- Families are treated as central to a child's everyday communication environment,
  because most language learning happens in ordinary daily interaction.

## Neuroplasticity Explanation

- The brain builds and strengthens its language pathways through repeated,
  responsive interaction, particularly during the early years.
- Because these pathways continue to develop, supportive everyday experiences can
  meaningfully influence how communication skills grow.
- Small, frequent, enjoyable interactions generally do more for these pathways than
  occasional intensive practice.
- Progress in communication often appears in uneven steps rather than at a steady
  pace, and periods of little visible change are common.

## Professional Boundary

- Manasi can provide educational information, but cannot diagnose medical conditions.
- Only a qualified healthcare professional can determine whether a child's speech is
  developing as expected, and which of the possible reasons applies.
- The professionals who assess this are usually a speech-language pathologist, a
  paediatrician, or an audiologist where hearing is in question.
- Information here describes possibilities in general and cannot describe what is
  true for an individual child.
- Manasi does not recommend or prescribe any specific therapy, programme or
  intervention for a child.

## When Professional Evaluation May Help

- When a family has been concerned about a child's speech for some time, an
  evaluation by an appropriate professional may help provide more clarity.
- When there are questions about how well a child hears, a hearing check is often a
  useful early step.
- When a child appears to understand much less than expected for their age.
- When words or skills a child previously used are no longer being used.
- When a child communicates very little in any form, including gestures and eye
  contact.
- When a child seems frustrated by not being understood, or is withdrawing from
  interaction.

## Common Misunderstandings

- The belief that boys always talk later than girls is a generalisation, and it can
  delay useful support for an individual child.
- Growing up with more than one language does not itself cause a speech delay,
  though it can change how early words are distributed.
- Waiting to see whether a child catches up is not the only option, since an
  assessment can be reassuring as well as informative.
- Being able to understand well does not rule out a delay in speaking.
- A quiet or shy temperament is not the same as a delay in developing speech.

## What This Concern Is Not

- This concern is about how much a child says, which is different from how clearly
  they say it — see [unclear speech](../communication/unclear_speech.md).
- It is distinct from a child who speaks freely at home but not in specific
  settings, which is a different pattern.
- It is not a description of autism, though speech development is one of several
  areas sometimes involved.

## Age-Specific Notes

- Between one and two years, the focus is usually on first words emerging and on
  how a child communicates without them.
- Between two and three years, families often notice whether single words are
  beginning to combine.
- Between three and five years, sentence length, variety of words and how well
  unfamiliar listeners understand the child tend to become more relevant.

## Cultural and Multilingual Notes

- In multilingual homes, a child's total vocabulary across languages gives a fuller
  picture than the count in any one language.
- Expectations about when children should talk vary between families and
  communities, which can affect when a concern is first raised.
- Extended-family caregiving arrangements can change how much back-and-forth
  conversation a child experiences in a day.

## References

- Late Language Emergence — American Speech-Language-Hearing Association — https://www.asha.org/
- Early Childhood Development — World Health Organization — https://www.who.int/
- Developmental Milestones — Centers for Disease Control and Prevention — https://www.cdc.gov/
```

**What this example demonstrates:** no sentence addresses the parent directly; every explanation is hedged; no condition is asserted; no therapy is prescribed; every section is reusable raw material; and the file is fully machine-parseable from the front matter alone.

**How it feeds the playbook.** Compare it against `MANASI_ANSWER_PLAYBOOK.md` Q1 ("My 3-year-old still doesn't speak properly. Should I be worried?"), whose answer was hand-written. Every element of that answer is sourceable from this file: the normalising opener from `## Summary`; the four explanations (speech muscles, hearing/processing, comprehension-versus-production, individual pace) from `## Possible Explanations`; the developmental-areas-plus-neuroplasticity paragraph from `## ManaScience Perspective` + `## Neuroplasticity Explanation` + `development_domains`; the boundary sentence verbatim from `## Professional Boundary`; and the "note what your child *does* do" next step from `## Things to Observe`. What the file deliberately does **not** supply is the answer's opening acknowledgement, its supportive line, its closing invitation, or its `worried`-state tone — all of which come from the playbook via the Empathy Node. That division is the whole design.

---

## 17. Contribution Guidelines

### 17.1 Roles

| Role | Responsibility |
|---|---|
| **Content Author** | Drafts the file, sources claims, writes phrasings from real parent language |
| **Clinical Reviewer** | Verifies accuracy, hedging and boundary language; sets `clinical_review_status` |
| **Content Maintainer** | Owns taxonomy, relationships, duplicate prevention, corpus health |
| **Engineering Owner** | Owns loader, validator, ingestion, retrieval quality gates |

### 17.2 Adding a concern

1. **Check for duplicates.** Search existing `keywords` and `search_terms`. If an existing concern covers ≥ 70 % of the intended phrasings, extend it instead of adding a file.
2. **Name it** per Section 9.2 — behaviour, not condition.
3. **Copy** `_templates/concern.template.md` into the correct category directory.
4. **Fill the front matter** using only Appendix A vocabularies. Set `status: draft`, `clinical_review_status: unreviewed`, `content_version: "0.1.0"`.
5. **Write phrasings first.** `## Typical User Questions` before the explanatory sections — it forces the file to be shaped by how parents actually ask.
6. **Write the knowledge sections**, obeying the hedging and boundary rules.
7. **Add relationships**, and add reciprocal edges in the target files in the same PR.
8. **Run the validator locally.** Fix every ERROR; justify every accepted WARN in the PR description.
9. **Open a PR** titled `content(concerns): add <concern_id>`.
10. **Clinical review.** Reviewer sets `clinical_review_status: reviewed` + `clinical_reviewer`.
11. **Publish.** Set `status: published`, `content_version: "1.0.0"`, update `last_updated`, merge. Ingestion picks it up on the next index build.

### 17.3 Editing a concern

* One concern per PR wherever possible; corpus-wide mechanical changes (a schema migration) are the exception and should touch nothing else.
* Bump `content_version` per Section 13.4 and always update `last_updated`.
* Any change to `## Possible Explanations`, `## Professional Boundary` or `## When Professional Evaluation May Help` resets `clinical_review_status` to `revision_needed`.
* Adding phrasings/keywords is encouraged and needs no clinical re-review (M-1) — retrieval improvements should be cheap.

### 17.4 Writing rules

**Read `docs/MANASI_ANSWER_PLAYBOOK.md` Parts 3, 4 and 6 before authoring.** They define the ManaScience perspective, the Never/Always list with its approved phrasings, and the behaviour-not-condition discipline. Nothing in this section replaces them; the table below is only the translation of those rules into the *knowledge-file* register, which differs from the answer register in one crucial way: **answers speak to a parent, knowledge files speak about children.**

| Do (knowledge register) | Don't | Playbook source |
|---|---|---|
| "Some children may…" | "Your child is probably…" | Part 4, Never — no diagnosis, even softly |
| "Families often find it helps to…" | "You should…" | Part 4, Never — no prescription |
| "A professional can assess whether…" | "This means your child needs therapy." | Part 4, Always — boundary phrasing |
| "Speech may develop alongside differences in social communication." | "This is an early sign of autism." | Part 6 — answer the behaviour, not the condition |
| "Progress often appears in uneven steps." | "With therapy, your child will be talking within six months." | Part 4, Never — no guaranteed outcomes |
| Name only approaches from Part 3's table | Name any other programme or practitioner | Part 4, Never — nothing outside the source material |
| Write *about* children in general | Write *to* this parent — that is the Empathy Node's register, not the library's | Part 2 — Acknowledge/Support/Invite are the answer's, not the source's |
| Use the parent's vocabulary in phrasings | Rewrite parent phrasings into clinical language | Retrieval quality (G-3) |
| One idea per bullet | Paragraph-length bullets | S-10 |

A useful test for the register boundary: if a sentence could be pasted into a chat window and read naturally to a parent, it belongs in the playbook's exemplars, not in a concern file.

### 17.5 PR checklist

- [ ] Filename == `concern_id` == front-matter ID; `category` == directory
- [ ] All 10 required sections present and non-empty
- [ ] `## Typical User Questions` ≥ 12 real phrasings
- [ ] Every `## Possible Explanations` bullet is hedged
- [ ] No diagnosis, prescription, guarantee, urgency, marketing or chatbot voice (Playbook Part 4)
- [ ] `## Professional Boundary` uses an approved Playbook Part 4 phrasing verbatim and names the relevant professional
- [ ] `related_therapies` and any named approach appear in Playbook Part 3's table
- [ ] All five Playbook Explain beats (Section 7.6) are sourceable from the file with zero invented facts
- [ ] All relationship IDs resolve; reciprocal edges added
- [ ] `cta_mapping` IDs exist in `data/cta/**`
- [ ] `content_version` and `last_updated` updated
- [ ] Validator passes with zero ERRORs
- [ ] Retrieval spot-check: 3 held-out phrasings resolve to this concern

### 17.6 Definition of Done

A concern is done when a reviewer who has never seen it can read only the file and answer: what behaviour is this, how do parents describe it, what may explain it, what should a family notice, what helps day to day, how does ManaScience frame it, and where does Manasi stop — without finding a single sentence that could be pasted directly into a chat window.

The stronger acceptance test (GD-4): **hand the file and `MANASI_ANSWER_PLAYBOOK.md` Part 5's template to a reviewer and ask them to draft an answer.** If they can complete all five Explain beats without inventing a fact, the file is done. If they reach for outside knowledge, the file has a gap — and the gap is in the library, not in the playbook. Playbook Part 7's sixty worked answers are the quality bar: for the concerns it covers (Q1–Q60), a generated answer built from the corresponding concern file should be substantively equivalent to the hand-written one.

---

## 18. Engineering Recommendations

### 18.1 Build order

| # | Deliverable | Depends on | Notes |
|---|---|---|---|
| 1 | `_schema/` docs + `_templates/concern.template.md` | — | Content authoring can start immediately after |
| 2 | Concern loader (`app/knowledge/concern_loader.py`) | 1 | Mirror `cta_loader.py`: never raises, skips invalid files with a machine-readable reason code, eager module-level load, `force_reload` for tests |
| 3 | Validator CLI (`scripts/validate_knowledge.py`) | 2 | Non-zero exit on ERROR; used by pre-commit and CI |
| 4 | Ingestion path in `scripts/build_knowledge_index.py` | 2 | Section-aware chunking; delete-by-`concern_uid` then upsert |
| 5 | `CONTENT_TYPES` + `INTENT_CONTENT_TYPE_MAP` updates | 4 | Additive; safe with an empty corpus |
| 6 | Stage B concern resolution in `knowledge_node.py` | 5 | Behind `CONCERN_RESOLUTION_ENABLED`, default on once ≥ 10 concerns exist |
| 7 | Response Generation section-slot prompt | 6 | The step that actually changes answer quality. The prompt **references** `MANASI_ANSWER_PLAYBOOK.md` Parts 2/4 for structure and boundaries and maps sections to Explain beats per Section 7.6 — it does not re-specify tone or format inline, which would fork the policy |
| 8 | Retrieval evaluation harness | 4 | Section 10.7 metrics, seeded from Playbook Part 7's sixty questions |
| 9 | Seed corpus: 15 concerns | 1 | **Draw them from Playbook Part 7**, whose sixty questions already span speech, autism concerns, attention, learning, sensory, emotional, social, motor, daily living, sleep and family-member perspectives. Each seeded concern arrives with a hand-written reference answer, which turns Part 7 into a free end-to-end regression suite: generate from the file, compare against the playbook's answer |

### 18.2 Loader design principles (carried from `cta_loader.py`, which got these right)

* **Never raise.** A malformed content file must not 500 the API. Skip it, record `(path, reason, detail)`, log a warning, keep serving.
* **Machine-readable reason codes** (`missing_required_field`, `invalid_vocabulary_value`, `duplicate_concern_id`, `unresolved_relation`, `unsupported_schema_version`) so failures are aggregatable, not just readable.
* **Eager load at import, cached in memory.** 500 files is a few MB; per-request disk I/O is not warranted.
* **Explicit `base_dir` bypasses the cache** so tests point at fixtures without touching global state.
* **Deterministic ordering** (sorted paths) so every build is reproducible.

### 18.3 Retrieval

* Keep `RAG_SIMILARITY_THRESHOLD` at 0.35 globally, but gate **concern resolution** at 0.45. Wrong-concern answers are worse than generic ones.
* Put `concern_knowledge` **first** in `INTENT_CONTENT_TYPE_MAP[personal_concern]`; the existing unfiltered retry already prevents a narrow filter from starving retrieval.
* Do not raise `KNOWLEDGE_TOP_K` when adding this corpus — Stage B aggregates by concern, so more chunks buy little and cost context.
* Log resolved `concern_id`, score, margin over runner-up, and section hits on every turn. That log is the retrieval-tuning dataset.

### 18.4 Content operations

* Ship the seed 15 concerns before writing 500 — retrieval behaviour at scale is only observable with real overlapping content.
* Track a **coverage backlog** of unmatched user queries; each entry is either a new concern or a phrasing gap in an existing one. This is the primary input to the content roadmap.
* Nightly corpus-health report: orphans, one-sided edges, near-duplicates, files unchanged > 365 days, files with `clinical_review_status: revision_needed`.

### 18.5 Things to explicitly avoid

* **Do not** reuse `RecursiveCharacterTextSplitter` on concern files — it will split mid-bullet and merge across sections, destroying section attribution.
* **Do not** reuse `compute_chunk_id(source_id, chunk_index)` — index-based IDs orphan vectors on any edit (Section 10.4).
* **Do not** let the CTA Node read concern content directly; `cta_mapping` IDs only, so CTA exclusion rules stay authoritative.
* **Do not** commit generated JSON — it becomes a second source of truth within a week.
* **Do not** allow authors to add front-matter keys ad hoc — V-3 exists because 500 files with 30 improvised keys is unmigratable.
* **Do not** copy answer-format, tone or approved-phrasing rules into concern files, node prompts or this specification. They live in `MANASI_ANSWER_PLAYBOOK.md` and are referenced from everywhere else (GD-3). Two copies of a safety rule means one of them is out of date and nobody knows which.
* **Do not** route CTAs from `cta_mapping` to work around Playbook Part 8's routing gaps — fix the trigger phrasings in `data/cta/**` (Section 10.6).

---

## 19. Risks

| # | Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|---|
| R-1 | **Content drifts into chatbot answers** — authors naturally write to the parent | High — duplicated/conflicting voice, Empathy Node fighting the source | High | V-33 style validator; template; PR checklist; the Section 16 example as the reference standard |
| R-2 | **Hedging erodes into diagnosis** across many edits | Critical — Manasi appears to diagnose | Medium | V-30/V-31 as hard ERRORs; clinical re-review on any explanation change; Safety Node as the last line |
| R-3 | **Concern overlap degrades retrieval** as the corpus grows | High — wrong-concern answers | High at 200+ files | V-43 near-duplicate detector; `differential` edges; `negative_terms`; Section 10.7 gate |
| R-4 | **Taxonomy churn** forces mass re-filing | Medium — path churn, broken links | Medium | Two-level tree (P-3); flat categories (P-4); `tags` as the escape valve; category changes are schema changes |
| R-5 | **Schema drift** — improvised keys and sections | High — blocks migration | Medium | V-3/V-10 reject unknowns; schema versioning; template-first authoring |
| R-6 | **Markdown outgrows its usefulness** at 1,000+ files | Medium — review and search friction | Medium | Migration path already specified (Section 14); trigger at Phase 2 |
| R-7 | **Stale index** vs corpus | Medium — outdated answers served | Medium | `content_version`/`last_updated` in chunk metadata; ingest on merge; nightly drift check |
| R-8 | **Related-graph rot** — dangling or one-sided edges | Medium — poor navigation, weak recall | High without tooling | V-22/V-28; nightly report; reciprocal edges required in the same PR |
| R-9 | **CTA coupling** — concern authors steering CTAs | Medium — CTA exclusions bypassed | Medium | `cta_mapping` is advisory only; CTA Node retains authority (Section 10.6) |
| R-10 | **Clinical review becomes the bottleneck** at scale | High — content stalls in `draft` | High | Reviewer pool; phrasing/keyword edits exempt (M-1); `draft` content merges safely without being served |
| R-11 | **Chunk explosion / cost** | Low | Low | ~14 chunks/file, ~$0.10 per full rebuild; incremental ingest |
| R-12 | **Empathy Node drops factual content** under higher fact density | High — knowledge silently lost | Medium | Existing `EMPATHY_FACT_RETENTION_MIN_RATIO` guard; monitor after concern rollout |
| R-13 | **Corpus written for the model, not for parents** — phrasings invented rather than observed | High — retrieval looks good in tests, fails in production | Medium | Source phrasings from real logs/support queries; coverage backlog drives new phrasings |
| R-14 | **Legacy `Label:`-style corpus and YAML corpus diverge** | Low–Medium — two conventions to maintain | High (by design) | Explicitly scoped: CTA keeps its parser; new corpora are YAML-only; no partial migration |
| R-15 | **Playbook and library drift apart** — an author adds tone or phrasing rules into concern files, or the playbook accumulates per-concern facts | High — two sources of truth for safety-critical behaviour, and the runtime follows neither reliably | Medium | GD-1…GD-5 precedence rules; V-33/V-34/V-47/V-49 catch behavioural copy in knowledge files; playbook edits that touch Part 3/4 trigger a validator vocabulary review; the two documents cross-reference rather than restate |
| R-16 | **Playbook Part 3's therapy list changes** (a new approach is added or dropped) and 500 files reference the old set | Medium — Manasi names an approach ManaScience no longer covers | Low–Medium | V-48 validates against a single vocabulary file mirroring Part 3; a change is one vocabulary edit plus a corpus-wide validation run that lists every affected file |

---

## 20. Future Enhancements

### 20.1 Retrieval
* Hybrid retrieval — BM25/`pg_trgm` over `## Typical User Questions` combined with dense vectors; parent phrasings are short and lexically distinctive, where sparse retrieval is strong.
* Cross-encoder re-ranking over the top 3 resolved concerns.
* Age- and perspective-aware boosting once the Understanding Node extracts child age reliably.
* `negative_terms` promoted from QA signal to a runtime penalty.
* Multi-concern resolution — return two concerns when scores are within a small margin, with `differential` edges guiding disambiguation in the answer.

### 20.2 Content
* Sibling corpora built on this envelope: `conditions/`, `therapies/`, `assessments/`, `research/`, `faqs/`, `blogs/`.
* Milestone reference data cross-linked to concerns (as reference material, never as a screening tool).
* "Questions a professional may ask" expanded into appointment-preparation material.
* Concern → roadmap linkage against the existing `data/roadmap/` mapping workbooks.

### 20.3 Tooling
* Authoring CLI that scaffolds a file, checks duplicates and previews retrieval before commit.
* Retrieval playground — type a parent phrasing, see resolved concern + scores + section hits.
* Coverage dashboard: unmatched queries, weak concerns, orphaned files, review backlog.
* **Golden-answer regression suite** built from Playbook Part 7: for each of the sixty questions, generate an answer from the corresponding concern file and diff it against the playbook's hand-written version on facts covered, beats present, boundary phrasing retained and qualifiers preserved. This turns the playbook from documentation into an executable acceptance test, and it is the cheapest available guard against silent quality regressions in Response Generation or Empathy.
* Auto-suggested `related_concerns` from embedding proximity, proposed for human approval.

### 20.4 Localization
* `lang` front-matter field + `concerns/<lang>/<category>/` layout, sharing `concern_id` across languages.
* Per-language `keywords` / `search_terms` (transliterated Hindi/Marathi/Tamil phrasings are a genuine retrieval need in Indian-English homes).
* Translation status tracked per file against the source language's `content_version`.

### 20.5 Governance
* Scheduled review cadence — every published concern re-reviewed annually.
* Source-citation strengthening: structured `sources` entries with type, year and evidence strength.
* Change-impact reporting: which live answers a given content edit would have altered.

---

## 21. Appendix A — Controlled Vocabularies

Canonical copy lives in `data/knowledge/_schema/vocabularies.md`; the validator reads that file. Adding a value is a schema MINOR bump.

### A.1 `primary_intents` — mirrors the Understanding Node enum exactly
`concept_explanation`, `therapy_information`, `course_information`, `research_information`, `website_information`, `personal_concern`, `emotional_support`, `general_chat`

*(`general_chat` is never valid on a concern file — that intent skips retrieval entirely.)*

### A.2 `common_emotional_states` — mirrors the Understanding Node enum exactly
`neutral`, `curious`, `confused`, `worried`, `overwhelmed`, `frustrated`

### A.3 `development_domains`
`speech_language`, `communication`, `social_emotional`, `gross_motor`, `fine_motor`, `sensory_processing`, `cognition_learning`, `attention_executive_function`, `behaviour_regulation`, `adaptive_daily_living`, `sleep`, `feeding`

### A.4 `age_groups`
`infant_0_12m`, `toddler_1_3y`, `preschool_3_5y`, `early_school_5_8y`, `middle_childhood_8_12y`, `adolescent_12_18y`, `any`

### A.5 `family_perspectives`
`parent`, `mother`, `father`, `grandparent`, `sibling`, `caregiver`, `teacher`, `self`

### A.6 `related_concerns.relation`
`co_occurring`, `differential`, `broader`, `narrower`, `precursor`, `consequence`

### A.7 `category`
`communication`, `social`, `behaviour`, `sensory`, `motor`, `attention`, `learning`, `emotional`, `sleep`, `feeding`, `daily_living`, `milestones`

### A.8 `status`
`draft`, `in_review`, `published`, `deprecated`

### A.9 `clinical_review_status`
`unreviewed`, `reviewed`, `revision_needed`

### A.10 `related_therapies` — **not defined here**

The therapy vocabulary is `MANASI_ANSWER_PLAYBOOK.md` Part 3, "The therapies Manasi may reference". `_schema/vocabularies.md` holds a slug mirror of that table (with a pointer back to it, and no additions), plus the two generic disciplines `speech_therapy` and `occupational_therapy`. V-48 validates against the mirror; changing the mirror without a corresponding playbook change is a review failure (GD-5).

### A.11 `section` keys (chunk metadata)
`matcher`, `summary`, `typical_user_questions`, `alternative_user_phrasings`, `possible_explanations`, `things_to_observe`, `everyday_support_ideas`, `manascience_perspective`, `neuroplasticity_explanation`, `professional_boundary`, `when_professional_evaluation_may_help`, `common_misunderstandings`, `what_this_concern_is_not`, `age_specific_notes`, `family_perspective_notes`, `cultural_and_multilingual_notes`, `questions_a_professional_may_ask`, `references`

---

## 22. Appendix B — Field → Storage Mapping Matrix

| Field | Markdown | JSON | MongoDB | PostgreSQL | ChromaDB | Pinecone |
|---|---|---|---|---|---|---|
| `concern_id` | front matter | string | `_id` | `concerns.concern_id` PK | metadata str | metadata str |
| `concern_uid` | front matter | string | field | `concerns.concern_uid` UNIQUE | metadata str | metadata str + ID prefix |
| `title` | front matter + H1 | string | field | column | metadata str | metadata str |
| `status` | front matter | string | field | enum/lookup | ingest filter (not stored) | ingest filter |
| `category` | directory + front matter | string | field | FK → `categories` | metadata str | metadata str |
| `topic` | front matter | string | field | column | metadata str | metadata str |
| `subtopics` | front matter | array | array | `concern_subtopics` | piped str | list[str] |
| `development_domains` | front matter | array | array (multikey) | `concern_domains` | piped str | list[str] |
| `tags` | front matter | array | array (multikey) | `concern_tags` | piped str | list[str] |
| `primary_intents` | front matter | array | array | `concern_intents` | piped str | list[str] |
| `common_emotional_states` | front matter | array | array | `concern_emotions` | piped str | list[str] |
| `age_groups` | front matter | array | array | `concern_age_groups` | piped str | list[str] |
| `family_perspectives` | front matter | array | array | `concern_perspectives` | piped str | list[str] |
| `keywords` | front matter | array | array + text index | `concern_keywords` (kind=keyword) | in matcher chunk text | in matcher chunk text |
| `search_terms` | front matter | array | array + text index | `concern_keywords` (kind=search_term) | in matcher chunk text | in matcher chunk text |
| `negative_terms` | front matter | array | array | `concern_keywords` (kind=negative_term) | not indexed | not indexed |
| `related_concerns` | front matter | array[obj] | array[subdoc] | `concern_relations` | not stored | not stored |
| `related_conditions` / `related_therapies` | front matter | array | array | `concern_external_relations` | not stored | not stored |
| `cta_mapping` | front matter | array[obj] | array[subdoc] | `concern_cta_mappings` | not stored | not stored |
| `escalation_sensitive` | front matter | bool | field | boolean column | metadata bool | metadata bool |
| `clinical_review_status` / `clinical_reviewer` | front matter | string | field | column | not stored | not stored |
| `content_version` / `schema_version` | front matter | string | field | column | metadata str | metadata str |
| `last_updated` | front matter | date str | ISODate | `date` column | metadata str | metadata str |
| `authors` / `sources` | front matter | array | array | join tables | not stored | not stored |
| `## Summary` | H2 section | `sections.summary` | `sections.summary` | `concern_sections` row | summary chunk | summary chunk |
| Each `##` prose section | H2 section | `sections.<key>.bullets` | subdoc | `concern_sections` + `concern_bullets` | one chunk per section | one chunk per section |
| Question/phrasing sections | H2 sections | arrays | arrays | `concern_questions` | matcher chunk | matcher chunk |

**The invariant:** every row above is a *re-serialization*. No target requires a field the Markdown lacks, and no target loses a field the Markdown has. That is what "migrate without changing the information architecture" means concretely.

---

**End of specification.**
