"""Stage B (concern resolution) in the Knowledge Node, and the Response Generation
changes that consume its output.

Complements tests/test_knowledge_node.py (stage A retrieval) and
tests/test_response_node.py (generation quality guards).
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from langchain_core.documents import Document  # noqa: E402

from app.config import settings  # noqa: E402
from app.knowledge.concern_loader import get_concern_by_id  # noqa: E402
from app.nodes.knowledge_node import knowledge_node  # noqa: E402
from app.services.response_generator import (  # noqa: E402
    CONCEPT_STRUCTURE_INSTRUCTIONS,
    CONCERN_STRUCTURE_INSTRUCTIONS,
    DIRECT_STRUCTURE_INSTRUCTIONS,
    NO_CONCERN_KNOWLEDGE,
    _build_prompt,
    _format_concern_knowledge,
    _format_retrieved_context,
    _is_document_dump,
    _select_structure_instructions,
)


class FakeRetriever:
    def __init__(self, result):
        self.result = result

    def __call__(self, search_query: str, intent: str):
        return self.result


def concern_doc(concern_id="speech_delay", section="matcher", content="Speech Delay — matcher text"):
    return Document(
        page_content=content,
        metadata={
            "chunk_id": f"{concern_id}:{section}",
            "content_type": "concern_knowledge",
            "source_id": f"data/knowledge/concerns/communication/{concern_id}.md",
            "source_title": "Speech Delay",
            "source_url": None,
            "chunk_index": 0,
            "ingested_at": "2026-07-28T00:00:00+00:00",
            "concern_id": concern_id,
            "concern_uid": f"concerns/communication/{concern_id}",
            "category": "communication",
            "topic": "speech delay",
            "section": section,
            "section_rank": 0,
        },
    )


def faq_doc(chunk_id="faq1", content="ManaScience offers a range of therapies."):
    return Document(
        page_content=content,
        metadata={
            "chunk_id": chunk_id,
            "content_type": "faq",
            "source_id": "manascience_faq.md",
            "source_title": "ManaScience FAQ",
            "source_url": None,
            "chunk_index": 0,
            "ingested_at": "2026-07-28T00:00:00+00:00",
        },
    )


def make_state(intent="personal_concern"):
    return {
        "user_message": "my 3 year old is still not talking",
        "chat_history": [],
        "understanding": {
            "intent": intent,
            "topic": "speech delay",
            "search_query": "three year old not talking speech delay",
            "emotional_state": "worried",
        },
        "knowledge": None,
    }


def run_node(scored_chunks, concern_lookup=get_concern_by_id):
    retriever = FakeRetriever((scored_chunks, ["concern_knowledge"]))
    return knowledge_node(make_state(), retriever=retriever, concern_lookup=concern_lookup)["knowledge"]


# ---------------------------------------------------------------------------
# Resolution scoring
# ---------------------------------------------------------------------------


def test_matcher_hit_above_threshold_resolves_the_concern():
    knowledge = run_node([(concern_doc(section="matcher"), 0.60)])
    resolved = knowledge["resolved_concern"]
    assert resolved is not None
    assert resolved["concern_id"] == "speech_delay"
    assert resolved["title"] == "Speech Delay"
    assert resolved["matched_sections"] == ["matcher"]


def test_score_below_threshold_does_not_resolve():
    # 0.36 clears rag_similarity_threshold (0.35) but not concern_resolution_threshold
    # (0.45), even with the matcher bonus -- resolving to the wrong concern is worse
    # than resolving to none.
    knowledge = run_node([(concern_doc(section="summary"), 0.36)])
    assert knowledge["source"] == "rag"
    assert knowledge["resolved_concern"] is None


def test_multi_section_agreement_adds_a_capped_bonus():
    sections = ["summary", "possible_explanations", "things_to_observe", "everyday_support_ideas",
                "manascience_perspective", "professional_boundary"]
    chunks = [(concern_doc(section=section), 0.40) for section in sections]
    resolved = run_node(chunks)["resolved_concern"]
    # 0.40 + capped 0.15 = 0.55, comfortably over threshold; the cap keeps it from
    # climbing indefinitely with section count.
    assert resolved is not None
    assert resolved["score"] == 0.55
    assert len(resolved["matched_sections"]) == len(sections)


def test_matcher_bonus_applies_on_top_of_section_corroboration():
    chunks = [(concern_doc(section="matcher"), 0.42), (concern_doc(section="summary"), 0.42)]
    resolved = run_node(chunks)["resolved_concern"]
    assert resolved["score"] == 0.50  # 0.42 + 0.05 (one extra section) + 0.03 (matcher)


def test_strongest_concern_wins_and_margin_is_reported():
    chunks = [
        (concern_doc(concern_id="speech_delay", section="matcher"), 0.70),
        (concern_doc(concern_id="avoids_eye_contact", section="summary"), 0.50),
    ]
    resolved = run_node(chunks)["resolved_concern"]
    assert resolved["concern_id"] == "speech_delay"
    assert resolved["margin"] > 0


def test_ties_resolve_deterministically_by_concern_id():
    chunks = [
        (concern_doc(concern_id="speech_delay", section="summary"), 0.60),
        (concern_doc(concern_id="avoids_eye_contact", section="summary"), 0.60),
    ]
    first = run_node(chunks)["resolved_concern"]["concern_id"]
    second = run_node(list(reversed(chunks)))["resolved_concern"]["concern_id"]
    assert first == second == "avoids_eye_contact"


def test_dominant_low_scoring_concern_resolves_on_concentration():
    """Colloquial phrasings score low in absolute terms while the correct concern sweeps
    nearly every retrieved chunk. Measured against the live index: 0.24-0.39 with a
    0.83-1.00 share. Concentration is the signal there, not magnitude."""
    chunks = [(concern_doc(section=section), 0.30) for section in
              ["matcher", "summary", "possible_explanations", "everyday_support_ideas", "things_to_observe"]]
    chunks.append((concern_doc(concern_id="daily_tantrums", section="summary"), 0.24))
    resolved = run_node(chunks)["resolved_concern"]
    assert resolved is not None
    assert resolved["concern_id"] == "speech_delay"


def test_spread_across_concerns_does_not_resolve_even_at_higher_scores():
    """The 'what is neuroplasticity?' shape: one Neuroplasticity Explanation chunk from
    every concern at ~0.5. Higher scores than the case above, but nothing dominates -- and
    no single concern is what the question is about."""
    chunks = [
        (concern_doc(concern_id=cid, section="neuroplasticity_explanation"), score)
        for cid, score in [
            ("hyperactivity", 0.44), ("daily_tantrums", 0.43), ("speech_delay", 0.42),
            ("not_responding_to_name", 0.41), ("distressed_by_loud_sounds", 0.40),
            ("avoids_eye_contact", 0.39),
        ]
    ]
    assert run_node(chunks)["resolved_concern"] is None


def test_intent_must_be_declared_by_the_concern_file():
    """Every seed concern declares personal_concern + emotional_support. A concept question
    matches their Neuroplasticity Explanation sections but is not what they are for, so the
    file's own primary_intents decides -- not a hardcoded intent list."""
    chunks = [(concern_doc(section=s), 0.80) for s in ["matcher", "summary", "possible_explanations"]]
    retriever = FakeRetriever((chunks, ["concern_knowledge"]))

    state = make_state(intent="concept_explanation")
    assert knowledge_node(state, retriever=retriever)["knowledge"]["resolved_concern"] is None

    state = make_state(intent="personal_concern")
    assert knowledge_node(state, retriever=retriever)["knowledge"]["resolved_concern"] is not None


