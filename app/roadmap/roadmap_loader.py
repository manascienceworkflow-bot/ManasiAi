import logging
from typing import Optional

from app.roadmap.models import RoadmapDomainScore, RoadmapResult

logger = logging.getLogger("app.roadmap.roadmap_loader")


class RoadmapValidationError(Exception):
    """Raised when the incoming payload violates a validation rule. Carries a
    machine-readable `code`, a human `message`, and the offending `field` path
    (when one applies). The route maps this to a 422 response -- it is the only
    exception the loader ever raises out of `load_roadmap`."""

    def __init__(self, code: str, message: str, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


# The frontend sends classification as a full word; the backend also accepts an
# already-coded value so the contract is forgiving. Everything is matched
# case-insensitively. This is the ONLY normalization applied to any value --
# scores and severities pass through untouched (spec P1).
_CLASSIFICATION_MAP = {
    "neurodivergent": "ND",
    "neurotypical": "NT",
    "nd": "ND",
    "nt": "NT",
}


def _unwrap(payload) -> dict:
    """The current frontend wraps the single submission in a one-element list;
    a bare object is also accepted. An empty list, a multi-element list (which
    submission would we take?), or a non-object are all rejected rather than
    guessed at."""
    if isinstance(payload, list):
        if len(payload) == 0:
            raise RoadmapValidationError("payload_not_object", "Payload list is empty.")
        if len(payload) > 1:
            raise RoadmapValidationError(
                "ambiguous_batch",
                "Payload list carries more than one submission; exactly one is expected.",
            )
        payload = payload[0]
    if not isinstance(payload, dict):
        raise RoadmapValidationError(
            "payload_not_object", "Payload must be a JSON object or a one-element list."
        )
    return payload


def _require(obj: dict, key: str) -> object:
    if key not in obj or obj[key] is None:
        raise RoadmapValidationError("missing_field", f"Required field '{key}' is missing.", key)
    return obj[key]


def _normalize_classification(value: object) -> tuple[str, str]:
    """Returns (raw, code). `raw` is preserved as received; `code` is the ND/NT
    literal. Anything outside the accepted vocabulary is a hard rejection."""
    raw = str(value)
    code = _CLASSIFICATION_MAP.get(raw.strip().lower())
    if code is None:
        raise RoadmapValidationError(
            "invalid_classification",
            f"Classification {raw!r} is not one of neurodivergent/neurotypical/ND/NT.",
            "Classification",
        )
    return raw, code


def _parse_scores(value: object) -> list[RoadmapDomainScore]:
    if not isinstance(value, list) or len(value) == 0:
        raise RoadmapValidationError(
            "empty_scores", "Field 'score' must be a non-empty list.", "score"
        )
    parsed: list[RoadmapDomainScore] = []
    for i, entry in enumerate(value):
        if not isinstance(entry, dict):
            raise RoadmapValidationError(
                "invalid_score_entry", f"score[{i}] is not an object.", f"score[{i}]"
            )
        domain = entry.get("domain")
        if not isinstance(domain, str) or not domain.strip():
            raise RoadmapValidationError(
                "invalid_score_entry",
                f"score[{i}] is missing a non-empty 'domain'.",
                f"score[{i}].domain",
            )
        if "Score" not in entry or entry["Score"] is None:
            raise RoadmapValidationError(
                "invalid_score_entry",
                f"score[{i}] is missing 'Score'.",
                f"score[{i}].Score",
            )
        # Stored verbatim -- no coercion beyond keeping the JSON-native type.
        raw_score = entry["Score"]
        if not isinstance(raw_score, (str, int, float)) or isinstance(raw_score, bool):
            raise RoadmapValidationError(
                "invalid_score_entry",
                f"score[{i}].Score must be a string or number.",
                f"score[{i}].Score",
            )
        severity = entry.get("Severity")
        domain_type = entry.get("domain_type")
        parsed.append(
            RoadmapDomainScore(
                domain=domain.strip(),
                domain_type=str(domain_type) if domain_type is not None else None,
                score=raw_score,
                severity=str(severity) if severity is not None else None,
            )
        )
    return parsed


def load_roadmap(payload) -> RoadmapResult:
    """Parse and validate a raw frontend roadmap score payload into a canonical
    RoadmapResult. This is the ONLY place the raw wire format is touched (spec
    P2). Pure: no persistence, no network, no arithmetic on any score. Raises
    RoadmapValidationError on any violation; never returns a partial result."""
    obj = _unwrap(payload)

    user_id = _require(obj, "user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise RoadmapValidationError("missing_field", "Field 'user_id' must be a non-empty string.", "user_id")

    classification_value = _require(obj, "Classification")
    classification_raw, classification = _normalize_classification(classification_value)

    scores = _parse_scores(_require(obj, "score"))

    result = RoadmapResult(
        user_id=user_id.strip(),
        classification_raw=classification_raw,
        classification=classification,
        scores=scores,
        raw=obj,
    )
    logger.info(
        "load_roadmap ok: user_id=%s classification=%s domains=%d",
        result.user_id,
        result.classification,
        len(result.scores),
    )
    return result
