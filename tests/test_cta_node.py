import logging
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.nodes.cta_node import CTAOutput, cta_node  # noqa: E402
from app.services.cta_loader import CTARecord, get_all_ctas, reload_cta_data  # noqa: E402
from app.services.cta_service import (  # noqa: E402
    CTAMatch,
    INTENT_CATEGORY_AFFINITY,
    _is_greeting_or_small_talk,
    build_cta_response,
    find_cta,
    process,
)


def make_cta_record(
    cta_id="therapies/mnri",
    title="MNRI Therapy CTA",
    category="Therapy",
    cta_type="Specific Therapy",
    status="Active",
    aliases=None,
    trigger_examples=None,
    related_topics=None,
    exclusion_conditions=None,
    do_not_trigger_examples=None,
    output_label="Learn More About MNRI",
    cta_url="https://manascience.webflow.io/post/mnri",
    priority="Specific Therapy - MNRI",
    description="Synthetic test CTA.",
    match_rule_raw="Category = Therapy",
    do_not_trigger_raw="N/A",
    fallback_rule="N/A",
):
    return CTARecord(
        cta_id=cta_id,
        title=title,
        source_path=f"{cta_id}.md",
        category_dir=cta_id.split("/")[0],
        status=status,
        category=category,
        cta_type=cta_type,
        priority=priority,
        match_rule_raw=match_rule_raw,
        match_conditions=[],
        exclusion_conditions=exclusion_conditions if exclusion_conditions is not None else [],
        description=description,
        trigger_examples=trigger_examples if trigger_examples is not None else ["placeholder trigger"],
        trigger_groups={},
        aliases=aliases if aliases is not None else [],
        related_topics=related_topics if related_topics is not None else [],
        do_not_trigger_raw=do_not_trigger_raw,
        do_not_trigger_examples=do_not_trigger_examples if do_not_trigger_examples is not None else [],
        fallback_rule=fallback_rule,
        output_label=output_label,
        cta_url=cta_url,
        extra_fields={},
        raw_text="",
    )


def make_understanding(intent="therapy_information", topic="MNRI", search_query="", emotional_state="curious"):
    return {
        "intent": intent,
        "topic": topic,
        "search_query": search_query,
        "emotional_state": emotional_state,
    }


def make_safety(safe_response="Here is some information."):
    return {
        "safe_response": safe_response,
        "safety_status": "approved",
        "violations_detected": [],
        "escalation_level": "none",
        "disclaimer_added": False,
        "original_final_answer": safe_response,
        "emotional_state": "curious",
        "source": "rag",
        "answer_type": "therapy_information",
        "topic": "MNRI",
        "intent": "therapy_information",
        "confidence": 0.9,
        "grounded_chunk_ids": [],
        "validation_time_ms": 5.0,
        "error": None,
    }


def make_state(user_message="What is MNRI?", understanding=None, safe_response="Here is some information."):
    return {
        "user_message": user_message,
        "chat_history": [],
        "understanding": understanding if understanding is not None else make_understanding(),
        "knowledge": None,
        "response": None,
        "empathy": None,
        "safety": make_safety(safe_response=safe_response),
        "cta": None,
    }


def test_specific_therapy_match_mnri(monkeypatch):
    mnri = make_cta_record(cta_id="therapies/mnri", category="Therapy", cta_type="Specific Therapy", aliases=["MNRI"])
    general = make_cta_record(
        cta_id="therapies/general",
        category="Therapy",
        cta_type="Library",
        trigger_examples=["What therapies are available?"],
        output_label="Explore the Therapy Library",
        cta_url="https://manascience.webflow.io/therapy-library",
    )
    monkeypatch.setattr("app.services.cta_service.get_ctas_by_status", lambda status: [mnri, general])
    state = make_state(
        user_message="What is MNRI?",
        understanding=make_understanding(intent="therapy_information", topic="MNRI"),
    )
    result = cta_node(state)["cta"]
    assert result["cta_found"] is True
    assert result["cta_id"] == "therapies/mnri"
    assert result["match_reason"] == "specific_match"