def test_resolution_promotes_source_to_rag_when_stage_a_found_nothing_relevant():
    """Stage A's generic 0.35 bar rejects these chunks, but stage B is confident. Content
    written for exactly this question outranks a generic LLM answer."""
    chunks = [(concern_doc(section=s), 0.30) for s in
              ["matcher", "summary", "possible_explanations", "things_to_observe"]]
    knowledge = run_node(chunks)
    assert knowledge["resolved_concern"]["concern_id"] == "speech_delay"
    assert knowledge["source"] == "rag"  # promoted
    assert knowledge["retrieved_docs"], "promotion must supply grounding chunks"
    assert knowledge["confidence"] > 0


def test_non_concern_chunks_are_ignored_by_resolution():
    knowledge = run_node([(faq_doc(), 0.80)])
    assert knowledge["source"] == "rag"
    assert knowledge["resolved_concern"] is None


def test_concern_and_faq_chunks_coexist():
    knowledge = run_node([(concern_doc(section="matcher"), 0.62), (faq_doc(), 0.55)])
    assert knowledge["resolved_concern"]["concern_id"] == "speech_delay"
    assert len(knowledge["retrieved_docs"]) == 2  # supporting chunks are still returned


def test_missing_record_degrades_without_changing_source():
    """A stale vector pointing at a since-deleted file must not break the turn."""
    knowledge = run_node([(concern_doc(section="matcher"), 0.90)], concern_lookup=lambda _id: None)
    assert knowledge["source"] == "rag"
    assert knowledge["resolved_concern"] is None
    assert knowledge["error"] is None


def test_resolution_can_be_disabled_by_configuration(monkeypatch):
    monkeypatch.setattr(settings, "concern_resolution_enabled", False)
    assert run_node([(concern_doc(section="matcher"), 0.90)])["resolved_concern"] is None


def test_general_chat_skips_retrieval_and_reports_no_concern():
    state = make_state(intent="general_chat")
    state["understanding"]["search_query"] = ""
    state["understanding"]["topic"] = ""
    knowledge = knowledge_node(state, retriever=FakeRetriever(([], [])))["knowledge"]
    assert knowledge["retrieval_skipped"] is True
    assert knowledge["resolved_concern"] is None


