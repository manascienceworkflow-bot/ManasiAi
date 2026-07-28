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

# Structure for a turn where the Knowledge Node resolved a concern file. The five beats
# are MANASI_ANSWER_PLAYBOOK.md Part 2's Explain shape; the section->beat mapping is spec
# Section 7.6. This prompt references that structure rather than re-specifying tone or
# format, which stay with the playbook and the Empathy Node.
CONCERN_STRUCTURE_INSTRUCTIONS = (
    "Structured knowledge about this exact concern was found (see CONCERN KNOWLEDGE "
    "below). Build the body of your answer from it, as flowing prose, in this order:\n"
    "1. Normalise without dismissing — draw on Summary and Common Misunderstandings.\n"
    "2. Give two to four plausible, non-diagnostic reasons — draw on Possible "
    "Explanations. Select the ones that best fit what the user actually described.\n"
    "3. Apply the ManaScience lens — draw on ManaScience Perspective and Neuroplasticity "
    "Explanation, naming the developmental areas involved.\n"
    "4. State the boundary — draw on Professional Boundary. This element is never "
    "optional, and its wording is approved: reproduce it as written rather than "
    "rephrasing it.\n"
    "5. Point to a next step — draw on Things to Observe, Everyday Support Ideas, and "
    "When Professional Evaluation May Help.\n\n"
    "Hard rules for this material:\n"
    "- Keep every qualifier exactly as written. 'some children' stays 'some children'; "
    "'may help' stays 'may help'. Removing a hedge turns an explanation into a diagnosis.\n"
    "- Never state or imply that the child has any condition, and never rule one out.\n"
    "- Name only the therapies or approaches that appear in the material, and only as "
    "areas to understand — never as a recommendation for this child.\n"
    "- Do not output section headings, labels, or bullet-point dumps of a section. The "
    "sections are raw material; the answer is prose.\n"
    "- Do not add an opening acknowledgement, a supportive closing line, or an invitation "
    "to continue. Those are added later by a different system."
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


# Section key -> the label the model sees. Ordered as in the concern schema so the
# rendered block reads top-to-bottom like the source file.
CONCERN_SECTION_LABELS = [
    ("summary", "Summary"),
    ("possible_explanations", "Possible Explanations"),
    ("things_to_observe", "Things to Observe"),
    ("everyday_support_ideas", "Everyday Support Ideas"),
    ("manascience_perspective", "ManaScience Perspective"),
    ("neuroplasticity_explanation", "Neuroplasticity Explanation"),
    ("professional_boundary", "Professional Boundary"),
    ("when_professional_evaluation_may_help", "When Professional Evaluation May Help"),
    ("common_misunderstandings", "Common Misunderstandings"),
    ("what_this_concern_is_not", "What This Concern Is Not"),
    ("age_specific_notes", "Age-Specific Notes"),
    ("cultural_and_multilingual_notes", "Cultural and Multilingual Notes"),
]

NO_CONCERN_KNOWLEDGE = "(No specific concern was resolved for this question.)"


def _format_concern_knowledge(resolved_concern: Optional[dict]) -> str:
    """Render the resolved concern record as labelled sections for the prompt."""
    if not resolved_concern:
        return NO_CONCERN_KNOWLEDGE

    lines = [f"CONCERN: {resolved_concern['title']} ({resolved_concern['concern_id']})"]
    domains = resolved_concern.get("development_domains") or []
    if domains:
        lines.append(f"Developmental areas: {', '.join(domains)}")
    lines.append("")

    summary = (resolved_concern.get("summary") or "").strip()
    sections = resolved_concern.get("sections") or {}
    for key, label in CONCERN_SECTION_LABELS:
        if key == "summary":
            if summary:
                lines.extend([label + ":", summary, ""])
            continue
        bullets = sections.get(key) or []
        if not bullets:
            continue
        lines.append(label + ":")
        lines.extend(f"- {bullet}" for bullet in bullets)
        lines.append("")

    for related in resolved_concern.get("related_concerns") or []:
        lines.append(
            f"Related concern ({related['relation']}) — {related['title']}: {related['summary']}"
        )
    return "\n".join(lines).strip()


def _format_retrieved_context(retrieved_docs: list[dict], resolved_concern: Optional[dict] = None) -> str:
    """Render supporting chunks. Chunks belonging to the resolved concern are omitted --
    the structured record above already carries that material in full, and sending both
    wastes context and invites the model to quote the fragment instead of explaining it."""
    concern_id = (resolved_concern or {}).get("concern_id")
    docs = [
        doc for doc in retrieved_docs
        if not (concern_id and (doc.get("metadata") or {}).get("concern_id") == concern_id)
    ]
    if not docs:
        if resolved_concern:
            return "(No additional reference material beyond the concern knowledge above.)"
        return "(No ManaScience content was retrieved for this question. Answer using general knowledge.)"
    blocks = [
        f"[{i}] ({doc['content_type']} — {doc['source_title']})\n{doc['content']}"
        for i, doc in enumerate(docs, start=1)
    ]
    return "\n\n".join(blocks)


def _select_structure_instructions(understanding: dict, resolved_concern: Optional[dict]) -> str:
    if resolved_concern:
        return CONCERN_STRUCTURE_INSTRUCTIONS
    if understanding["intent"] == "concept_explanation":
        return CONCEPT_STRUCTURE_INSTRUCTIONS
    return DIRECT_STRUCTURE_INSTRUCTIONS


def _build_prompt(understanding: dict, knowledge: dict, user_message: str, extra_suffix: str = "") -> str:
    knowledge_instructions = RAG_INSTRUCTIONS if knowledge["source"] == "rag" else LLM_INSTRUCTIONS
    resolved_concern = knowledge.get("resolved_concern")
    structure_instructions = _select_structure_instructions(understanding, resolved_concern)
    prompt = (
        _PROMPT_TEMPLATE.replace("{{knowledge_instructions}}", knowledge_instructions)
        .replace("{{structure_instructions}}", structure_instructions)
        .replace("{{intent}}", understanding["intent"])
        .replace("{{topic}}", understanding["topic"])
        .replace("{{concern_knowledge}}", _format_concern_knowledge(resolved_concern))
        .replace(
            "{{retrieved_context}}",
            _format_retrieved_context(knowledge["retrieved_docs"], resolved_concern),
        )
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


def _boundary_exempt_shingles(resolved_concern: Optional[dict], n: int) -> set[str]:
    """Shingles the copy-detector must ignore.

    The Professional Boundary bullets carry MANASI_ANSWER_PLAYBOOK.md Part 4's approved
    phrasings, which the answer is *required* to reproduce as written (spec V-47). Without
    this exemption the copy guard would penalise exactly the behaviour the playbook
    mandates. Scoped to that one section: every other chunk stays under the full check.
    """
    if not resolved_concern:
        return set()
    bullets = (resolved_concern.get("sections") or {}).get("professional_boundary") or []
    exempt: set[str] = set()
    for bullet in bullets:
        exempt |= _shingles(bullet, n)
    return exempt


def _is_document_dump(
    answer: str, retrieved_docs: list[dict], resolved_concern: Optional[dict] = None
) -> bool:
    if not retrieved_docs:
        return False
    n = settings.response_document_dump_shingle_words
    answer_shingles = _shingles(answer, n) - _boundary_exempt_shingles(resolved_concern, n)
    if not answer_shingles:
        return False
    return any(_shingles(doc["content"], n) & answer_shingles for doc in retrieved_docs)


def _contains_banned_phrase(answer: str) -> bool:
    lowered = answer.lower()
    return any(phrase in lowered for phrase in BANNED_PHRASES)


def _is_too_short(answer: str) -> bool:
    return len(answer.strip()) < settings.response_min_answer_length


def _count_violations(
    answer: str, retrieved_docs: list[dict], resolved_concern: Optional[dict] = None
) -> int:
    return (
        int(_is_too_short(answer))
        + int(_contains_banned_phrase(answer))
        + int(_is_document_dump(answer, retrieved_docs, resolved_concern))
    )


def _corrective_suffix_for(
    answer: str, retrieved_docs: list[dict], resolved_concern: Optional[dict] = None
) -> str:
    suffixes = []
    if _is_too_short(answer):
        suffixes.append(CORRECTIVE_REPROMPT_SUFFIX_TOO_SHORT)
    if _contains_banned_phrase(answer):
        suffixes.append(CORRECTIVE_REPROMPT_SUFFIX_BANNED_PHRASE)
    if _is_document_dump(answer, retrieved_docs, resolved_concern):
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

        resolved_concern = knowledge.get("resolved_concern")
        violations = _count_violations(answer, knowledge["retrieved_docs"], resolved_concern)
        attempts.append(_Attempt(answer=answer, violation_count=violations))
        if violations == 0:
            break
        extra_suffix = _corrective_suffix_for(answer, knowledge["retrieved_docs"], resolved_concern)

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
