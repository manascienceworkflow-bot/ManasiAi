import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.roadmap.context_builder import (  # noqa: E402
    build_context,
    empty_context,
    render_context_text,
)
from app.roadmap.roadmap_loader import load_roadmap  # noqa: E402


def _result():
    return load_roadmap(
        {
            "user_id": "u_demo",
            "Classification": "neurodivergent",
            "score": [
                {"domain": "communication", "Score": "72%", "Severity": "moderate"},
                {"domain": "social", "Score": 40},
            ],
        }
    )


def test_present_flag_and_fields():
    ctx = build_context(_result())
    assert ctx["present"] is True
    assert ctx["classification"] == "ND"
    assert ctx["classification_raw"] == "neurodivergent"
    assert len(ctx["scores"]) == 2


def test_summary_preserves_scores_verbatim():
    text = build_context(_result())["summary_text"]
    assert "72%" in text
    assert "communication: 72%" in text
    assert "social: 40" in text
    assert "severity: moderate" in text


def test_summary_carries_guardrail_line():
    text = build_context(_result())["summary_text"]
    assert "read-only" in text.lower()
    assert "do not recommend therapies" in text.lower()


def test_domain_order_preserved_not_sorted_by_score():
    # social (40) must stay AFTER communication ("72%") -- insertion order, not a
    # magnitude ranking the backend must never assert.
    text = build_context(_result())["summary_text"]
    assert text.index("communication") < text.index("social")


def test_build_context_does_not_mutate_result():
    result = _result()
    before = [(s.domain, s.score, s.severity) for s in result.scores]
    build_context(result)
    after = [(s.domain, s.score, s.severity) for s in result.scores]
    assert before == after


def test_empty_context_is_absent_and_blank():
    ctx = empty_context()
    assert ctx["present"] is False
    assert ctx["summary_text"] == ""
    assert render_context_text(ctx) == ""
