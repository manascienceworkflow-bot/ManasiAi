"""Therapy Recommendation Aggregation -- transpose the domain-centric mapped view
into a therapy-centric one.

The mapped-therapy response (``MappedTherapyResponse.mapped_domains``) lists each
matched domain with its own therapies, so a therapy recommended by several domains
appears once per domain. This module collapses those occurrences into ONE object
per unique therapy, carrying the union of domains that recommended it and the set
of relevance labels seen -- so the frontend renders exactly one card per therapy.

PURE and DETERMINISTIC. No I/O, no clock, no randomness, no global state. Given the
same ``mapped_domains`` it returns the same list, forever. It carries therapy /
domain / relevance strings through VERBATIM (first-seen spelling); casing is used
only to build match keys, never to rewrite what the user sees.

Aggregates from the already-serialized ``list[MappedDomainOut]`` (not the internal
frozen mapper output) so the two views can never disagree -- both are derived from
the same data.

Public surface
--------------
- ``therapy_key(name)`` -- canonical case-insensitive identity key for a therapy.
- ``aggregate_therapies(domains)`` -- the O(n) domain->therapy transpose.

See .claude/spec/therapy-recommendation-aggregation.md
"""

import logging
import unicodedata
from typing import Optional

from app.roadmap.therapy_mapper import domain_key

logger = logging.getLogger("app.roadmap.therapy_aggregator")


def therapy_key(value: object) -> Optional[str]:
    """Throwaway canonical key for matching a therapy name -- NEVER written to any
    output. Two therapy names are the SAME therapy iff their keys are equal.

    None/non-str/blank -> None (no match). Otherwise: NFKC normalize (folds
    fullwidth and other compatibility forms), collapse whitespace, and casefold
    (the Unicode-correct caseless match). "MNRI", "mnri", "Mnri", and "  MNRI  "
    all key to "mnri".

    Unlike ``domain_key`` (therapy_mapper.py) this does NOT strip a leading ordinal
    prefix -- therapy names are not ordinal-labelled, and a real therapy could
    legitimately look like one ("B. Something").
    """
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value)
    key = " ".join(text.split()).casefold()
    return key or None


class _TherapyAcc:
    """Mutable accumulator for one unique therapy while a single aggregation pass
    runs. `domain_keys` / `relevance_seen` are transient dedup helpers and are
    NEVER emitted -- only `therapy`, `domains`, and `relevance` reach the output."""

    __slots__ = ("therapy", "domain_keys", "domains", "relevance_seen", "relevance")

    def __init__(self, therapy: str) -> None:
        self.therapy = therapy              # first-seen verbatim spelling
        self.domain_keys: set[str] = set()  # dedup by domain_key
        self.domains: list[str] = []        # ordered, unique, verbatim
        self.relevance_seen: set[str] = set()
        self.relevance: list[str] = []      # ordered, unique, verbatim


def aggregate_therapies(domains: list) -> list:
    """Transpose ``mapped_domains`` (domain -> therapies) into a therapy-centric
    list (therapy -> domains + relevance).

    `domains` is the serialized ``list[MappedDomainOut]``. Returns a
    ``list[AggregatedTherapyOut]`` (imported locally to avoid a circular import
    with the serializer that owns that model).

    Single pass, insertion-ordered: a therapy's position is fixed by its FIRST
    appearance walking domains in order and therapies in list order. Each therapy
    is emitted once; its `domains` are every unique domain that recommended it
    (first-seen order), and its `relevance` is every unique non-empty relevance
    label seen for it (first-seen order). O(n) in total (domain, therapy) pairs.

    Defensive (never raises on data quality): a domain with no name, a null/empty
    therapy object, or a therapy whose name keys to None is skipped and counted.
    """
    # Local import breaks the cycle: serializers imports this module.
    from app.roadmap.serializers import AggregatedTherapyOut

    order: list[str] = []            # therapy_keys in first-seen order
    by_key: dict[str, _TherapyAcc] = {}
    skipped_domains = 0
    skipped_therapies = 0

    for domain in domains or []:
        d_name = getattr(domain, "domain", None)
        if not d_name or not str(d_name).strip():
            skipped_domains += 1
            continue
        d_key = domain_key(d_name)

        for t in getattr(domain, "therapies", None) or []:
            t_name = getattr(t, "therapy", None)
            k = therapy_key(t_name)
            if k is None:
                skipped_therapies += 1
                continue

            acc = by_key.get(k)
            if acc is None:
                acc = _TherapyAcc(therapy=t_name)  # first-seen verbatim
                by_key[k] = acc
                order.append(k)

            # Union the domain (dedup by canonical key, keep verbatim name).
            if d_key is not None and d_key not in acc.domain_keys:
                acc.domain_keys.add(d_key)
                acc.domains.append(d_name)

            # Collect unique non-empty relevance labels, verbatim, first-seen order.
            rel = getattr(t, "relevance", None)
            rel = rel.strip() if isinstance(rel, str) else ""
            if rel and rel not in acc.relevance_seen:
                acc.relevance_seen.add(rel)
                acc.relevance.append(rel)

    if skipped_domains or skipped_therapies:
        logger.warning(
            "aggregate_therapies skipped malformed items: domains=%d therapies=%d",
            skipped_domains,
            skipped_therapies,
        )

    return [
        AggregatedTherapyOut(
            therapy=acc.therapy,
            domains=acc.domains,
            relevance=acc.relevance,
        )
        for k in order
        for acc in (by_key[k],)
    ]
