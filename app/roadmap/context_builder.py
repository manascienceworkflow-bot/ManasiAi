import logging

from app.roadmap.models import RoadmapContext, RoadmapResult

logger = logging.getLogger("app.roadmap.context_builder")

# Literal guardrail line prepended to every rendered context. It reminds Manasi
# that the assessment is read-only reference material -- Manasi may explain the
# stored numbers but must not turn them into a therapy recommendation or a
# clinical conclusion (spec P4, out of scope this phase).
_GUARDRAIL = (
    "USER'S ROADMAP ASSESSMENT (read-only context -- explain these results if "
    "asked, but do NOT recommend therapies, diagnose, or suggest next steps):"
)

# Human-readable long form of the classification, kept purely for the prose line.
_CLASSIFICATION_LONG = {"ND": "Neurodivergent", "NT": "Neurotypical"}


def empty_context() -> RoadmapContext:
    """The canonical 'no roadmap on file' context. Used on chat turns for users
    who have not submitted an assessment -- present=False, summary_text="" so
    the chat prompt is byte-for-byte unchanged from today's behaviour."""
    return {
        "present": False,
        "classification": None,
        "classification_raw": None,
        "scores": None,
        "summary_text": "",
    }


def _render_score_line(entry: dict) -> str:
    severity = entry.get("severity")
    tail = f" (severity: {severity})" if severity else ""
    return f"  - {entry['domain']}: {entry['score']}{tail}"


def build_context(result: RoadmapResult) -> RoadmapContext:
    """Render a RoadmapResult into the read-only RoadmapContext Manasi consumes.
    Every score and severity is reproduced exactly as stored -- no rounding, no
    reordering by magnitude (which would assert a ranking the backend must not
    make), no interpretive language. Never mutates `result`."""
    scores = [entry.model_dump() for entry in result.scores]

    long_label = _CLASSIFICATION_LONG.get(result.classification, result.classification)
    lines = [
        _GUARDRAIL,
        f"Classification: {result.classification} ({long_label})",
        "Domain scores:",
        *[_render_score_line(entry) for entry in scores],
    ]
    summary_text = "\n".join(lines)

    return {
        "present": True,
        "classification": result.classification,
        "classification_raw": result.classification_raw,
        "scores": scores,
        "summary_text": summary_text,
    }


def render_context_text(context: RoadmapContext) -> str:
    """The single string fed into the chat chain's {roadmap_context} slot. Empty
    string when no roadmap is present, so the prompt collapses cleanly."""
    return context["summary_text"]
