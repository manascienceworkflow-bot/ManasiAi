from typing import Literal, Optional, TypedDict

from pydantic import BaseModel


class RoadmapDomainScore(BaseModel):
    """One domain's result exactly as the frontend scoring engine produced it.
    `score` and `severity` are stored verbatim and are NEVER recomputed,
    rounded, or re-ranked by the backend (spec P1) -- `score` is typed as a
    union because the frontend may send a percentage as a bare number (72) or
    as a string ("72%"), and we preserve whichever arrived."""

    domain: str
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


class RoadmapSubmitResponse(BaseModel):
    """Success acknowledgement returned by POST /roadmap/submit. Echoes only
    identifiers and counts -- never the scores themselves, which the frontend
    already holds. `context_ready` confirms the result was persisted and a
    context can be built on the next chat turn."""

    status: Literal["accepted"]
    user_id: str
    classification: Literal["ND", "NT"]
    domains_received: int
    context_ready: bool
