import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.services.empathy_service import EMPATHY_BANNED_PHRASES
from app.validators.boundary_validator import (
    BOUNDARY_REDIRECT_TEMPLATE,
    fails_domain_boundary,
    has_supported_domain_content,
)
from app.validators.hallucination_validator import (
    HALLUCINATION_HONEST_FALLBACK_PHRASES,
    flagged_entities,
)
from app.validators.medical_validator import (
    MEDICAL_SAFE_REDIRECT_PHRASES,
    fails_medical_safety,
)

logger = logging.getLogger("app.services.safety_service")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "safety_prompt.txt"
_PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")

CRISIS_KEYWORDS_HIGH = [
    "kill myself", "killing myself", "want to die", "wants to die",
    "wish i was dead", "wish i were dead", "end my life", "ending my life",
    "ending it all", "suicide", "suicidal", "hurt myself", "hurting myself",
    "harm myself", "self-harm", "self harm", "cutting myself",
    "no reason to live", "better off dead", "don't want to be here",
    "don't want to live anymore", "can't go on", "take my own life",
    # Third-person variants -- a parent or caregiver relaying someone else's
    # (often a child's) crisis disclosure must trigger escalation just as
    # reliably as first-person language (Section 9.4's child-template path).
    "kill herself", "kill himself", "kill themselves",
    "hurt herself", "hurt himself", "hurt themselves",
    "harm herself", "harm himself", "harm themselves",
]

SEVERE_DISTRESS_KEYWORDS_MODERATE = [
    "i can't take this anymore", "i have nothing left", "there's no way out",
    "i'm completely hopeless", "everything feels pointless", "i give up entirely",
]

CHILD_REFERENCE_PHRASES = [
    "my son", "my daughter", "my child", "my kid",
    "she wants to", "he wants to", "she said", "he said",
]

CRISIS_RESPONSE_TEMPLATE_HIGH = (
    "I'm really glad you told me this, and I don't want you to go through it "
    "alone. I'm an AI guide, and I'm not able to keep you safe in a moment "
    "like this -- but immediate, real support is available right now. If "
    "you're in the US, you can call or text 988 (the Suicide & Crisis "
    "Lifeline) any time, day or night. If you're outside the US, please "
    "contact your local emergency number or a crisis line where you are. If "
    "you're in immediate danger, please call your local emergency services "
    "right now. I'm here when you're ready to keep talking, and I care about "
    "how you're doing."
)

CRISIS_RESPONSE_TEMPLATE_CHILD = (
    "Thank you for telling me this -- it matters, and you're right to take "
    "it seriously. I'm an AI guide, and a situation like this needs immediate "
    "support from people who can actually help keep your child safe. Please "
    "contact your child's doctor, a children's crisis line, or your local "
    "emergency services right now, and try not to leave your child alone in "
    "the meantime. I know how frightening this is, and I'm here to keep "
    "talking with you once you've reached out for that help."
)

CERTAINTY_OVERCLAIM_PHRASES = [
    "this will definitely", "this will always", "guaranteed to work",
    "guaranteed results", "always works", "never fails", "100% effective",
    "completely cures", "will cure", "proven to cure", "this always fixes",
    "will fix this", "certain to help", "definitely the cause",
    "definitely caused by", "without a doubt this is",
]

VIOLATION_REVIEW_INSTRUCTIONS = {
    "medical_safety": (
        "The draft below contains language that diagnoses, confirms a "
        "diagnosis, prescribes a treatment, or recommends a medication "
        "change. Rewrite it to remove that specific claim, replacing it with "
        "one of the approved alternative phrasings provided, while leaving "
        "everything else -- tone, structure, unrelated facts -- unchanged."
    ),
    "domain_boundary": (
        "The draft below answers a question outside ManaScience's "
        "supported topics. If the ENTIRE draft is off-domain, replace it "
        "with a warm redirect to what Manasi can help with instead. If only "
        "PART of the draft is off-domain, keep the in-domain portion intact "
        "and replace only the off-domain portion with a brief, warm redirect."
    ),
    "hallucination_risk": (
        "The draft below names a specific therapy, practitioner, "
        "ManaScience program, or research finding that could not be "
        "verified against this turn's source material. Rewrite it to "
        "remove or soften that specific claim into an honest statement of "
        "what is and isn't known, without inventing a replacement claim."
    ),
    "trust_overclaim": (
        "The draft below states something with more certainty than is "
        "warranted -- an absolute guarantee, an unqualified 'this will "
        "work,' or similar. Rewrite that specific phrase into a properly "
        "scoped statement (e.g. 'many children show improvement' instead of "
        "'this will fix it'), without changing anything else."
    ),
    "identity_violation": (
        "The draft below implies Manasi has emotions, is human, or is a "
        "doctor/therapist/nurse. Rewrite it so Manasi remains clearly an AI "
        "guide, without removing the warmth of the surrounding sentence."
    ),
}

