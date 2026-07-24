import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, Optional

from app.services.cta_loader import CTARecord, get_ctas_by_status

logger = logging.getLogger("app.services.cta_service")

_WORD = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def _phrase_in_text(phrase_norm: str, text_norm: str, text_tokens: set[str]) -> bool:
    """A normalized phrase matches normalized text if it appears as a substring
    in either direction (handles both a full trigger-example question appearing
    in a longer user message, and a short user message like "mnri" matching a
    short alias), or if every one of the phrase's words is present somewhere in
    the text's token set (handles word-order variation, e.g. a phrase "primitive
    reflexes" against "tell me about primitive reflexes please"). No fuzzy
    matching, no embeddings, no edit distance -- exact normalized containment
    or exact token-subset only, mirroring the loader's own "exact-match, never-
    guess" philosophy (cta_loader spec FR-5)."""
    if not phrase_norm:
        return False
    if phrase_norm in text_norm or text_norm in phrase_norm:
        return True
    phrase_tokens = set(phrase_norm.split())
    return bool(phrase_tokens) and phrase_tokens.issubset(text_tokens)


def _is_excluded(record: CTARecord, text_norm: str, text_tokens: set[str]) -> bool:
    for phrase in record.exclusion_conditions + record.do_not_trigger_examples:
        if _phrase_in_text(_normalize(phrase), text_norm, text_tokens):
            return True
    return False


_ALIAS_WEIGHT = 3
_TRIGGER_WEIGHT = 2
_TOPIC_WEIGHT = 1


@dataclass
class _Hit:
    score: int
    tier: Literal["alias", "trigger", "topic"]
    matched_phrase: str


def _best_hit(
    phrases: list[str], tier: str, weight: int, text_norm: str, text_tokens: set[str]
) -> Optional[_Hit]:
    for phrase in phrases:
        if _phrase_in_text(_normalize(phrase), text_norm, text_tokens):
            return _Hit(score=weight, tier=tier, matched_phrase=phrase)
    return None


def _score_candidate(
    record: CTARecord, text_norm: str, text_tokens: set[str]
) -> Optional[_Hit]:
    """None means "not a candidate at all" -- either excluded, or it matched
    nothing. Aliases outrank trigger examples outrank related topics: aliases
    are short canonical names least likely to false-positive, trigger examples
    are full example questions, related topics are single generic words (e.g.
    "Development", "Learning") that are deliberately the weakest signal so they
    can never alone promote a specific CTA over a more literally-matched one."""
    if _is_excluded(record, text_norm, text_tokens):
        return None
    return (
        _best_hit(record.aliases, "alias", _ALIAS_WEIGHT, text_norm, text_tokens)
        or _best_hit(record.trigger_examples, "trigger", _TRIGGER_WEIGHT, text_norm, text_tokens)
        or _best_hit(record.related_topics, "topic", _TOPIC_WEIGHT, text_norm, text_tokens)
    )


def _general_cta_for_category(
    category: str, candidates: list[CTARecord]
) -> Optional[CTARecord]:
    """The category's fallback CTA: its `Library`-typed record if one exists,
    else its sole CTA if the category has exactly one. A category with two-plus
    CTAs and no `Library` type has no defined fallback -- this returns None
    rather than guessing, consistent with the loader's never-guess posture."""
    in_category = [c for c in candidates if c.category == category]
    libraries = [c for c in in_category if c.cta_type == "Library"]
    if libraries:
        return libraries[0]
    if len(in_category) == 1:
        return in_category[0]
    return None


INTENT_CATEGORY_AFFINITY: dict[str, str] = {
    "therapy_information": "Therapy",
    "course_information": "Courses",
    "personal_concern": "Condition",
    "emotional_support": "Condition",
}
# concept_explanation, research_information, website_information, and
# general_chat carry no affinity entry -- they are resolved purely by
# phrase-match score, never by a forced category guess.


def _resolve_winner(
    scored: list[tuple[CTARecord, _Hit]], intent: str
) -> tuple[CTARecord, _Hit]:
    by_category: dict[str, list[tuple[CTARecord, _Hit]]] = defaultdict(list)
    for record, hit in scored:
        by_category[record.category].append((record, hit))

    if len(by_category) > 1:
        affinity_category = INTENT_CATEGORY_AFFINITY.get(intent)

        def category_key(category: str) -> tuple[int, str]:
            best = max(hit.score for _, hit in by_category[category])
            bonus = 1 if category == affinity_category else 0
            return (best + bonus, category)

        ranked = sorted(by_category, key=category_key, reverse=True)
        if len(ranked) > 1 and category_key(ranked[0])[0] == category_key(ranked[1])[0]:
            logger.warning(
                "cta_service: category tie broken deterministically intent=%s categories=%s",
                intent, ranked,
            )
        category_items = by_category[ranked[0]]
    else:
        category_items = next(iter(by_category.values()))

    specific = [(r, h) for r, h in category_items if r.cta_type != "Library"]
    pool = specific or category_items
    pool.sort(key=lambda rh: (-rh[1].score, rh[0].cta_id))
    if len(pool) > 1 and pool[0][1].score == pool[1][1].score:
        logger.warning(
            "cta_service: multiple CTAs matched with equal score, tie broken by cta_id: %s",
            [r.cta_id for r, _ in pool],
        )
    return pool[0]


@dataclass
class CTAMatch:
    cta: CTARecord
    match_reason: Literal["specific_match", "category_fallback"]
    matched_phrase: Optional[str]


