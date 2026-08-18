# Concern Knowledge Library — Controlled Vocabularies

**Schema version:** 1.0.0
**Machine-read by:** `scripts/validate_knowledge.py` and `app/knowledge/concern_loader.py`
**Spec:** `.claude/spec/manasi-ai-concern-knowledge-library-spec.md` Appendix A

This file is the single source of truth for every closed vocabulary in the concern
corpus. Adding a value is a schema MINOR bump (record it in `CHANGELOG.md`).

**Parsing contract — do not break it.** Each vocabulary is an `##` heading whose text is
the exact field name, followed by a flat `- value` bullet list. Text outside bullets is
commentary and is ignored by the parser. Do not nest bullets. Do not add tables inside a
vocabulary section.

---

## content_type

- concern_knowledge
- condition_knowledge
- therapy_knowledge
- assessment_knowledge
- milestone_knowledge

---

## status

- draft
- in_review
- published
- deprecated

---

## clinical_review_status

- unreviewed
- reviewed
- revision_needed

---

## category

Mirrors the directory names under `data/knowledge/concerns/`.

- communication
- social
- behaviour
- sensory
- motor
- attention
- learning
- emotional
- sleep
- feeding
- daily_living
- milestones

---

## development_domains

- speech_language
- communication
- social_emotional
- gross_motor
- fine_motor
- sensory_processing
- cognition_learning
- attention_executive_function
- behaviour_regulation
- adaptive_daily_living
- sleep
- feeding

---

## primary_intents

Mirrors the Understanding Node intent enum (`app/graph/state.py`). `general_chat` is
deliberately absent — that intent skips retrieval entirely, so no concern file can serve it.

- concept_explanation
- therapy_information
- course_information
- research_information
- website_information
- personal_concern
- emotional_support

---

## common_emotional_states

Mirrors the Understanding Node emotion enum. Declares which states a concern typically
arrives with, for content review against Playbook Part 4's tone table. Never a retrieval
filter, never a tone instruction.

- neutral
- curious
- confused
- worried
- overwhelmed
- frustrated

---

## age_groups

- infant_0_12m
- toddler_1_3y
- preschool_3_5y
- early_school_5_8y
- middle_childhood_8_12y
- adolescent_12_18y
- any

---

## family_perspectives

- parent
- mother
- father
- grandparent
- sibling
- caregiver
- teacher
- self

---

## relation

Relation types for `related_concerns` entries.

- co_occurring
- differential
- broader
- narrower
- precursor
- consequence

---

## cta_priority

- primary
- secondary

---

## related_therapies

**Mirror of `docs/MANASI_ANSWER_PLAYBOOK.md` Part 3, "The therapies Manasi may reference."**

Do NOT add an entry here without a corresponding change to the playbook — the playbook is
authoritative and this list follows it (spec GD-5). The final two entries are generic
professional disciplines, not ManaScience-covered programmes, and are permitted so a
concern can point at the right kind of assessment.

- mnri
- feldenkrais
- arrowsmith
- jill_stowell
- neurofeedback
- access_consciousness
- vision_therapy
- neurovision
- lynn_valley_optometry
- nemechek_protocol
- cellular_hydration
- ayurveda
- naturopathy
- safe_and_sound_protocol
- tomatis
- integrated_listening
- speech_therapy
- occupational_therapy

---

## disallowed_therapy_terms

Therapy and intervention names that ManaScience does **not** cover. Naming one in prose
violates Playbook Part 4 ("never name a ManaScience program, practitioner, or research
finding that isn't in the source material"), so V-48 rejects them. Matched
case-insensitively as whole phrases.

- applied behaviour analysis
- applied behavior analysis
- floortime
- son-rise
- teacch
- chelation
- hyperbaric oxygen
- stem cell therapy
- gluten-free casein-free diet
- auditory integration training
- craniosacral therapy
- equine therapy
- brushing protocol

---

## related_conditions

Condition slugs a concern may reference. Reserved for the future `conditions/` corpus;
until that exists, this list is the authority.

- autism
- adhd
- anxiety
- depression
- dyslexia
- dysgraphia
- dyscalculia
- dyspraxia
- hearing_impairment
- vision_impairment
- developmental_language_disorder
- speech_sound_disorder
- global_developmental_delay
- intellectual_disability
- sensory_processing_difficulties
- sleep_disorder
- oppositional_defiant_disorder
- tourette_syndrome
- ocd
- epilepsy

---

## approved_boundary_phrasings

**Match cores derived from `docs/MANASI_ANSWER_PLAYBOOK.md` Part 4, "Always."** V-47
requires at least one `## Professional Boundary` bullet to contain one of these
case-insensitively, which permits grammatical adaptation of the leading clause while
keeping the boundary language itself exactly as the playbook approved it.

Full approved sentences:
- *"Only a qualified healthcare professional can determine that."*
- *"An evaluation by an appropriate professional may help provide more clarity."*
- *"Manasi can provide educational information, but cannot diagnose medical conditions."*

Match cores:

- qualified healthcare professional can determine
- evaluation by an appropriate professional may help provide more clarity
- can provide educational information, but cannot diagnose

---

## hedge_terms

V-31 requires every `## Possible Explanations` bullet to contain at least one of these.
Enforces Playbook Part 4's "keep qualifiers exactly as written."

- may
- might
- can
- could
- sometimes
- often
- for some children
- in some cases
- tends to
- tend to
- typically
- usually
- varies
- some children
