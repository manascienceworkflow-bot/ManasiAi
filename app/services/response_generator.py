import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger("app.services.response_generator")

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "response_prompt.txt"
_PROMPT_TEMPLATE = PROMPT_PATH.read_text(encoding="utf-8")

RAG_INSTRUCTIONS = (
    "ManaScience reference material was found for this question (see CONTEXT below). "
    "Treat it as your primary source: read it, understand it, and explain it in your "
    "own words. Stay faithful to what the material actually says — do not contradict "
    "it, and do not invent ManaScience-specific facts, programs, or claims that are not "
    "supported by the material. You may add general background knowledge to help "
    "explain the material more clearly, as long as you do not contradict it."
)

LLM_INSTRUCTIONS = (
    "No ManaScience reference material was found for this question. Answer using your "
    "own general knowledge instead. Treat the question like any reasonable question a "
    "curious person could ask, and give a genuinely useful, accurate answer. Do not "
    "mention that no ManaScience material was found, and do not apologize for or hedge "
    "the absence of ManaScience-specific content — just answer the question well."
)

CONCEPT_STRUCTURE_INSTRUCTIONS = (
    "This is a concept-explanation question. Structure your answer so that it "
    "naturally contains all four of the following elements, in this order, woven "
    "into clear prose (not labeled headers):\n"
    "1. Definition — state plainly what the thing is.\n"
    "2. Simple Explanation — explain it the way you'd explain it to a curious adult "
    "with no background in the subject.\n"
    "3. Why It Matters — say why this concept is useful or relevant to know.\n"
    "4. Example — give one concrete, relatable example, when an example would "
    "genuinely help understanding."
)

DIRECT_STRUCTURE_INSTRUCTIONS = (
    "This is not a general concept-explanation question. Answer it directly and "
    "proportionately — give the user what they actually asked for without forcing it "
    "into a definition/explanation/example essay format. Add brief helpful context "
    "only if it makes the answer clearer."
)

# Maps Phase 1's `understanding.intent` to this node's `answer_type` (spec Section 6.5).
# Independent of `source` — a concept question keeps answer_type="concept_explanation"
# whether it was grounded in ManaScience content or answered from general knowledge.
ANSWER_TYPE_BY_INTENT = {
    "concept_explanation": "concept_explanation",
    "therapy_information": "therapy_information",
    "course_information": "course_information",
    "research_information": "research_summary",
    "website_information": "website_information",
    "personal_concern": "personal_guidance",
    "emotional_support": "supportive_information",
    "general_chat": "general_knowledge",
}

BANNED_PHRASES = [
    "i don't know", "i do not know", "i'm not sure", "i am not sure",
    "no information found", "no information available", "information unavailable",
    "i'm unable to answer", "i am unable to answer", "unable to answer this",
    "i cannot answer", "i can't answer", "i don't have information",
    "i don't have enough information", "not available in my knowledge base",
    "i have no information",
]

CORRECTIVE_REPROMPT_SUFFIX_TOO_SHORT = (
    "\n\nYour previous answer was too short to be useful. Give a fuller, more complete "
    "answer. Try again."
)

CORRECTIVE_REPROMPT_SUFFIX_BANNED_PHRASE = (
    "\n\nYour previous answer was a refusal or near-refusal. You must answer "
    "substantively — do not say you don't know or that information is unavailable. "
    "Use your general knowledge if needed. Try again."
)

CORRECTIVE_REPROMPT_SUFFIX_DOCUMENT_DUMP = (
    "\n\nYour previous answer copied wording directly from the reference material. "
    "Rewrite the answer completely in your own words — explain the ideas, do not "
    "quote or closely paraphrase the source text. Try again."
)

CORRECTIVE_REPROMPT_SUFFIX_MALFORMED = (
    "\n\nYour previous output was not valid JSON matching the required schema. Return "
    'ONLY a valid JSON object with a single "answer" field.'
)

INFRA_FAILURE_FALLBACK_ANSWER = (
    "I'm having trouble putting together an answer right now — could you ask that "
    "again in a moment?"
)


@dataclass
class _Attempt:
    answer: str
    violation_count: int


def _format_retrieved_context(retrieved_docs: list[dict]) -> str:
    if not retrieved_docs:
        return "(No ManaScience content was retrieved for this question. Answer using general knowledge.)"
    blocks = [
        f"[{i}] ({doc['content_type']} — {doc['source_title']})\n{doc['content']}"
        for i, doc in enumerate(retrieved_docs, start=1)
    ]
    return "\n\n".join(blocks)