def test_resolved_record_carries_sections_and_related_concerns():
    resolved = run_node([(concern_doc(section="matcher"), 0.80)])["resolved_concern"]
    assert resolved["sections"]["possible_explanations"]
    assert resolved["sections"]["professional_boundary"]
    assert resolved["summary"].startswith("Speech delay describes")
    assert resolved["development_domains"] == ["speech_language", "communication"]
    assert len(resolved["related_concerns"]) <= settings.concern_max_related
    assert all(item["summary"] for item in resolved["related_concerns"])


# ---------------------------------------------------------------------------
# Response generation
# ---------------------------------------------------------------------------


def resolved_fixture():
    return run_node([(concern_doc(section="matcher"), 0.80)])["resolved_concern"]


def test_concern_structure_instructions_are_selected_when_a_concern_resolves():
    understanding = make_state()["understanding"]
    assert _select_structure_instructions(understanding, resolved_fixture()) is CONCERN_STRUCTURE_INSTRUCTIONS
    assert _select_structure_instructions(understanding, None) is DIRECT_STRUCTURE_INSTRUCTIONS
    concept = dict(understanding, intent="concept_explanation")
    assert _select_structure_instructions(concept, None) is CONCEPT_STRUCTURE_INSTRUCTIONS


def test_formatted_concern_knowledge_carries_labelled_sections():
    rendered = _format_concern_knowledge(resolved_fixture())
    assert "CONCERN: Speech Delay (speech_delay)" in rendered
    assert "Possible Explanations:" in rendered
    assert "Professional Boundary:" in rendered
    assert "Manasi can provide educational information, but cannot diagnose" in rendered
    assert "Related concern (co_occurring)" in rendered


def test_no_resolved_concern_renders_an_explicit_placeholder():
    assert _format_concern_knowledge(None) == NO_CONCERN_KNOWLEDGE


def test_resolved_concerns_own_chunks_are_omitted_from_the_context_block():
    resolved = resolved_fixture()
    docs = [
        {
            "chunk_id": "c1", "content": "Speech Delay — Possible Explanations ...",
            "content_type": "concern_knowledge", "source_title": "Speech Delay",
            "source_url": None, "similarity_score": 0.8, "metadata": {"concern_id": "speech_delay"},
        },
        {
            "chunk_id": "c2", "content": "ManaScience offers a range of therapies.",
            "content_type": "faq", "source_title": "ManaScience FAQ",
            "source_url": None, "similarity_score": 0.5, "metadata": {},
        },
    ]
    rendered = _format_retrieved_context(docs, resolved)
    assert "ManaScience offers a range of therapies." in rendered
    assert "Speech Delay — Possible Explanations" not in rendered


def test_context_block_explains_itself_when_only_concern_chunks_were_retrieved():
    resolved = resolved_fixture()
    docs = [{
        "chunk_id": "c1", "content": "Speech Delay — Summary ...", "content_type": "concern_knowledge",
        "source_title": "Speech Delay", "source_url": None, "similarity_score": 0.8,
        "metadata": {"concern_id": "speech_delay"},
    }]
    assert "No additional reference material" in _format_retrieved_context(docs, resolved)


def test_prompt_contains_both_blocks_and_the_concern_structure():
    resolved = resolved_fixture()
    knowledge = {
        "source": "rag", "retrieved_docs": [], "confidence": 0.8, "query_used": "q",
        "intent": "personal_concern", "retrieval_skipped": False, "content_types_searched": [],
        "retrieval_time_ms": 1.0, "error": None, "resolved_concern": resolved,
    }
    prompt = _build_prompt(make_state()["understanding"], knowledge, "my child is not speaking")
    assert "CONCERN KNOWLEDGE" in prompt
    assert "Possible Explanations:" in prompt
    assert "Keep every qualifier exactly as written" in prompt
    assert "{{concern_knowledge}}" not in prompt
    assert "{{retrieved_context}}" not in prompt


def test_approved_boundary_phrasing_is_exempt_from_the_copy_detector():
    """V-47 requires the boundary sentence verbatim; the copy guard must not punish it."""
    resolved = resolved_fixture()
    boundary = resolved["sections"]["professional_boundary"][1]
    docs = [{
        "chunk_id": "c1", "content": f"Speech Delay — Professional Boundary\n\n- {boundary}",
        "content_type": "concern_knowledge", "source_title": "Speech Delay", "source_url": None,
        "similarity_score": 0.8, "metadata": {"concern_id": "speech_delay"},
    }]
    answer = f"Speech develops on a wide timeline. {boundary} A hearing check is often a useful step."
    assert _is_document_dump(answer, docs, resolved) is False
    # Without the resolved concern, the same text is still treated as copying.
    assert _is_document_dump(answer, docs, None) is True


def test_copying_a_non_boundary_section_is_still_a_dump():
    resolved = resolved_fixture()
    explanation = resolved["sections"]["possible_explanations"][0]
    docs = [{
        "chunk_id": "c1", "content": f"Speech Delay — Possible Explanations\n\n- {explanation}",
        "content_type": "concern_knowledge", "source_title": "Speech Delay", "source_url": None,
        "similarity_score": 0.8, "metadata": {"concern_id": "speech_delay"},
    }]
    assert _is_document_dump(explanation, docs, resolved) is True
