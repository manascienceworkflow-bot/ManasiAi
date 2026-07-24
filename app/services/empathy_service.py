import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger("app.services.empathy_service")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "empathy_prompt.txt"
_PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")

EMPATHY_BANNED_PHRASES = [
    "as a doctor", "as your doctor", "as a therapist", "as your therapist",
    "as a nurse", "as your nurse", "as a healthcare professional",
    "i am a doctor", "i'm a doctor", "i am a therapist", "i'm a therapist",
    "i am a nurse", "i'm a nurse", "i am human", "i'm human", "as a human",
    "i have feelings", "i feel your pain", "my feelings", "i can diagnose",
    "i diagnose", "my own experience as a parent", "speaking as someone who",
]

EMOTIONAL_TONE_INSTRUCTIONS = {
    "neutral": (
        "The user's tone is neutral. Keep the Acknowledge brief and pleasant -- "
        "don't over-validate a question with no emotional charge. Explain plainly. "
        "Keep Support to one light, affirming line. Use a standard Invite."
    ),
    "curious": (
        "The user sounds curious and engaged. Acknowledge with genuine enthusiasm "
        "('That's a great question,' 'I'm glad you brought that up'). Frame the "
        "Explain as something you're exploring together. Affirm the curiosity "
        "itself in Support. Invite them to go deeper or ask for an example."
    ),
    "confused": (
        "The user sounds confused or unsure. Acknowledge by normalizing the "
        "confusion -- it's a completely fair thing to find unclear. Break the "
        "Explain into smaller, very concrete steps with simple comparisons, "
        "avoiding abstraction. In Support, reassure them that needing a "
        "different explanation is normal. Invite them toward a simpler example "
        "or a different angle, explicitly."
    ),
    "worried": (
        "The user sounds worried or concerned. Acknowledge with genuine "
        "gratitude and validation ('Thank you for sharing that,' 'I can "
        "understand why that might feel concerning'). Keep the Explain calm and "
        "steady -- no alarming language, but no minimizing the concern either. "
        "In Support, make clear the concern is heard and shared ('Let's look at "
        "this together,' 'many families have asked this'). Invite continued "
        "support, not just more information."
    ),
    "overwhelmed": (
        "The user sounds overwhelmed. Acknowledge by naming the load directly "
        "('This can feel like a lot of information at first'). Sequence the "
        "Explain into clearly separated, small steps. In Support, reassure them "
        "about pacing ('we can go at whatever pace feels comfortable'). Invite "
        "them to take it one step at a time, explicitly low-pressure."
    ),
    "frustrated": (
        "The user sounds frustrated. Acknowledge by validating the frustration "
        "without sounding defensive ('I hear that this has been frustrating'). "
        "Make the Explain extra clear with no hedging that could read as "
        "evasive. In Support, frame it as working through this together, one "
        "piece at a time. Invite them to say what specifically hasn't helped "
        "yet, or offer to explain it differently."
    ),
}

CORRECTIVE_REPROMPT_SUFFIX_IDENTITY = (
    "\n\nYour previous answer claimed Manasi has emotions, is human, or is a "
    "healthcare professional (doctor/therapist/nurse). Rewrite it -- Manasi is an "
    "AI guide, never any of those things. Try again."
)

CORRECTIVE_REPROMPT_SUFFIX_TOO_SHORT = (
    "\n\nYour previous answer dropped information from the original answer while "
    "adding warmth. Rewrite it so it keeps all the same facts and detail, just "
    "delivered more warmly. Try again."
)

CORRECTIVE_REPROMPT_SUFFIX_TOO_LONG = (
    "\n\nYour previous answer added too much extra wording around the actual "
    "information. Keep the warmth, but tighten it up -- don't pad it. Try again."
)

CORRECTIVE_REPROMPT_SUFFIX_FACT_DROP = (
    "\n\nYour previous answer lost a specific fact, number, or name that was in "
    "the original answer. Rewrite it so every specific detail from the original "
    "answer is still present, just delivered more warmly. Try again."
)

CORRECTIVE_REPROMPT_SUFFIX_MALFORMED = (
    "\n\nYour previous output was not valid JSON matching the required schema. Return "
    'ONLY a valid JSON object with a single "final_answer" field.'
)


@dataclass
class _Attempt:
    final_answer: str
    violation_count: int


def _significant_tokens(text: str) -> set[str]:
    """Numbers/percentages and capitalized multi-letter words, lowercased for
    comparison. A deliberately coarse proxy for 'load-bearing facts' -- precise
    semantic fact-checking is out of scope for a mechanical guard."""
    numbers = re.findall(r"\d+(?:\.\d+)?%?", text)
    # Exclude ordinary sentence-initial capitalization after ". "/"? "/"! " or a
    # paragraph-break newline (LLM prose uses "\n" between paragraphs, not just
    # ". "). Mirrors hallucination_validator; without the fuller exclusion, words
    # that merely start a sentence are miscounted as load-bearing facts.
    proper_nouns = re.findall(
        r"(?<!^)(?<!\. )(?<!\.\n)(?<!\? )(?<!\?\n)(?<!\! )(?<!\!\n)(?<!\n)"
        r"\b[A-Z][a-zA-Z]{3,}\b",
        text,
    )
    return {tok.lower() for tok in numbers + proper_nouns}