def test_specific_condition_match_adhd(monkeypatch):
    adhd = make_cta_record(
        cta_id="conditions/adhd",
        category="Condition",
        cta_type="Individual Condition",
        aliases=["ADHD"],
        output_label="Learn More About ADHD",
        cta_url="https://manascience.webflow.io/post/adhd",
        priority="Specific Condition",
    )
    general = make_cta_record(
        cta_id="conditions/general",
        category="Condition",
        cta_type="Library",
        trigger_examples=["What conditions does ManaScience cover?"],
        output_label="Explore Conditions",
        cta_url="https://manascience.webflow.io/conditions",
        priority="General Condition",
    )
    monkeypatch.setattr("app.services.cta_service.get_ctas_by_status", lambda status: [adhd, general])
    state = make_state(
        user_message="What is ADHD?",
        understanding=make_understanding(intent="personal_concern", topic="ADHD"),
    )
    result = cta_node(state)["cta"]
    assert result["cta_found"] is True
    assert result["cta_id"] == "conditions/adhd"


def test_general_therapy_library_direct_match():
    mnri = make_cta_record(cta_id="therapies/mnri", aliases=["MNRI"])
    general = make_cta_record(
        cta_id="therapies/general", cta_type="Library", trigger_examples=["What therapies are available?"]
    )
    match = find_cta(
        "What therapies are available?",
        make_understanding(intent="therapy_information", topic=""),
        [mnri, general],
    )
    assert match.cta.cta_id == "therapies/general"
    assert match.match_reason == "specific_match"


def test_intent_driven_category_fallback_when_nothing_matches():
    mnri = make_cta_record(cta_id="therapies/mnri", aliases=["MNRI"])
    general = make_cta_record(
        cta_id="therapies/general", cta_type="Library", trigger_examples=["What therapies are available?"]
    )
    understanding = make_understanding(intent="therapy_information", topic="")
    match = find_cta("hmm, not sure what to ask", understanding, [mnri, general])
    assert match is not None
    assert match.cta.cta_id == "therapies/general"
    assert match.match_reason == "category_fallback"
    assert match.matched_phrase is None


def test_no_match_when_nothing_scores_and_no_intent_affinity():
    mnri = make_cta_record(cta_id="therapies/mnri", aliases=["MNRI"])
    general = make_cta_record(
        cta_id="therapies/general", cta_type="Library", trigger_examples=["What therapies are available?"]
    )
    understanding = make_understanding(intent="general_chat", topic="")
    match = find_cta("hmm, not sure what to ask", understanding, [mnri, general])
    assert match is None


def test_no_match_returns_none_not_empty_list():
    match = find_cta(
        "hmm, not sure what to ask", make_understanding(intent="general_chat", topic=""), [make_cta_record()]
    )
    assert match is None
    assert not isinstance(match, list)


def test_exclusion_blocks_an_otherwise_matching_cta():
    record = make_cta_record(
        cta_id="therapies/mnri",
        trigger_examples=["What is MNRI therapy?"],
        do_not_trigger_examples=["What is MNRI therapy?"],
    )
    understanding = make_understanding(intent="general_chat", topic="")
    match = find_cta("What is MNRI therapy?", understanding, [record])
    assert match is None


def test_exclusion_also_blocks_the_category_fallback_path():
    general = make_cta_record(
        cta_id="therapies/general",
        category="Therapy",
        cta_type="Library",
        trigger_examples=["What therapies are available?"],
        do_not_trigger_examples=["something unrelated to therapy"],
    )
    understanding = make_understanding(intent="therapy_information", topic="")
    match = find_cta("something unrelated to therapy", understanding, [general])
    assert match is None


def test_specific_beats_general_in_same_category():
    mnri = make_cta_record(cta_id="therapies/mnri", category="Therapy", cta_type="Specific Therapy", aliases=["MNRI"])
    general = make_cta_record(
        cta_id="therapies/general",
        category="Therapy",
        cta_type="Library",
        trigger_examples=["tell me about mnri and other therapies"],
    )
    understanding = make_understanding(intent="therapy_information", topic="")
    match = find_cta("tell me about mnri and other therapies", understanding, [mnri, general])
    assert match.cta.cta_id == "therapies/mnri"


def test_alias_outranks_trigger_example_tier():
    a = make_cta_record(
        cta_id="therapies/a", category="Therapy", cta_type="Individual Therapy",
        related_topics=["reflex integration"],
    )
    b = make_cta_record(
        cta_id="therapies/b", category="Therapy", cta_type="Individual Therapy",
        aliases=["reflex integration"],
    )
    understanding = make_understanding(intent="therapy_information", topic="")
    match = find_cta("tell me about reflex integration", understanding, [a, b])
    assert match.cta.cta_id == "therapies/b"


