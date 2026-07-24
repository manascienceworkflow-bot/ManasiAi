import re

KNOWN_SAFE_SELF_REFERENCES = {"manascience", "manasi"}

HALLUCINATION_HONEST_FALLBACK_PHRASES = [
    "I don't have verified information specific to that, but I can share what I do know about {topic}.",
    "I'm not able to confirm that specific detail, though the general picture I can offer is this:",
    "ManaScience material I have access to doesn't go into that level of detail -- here's what it does cover:",
]


_SENTENCE_START_EXCLUSIONS = (
    r"(?<!^)(?<!\. )(?<!\.\n)(?<!\? )(?<!\?\n)(?<!\! )(?<!\!\n)(?<!\n)"
)


def _candidate_entities(text: str) -> set[str]:
    """Capitalized multi-word phrases and standalone proper nouns -- a coarse
    proxy for 'specific named things,' not a named-entity recognizer. The
    single-word pattern excludes ordinary sentence-initial capitalization
    (start of string, or right after ". "/"? "/"! " or a paragraph-break
    newline -- LLM-generated prose uses "\n" between paragraphs, not just
    ". ", so both must be treated as sentence boundaries)."""
    multi_word = re.findall(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3}\b", text)
    single_word = re.findall(_SENTENCE_START_EXCLUSIONS + r"\b[A-Z][a-zA-Z]{3,}\b", text)
    return {e.strip() for e in multi_word + single_word}


def _is_grounded(entity: str, retrieved_docs: list[dict]) -> bool:
    haystack = " ".join(doc["content"] for doc in retrieved_docs).lower()
    return entity.lower() in haystack


def flagged_entities(
    final_answer: str, source: str, retrieved_docs: list[dict]
) -> list[str]:
    """Returns entities in final_answer that cannot be verified against this
    turn's grounding. Always returns the full list of named things when
    source == 'llm', since no grounding exists to verify against."""
    candidates = {
        e for e in _candidate_entities(final_answer)
        if e.lower() not in KNOWN_SAFE_SELF_REFERENCES
    }
    if source == "llm":
        return sorted(candidates)
    return sorted(e for e in candidates if not _is_grounded(e, retrieved_docs))