def _fact_retention_ratio(answer: str, final_answer: str) -> float:
    original_tokens = _significant_tokens(answer)
    if not original_tokens:
        return 1.0
    retained = original_tokens & _significant_tokens(final_answer)
    return len(retained) / len(original_tokens)


def _fails_fact_retention(answer: str, final_answer: str) -> bool:
    return _fact_retention_ratio(answer, final_answer) < settings.empathy_fact_retention_min_ratio


def _word_count(text: str) -> int:
    return len(text.split())


def _length_ratio(answer: str, final_answer: str) -> float:
    original_words = _word_count(answer)
    if original_words == 0:
        return 1.0
    return _word_count(final_answer) / original_words


def _fails_length_bounds(answer: str, final_answer: str) -> bool:
    ratio = _length_ratio(answer, final_answer)
    return ratio < settings.empathy_min_length_ratio or ratio > settings.empathy_max_length_ratio


def _fails_identity_violation(final_answer: str) -> bool:
    lowered = final_answer.lower()
    return any(phrase in lowered for phrase in EMPATHY_BANNED_PHRASES)


def _count_violations(answer: str, final_answer: str) -> int:
    return (
        int(_fails_identity_violation(final_answer))
        + int(_fails_length_bounds(answer, final_answer))
        + int(_fails_fact_retention(answer, final_answer))
    )


def _corrective_suffix_for(answer: str, final_answer: str) -> str:
    suffixes = []
    if _fails_identity_violation(final_answer):
        suffixes.append(CORRECTIVE_REPROMPT_SUFFIX_IDENTITY)
    ratio = _length_ratio(answer, final_answer)
    if ratio < settings.empathy_min_length_ratio:
        suffixes.append(CORRECTIVE_REPROMPT_SUFFIX_TOO_SHORT)
    elif ratio > settings.empathy_max_length_ratio:
        suffixes.append(CORRECTIVE_REPROMPT_SUFFIX_TOO_LONG)
    if _fails_fact_retention(answer, final_answer):
        suffixes.append(CORRECTIVE_REPROMPT_SUFFIX_FACT_DROP)
    return "".join(suffixes)


def _build_prompt(answer: str, emotional_state: str, extra_suffix: str = "") -> str:
    tone_instructions = EMOTIONAL_TONE_INSTRUCTIONS.get(
        emotional_state, EMOTIONAL_TONE_INSTRUCTIONS["neutral"]
    )
    prompt = (
        _PROMPT_TEMPLATE.replace("{{emotional_state}}", emotional_state)
        .replace("{{emotional_tone_instructions}}", tone_instructions)
        .replace("{{answer}}", answer.strip())
    )
    return prompt + extra_suffix


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_final_answer(raw_text: str) -> str:
    cleaned = _strip_code_fences(raw_text)
    parsed = json.loads(cleaned)
    final_answer = parsed["final_answer"]
    if not isinstance(final_answer, str) or not final_answer.strip():
        raise ValueError("final_answer field missing, empty, or not a string")
    return final_answer


def _select_fallback(answer: str, llm_call_failed: bool) -> tuple[str, str]:
    """Returns (final_answer, error_code). Never raises. Never empty. Always at
    least as informative as the input answer, because it *is* the input answer."""
    error_code = "llm_call_failure" if llm_call_failed else "quality_guard_exhausted"
    return answer, error_code


def _build_llm():
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=settings.empathy_model, temperature=settings.empathy_temperature)


def _invoke(llm: Any, prompt: str) -> str:
    response = llm.invoke(prompt)
    return response.content if hasattr(response, "content") else str(response)


def humanize_response(
    response: dict, emotional_state: str, llm: Optional[Any] = None
) -> dict:
    """Rewrite response['answer'] into a warm, structured final_answer for the given
    emotional_state.

    Never raises -- always returns a complete dict matching the Empathy schema
    (Section 9.2), minus `humanization_time_ms`, which the calling node times itself.
    """
    answer = response["answer"]
    llm = llm or _build_llm()
    attempts: list[_Attempt] = []
    extra_suffix = ""
    max_attempts = 1 + settings.empathy_max_retries

    for attempt_index in range(max_attempts):
        prompt = _build_prompt(answer, emotional_state, extra_suffix=extra_suffix)
        try:
            final_answer = _parse_final_answer(_invoke(llm, prompt))
        except Exception as exc:
            logger.warning(
                "empathy_service attempt %d produced no usable final_answer: %s", attempt_index, exc
            )
            extra_suffix = CORRECTIVE_REPROMPT_SUFFIX_MALFORMED
            continue

        violations = _count_violations(answer, final_answer)
        attempts.append(_Attempt(final_answer=final_answer, violation_count=violations))
        if violations == 0:
            break
        extra_suffix = _corrective_suffix_for(answer, final_answer)

    clean_attempt = next((a for a in attempts if a.violation_count == 0), None)
    if clean_attempt is not None:
        final_answer, error = clean_attempt.final_answer, None
    else:
        final_answer, error = _select_fallback(answer, llm_call_failed=not attempts)

    return {
        "final_answer": final_answer,
        "emotional_state": emotional_state,
        "source": response["source"],
        "answer_type": response["answer_type"],
        "topic": response["topic"],
        "intent": response["intent"],
        "confidence": response["confidence"],
        "grounded_chunk_ids": response["grounded_chunk_ids"],
        "error": error,
    }
