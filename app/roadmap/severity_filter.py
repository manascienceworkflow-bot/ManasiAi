"""Step 2 of the Roadmap Assessment Pipeline: severity filtering.

Keeps ONLY the domains the frontend's scoring engine flagged High or Moderate --
these are the "actionable" domains that downstream steps (therapy mapping,
roadmap generation) operate on. Low, missing, and unrecognized severities are
excluded and recorded.

PURE. No persistence, no network, no LLM, no mutation of the input. Given the
same RoadmapResult it returns the same FilteredRoadmapResult, forever. The
absence of any client/session parameter in the signature is what enforces that --
do not add one.

See .claude/spec/manasi-ai-roadmap-step2-severity-filter-spec.md
"""

import logging
import unicodedata
from typing import Optional

from app.roadmap.models import (
    DroppedDomain,
    FilterDiagnostics,
    FilteredDomainScore,
    FilteredRoadmapResult,
    RoadmapResult,
)
from app.roadmap.roadmap_loader import RoadmapValidationError

logger = logging.getLogger("app.roadmap.severity_filter")

# The ONE definition of the severity vocabulary. Rank drives both membership and
# duplicate resolution (higher wins). Adding a level is a one-line change here;
# the algorithm below never branches on a literal, which is what keeps this
# open for extension and closed for modification.
_SEVERITY_RANK: dict[str, int] = {"low": 1, "moderate": 2, "high": 3}

ACTIONABLE_SEVERITIES: frozenset[str] = frozenset({"high", "moderate"})
EXCLUDED_SEVERITIES: frozenset[str] = frozenset(_SEVERITY_RANK) - ACTIONABLE_SEVERITIES

# Resource guard on an endpoint that has no authentication in front of it. Real
# assessments carry 5-15 domains, so this can never reject a legitimate user.
MAX_DOMAINS: int = 500

assert ACTIONABLE_SEVERITIES <= _SEVERITY_RANK.keys(), (
    "every actionable severity must also be ranked"
)


def _normalize(value: object) -> Optional[str]:
    """Derive a canonical comparison key. Returns None for absent/blank input.

    NFKC first -- it folds fullwidth and other compatibility forms, so a crafted
    severity cannot look like "Low" in a log while comparing as something else.
    Then strip, collapse internal whitespace, and casefold (the Unicode-correct
    caseless match; .lower() is not).

    READ-ONLY: the caller carries the ORIGINAL string into the output verbatim.
    """
    if not isinstance(value, str):
        return None
    key = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    return key or None


