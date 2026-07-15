"""Immutable output models for the roadmap Domain -> Therapy mapping step.

These carry the result of joining the actionable (High/Moderate) domains from the
severity filter against the loaded therapy-mapping tables: for each matched
domain, the ordered list of therapies with their relevance labels, VERBATIM.

All models are frozen (spec S3.2, principle P1/P4): therapy names, relevance
labels, and the incoming domain/severity are carried through exactly as they
arrived -- never re-cased, trimmed-in-place, deduped, or ranked here. That is a
future roadmap-generation concern.

See .claude/spec/manasi-ai-roadmap-step2-therapy-mapping-spec.md
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class TherapyRef(BaseModel):
    """One therapy suggested for a domain, VERBATIM from a mapping row.

    `therapy` is the `ModalityRow.modality` (always present). `relevance` is
    carried through unchanged and MAY be None (a mapping row with no relevance
    label is preserved, not dropped). `source_row` is the 1-based sheet row the
    therapy came from -- provenance for downstream citation/debugging.
    """

    model_config = ConfigDict(frozen=True)

    therapy: str
    relevance: Optional[str] = None
    source_row: int


class DomainTherapyMapping(BaseModel):
    """All therapies mapped to ONE matched actionable domain.

    `domain`, `domain_type`, and `severity` are the INCOMING values (from the
    filtered assessment), carried verbatim. `domain_type` is the frontend's
    per-domain classification (e.g. "Spine"/"Complementary"), Optional and never
    interpreted here. `matched_domain` is the mapping-table label that matched
    (e.g. "A. Sensory Processing") -- kept as provenance so a consumer can see what
    the bare incoming "Sensory Processing" resolved to. `therapies` are in
    mapping-table row order; duplicates are NOT removed and the list is NOT ranked.
    """

    model_config = ConfigDict(frozen=True)

    domain: str
    domain_type: Optional[str] = None
    severity: Optional[str] = None
    matched_domain: str
    therapies: tuple[TherapyRef, ...]


class UnmappedDomain(BaseModel):
    """An actionable domain that produced NO therapies, with the reason.

    Recorded rather than silently dropped (principle P5) so a caller can observe
    every actionable domain's fate. `domain`/`domain_type`/`severity` are the
    incoming values, carried verbatim. `domain_type` is the frontend's per-domain
    classification -- preserved exactly as received, never inferred from the Excel
    `Track` column (an unmatched domain has no Excel row to derive it from anyway).
    """

    model_config = ConfigDict(frozen=True)

    domain: str
    domain_type: Optional[str] = None
    severity: Optional[str] = None
    reason: Literal["domain_not_found", "empty_dataset"]


class TherapyMappingDiagnostics(BaseModel):
    """Counts + human-readable warnings about the mapping run. Exists so a caller
    can observe data-quality problems (unmatched domains, an empty dataset)
    WITHOUT the mapper having to fail the request. `warnings` is empty on a clean
    run. `classification` is what the caller asked for; `dataset_source` is which
    workbook was actually selected -- they always agree, but both are recorded."""

    model_config = ConfigDict(frozen=True)

    classification: Literal["ND", "NT"]
    dataset_source: Literal["ND", "NT"]
    total_domains: int
    total_mapped: int
    total_unmapped: int
    total_therapies: int
    warnings: tuple[str, ...] = ()


class DomainTherapyResult(BaseModel):
    """What `map_domains_to_therapies()` returns.

    `mappings` holds the matched domains (in the order they arrived from the
    filter); `unmapped` holds the actionable domains that matched nothing. Every
    input domain appears in exactly one of the two. `to_list()` is the thin view
    matching the brief's JSON shape; the full object is what a future
    roadmap-generation step consumes.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str
    classification: Literal["ND", "NT"]
    mappings: tuple[DomainTherapyMapping, ...]
    unmapped: tuple[UnmappedDomain, ...]
    diagnostics: TherapyMappingDiagnostics

    def to_list(self) -> list[dict]:
        """The thin JSON view -- matched domains only. Extends the brief's shape
        with the frontend's `domain_type` (carried verbatim)."""
        return [
            {
                "domain": m.domain,
                "domain_type": m.domain_type,
                "severity": m.severity,
                "therapies": [
                    {"therapy": t.therapy, "relevance": t.relevance}
                    for t in m.therapies
                ],
            }
            for m in self.mappings
        ]
