# Concern File Schema — v1.0.0

The field contract for every file under `data/knowledge/concerns/`. Full rationale lives in
`.claude/spec/manasi-ai-concern-knowledge-library-spec.md` (§7, §8); this is the working
reference for authors and the checklist the loader enforces.

**Before authoring, read `docs/MANASI_ANSWER_PLAYBOOK.md` Parts 3, 4 and 6.** They define
the ManaScience perspective, the Never/Always safety rules with approved phrasings, and the
behaviour-not-condition discipline. This schema does not restate them.

---

## File shape

```
---
<YAML front matter>          ← machine-readable, closed vocabularies
---

# <Title>                     ← exactly one H1, must equal `title`

## <Section Name>             ← fixed names, fixed order, no ### nesting
- bullet
- bullet
```

Rules: UTF-8, LF endings, 2-space YAML indent, no tabs. No `---` anywhere in the body (it
collides with front-matter delimiting). No tables, images, HTML or code fences outside
`## References`. Bullets are 8–45 words, one self-contained idea each, ending with a period.

---

## Front matter

`R` = required. Closed = value must appear in `vocabularies.md`.

### Identity

| Key | Type | R | Notes |
|---|---|---|---|
| `schema_version` | string | R | Semver. Loader rejects unknown majors. Currently `"1.0.0"` |
| `content_type` | closed | R | Always `concern_knowledge` here |
| `concern_id` | string | R | `snake_case`, must equal the filename stem, globally unique, immutable once published |
| `concern_uid` | string | R | `concerns/<category>/<concern_id>` |
| `title` | string | R | Title Case, 2–6 words, must equal the H1 |
| `status` | closed | R | Only `published` is ingested |

### Classification

| Key | Type | R | Notes |
|---|---|---|---|
| `category` | closed | R | Must equal the parent directory name |
| `topic` | string | R | Lowercase canonical label, e.g. `speech delay` |
| `subtopics` | list[string] | — | 0–6, lowercase |
| `development_domains` | closed list | R | 1–4, primary first |
| `tags` | list[string] | — | 0–10 free-text cross-cutting labels |

### Query affinity (retrieval surface)

| Key | Type | R | Notes |
|---|---|---|---|
| `primary_intents` | closed list | R | 1–3; almost always includes `personal_concern` |
| `common_emotional_states` | closed list | R | 1–4; advisory for review, never a filter |
| `age_groups` | closed list | R | 1–N, or `[any]` |
| `family_perspectives` | closed list | R | 1–N; default `[parent]` |
| `keywords` | list[string] | R | 8–25 lowercase words/short phrases, lay **and** clinical |
| `search_terms` | list[string] | R | 5–15 multi-word phrases resembling real search queries |
| `negative_terms` | list[string] | — | 0–10 phrases that must not pull this concern |

These may be tuned freely without clinical re-review, provided no new claim is introduced.

### Relationships

| Key | Type | R | Notes |
|---|---|---|---|
| `related_concerns` | list[{id, relation, weight}] | R (may be `[]`) | Max 8. `relation` closed; `weight` 0.0–1.0 |
| `related_conditions` | closed list | R (may be `[]`) | Max 8 |
| `related_therapies` | closed list | R (may be `[]`) | Max 8. Restricted to Playbook Part 3's table |
| `cta_mapping` | list[{cta_id, priority}] | R (may be `[]`) | `cta_id` must exist in `data/cta/**`; max one `primary` |

Relationships are IDs, never titles or URLs. Symmetric relations (`co_occurring`,
`differential`) and inverse pairs (`broader`/`narrower`, `precursor`/`consequence`) should
be reciprocated in the target file — add both edges in the same PR.

### Governance

| Key | Type | R | Notes |
|---|---|---|---|
| `professional_boundary_required` | bool | R | Always `true` in v1 |
| `escalation_sensitive` | bool | R | `true` for regression, self-injury, feeding/growth risk |
| `clinical_review_status` | closed | R | Must be `reviewed` before `status: published` |
| `clinical_reviewer` | string | — | Required when `clinical_review_status: reviewed` |
| `content_version` | string | R | Semver for this file's content |
| `last_updated` | date | R | ISO `YYYY-MM-DD`, never in the future |
| `authors` | list[string] | R | ≥ 1 |
| `sources` | list[string] | — | Source identifiers backing clinical claims |
| `supersedes` / `superseded_by` | string | — | For merges, splits and renames |

---

## Sections

### Required

| Order | Section | Size |
|---|---|---|
| 1 | `## Summary` — prose, 40–90 words, neutral definition of the **behaviour** | prose |
| 2 | `## Typical User Questions` — verbatim parent phrasings, first person | 12–30 |
| 3 | `## Alternative User Phrasings` — statements, fragments, colloquialisms | 8–25 |
| 4 | `## Possible Explanations` — **every bullet hedged**, common → less common | 6–15 |
| 5 | `## Things to Observe` — observable, non-technical, no scoring | 6–12 |
| 6 | `## Everyday Support Ideas` — zero-risk, no equipment, no protocol | 6–14 |
| 7 | `## ManaScience Perspective` — Playbook Part 3 applied to **this** concern | 4–8 |
| 8 | `## Neuroplasticity Explanation` — domain-specific, no cure/timeline claims | 4–8 |
| 9 | `## Professional Boundary` — ≥ 1 approved phrasing verbatim + which professional | 3–6 |
| 10 | `## When Professional Evaluation May Help` — non-alarming, no numeric cut-offs | 4–10 |

A genuinely inapplicable section is filled with `- Not applicable for this concern.` so
reviewers can tell "considered" from "forgotten".

### Optional

`## Common Misunderstandings`, `## What This Concern Is Not`, `## Age-Specific Notes`,
`## Family Perspective Notes`, `## Cultural and Multilingual Notes`,
`## Questions a Professional May Ask`, `## References` (the only section allowing links).

---

## How sections feed an answer

Response Generation composes prose under Playbook Part 2's five-beat Explain shape:

| Beat | Sourced from |
|---|---|
| 1. Normalise without dismissing | `Summary`, `Common Misunderstandings` |
| 2. Give the actual explanations | `Possible Explanations` |
| 3. Apply the ManaScience lens | `ManaScience Perspective`, `Neuroplasticity Explanation`, `development_domains` |
| 4. State the boundary | `Professional Boundary` |
| 5. Point to the next step | `Things to Observe`, `When Professional Evaluation May Help`, `Everyday Support Ideas` |

Acknowledge, Support, Invite and tone come from the playbook via the Empathy Node and draw
nothing from concern files. A file containing material for them is defective.

**Completeness test:** if a reviewer can draft all five beats from the file alone, without
reaching for outside knowledge, the file is done.

---

## Validation

`./venv/bin/python scripts/validate_knowledge.py` — exit 1 on any ERROR. Every rule is
tagged with its spec ID (`V-4`, `V-31`, `V-47`, …) so output maps straight back to §12.
