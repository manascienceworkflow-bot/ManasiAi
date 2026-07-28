"""Turns a ConcernRecord into the chunks that get embedded.

Spec: `.claude/spec/manasi-ai-concern-knowledge-library-spec.md` Section 10.3-10.4.

Chunking here is *structural*, not character-based, and deliberately does NOT reuse
`RecursiveCharacterTextSplitter` (used by the legacy corpora in
`scripts/build_knowledge_index.py`): that splitter would cut mid-bullet and merge across
sections, destroying the section attribution that concern resolution and response assembly
both depend on.

Pure functions, no I/O and no embedding calls, so ingestion and tests share one
implementation of the chunk contract.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import settings
from app.knowledge.concern_loader import (
    OPTIONAL_SECTIONS,
    REQUIRED_SECTIONS,
    SECTION_RANK_BY_KEY,
    ConcernRecord,
)

CONTENT_TYPE = "concern_knowledge"

MATCHER_SECTION = "matcher"
SUMMARY_SECTION = "summary"

# The matcher chunk is assembled from these; they are therefore not emitted as chunks of
# their own -- a bare list of parent questions is only useful as matching surface.
_PHRASING_SECTION_KEYS = ("typical_user_questions", "alternative_user_phrasings")

# Ranks for the two synthetic chunks. Negative so they sort ahead of every prose section
# while leaving the loader's canonical section ranks untouched.
_SYNTHETIC_RANKS = {MATCHER_SECTION: -2, SUMMARY_SECTION: -1}

# `references` is a list of source links, not answer material: embedding it would put
# organization names and URLs into vector space, where they compete with real content for
# similarity without ever grounding an answer.
_NON_CHUNKED_SECTION_KEYS = set(_PHRASING_SECTION_KEYS) | {SUMMARY_SECTION, "references"}

_PROSE_SECTION_KEYS = [
    key for _, key in REQUIRED_SECTIONS + OPTIONAL_SECTIONS if key not in _NON_CHUNKED_SECTION_KEYS
]


@dataclass
class ChunkSpec:
    chunk_id: str
    text: str
    section: str
    concern_uid: str
    metadata: "dict[str, Any]" = field(default_factory=dict)


def serialize_list(values: "list[str]") -> str:
    """Pipe-wrap a list for Chroma metadata, which only accepts scalar values.

    Leading and trailing pipes keep substring containment a usable filter primitive:
    `|speech_language|` matches the whole token and never a prefix of another value.
    """
    if not values:
        return ""
    return "|" + "|".join(str(value) for value in values) + "|"


def deserialize_list(value: Optional[str]) -> "list[str]":
    """Inverse of `serialize_list`. Used by the migration targets that support native
    lists (Pinecone) and by tests asserting the round-trip."""
    if not value:
        return []
    return [part for part in value.strip("|").split("|") if part]


def compute_chunk_id(concern_uid: str, section: str, part: int = 0) -> str:
    """Section-keyed, deliberately NOT `source_id:chunk_index` like the legacy corpora.

    An index-keyed id shifts every downstream chunk when a section is inserted, orphaning
    stale vectors on upsert. Keying on the section means editing one section changes
    exactly one vector, which is what makes re-ingestion genuinely idempotent.
    """
    return hashlib.sha256(f"{concern_uid}:{section}:{part}".encode("utf-8")).hexdigest()


def source_id_for(record: ConcernRecord) -> str:
    """Repo-relative path, derived from `concern_uid` so it never depends on where the
    corpus happens to be mounted."""
    return f"data/knowledge/{record.concern_uid}.md"


def _retrieval_header(record: ConcernRecord, section_label: str) -> str:
    """Spec C-1. Without it, bullet lists of support strategies embed almost identically
    across concerns, and the nearest neighbour becomes essentially arbitrary."""
    return f"{record.title} — {section_label}"


def _base_metadata(record: ConcernRecord) -> "dict[str, Any]":
    return {
        "content_type": CONTENT_TYPE,
        "source_id": source_id_for(record),
        "source_title": record.title,
        "source_url": None,
        "concern_id": record.concern_id,
        "concern_uid": record.concern_uid,
        "category": record.category,
        "topic": record.topic,
        "development_domains": serialize_list(record.development_domains),
        "age_groups": serialize_list(record.age_groups),
        "primary_intents": serialize_list(record.primary_intents),
        "family_perspectives": serialize_list(record.family_perspectives),
        "escalation_sensitive": record.escalation_sensitive,
        "content_version": record.content_version,
        "last_updated": record.last_updated.isoformat(),
    }


def _matcher_text(record: ConcernRecord) -> str:
    """Title, topic, every authored parent phrasing, plus the tuned retrieval fields.

    This is the highest-leverage chunk in the design: it compares the user's sentence
    against sentences shaped like theirs, rather than against clinical prose.
    """
    lines = [_retrieval_header(record, "How families ask about this"), "", f"Topic: {record.topic}", ""]
    for key in _PHRASING_SECTION_KEYS:
        lines.extend(record.section_bullets(key))
    lines.extend(record.search_terms)
    if record.keywords:
        lines.append(", ".join(record.keywords))
    return "\n".join(line for line in lines if line is not None).strip()


def _split_bullets_by_chars(bullets: "list[str]", max_chars: int) -> "list[list[str]]":
    """Group bullets into parts under `max_chars`, never splitting a bullet (spec C-2).

    A bullet longer than the budget gets its own oversized part rather than being cut --
    truncating a clinical statement mid-sentence is worse than an oversized chunk.
    """
    parts: "list[list[str]]" = []
    current: "list[str]" = []
    current_len = 0
    for bullet in bullets:
        bullet_len = len(bullet) + 1
        if current and current_len + bullet_len > max_chars:
            parts.append(current)
            current = []
            current_len = 0
        current.append(bullet)
        current_len += bullet_len
    if current:
        parts.append(current)
    return parts or [[]]


def chunk_concern(record: ConcernRecord, max_chunk_chars: Optional[int] = None) -> "list[ChunkSpec]":
    """Chunk one concern: 1 matcher + 1 summary + 1 per prose section (split on bullet
    boundaries when oversized). Chunk order is deterministic, and `chunk_index` is the
    ordinal within this concern only."""
    max_chunk_chars = max_chunk_chars or settings.concern_max_chunk_chars
    base = _base_metadata(record)
    chunks: "list[ChunkSpec]" = []

    def _emit(section: str, text: str, rank: int, part: int = 0, part_count: int = 1) -> None:
        metadata = dict(base)
        metadata.update(
            {
                "chunk_id": compute_chunk_id(record.concern_uid, section, part),
                "section": section,
                "section_rank": rank,
                "section_part": part,
                "section_part_count": part_count,
                "chunk_index": len(chunks),
            }
        )
        chunks.append(
            ChunkSpec(
                chunk_id=metadata["chunk_id"],
                text=text,
                section=section,
                concern_uid=record.concern_uid,
                metadata=metadata,
            )
        )

    # The matcher chunk is deliberately never split, even when it exceeds max_chunk_chars:
    # halving the phrasing list would leave two chunks that each match a subset of how
    # families ask, and the whole point of this chunk is that any of those phrasings finds
    # the concern. It stays comfortably within embedding token limits regardless.
    _emit(MATCHER_SECTION, _matcher_text(record), _SYNTHETIC_RANKS[MATCHER_SECTION])

    summary = record.sections.get(SUMMARY_SECTION)
    if summary is not None and summary.raw.strip():
        text = f"{_retrieval_header(record, 'Summary')}\n\n{summary.raw.strip()}"
        _emit(SUMMARY_SECTION, text, _SYNTHETIC_RANKS[SUMMARY_SECTION])

    for key in _PROSE_SECTION_KEYS:
        section = record.sections.get(key)
        if section is None or section.is_not_applicable() or not section.bullets:
            continue
        header = _retrieval_header(record, section.name)
        parts = _split_bullets_by_chars(section.bullets, max_chunk_chars - len(header) - 2)
        for part_index, bullets in enumerate(parts):
            if not bullets:
                continue
            body = "\n".join(f"- {bullet}" for bullet in bullets)
            _emit(
                key,
                f"{header}\n\n{body}",
                SECTION_RANK_BY_KEY[key],
                part=part_index,
                part_count=len(parts),
            )

    return chunks