def _build_prompt(understanding: dict, knowledge: dict, user_message: str, extra_suffix: str = "") -> str:
    knowledge_instructions = RAG_INSTRUCTIONS if knowledge["source"] == "rag" else LLM_INSTRUCTIONS
    structure_instructions = (
        CONCEPT_STRUCTURE_INSTRUCTIONS
        if understanding["intent"] == "concept_explanation"
        else DIRECT_STRUCTURE_INSTRUCTIONS
    )
    prompt = (
        _PROMPT_TEMPLATE.replace("{{knowledge_instructions}}", knowledge_instructions)
        .replace("{{structure_instructions}}", structure_instructions)
        .replace("{{intent}}", understanding["intent"])
        .replace("{{topic}}", understanding["topic"])
        .replace("{{retrieved_context}}", _format_retrieved_context(knowledge["retrieved_docs"]))
        .replace("{{user_message}}", user_message.strip())
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


def _parse_answer(raw_text: str) -> str:
    cleaned = _strip_code_fences(raw_text)
    parsed = json.loads(cleaned)
    answer = parsed["answer"]
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("answer field missing, empty, or not a string")
    return answer


def _shingles(text: str, n: int) -> set[str]:
    words = text.lower().split()
    if len(words) < n:
        return set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def _is_document_dump(answer: str, retrieved_docs: list[dict]) -> bool:
    if not retrieved_docs:
        return False
    n = settings.response_document_dump_shingle_words
    answer_shingles = _shingles(answer, n)
    if not answer_shingles:
        return False
    return any(_shingles(doc["content"], n) & answer_shingles for doc in retrieved_docs)


def _contains_banned_phrase(answer: str) -> bool:
    lowered = answer.lower()
    return any(phrase in lowered for phrase in BANNED_PHRASES)


def _is_too_short(answer: str) -> bool:
    return len(answer.strip()) < settings.response_min_answer_length


def _count_violations(answer: str, retrieved_docs: list[dict]) -> int:
    return (
        int(_is_too_short(answer))
        + int(_contains_banned_phrase(answer))
        + int(_is_document_dump(answer, retrieved_docs))
    )


def _corrective_suffix_for(answer: str, retrieved_docs: list[dict]) -> str:
    suffixes = []
    if _is_too_short(answer):
        suffixes.append(CORRECTIVE_REPROMPT_SUFFIX_TOO_SHORT)
    if _contains_banned_phrase(answer):
        suffixes.append(CORRECTIVE_REPROMPT_SUFFIX_BANNED_PHRASE)
    if _is_document_dump(answer, retrieved_docs):
        suffixes.append(CORRECTIVE_REPROMPT_SUFFIX_DOCUMENT_DUMP)
    return "".join(suffixes)


def _select_fallback(attempts: list[_Attempt], llm_call_failed: bool) -> tuple[str, str]:
    """Returns (answer, error_code). Never raises. Never empty."""
    if llm_call_failed or not attempts:
        return INFRA_FAILURE_FALLBACK_ANSWER, "llm_call_failure"
    best = min(attempts, key=lambda a: (a.violation_count, -len(a.answer)))
    return best.answer, "quality_guard_exhausted"


def _build_llm():
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=settings.response_model, temperature=settings.response_temperature)


def _invoke(llm: Any, prompt: str) -> str:
    response = llm.invoke(prompt)
    return response.content if hasattr(response, "content") else str(response)


def generate_response(
    understanding: dict, knowledge: dict, user_message: str, llm: Optional[Any] = None
) -> dict:
    """Generate a fresh, simplified answer from understanding + knowledge.

    Never raises -- always returns a complete dict matching the Response schema
    (Section 8), minus `generation_time_ms` which the calling node times itself.
    """
    llm = llm or _build_llm()
    attempts: list[_Attempt] = []
    extra_suffix = ""
    max_attempts = 1 + settings.response_max_retries

    for attempt_index in range(max_attempts):
        prompt = _build_prompt(understanding, knowledge, user_message, extra_suffix=extra_suffix)
        try:
            answer = _parse_answer(_invoke(llm, prompt))
        except Exception as exc:
            logger.warning(
                "response_generator attempt %d produced no usable answer: %s", attempt_index, exc
            )
            extra_suffix = CORRECTIVE_REPROMPT_SUFFIX_MALFORMED
            continue

        violations = _count_violations(answer, knowledge["retrieved_docs"])
        attempts.append(_Attempt(answer=answer, violation_count=violations))
        if violations == 0:
            break
        extra_suffix = _corrective_suffix_for(answer, knowledge["retrieved_docs"])

    clean_attempt = next((a for a in attempts if a.violation_count == 0), None)
    if clean_attempt is not None:
        answer, error = clean_attempt.answer, None
    else:
        answer, error = _select_fallback(attempts, llm_call_failed=not attempts)

    intent = understanding["intent"]
    source = knowledge["source"]
    return {
        "answer": answer,
        "source": source,
        "answer_type": ANSWER_TYPE_BY_INTENT.get(intent, "general_knowledge"),
        "topic": understanding["topic"],
        "intent": intent,
        "confidence": knowledge["confidence"],
        "grounded_chunk_ids": (
            [doc["chunk_id"] for doc in knowledge["retrieved_docs"]] if source == "rag" else []
        ),
        "error": error,
    }