def filter_by_severity(
    result: RoadmapResult, *, strict: bool = False
) -> FilteredRoadmapResult:
    """Keep only the High/Moderate domains; drop and record everything else.

    strict=False (production): an unrecognized or missing severity DROPS that
      domain, warns, and records it -- it never fails the request. A user who
      completed a 40-minute assessment must not get a 422 because one domain came
      back "Borderline".
    strict=True (contract tests / batch): the same condition raises instead.
    """
    if not isinstance(result, RoadmapResult):
        raise TypeError(
            f"filter_by_severity expects a RoadmapResult (the output of Step 1's "
            f"load_roadmap); got {type(result).__name__}. Do not pass raw JSON -- "
            f"parsing the wire format is the loader's job."
        )

    entries = result.scores
    if len(entries) > MAX_DOMAINS:
        logger.error(
            "filter rejected: user_id=%s domains=%d exceeds MAX_DOMAINS=%d",
            result.user_id,
            len(entries),
            MAX_DOMAINS,
        )
        raise RoadmapValidationError(
            "payload_too_large",
            f"score array carries {len(entries)} domains; the maximum is {MAX_DOMAINS}.",
            "score",
        )

    kept: list[FilteredDomainScore] = []
    dropped: list[DroppedDomain] = []
    warnings: list[str] = []
    by_domain: dict[str, int] = {}  # normalized domain -> slot in `kept`
    origin: dict[str, int] = {}  # normalized domain -> original index of the incumbent

    for i, entry in enumerate(entries):
        key = _normalize(entry.severity)

        # Not a usable severity: missing/null/blank, or outside the vocabulary.
        if key is None or key not in _SEVERITY_RANK:
            missing = key is None
            code = "missing_severity" if missing else "unknown_severity"
            if missing:
                message = (
                    f"score[{i}] {entry.domain!r}: severity is missing or null; "
                    f"domain excluded from the actionable set."
                )
            else:
                message = (
                    f"score[{i}] {entry.domain!r}: severity {entry.severity!r} is not a "
                    f"recognized level (expected High/Moderate/Low); domain excluded "
                    f"from the actionable set."
                )
            if strict:
                raise RoadmapValidationError(code, message, f"score[{i}].Severity")
            # %r, not %s -- an attacker-controlled value must not be able to forge
            # a log line with an embedded newline.
            logger.warning(
                "filter drop(%s): user_id=%s idx=%d domain=%s severity=%r",
                code,
                result.user_id,
                i,
                entry.domain,
                entry.severity,
            )
            dropped.append(
                DroppedDomain(
                    domain=entry.domain, severity=entry.severity, reason=code, index=i
                )
            )
            warnings.append(message)
            continue

        # Known-good but deliberately excluded (Low). This is the single most
        # common event in the system, so it is DEBUG -- logging it at WARNING
        # would desensitize on-call to the genuine anomalies above.
        if key in EXCLUDED_SEVERITIES:
            logger.debug(
                "filter drop(low): user_id=%s idx=%d domain=%s",
                result.user_id,
                i,
                entry.domain,
            )
            dropped.append(
                DroppedDomain(
                    domain=entry.domain,
                    severity=entry.severity,
                    reason="low_severity",
                    index=i,
                )
            )
            continue

        # Actionable. Resolve duplicates before keeping.
        rank = _SEVERITY_RANK[key]
        domain_key = _normalize(entry.domain) or entry.domain.casefold()

        if domain_key in by_domain:
            slot = by_domain[domain_key]
            incumbent = kept[slot]
            # HIGHER SEVERITY ALWAYS WINS; a tie keeps the first occurrence. This
            # makes the outcome invariant under input reordering and guarantees a
            # more-severe signal is never discarded because of payload order.
            if rank > incumbent.severity_rank:
                kept[slot] = FilteredDomainScore(
                    domain=entry.domain,
                    domain_type=entry.domain_type,
                    score=entry.score,
                    severity=entry.severity,
                    severity_key=key,
                    severity_rank=rank,
                )
                # The incumbent lost -- record it at ITS original index, not i.
                dropped.append(
                    DroppedDomain(
                        domain=incumbent.domain,
                        severity=incumbent.severity,
                        reason="duplicate_domain",
                        index=origin[domain_key],
                    )
                )
                origin[domain_key] = i
            else:
                dropped.append(
                    DroppedDomain(
                        domain=entry.domain,
                        severity=entry.severity,
                        reason="duplicate_domain",
                        index=i,
                    )
                )
            logger.warning(
                "filter dedupe: user_id=%s domain=%s idx=%d severity=%r",
                result.user_id,
                entry.domain,
                i,
                entry.severity,
            )
            warnings.append(
                f"score[{i}] {entry.domain!r}: duplicate domain; kept the "
                f"highest-severity entry."
            )
            continue

        logger.debug(
            "filter keep: user_id=%s idx=%d domain=%s severity=%s",
            result.user_id,
            i,
            entry.domain,
            key,
        )
        by_domain[domain_key] = len(kept)
        origin[domain_key] = i
        # A NEW model built from the entry's values, so nothing downstream can
        # reach back and mutate the caller's RoadmapResult.
        kept.append(
            FilteredDomainScore(
                domain=entry.domain,
                domain_type=entry.domain_type,
                score=entry.score,
                severity=entry.severity,
                severity_key=key,
                severity_rank=rank,
            )
        )

    # Every input entry landed in exactly one bucket. A violation means the
    # decision table above has a hole, and it must be loud rather than silently
    # eating a domain out of someone's clinical roadmap.
    assert len(kept) + len(dropped) == len(entries), (
        f"filter accounting violated: {len(kept)} kept + {len(dropped)} dropped "
        f"!= {len(entries)} received"
    )

    diagnostics = FilterDiagnostics(
        total_received=len(entries),
        total_kept=len(kept),
        total_dropped=len(dropped),
        dropped_low=sum(d.reason == "low_severity" for d in dropped),
        dropped_missing_severity=sum(d.reason == "missing_severity" for d in dropped),
        dropped_unknown_severity=sum(d.reason == "unknown_severity" for d in dropped),
        dropped_duplicate=sum(d.reason == "duplicate_domain" for d in dropped),
        warnings=warnings,
    )

    if not kept:
        logger.info(
            "filter complete: user_id=%s NO actionable domains (all %d were low/excluded)",
            result.user_id,
            len(entries),
        )
    else:
        logger.info(
            "filter complete: user_id=%s received=%d kept=%d dropped=%d "
            "(low=%d missing=%d unknown=%d dup=%d)",
            result.user_id,
            diagnostics.total_received,
            diagnostics.total_kept,
            diagnostics.total_dropped,
            diagnostics.dropped_low,
            diagnostics.dropped_missing_severity,
            diagnostics.dropped_unknown_severity,
            diagnostics.dropped_duplicate,
        )

    return FilteredRoadmapResult(
        user_id=result.user_id,
        classification=result.classification,
        classification_raw=result.classification_raw,
        filtered_scores=kept,
        dropped=dropped,
        diagnostics=diagnostics,
    )
