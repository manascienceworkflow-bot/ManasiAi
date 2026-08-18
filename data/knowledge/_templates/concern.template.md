---
# Copy this file to data/knowledge/concerns/<category>/<concern_id>.md and fill it in.
# Delete every "#" comment line before committing.
# Field contract: data/knowledge/_schema/concern.schema.md
# Vocabularies:   data/knowledge/_schema/vocabularies.md
# Answer behaviour (READ FIRST): docs/MANASI_ANSWER_PLAYBOOK.md Parts 3, 4, 6

schema_version: "1.0.0"
content_type: concern_knowledge
concern_id: replace_me            # snake_case, must equal the filename stem
concern_uid: concerns/replace_category/replace_me
title: Replace Me                 # Title Case, must equal the H1 below
status: draft                     # draft until clinically reviewed

category: replace_category        # must equal the parent directory name
topic: replace me                 # lowercase canonical label
subtopics: []
development_domains:
  - replace_domain                # 1-4, primary first
tags: []

primary_intents:
  - personal_concern
common_emotional_states:
  - worried
age_groups:
  - toddler_1_3y
family_perspectives:
  - parent

# 8-25 lowercase words/short phrases. Include BOTH lay and clinical terms.
keywords: []

# 5-15 multi-word phrases that look like something a parent would actually type.
# These are the highest-leverage retrieval field in the file.
search_terms: []

# 0-10 phrases that must NOT pull this concern (e.g. adult-only variants).
negative_terms: []

related_concerns: []
# - id: some_other_concern
#   relation: co_occurring        # co_occurring | differential | broader | narrower | precursor | consequence
#   weight: 0.7
related_conditions: []
related_therapies: []             # Playbook Part 3 allowlist only
cta_mapping: []
# - cta_id: conditions/autism     # must exist in data/cta/**
#   priority: secondary

professional_boundary_required: true
escalation_sensitive: false
clinical_review_status: unreviewed
content_version: "0.1.0"
last_updated: 2026-01-01
authors:
  - "Replace Me"
sources: []
---

# Replace Me

## Summary

<!-- 40-90 words of prose, no bullets. Define the BEHAVIOUR, not a condition. Neutral and
     factual: this is retrieval anchoring and grounding material, not reassurance copy.
     Do not address the reader. -->

## Typical User Questions

<!-- 12-30 real parent phrasings, first person, AS TYPED. Do not tidy them into formal
     English - the whole point is that a parent's sentence matches sentences like theirs. -->

- Replace me.

## Alternative User Phrasings

<!-- 8-25 non-question forms: statements, fragments, colloquialisms, Indian-English
     variants, the words grandparents and teachers use. -->

- Replace me.

## Possible Explanations

<!-- 6-15 bullets, ordered common -> less common. EVERY bullet must be hedged (may, can,
     sometimes, for some children...). Never assert a cause for a specific child. -->

- Some children may replace me.

## Things to Observe

<!-- 6-12 bullets. Observable and non-technical - what a family can notice and describe to
     a professional. No "if X then Y", no counts, no thresholds. -->

- Replace me.

## Everyday Support Ideas

<!-- 6-14 bullets. Zero-risk, no equipment, no protocol, no therapy substitution.
     Frame as "families often find..." rather than "you should...". -->

- Families often find it helps to replace me.

## ManaScience Perspective

<!-- 4-8 bullets applying Playbook Part 3's five commitments TO THIS CONCERN. If a bullet
     would read identically in another concern file, it belongs in the playbook, not here. -->

- Replace me.

## Neuroplasticity Explanation

<!-- 4-8 bullets, specific to this concern's developmental domain. No cure claims, no
     guaranteed outcomes, no timelines. -->

- Replace me.

## Professional Boundary

<!-- 3-6 bullets. At least one MUST use a Playbook Part 4 approved phrasing verbatim:
       "Only a qualified healthcare professional can determine that."
       "An evaluation by an appropriate professional may help provide more clarity."
       "Manasi can provide educational information, but cannot diagnose medical conditions."
     The concern-specific job is naming WHICH professional assesses this. -->

- Manasi can provide educational information, but cannot diagnose medical conditions.

## When Professional Evaluation May Help

<!-- 4-10 bullets. "Worth discussing with a professional", never "warning signs", never a
     numeric cut-off. If any bullet touches genuine urgency, set escalation_sensitive: true. -->

- Replace me.

<!-- OPTIONAL SECTIONS - keep only the ones that add real value, in this order:
## Common Misunderstandings
## What This Concern Is Not
## Age-Specific Notes
## Family Perspective Notes
## Cultural and Multilingual Notes
## Questions a Professional May Ask
## References        (the only section where links are allowed)
-->