GENERIC_HOLISTIC_REVIEW_INSTRUCTIONS = (
    "No specific issue was flagged mechanically -- review the draft for "
    "accuracy and trust-calibration concerns per the six-point pipeline "
    "above. If it's genuinely fine as-is, return it unchanged with "
    "\"is_clean\": true."
)

GROUNDING_CONTEXT_EMPTY_PLACEHOLDER = (
    "(No retrieval grounding exists for this turn. Treat every named "
    "therapy, practitioner, program, or research finding as unconfirmed.)"
)

CORRECTIVE_REPROMPT_SUFFIX_MALFORMED = (
    "\n\nYour previous output was not valid JSON matching the required "
    'schema. Return ONLY a valid JSON object with "is_clean" and '
    '"safe_response" fields.'
)


@dataclass
class _Attempt:
    safe_response: str
    is_clean: bool
    violations: list[str]


def detect_crisis(user_message: str) -> str:
    """Returns 'high', 'moderate', or 'none'."""
    lowered = user_message.lower()
    if any(kw in lowered for kw in CRISIS_KEYWORDS_HIGH):
        return "high"
    if any(kw in lowered for kw in SEVERE_DISTRESS_KEYWORDS_MODERATE):
        return "moderate"
    return "none"


def _select_crisis_template(user_message: str) -> str:
    lowered = user_message.lower()
    if any(phrase in lowered for phrase in CHILD_REFERENCE_PHRASES):
        return CRISIS_RESPONSE_TEMPLATE_CHILD
    return CRISIS_RESPONSE_TEMPLATE_HIGH


def _fails_certainty_overclaim(final_answer: str) -> bool:
    lowered = final_answer.lower()
    return any(phrase in lowered for phrase in CERTAINTY_OVERCLAIM_PHRASES)


def _fails_identity_violation(final_answer: str) -> bool:
    lowered = final_answer.lower()
    return any(phrase in lowered for phrase in EMPATHY_BANNED_PHRASES)


def _run_guards(
    final_answer: str, topic: str, source: str, retrieved_docs: list[dict]
) -> list[str]:
    """Shared guard-runner, called both on the original final_answer and on
    every rewrite candidate -- this is what makes the LLM's own `is_clean`
    claim non-authoritative; the same function re-validates every candidate."""
    violations = []
    if fails_medical_safety(final_answer):
        violations.append("medical_safety")
    if fails_domain_boundary(final_answer, topic):
        violations.append("domain_boundary")
    if flagged_entities(final_answer, source, retrieved_docs):
        violations.append("hallucination_risk")
    if _fails_certainty_overclaim(final_answer):
        violations.append("trust_overclaim")
    if _fails_identity_violation(final_answer):
        violations.append("identity_violation")
    return violations


def _is_full_domain_violation(final_answer: str, topic: str) -> bool:
    return fails_domain_boundary(final_answer, topic) and not has_supported_domain_content(
        final_answer
    )


def _format_grounding_context(retrieved_docs: list[dict], source: str) -> str:
    if source != "rag" or not retrieved_docs:
        return GROUNDING_CONTEXT_EMPTY_PLACEHOLDER
    joined = " ".join(doc["content"] for doc in retrieved_docs)
    return joined[: settings.knowledge_max_context_chars]


def _violation_instructions_block(violations: list[str]) -> str:
    if not violations:
        return GENERIC_HOLISTIC_REVIEW_INSTRUCTIONS
    return "\n\n".join(VIOLATION_REVIEW_INSTRUCTIONS[v] for v in violations)


def _build_prompt(
    final_answer: str,
    topic: str,
    source: str,
    retrieved_docs: list[dict],
    violations: list[str],
    extra_suffix: str = "",
) -> str:
    prompt = (
        _PROMPT_TEMPLATE.replace(
            "{{grounding_context}}", _format_grounding_context(retrieved_docs, source)
        )
        .replace("{{violation_instructions}}", _violation_instructions_block(violations))
        .replace("{{final_answer}}", final_answer.strip())
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


def _parse_safety_review(raw_text: str) -> tuple[bool, str]:
    cleaned = _strip_code_fences(raw_text)
    parsed = json.loads(cleaned)
    is_clean = parsed["is_clean"]
    safe_response = parsed["safe_response"]
    if not isinstance(is_clean, bool):
        raise ValueError("is_clean field missing or not a boolean")
    if not isinstance(safe_response, str) or not safe_response.strip():
        raise ValueError("safe_response field missing, empty, or not a string")
    return is_clean, safe_response


def _corrective_suffix_for(violations: list[str]) -> str:
    if not violations:
        return ""
    parts = [
        f"\n\nYour previous rewrite still has this problem: {VIOLATION_REVIEW_INSTRUCTIONS[v]}"
        for v in violations
    ]
    return "".join(parts)


def _safe_template_for(violations: list[str]) -> str:
    if "medical_safety" in violations or "identity_violation" in violations:
        return MEDICAL_SAFE_REDIRECT_PHRASES[2]
    if "domain_boundary" in violations:
        return BOUNDARY_REDIRECT_TEMPLATE
    if "hallucination_risk" in violations:
        return HALLUCINATION_HONEST_FALLBACK_PHRASES[1]
    return MEDICAL_SAFE_REDIRECT_PHRASES[2]


def _select_fallback(
    final_answer: str, violations: list[str], llm_call_failed: bool
) -> tuple[str, str, Optional[str]]:
    """Returns (safe_response, safety_status, error_code). Never raises.

    If no deterministic guard confirmed a violation, the only failure was the
    safety-review LLM call itself -- safe to fall back to the original text.

    If a deterministic guard DID confirm a violation, falling back to
    final_answer unchanged would deliver the very thing this node exists to
    block -- so the fallback is a fixed, category-specific safe template
    instead, never the unreviewed input.
    """
    if not violations:
        return final_answer, "approved", ("llm_call_failure" if llm_call_failed else None)
    return _safe_template_for(violations), "modified", "quality_guard_exhausted_safe_fallback"


def _build_llm():
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=settings.safety_model, temperature=settings.safety_temperature)


