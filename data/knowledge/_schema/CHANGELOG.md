# Concern Knowledge Library — Schema Changelog

Semver on the **schema**, independent of any file's `content_version`.

- **MAJOR** — breaks existing files (required field/section removed or renamed, type
  changed). Requires a mechanical migration of the whole corpus in one commit, and a loader
  that rejects unsupported majors. "Hand-edit every file" is not a migration path.
- **MINOR** — additive and backward-compatible (new optional field, new optional section,
  new vocabulary value).
- **PATCH** — clarified docs, tightened validator messages, no file changes required.

---

## 1.0.0 — 2026-07-28

Initial schema.

- YAML front matter + fixed `##` section set (`concern.schema.md`).
- Closed vocabularies (`vocabularies.md`), including the `related_therapies` mirror of
  `docs/MANASI_ANSWER_PLAYBOOK.md` Part 3 and the approved boundary phrasings from Part 4.
- Loader (`app/knowledge/concern_loader.py`), chunker (`app/knowledge/concern_chunker.py`),
  validator (`scripts/validate_knowledge.py`).
- Supported schema majors: `1`.
