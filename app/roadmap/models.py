from typing import Literal, Optional, TypedDict

from pydantic import BaseModel


class RoadmapDomainScore(BaseModel):
    """One domain's result exactly as the frontend scoring engine produced it.
    `score` and `severity` are stored verbatim and are NEVER recomputed,
    rounded, or re-ranked by the backend (spec P1) -- `score` is typed as a
    union because the frontend may send a percentage as a bare number (72) or
    as a string ("72%"), and we preserve whichever arrived."""

    domain: str
    domain_type: Optional[str] = None
    score: str | float | int
    severity: Optional[str] = None


class RoadmapResult(BaseModel):
    """The single canonical object the whole backend speaks. Built by the
    Roadmap Loader from the raw frontend payload; no other module ever touches
    the raw wire format (spec P2/P3). Only the fields the current frontend
    actually sends are required -- `roadmap_id`, `answers`, and richer metadata
    are reserved for later phases and are simply absent here, preserved (if ever
    present) inside `raw`."""

    user_id: str
    classification_raw: str
    classification: Literal["ND", "NT"]
    scores: list[RoadmapDomainScore]
    raw: dict


class RoadmapContext(TypedDict):
    """Read-only view of a RoadmapResult handed onward to Manasi. `summary_text`
    is the human-readable block injected into the chat chain's system prompt;
    the structured fields are kept alongside it for any future consumer. An
    absent roadmap is represented by present=False and summary_text="" (see
    context_builder.empty_context), never by None."""

    present: bool
    classification: Optional[str]
    classification_raw: Optional[str]
    scores: Optional[list[dict]]
    summary_text: str


class FilteredDomainScore(BaseModel):
    """One domain that SURVIVED the Step 2 severity filter, i.e. its severity is
    High or Moderate. `domain`, `domain_type`, `score`, and `severity` are carried
    VERBATIM from the frontend (spec P1) -- `severity_key` is the normalized
    comparison key the filter derived, exposed so downstream steps can branch on a
    canonical value without re-implementing normalization. `domain_type` (the
    frontend's per-domain classification, e.g. "Spine"/"Complementary") is Optional
    and passed straight through to the therapy-mapping output."""

    domain: str
    domain_type: Optional[str] = None
    score: str | float | int
    severity: Optional[str] = None
    severity_key: Literal["high", "moderate"]
    severity_rank: int


class DroppedDomain(BaseModel):
    """One domain the Step 2 filter EXCLUDED, with the machine-readable reason.
    Retained for diagnostics/observability -- NOT for downstream therapy mapping.
    Every input entry appears in exactly one of `filtered_scores` or `dropped`."""

    domain: str
    severity: Optional[str] = None
    reason: Literal[
        "low_severity",  # known-good, deliberately excluded -- the normal case
        "missing_severity",  # None / blank / non-string
        "unknown_severity",  # non-empty but outside the vocabulary
        "duplicate_domain",  # same domain kept elsewhere at >= severity
    ]
    index: int


class FilterDiagnostics(BaseModel):
    """Counts + human-readable warnings about what Step 2 threw away. Exists so a
    caller can observe data-quality problems WITHOUT the filter having to fail the
    request (spec 6.3). `warnings` is empty on a clean payload."""

    total_received: int
    total_kept: int
    total_dropped: int
    dropped_low: int
    dropped_missing_severity: int
    dropped_unknown_severity: int
    dropped_duplicate: int
    warnings: list[str] = []


class FilteredRoadmapResult(BaseModel):
    """The output of Step 2. Carries ONLY the actionable (High/Moderate) domains.

    Deliberately NOT a subclass of RoadmapResult (Liskov): a filtered result is
    not substitutable for a complete one, and a downstream module that treated it
    as 'all the user's domains' would be silently, dangerously wrong."""

    user_id: str
    classification: Literal["ND", "NT"]
    classification_raw: str
    filtered_scores: list[FilteredDomainScore]
    dropped: list[DroppedDomain]
    diagnostics: FilterDiagnostics

    @property
    def is_empty(self) -> bool:
        """True when NO domain was actionable. A legitimate, non-error outcome:
        the user scored Low everywhere. Callers MUST handle this."""
        return len(self.filtered_scores) == 0


class RoadmapSubmitResponse(BaseModel):
    """Success acknowledgement returned by POST /roadmap/submit. Echoes only
    identifiers and counts -- never the scores themselves, which the frontend
    already holds. `context_ready` confirms the result was persisted and a
    context can be built on the next chat turn. The Step 2 filter fields are
    additive and defaulted, so a pre-Step-2 client is unaffected."""

    status: Literal["accepted"]
    user_id: str
    classification: Literal["ND", "NT"]
    domains_received: int
    context_ready: bool
    domains_actionable: int = 0
    domains_filtered_out: int = 0
    filter_warnings: list[str] = []