def _invoke(llm: Any, prompt: str) -> str:
    response = llm.invoke(prompt)
    return response.content if hasattr(response, "content") else str(response)


def validate_response(
    empathy: dict,
    user_message: str,
    retrieved_docs: list[dict],
    llm: Optional[Any] = None,
) -> dict:
    """Review empathy['final_answer'] for medical/domain/hallucination/trust
    violations, and resolve crisis signals from user_message.

    Never raises -- always returns a complete dict matching the Safety schema
    minus `validation_time_ms`, which the calling node times itself.
    """
    final_answer = empathy["final_answer"]
    topic = empathy["topic"]
    source = empathy["source"]

    passthrough = {
        "original_final_answer": final_answer,
        "emotional_state": empathy["emotional_state"],
        "source": source,
        "answer_type": empathy["answer_type"],
        "topic": topic,
        "intent": empathy["intent"],
        "confidence": empathy["confidence"],
        "grounded_chunk_ids": empathy["grounded_chunk_ids"],
    }

    crisis_level = detect_crisis(user_message)
    if crisis_level == "high":
        return {
            "safe_response": _select_crisis_template(user_message),
            "safety_status": "escalated",
            "violations_detected": [],
            "escalation_level": "high",
            "disclaimer_added": False,
            "error": None,
            **passthrough,
        }

    violations = _run_guards(final_answer, topic, source, retrieved_docs)
    needs_moderate_support = crisis_level == "moderate"

    if (
        violations == ["domain_boundary"]
        and _is_full_domain_violation(final_answer, topic)
        and not needs_moderate_support
    ):
        return {
            "safe_response": BOUNDARY_REDIRECT_TEMPLATE,
            "safety_status": "modified",
            "violations_detected": ["domain_boundary"],
            "escalation_level": "none",
            "disclaimer_added": False,
            "error": None,
            **passthrough,
        }

    llm = llm or _build_llm()
    attempts: list[_Attempt] = []
    extra_suffix = ""
    max_attempts = 1 + settings.safety_max_retries

    for attempt_index in range(max_attempts):
        prompt = _build_prompt(
            final_answer, topic, source, retrieved_docs, violations, extra_suffix=extra_suffix
        )
        try:
            is_clean, candidate = _parse_safety_review(_invoke(llm, prompt))
        except Exception as exc:
            logger.warning(
                "safety_service attempt %d produced no usable review: %s", attempt_index, exc
            )
            extra_suffix = CORRECTIVE_REPROMPT_SUFFIX_MALFORMED
            continue

        post_violations = _run_guards(candidate, topic, source, retrieved_docs)
        attempts.append(_Attempt(safe_response=candidate, is_clean=is_clean, violations=post_violations))
        if not post_violations:
            break
        extra_suffix = _corrective_suffix_for(post_violations)

    clean_attempt = next((a for a in attempts if not a.violations), None)
    if clean_attempt is not None:
        safe_response = clean_attempt.safe_response
        if violations or needs_moderate_support:
            safety_status = "modified"
            violations_detected = violations
        elif not clean_attempt.is_clean:
            # Holistic pass (Section 12.2 case 2): no guard fired, but the model
            # itself flagged and fixed something -- label it as the catch-all
            # trust/accuracy category rather than inventing a new enum value.
            safety_status = "modified"
            violations_detected = ["trust_overclaim"]
        else:
            safety_status = "approved"
            violations_detected = []
        error = None
    else:
        safe_response, safety_status, error = _select_fallback(
            final_answer, violations, llm_call_failed=not attempts
        )
        violations_detected = violations

    escalation_level = "moderate" if needs_moderate_support else "none"
    disclaimer_added = needs_moderate_support or any(
        phrase.lower() in safe_response.lower() for phrase in MEDICAL_SAFE_REDIRECT_PHRASES
    )

    return {
        "safe_response": safe_response,
        "safety_status": safety_status,
        "violations_detected": violations_detected,
        "escalation_level": escalation_level,
        "disclaimer_added": disclaimer_added,
        "error": error,
        **passthrough,
    }
