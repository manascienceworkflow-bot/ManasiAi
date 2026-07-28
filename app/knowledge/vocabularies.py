"""Reader for `data/knowledge/_schema/vocabularies.md`.

Shared by the concern loader (closed-vocabulary validation) and
`scripts/validate_knowledge.py` (V-16, V-31, V-47, V-48). Keeping one parser means the
loader and the validator can never disagree about what a legal value is.

The file's parsing contract (documented in its own header): each vocabulary is an `##`
heading whose text is the field name, followed by a flat `- value` bullet list. Prose
between the heading and the bullets is commentary and is ignored.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger("app.knowledge.vocabularies")

VOCAB_RELATIVE_PATH = Path("_schema") / "vocabularies.md"

_HEADING = re.compile(r"^##\s+(.+?)\s*$")
_BULLET = re.compile(r"^-\s+(.+?)\s*$")

# Vocabularies whose values are free-form phrases rather than slugs, so they keep their
# original casing and spacing (everything else is lowercased for comparison).
_PHRASE_VOCABULARIES = {
    "approved_boundary_phrasings",
    "hedge_terms",
    "disallowed_therapy_terms",
}

_CACHE: "Optional[dict[str, list[str]]]" = None


def _parse(text: str) -> "dict[str, list[str]]":
    vocabularies: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in text.splitlines():
        heading = _HEADING.match(line)
        if heading:
            current = heading.group(1).strip()
            vocabularies.setdefault(current, [])
            continue
        if current is None:
            continue
        bullet = _BULLET.match(line)
        if bullet:
            value = bullet.group(1).strip()
            # Bullets inside a phrase vocabulary may carry markdown emphasis from the
            # commentary examples above them; strip it so matching is on plain text.
            value = value.strip("*_ ").rstrip(".")
            vocabularies[current].append(value.lower())
    return {name: values for name, values in vocabularies.items() if values}


def load_vocabularies(
    knowledge_dir: "Optional[Path]" = None, force_reload: bool = False
) -> "dict[str, list[str]]":
    """Return {vocabulary_name: [values]} read from `<knowledge_dir>/_schema/vocabularies.md`.

    `knowledge_dir` is the corpus root (`data/knowledge` by default), not the schema
    directory.

    Never raises. An unreadable or missing vocabularies file returns `{}` and logs an
    error; callers treat an empty result as "vocabulary checks unavailable" and fall back
    to structural validation only, rather than rejecting the entire corpus because a
    schema file went missing.

    A call with an explicit `knowledge_dir` always re-reads and never touches the module
    cache, so tests can point at a fixture corpus without affecting global state.
    """
    global _CACHE
    if knowledge_dir is None:
        if _CACHE is not None and not force_reload:
            return _CACHE
        _CACHE = load_vocabularies(settings.knowledge_data_dir)
        return _CACHE

    path = knowledge_dir / VOCAB_RELATIVE_PATH
    if not path.is_file():
        # Normal for a fixture corpus that has no schema directory of its own; the caller
        # falls back to the real vocabularies. Not an error condition.
        logger.info("vocabularies: no file at %s", path)
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("vocabularies: unreadable path=%s error=%s", path, exc)
        return {}

    vocabularies = _parse(text)
    if not vocabularies:
        logger.error("vocabularies: parsed zero vocabularies from %s", path)
    return vocabularies


def get_values(name: str, vocabularies: "Optional[dict[str, list[str]]]" = None) -> "list[str]":
    """Values for one vocabulary, or [] when it (or the whole file) is unavailable."""
    vocabularies = load_vocabularies() if vocabularies is None else vocabularies
    return vocabularies.get(name, [])


def is_phrase_vocabulary(name: str) -> bool:
    return name in _PHRASE_VOCABULARIES