# Centralized greeting/small-talk guard (spec: greetings must never reach CTA
# scoring). Lives here -- not in any CTA markdown file -- because it is a
# property of the *message*, not of any individual CTA's match rule, and the
# Understanding Node's intent taxonomy has no greeting/small-talk/
# acknowledgement category to key off of (its only catch-all, "general_chat",
# is too broad: plenty of genuine general_chat messages still deserve a CTA).
_RAW_GREETING_PHRASES = [
    "good morning", "good afternoon", "good evening",
    "how are you", "how is it going", "how's it going", "what's up", "whats up",
    "thanks", "thank you", "thanks a lot", "thank you so much", "many thanks",
    "ok", "okay", "kk", "cool", "nice", "great", "awesome",
    "bye", "goodbye", "good bye", "see you", "see ya", "see you later", "take care",
]
_GREETING_PHRASES = {_normalize(p) for p in _RAW_GREETING_PHRASES}

# Elongated/typo'd greeting interjections ("hy", "hii", "heyy", "yooo", ...)
# are matched by pattern instead of being enumerated.
_GREETING_PATTERNS = (
    re.compile(r"^h+i+$"),  # hi, hii, hiii, hiiii
    re.compile(r"^h+e*y+$"),  # hy, hey, heyy (e* also covers the "hy" typo)
    re.compile(r"^h+e+l+o+$"),  # hello, helloo
    re.compile(r"^y+o+$"),  # yo, yoo
)


def _is_greeting_or_small_talk(user_message: str) -> bool:
    """True for greetings, small talk, and acknowledgements ("hi", "thanks",
    "bye", a bare emoji, ...) that must never carry a CTA regardless of what
    they'd otherwise score against. Normalizes the same way candidate phrases
    do, so a message with no a-z0-9 characters at all (pure emoji/punctuation,
    e.g. "\U0001F44B") normalizes to "" and is treated as small talk too --
    there are no words in it for any CTA to legitimately match."""
    text_norm = _normalize(user_message)
    if not text_norm:
        return True
    if text_norm in _GREETING_PHRASES:
        return True
    return any(pattern.match(text_norm) for pattern in _GREETING_PATTERNS)


def find_cta(
    user_message: str, understanding: dict, candidates: list[CTARecord]
) -> Optional[CTAMatch]:
    """Pure, deterministic, LLM-free matching: scores every Active CTARecord
    against the user's message and topic, resolves category and
    specific-vs-general ties, and falls back to an intent-driven category CTA
    when nothing scores at all. Never raises; a missing match is `None`, not
    an exception. Greetings and small talk short-circuit to `None` before any
    candidate is scored -- see `_is_greeting_or_small_talk`."""
    if _is_greeting_or_small_talk(user_message):
        return None

    search_text = f"{user_message} {understanding.get('topic', '')}"
    text_norm = _normalize(search_text)
    text_tokens = set(text_norm.split())

    scored = [
        (record, hit)
        for record in candidates
        if (hit := _score_candidate(record, text_norm, text_tokens)) is not None
    ]
    if scored:
        winner, hit = _resolve_winner(scored, understanding.get("intent", ""))
        return CTAMatch(cta=winner, match_reason="specific_match", matched_phrase=hit.matched_phrase)

    intent = understanding.get("intent", "")
    fallback_category = INTENT_CATEGORY_AFFINITY.get(intent)
    if fallback_category:
        fallback_cta = _general_cta_for_category(fallback_category, candidates)
        if fallback_cta is not None and not _is_excluded(fallback_cta, text_norm, text_tokens):
            return CTAMatch(cta=fallback_cta, match_reason="category_fallback", matched_phrase=None)

    return None


def build_cta_response(safe_response: str, match: Optional[CTAMatch]) -> dict:
    """The single, code-only place the minimal external CTA contract is built --
    `{response, cta_found, cta}` -- for any future consumer (final pipeline
    formatter, a public API response) that wants the trimmed shape rather than
    the full audit-rich CTAOutput. Never mutates `safe_response`."""
    if match is None:
        return {"response": safe_response, "cta_found": False, "cta": None}
    return {
        "response": safe_response,
        "cta_found": True,
        "cta": {
            "url": match.cta.cta_url,
            "trigger": match.cta.output_label,
            "category": match.cta.category,
        },
    }


def process(user_message: str, understanding: dict, safe_response: str) -> dict:
    """Top-level orchestration the CTA Node calls: pulls the Active candidate
    pool from the loader, finds at most one match, and returns a dict shaped
    exactly like `CTAOutput` (minus `lookup_time_ms`/`error`, which the node
    layer adds, mirroring `safety_service.validate_response` /
    `empathy_service.humanize_response`)."""
    candidates = get_ctas_by_status("Active")
    if not candidates:
        logger.warning("cta_service: zero active CTAs available from loader")
        match = None
    else:
        match = find_cta(user_message, understanding, candidates)

    if match is None:
        return {
            "cta_found": False,
            "cta_id": None,
            "cta_url": None,
            "cta_trigger": None,
            "cta_category": None,
            "match_reason": "no_match",
            "matched_phrase": None,
            "response": safe_response,
        }
    return {
        "cta_found": True,
        "cta_id": match.cta.cta_id,
        "cta_url": match.cta.cta_url,
        "cta_trigger": match.cta.output_label,
        "cta_category": match.cta.category,
        "match_reason": match.match_reason,
        "matched_phrase": match.matched_phrase,
        "response": safe_response,
    }