def test_cross_category_tie_broken_by_intent_affinity():
    affinity_category = INTENT_CATEGORY_AFFINITY["therapy_information"]
    therapy_record = make_cta_record(
        cta_id="therapies/x", category=affinity_category, cta_type="Individual Therapy", aliases=["zzzmatch"]
    )
    condition_record = make_cta_record(
        cta_id="conditions/y", category="Condition", cta_type="Individual Condition", aliases=["zzzmatch"]
    )
    understanding = make_understanding(intent="therapy_information", topic="")
    match = find_cta("zzzmatch", understanding, [therapy_record, condition_record])
    assert match.cta.cta_id == "therapies/x"


def test_cross_category_genuine_tie_logged_and_deterministic(caplog):
    record_a = make_cta_record(cta_id="about/x", category="About", cta_type="Information Page", aliases=["zzzmatch"])
    record_b = make_cta_record(
        cta_id="community/y", category="Community", cta_type="Information Page", aliases=["zzzmatch"]
    )
    understanding = make_understanding(intent="general_chat", topic="")
    with caplog.at_level(logging.WARNING):
        match1 = find_cta("zzzmatch", understanding, [record_a, record_b])
        match2 = find_cta("zzzmatch", understanding, [record_a, record_b])
    assert match1.cta.cta_id == match2.cta.cta_id == "community/y"
    assert any("category tie broken" in r.message for r in caplog.records)


def test_duplicate_same_score_candidates_tie_broken_by_cta_id(caplog):
    record_a = make_cta_record(
        cta_id="therapies/zzz", category="Therapy", cta_type="Individual Therapy", aliases=["zzzmatch"]
    )
    record_b = make_cta_record(
        cta_id="therapies/aaa", category="Therapy", cta_type="Individual Therapy", aliases=["zzzmatch"]
    )
    understanding = make_understanding(intent="therapy_information", topic="")
    with caplog.at_level(logging.WARNING):
        match1 = find_cta("zzzmatch", understanding, [record_a, record_b])
        match2 = find_cta("zzzmatch", understanding, [record_a, record_b])
    assert match1.cta.cta_id == match2.cta.cta_id == "therapies/aaa"
    assert any("tie broken by cta_id" in r.message for r in caplog.records)


def test_empty_active_ctas_returns_no_match(monkeypatch, caplog):
    monkeypatch.setattr("app.services.cta_service.get_ctas_by_status", lambda status: [])
    with caplog.at_level(logging.WARNING):
        result = process("anything", make_understanding(), "some response")
    assert result["cta_found"] is False
    assert any("zero active CTAs" in r.message for r in caplog.records)


