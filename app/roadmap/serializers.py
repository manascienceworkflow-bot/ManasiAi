"""Serialization layer for the Roadmap Domain -> Therapy Mapping API.

This is the ONLY place the internal, `frozen` therapy models (and the score the
severity filter carries) are flattened into the public JSON contract returned by
`POST /roadmap/mapped-therapies`. It owns the wire shape so the frontend never
sees Python objects, tuples, `source_row`, `matched_domain`, or diagnostics.

It adds NO business logic: therapies, relevance, domain, domain_type, and severity
are carried through VERBATIM from the mapper's output; `score` is the one field the
mapper does not carry, so it is joined back from the severity filter's output using
the mapper's own `domain_key` (the same canonical key the mapping join used).

See .claude/spec/manasi-ai-roadmap-step3-mapped-therapy-api-spec.md
"""

import logging
from typing import Literal, Optional, Union

from pydantic import BaseModel

from app.roadmap.models import FilteredRoadmapResult
from app.roadmap.therapy_mapper import domain_key
from app.roadmap.therapy_models import DomainTherapyResult

logger = logging.getLogger("app.roadmap.serializers")


class TherapyOut(BaseModel):
    """One therapy in the response -- name + relevance label, nothing else. The
    internal `source_row` provenance is deliberately dropped."""

    therapy: str
    relevance: Optional[str] = None


class MappedDomainOut(BaseModel):
    """One matched domain with its therapies. `score` is joined back from the
    filtered scores (the mapper does not carry it) and is Optional only as a
    defensive fallback: under normal operation every matched domain has a score.
    The internal `matched_domain` is dropped; therapies are a plain list."""

    domain: str
    domain_type: Optional[str] = None
    score: Optional[Union[str, float, int]] = None
    severity: Optional[str] = None
    therapies: list[TherapyOut]


class AggregatedTherapyOut(BaseModel):
    """One unique therapy in the therapy-centric view -- the same therapy is
    emitted once no matter how many domains recommend it. `domains` is every unique
    domain that recommended it (first-seen order); `relevance` is every unique
    non-empty relevance label seen for it (first-seen order), empty if none. All
    strings are first-seen VERBATIM spellings; casing is used only for dedup keys.
    Built by therapy_aggregator.aggregate_therapies."""

    therapy: str
    domains: list[str]
    relevance: list[str] = []


class MappedTherapyResponse(BaseModel):
    """The public contract for POST /roadmap/mapped-therapies. Flat, list-based,
    JSON-safe. `mapped_domains` may be empty (a legitimate all-Low / all-unmatched
    outcome, not an error).

    `aggregated_therapies` is an ADDITIVE, therapy-centric view of the same data:
    the domain-centric `mapped_domains` transposed so each therapy appears once,
    with its recommending domains merged. It exists so the frontend renders no
    duplicate therapy cards; `mapped_domains` is left untouched for existing
    consumers. May be empty whenever `mapped_domains` is."""

    user_id: str
    classification: Literal["ND", "NT"]
    mapped_domains: list[MappedDomainOut]
    aggregated_therapies: list[AggregatedTherapyOut] = []


def build_mapped_response(
    filtered: FilteredRoadmapResult,
    mapped: DomainTherapyResult,
) -> MappedTherapyResponse:
    """Flatten the mapper's output into the public response, joining `score` back
    from the filtered scores.

    The mapper's `DomainTherapyResult` carries every field the contract needs
    EXCEPT `score`, which lives on the severity filter's `FilteredDomainScore`.
    Both describe the same actionable domains, so we index the filtered scores by
    the mapper's canonical `domain_key` and look each matched domain up by the same
    key -- order-independent and robust to the mapper's ordinal-prefix stripping.

    Matched-domain order (from the mapper) and therapy order (Excel order) are
    preserved; nothing is re-sorted, deduped, or re-cased.
    """
    score_by_key = {
        domain_key(fs.domain): fs.score for fs in filtered.filtered_scores
    }

    mapped_domains: list[MappedDomainOut] = []
    for m in mapped.mappings:
        key = domain_key(m.domain)
        if key in score_by_key:
            score = score_by_key[key]
        else:
            # Should be impossible: every matched domain came from a filtered
            # score. A miss means upstream drifted -- surface a null score and warn
            # rather than turning a successful mapping into a 500.
            score = None
            logger.warning("score_join_miss: domain=%r had no filtered score", m.domain)

        mapped_domains.append(
            MappedDomainOut(
                domain=m.domain,
                domain_type=m.domain_type,
                score=score,
                severity=m.severity,
                therapies=[
                    TherapyOut(therapy=t.therapy, relevance=t.relevance)
                    for t in m.therapies
                ],
            )
        )

    # Additive therapy-centric view: transpose the domain-centric list so each
    # therapy appears once. Derived from `mapped_domains` (not the frozen mapper
    # output) so the two views can never disagree. Local import breaks the cycle
    # (therapy_aggregator imports AggregatedTherapyOut from this module).
    from app.roadmap.therapy_aggregator import aggregate_therapies

    return MappedTherapyResponse(
        user_id=mapped.user_id,
        classification=mapped.classification,
        mapped_domains=mapped_domains,
        aggregated_therapies=aggregate_therapies(mapped_domains),
    )