def test_unexpected_service_exception_falls_back_safely(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.nodes.cta_node.process", boom)
    state = make_state(safe_response="original response")
    result = cta_node(state)["cta"]
    assert result["cta_found"] is False
    assert result["error"] == "cta_lookup_failure"
    assert result["response"] == "original response"


def test_empty_safe_response_passed_through_unchanged(monkeypatch):
    mnri = make_cta_record(cta_id="therapies/mnri", aliases=["MNRI"])
    monkeypatch.setattr("app.services.cta_service.get_ctas_by_status", lambda status: [mnri])

    state_match = make_state(
        user_message="What is MNRI?",
        understanding=make_understanding(intent="therapy_information", topic="MNRI"),
        safe_response="",
    )
    assert cta_node(state_match)["cta"]["response"] == ""

    state_no_match = make_state(
        user_message="zzz unrelated", understanding=make_understanding(intent="general_chat", topic=""), safe_response=""
    )
    assert cta_node(state_no_match)["cta"]["response"] == ""

    monkeypatch.setattr("app.nodes.cta_node.process", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    state_exc = make_state(safe_response="")
    assert cta_node(state_exc)["cta"]["response"] == ""


def test_response_is_never_modified(monkeypatch):
    mnri = make_cta_record(cta_id="therapies/mnri", aliases=["MNRI"])
    monkeypatch.setattr("app.services.cta_service.get_ctas_by_status", lambda status: [mnri])
    safe_response = "Here is some detailed information about reflex integration."

    state_match = make_state(
        user_message="What is MNRI?",
        understanding=make_understanding(intent="therapy_information", topic="MNRI"),
        safe_response=safe_response,
    )
    assert cta_node(state_match)["cta"]["response"] == safe_response

    state_no_match = make_state(
        user_message="zzz unrelated",
        understanding=make_understanding(intent="general_chat", topic=""),
        safe_response=safe_response,
    )
    assert cta_node(state_no_match)["cta"]["response"] == safe_response


def test_topic_alone_can_trigger_a_match():
    mnri = make_cta_record(cta_id="therapies/mnri", aliases=["MNRI"])
    understanding = make_understanding(intent="therapy_information", topic="MNRI")
    match = find_cta("tell me more about it", understanding, [mnri])
    assert match is not None
    assert match.cta.cta_id == "therapies/mnri"


def test_missing_topic_key_does_not_raise():
    mnri = make_cta_record(cta_id="therapies/mnri", trigger_examples=["What is MNRI?"])
    understanding = {"intent": "therapy_information"}
    match = find_cta("What is MNRI?", understanding, [mnri])
    assert match is not None
    assert match.cta.cta_id == "therapies/mnri"


def test_build_cta_response_minimal_shape_on_match():
    record = make_cta_record(
        cta_id="therapies/mnri",
        output_label="Learn More About MNRI",
        cta_url="https://manascience.webflow.io/post/mnri",
        category="Therapy",
    )
    match = CTAMatch(cta=record, match_reason="specific_match", matched_phrase="mnri")
    result = build_cta_response("some response", match)
    assert set(result.keys()) == {"response", "cta_found", "cta"}
    assert result["cta_found"] is True
    assert set(result["cta"].keys()) == {"url", "trigger", "category"}
    assert result["cta"]["trigger"] == record.output_label
    assert result["cta"]["url"] == record.cta_url
    assert result["cta"]["category"] == record.category


def test_build_cta_response_minimal_shape_on_no_match():
    result = build_cta_response("some response", None)
    assert result == {"response": "some response", "cta_found": False, "cta": None}


def test_performance_under_corpus_growth():
    categories = ["Therapy", "Condition", "About", "Community", "Courses", "FAQ"]
    records = [
        make_cta_record(
            cta_id=f"synthetic/{i}",
            category=categories[i % len(categories)],
            cta_type="Library" if i % 5 == 0 else "Individual Therapy",
            trigger_examples=[f"synthetic trigger phrase number {i}"],
        )
        for i in range(200)
    ]
    understanding = make_understanding(intent="therapy_information", topic="")
    start = time.monotonic()
    find_cta("synthetic trigger phrase number 150", understanding, records)
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


def test_real_corpus_smoke_no_crash_no_unexpected_match():
    # Forces a fresh scan of the real settings.cta_data_dir, undoing any global
    # cache pollution left by test_cta_loader.py's own reload_cta_data() calls
    # against a synthetic tmp_path corpus (monkeypatch reverts settings.cta_data_dir
    # itself, but not the loader's already-populated module-level cache).
    reload_cta_data()
    cases = [
        ("What is MNRI?", "therapy_information", "MNRI", "therapies/mnri"),
        ("What therapies are available?", "therapy_information", "", "therapies/general"),
        ("What is ADHD?", "personal_concern", "ADHD", "conditions/adhd"),
        ("asdkjasdkj random text", "general_chat", "", None),
    ]
    for message, intent, topic, expected_cta_id in cases:
        understanding = make_understanding(intent=intent, topic=topic)
        state = make_state(user_message=message, understanding=understanding)
        result = cta_node(state)["cta"]
        if expected_cta_id is None:
            assert result["cta_found"] is False
        else:
            assert result["cta_id"] == expected_cta_id


def test_cta_output_rejects_found_true_with_missing_cta_id():
    with pytest.raises(ValidationError):
        CTAOutput(
            cta_found=True,
            cta_id=None,
            cta_url="https://example.com",
            cta_trigger="Learn More",
            cta_category="Therapy",
            match_reason="specific_match",
            matched_phrase="x",
            response="r",
            lookup_time_ms=1.0,
            error=None,
        )


def test_cta_output_rejects_found_true_with_no_match_reason():
    with pytest.raises(ValidationError):
        CTAOutput(
            cta_found=True,
            cta_id="therapies/mnri",
            cta_url="https://example.com",
            cta_trigger="Learn More",
            cta_category="Therapy",
            match_reason="no_match",
            matched_phrase="x",
            response="r",
            lookup_time_ms=1.0,
            error=None,
        )


def test_cta_output_rejects_found_false_with_nonnull_cta_id():
    with pytest.raises(ValidationError):
        CTAOutput(
            cta_found=False,
            cta_id="therapies/mnri",
            cta_url=None,
            cta_trigger=None,
            cta_category=None,
            match_reason="no_match",
            matched_phrase=None,
            response="r",
            lookup_time_ms=1.0,
            error=None,
        )


GREETING_ACCEPTANCE_MESSAGES = [
    "hi", "hello", "hy", "hey", "hii", "hiiii",
    "good morning", "good afternoon", "good evening",
    "how are you", "thanks", "thank you",
    "ok", "okay", "cool", "bye", "goodbye", "see you",
    "\U0001F44B", "\U0001F60A", "\U0001F44D",  # 👋 😊 👍
]


@pytest.mark.parametrize("message", GREETING_ACCEPTANCE_MESSAGES)
def test_greeting_guard_blocks_small_talk_before_scoring(message):
    """A greeting must never score against any CTA, however strong the
    accidental substring overlap (e.g. "hy" inside "hyperactivity", "ok"
    inside "looking") would otherwise make it look like a match."""
    record = make_cta_record(
        cta_id="conditions/adhd",
        aliases=["ADHD"],
        trigger_examples=["Attention Deficit Hyperactivity Disorder", "I'm looking for therapy options."],
    )
    assert find_cta(message, make_understanding(intent="general_chat", topic=""), [record]) is None


@pytest.mark.parametrize("message", GREETING_ACCEPTANCE_MESSAGES)
def test_greeting_guard_against_real_corpus(message):
    """End-to-end through cta_node against the real CTA corpus, with
    understanding=None -- the exact partial state app/main.py's /chat
    handler builds, since /chat never runs the Understanding Node."""
    reload_cta_data()
    state = {"user_message": message, "understanding": None, "safety": {"safe_response": "some response"}}
    result = cta_node(state)["cta"]
    assert result["cta_found"] is False
    assert result["match_reason"] == "no_match"


@pytest.mark.parametrize(
    "message,expected_cta_id",
    [
        ("What is ADHD?", "conditions/adhd"),
        ("What is Depression?", "conditions/depression"),
        ("Tell me about therapies.", "therapies/general"),
        ("Tell me about Neurofeedback.", "therapies/neurofeedback"),
        ("How do I subscribe?", "subscription/subscription"),
        ("What is ManaScience?", "about/about"),
        ("What courses do you offer?", "courses/courses"),
    ],
)
def test_greeting_guard_does_not_affect_real_questions(message, expected_cta_id):
    """Regression guard: genuine questions must still match, including the
    ones that happen to be short or share letters with a greeting word."""
    reload_cta_data()
    state = {"user_message": message, "understanding": None, "safety": {"safe_response": "some response"}}
    result = cta_node(state)["cta"]
    assert result["cta_found"] is True
    assert result["cta_id"] == expected_cta_id


def test_greeting_guard_is_exact_not_substring():
    """Only a message that IS (after normalization) a greeting is small talk
    -- one that merely starts with or contains one must still be matched."""
    assert _is_greeting_or_small_talk("hi, what is ADHD?") is False
    assert _is_greeting_or_small_talk("ok so what is MNRI therapy?") is False


def test_greeting_guard_detects_punctuation_or_emoji_only_messages():
    assert _is_greeting_or_small_talk("\U0001F44B") is True  # 👋
    assert _is_greeting_or_small_talk("...") is True
    assert _is_greeting_or_small_talk("!!!") is True


def test_cta_output_rejects_found_false_with_wrong_match_reason():
    with pytest.raises(ValidationError):
        CTAOutput(
            cta_found=False,
            cta_id=None,
            cta_url=None,
            cta_trigger=None,
            cta_category=None,
            match_reason="specific_match",
            matched_phrase=None,
            response="r",
            lookup_time_ms=1.0,
            error=None,
        )


# =============================================================================
# REGRESSION TESTS — real-corpus guard for every confirmed bug / new-issue fix
# =============================================================================


@pytest.fixture(scope="module")
def corpus():
    """Real CTA corpus loaded once for the entire regression block."""
    reload_cta_data()
    return get_all_ctas()


def _cid(message, intent, records, topic=""):
    """find_cta wrapper: returns matched cta_id or None."""
    m = find_cta(message, make_understanding(intent=intent, topic=topic), records)
    return m.cta.cta_id if m else None


# ── BUG-01 ────────────────────────────────────────────────────────────────────
# "ManaScience" was an alias (weight=3) in about/about.md, hijacking every
# query containing "manascience" away from its correct CTA.

@pytest.mark.parametrize("message,expected", [
    ("What therapies does ManaScience offer?",  "therapies/general"),
    ("What therapies does ManaScience provide?", "therapies/general"),
    ("Is ManaScience paid?",                    "subscription/subscription"),
    ("Does ManaScience cost money?",            "subscription/subscription"),
    ("Is ManaScience GDPR compliant?",          "privacy/privacy_guidelines"),
    ("Does ManaScience follow privacy laws?",   "privacy/privacy_guidelines"),
])
def test_bug01_manascience_no_longer_routes_to_about(message, expected, corpus):
    assert _cid(message, "general_chat", corpus) == expected


def test_bug01_about_still_reachable(corpus):
    assert _cid("What is ManaScience?", "general_chat", corpus) == "about/about"


# ── BUG-02 ────────────────────────────────────────────────────────────────────
# "Learning", "Training", "Education" were aliases (weight=3) in courses/courses.md,
# hijacking generic learning/difficulty queries away from conditions/general.

@pytest.mark.parametrize("message", [
    "My child has learning difficulties.",
    "Learning difficulties.",
    "My child has difficulty learning.",
])
def test_bug02_learning_routes_to_conditions_not_courses(message, corpus):
    assert _cid(message, "personal_concern", corpus) == "conditions/general"


def test_bug02_courses_still_reachable(corpus):
    assert _cid("What courses do you offer?", "course_information", corpus) == "courses/courses"


# ── BUG-03 ────────────────────────────────────────────────────────────────────
# "Help" was an alias (weight=3) in faq/faq.md, pulling any "help" query into
# the FAQ CTA instead of its correct destination.

def test_bug03_i_need_help_returns_no_match(corpus):
    assert _cid("I need help.", "general_chat", corpus) is None


def test_bug03_brain_dev_routes_to_neuroplasticity_not_faq(corpus):
    assert _cid("Help me understand brain development.", "therapy_information", corpus) == "neuroplasticity/neuroplasticity"


def test_bug03_faq_still_reachable(corpus):
    assert _cid("FAQ", "general_chat", corpus) == "faq/faq"


# ── NEW-02 ────────────────────────────────────────────────────────────────────
# "Developmental Delay" in Do NOT Trigger normalized to "developmental delay",
# which substring-matched "developmental delays" — blocking the record entirely
# via _is_excluded before any scoring took place.

@pytest.mark.parametrize("message", [
    "My child has developmental delays.",
    "My child has a developmental delay.",
    "Developmental delays.",
    "Developmental delay.",
])
def test_new02_developmental_delay_routes_to_conditions_general(message, corpus):
    assert _cid(message, "personal_concern", corpus) == "conditions/general"


# ── BUG-04 ────────────────────────────────────────────────────────────────────
# URL typo "/neuroplasiticity" in neuroplasticity/neuroplasticity.md.
# Pre-solved before this session. Guard that the URL field is always populated.

def test_bug04_neuroplasticity_cta_url_is_present(corpus):
    rec = next((r for r in corpus if r.cta_id == "neuroplasticity/neuroplasticity"), None)
    assert rec is not None, "neuroplasticity/neuroplasticity CTA missing from corpus"
    assert rec.cta_url and len(rec.cta_url) > 0


# ── BUG-05 ────────────────────────────────────────────────────────────────────
# "Autism" in neurofeedback.md and neuroplasticity.md Related Topics caused
# autism queries to score against those CTAs instead of conditions/autism.

@pytest.mark.parametrize("message", [
    "My child has autism.",
    "What is autism?",
    "My child was diagnosed with autism.",
])
def test_bug05_autism_routes_to_conditions_autism_not_neurofeedback(message, corpus):
    assert _cid(message, "personal_concern", corpus) == "conditions/autism"


def test_bug05_neurofeedback_still_matches_neurofeedback_autism_query(corpus):
    # "Can Neurofeedback help autism?" has the Neurofeedback alias (weight=3) — still wins
    assert _cid(
        "Can Neurofeedback help autism?", "therapy_information", corpus, topic="Neurofeedback"
    ) == "therapies/neurofeedback"


# ── BUG-06 ────────────────────────────────────────────────────────────────────
# Trigger "My child struggles in school because of ADHD." matched the shorter
# "My child struggles in school." via text_norm-in-phrase_norm substring check;
# ADHD (non-Library) won over conditions/general (Library).

def test_bug06_struggles_in_school_without_adhd_routes_to_general(corpus):
    assert _cid("My child struggles in school.", "personal_concern", corpus) == "conditions/general"


def test_bug06_adhd_still_matches_when_adhd_mentioned(corpus):
    assert _cid(
        "My child with ADHD struggles in school.", "personal_concern", corpus, topic="ADHD"
    ) == "conditions/adhd"


# ── NEW-01 ────────────────────────────────────────────────────────────────────
# Trigger examples in conditions/general.md only used "My child". Queries
# with "My son", "My daughter", "My kid" returned no match.

@pytest.mark.parametrize("message", [
    "My son has trouble reading.",
    "My son has learning difficulties.",
    "My son struggles in school.",
    "My daughter can't focus.",
    "My daughter has learning difficulties.",
    "My daughter struggles in school.",
    "My kid has learning difficulties.",
    "My kid struggles in school.",
])
def test_new01_son_daughter_kid_route_to_conditions_general(message, corpus):
    assert _cid(message, "personal_concern", corpus) == "conditions/general"


# ── NEW-03 ────────────────────────────────────────────────────────────────────
# "Reading" (single word) in Arrowsmith Related Topics (weight=1) pulled generic
# reading queries to Arrowsmith. Fixed by replacing with "Reading Difficulties".

def test_new03_generic_reading_does_not_route_to_arrowsmith(corpus):
    result = _cid("My child struggles with reading.", "personal_concern", corpus)
    assert result != "therapies/arrowsmith"
    assert result == "conditions/general"


def test_new03_arrowsmith_still_reachable(corpus):
    assert _cid(
        "What is the Arrowsmith Program?", "therapy_information", corpus, topic="Arrowsmith"
    ) == "therapies/arrowsmith"


# ── NEW-06 ────────────────────────────────────────────────────────────────────
# No autism.md existed; autism queries fell through to conditions/general or
# incorrectly matched therapy CTAs.

@pytest.mark.parametrize("message,topic", [
    ("What is autism?",                  "Autism"),
    ("Explain autism.",                  "Autism"),
    ("What is ASD?",                     "ASD"),
    ("My child has autism.",             "Autism"),
    ("My child was diagnosed with ASD.", "ASD"),
    ("Autism Spectrum Disorder.",        "Autism"),
])
def test_new06_autism_queries_route_to_conditions_autism(message, topic, corpus):
    assert _cid(message, "personal_concern", corpus, topic=topic) == "conditions/autism"


# ── NEW-07 ────────────────────────────────────────────────────────────────────
# "Behaviour" and "Attention" in ADHD Related Topics (weight=1) caused ADHD
# (non-Library) to beat conditions/general (Library) for generic queries with
# no explicit ADHD signal.

@pytest.mark.parametrize("message", [
    "My child has behavioural challenges.",
    "My child has attention problems.",
])
def test_new07_behaviour_attention_without_adhd_routes_to_general(message, corpus):
    assert _cid(message, "personal_concern", corpus) == "conditions/general"


def test_new07_adhd_still_reachable(corpus):
    assert _cid("What is ADHD?", "personal_concern", corpus, topic="ADHD") == "conditions/adhd"


# ── NEW-04 (side-effect of BUG-03) ───────────────────────────────────────────
# "Support" in faq/faq.md Related Topics caused "My child needs support." to
# spuriously route to faq/faq. Resolved when "Support" was removed during
# the BUG-03 fix.

def test_new04_support_query_does_not_route_to_faq(corpus):
    assert _cid("My child needs support.", "personal_concern", corpus) != "faq/faq"


# ── NEW-05 ────────────────────────────────────────────────────────────────────
# "M.N.R.I." normalized to "m n r i" — four single-char tokens that could
# token-subset-match any text containing those letters as isolated words.
# Removed; the "MNRI" alias covers all practical cases.

def test_new05_mnri_still_reachable_after_dotted_alias_removed(corpus):
    assert _cid("What is MNRI?", "therapy_information", corpus, topic="MNRI") == "therapies/mnri"
    assert _cid("Tell me about MNRI.", "therapy_information", corpus, topic="MNRI") == "therapies/mnri"
