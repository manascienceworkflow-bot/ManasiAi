"""Roadmap Step 2 -- Domain -> Therapy Mapping.

Joins two already-loaded inputs and answers exactly one question per actionable
domain: which therapies does the mapping table list, and in what order?

  FilteredRoadmapResult (High/Moderate domains, from the severity filter)
  MappingBundle         (the two therapy-mapping tables, from mapping_loader)
        --map_domains_to_therapies()-->  DomainTherapyResult

PURE and INJECTED. Both inputs are parameters; this module never opens an .xlsx,
never calls the loader or the severity filter, never persists, and never mutates
either input. Given the same two inputs it returns the same result, forever.

It does NOT filter severity, dedupe therapies, rank them, group Spine vs
Complementary (the `Track` column is carried but not interpreted), or generate a
roadmap -- those build FROM this output in later modules.

The one non-obvious job it DOES own (the loader deliberately defers it, see
mapping_models.ModalityRow): the Excel Domain column is merged, so continuation
rows arrive with domain=None, and Excel domains are ordinal-prefixed
("A. Sensory Processing") while the incoming domain is bare ("Sensory
Processing"). Matching therefore forward-fills the Domain column into a
read-only local index (S9.2) and compares on a prefix/case/whitespace-insensitive
key (S9.3). Neither touches the loaded reference data.

Public surface
--------------
- ``map_domains_to_therapies(filtered, bundle, *, strict=False)`` -- the mapping.

See .claude/spec/manasi-ai-roadmap-step2-therapy-mapping-spec.md
"""

import logging
import re
import unicodedata
from typing import Optional

from app.roadmap.mapping_models import MappingBundle, MappingDataset
from app.roadmap.models import FilteredRoadmapResult
from app.roadmap.therapy_models import (
    DomainTherapyMapping,
    DomainTherapyResult,
    TherapyMappingDiagnostics,
    TherapyRef,
    UnmappedDomain,
)

logger = logging.getLogger("app.roadmap.therapy_mapper")


class TherapyMappingError(Exception):
    """The one error the mapper raises. Carries a machine-readable ``code`` (see
    spec S11), a human ``message``, and -- when they apply -- the ``classification``
    and offending ``domain``. Mirrors ``MappingLoadError`` / ``RoadmapValidationError``."""

    def __init__(
        self,
        code: str,
        message: str,
        classification: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.classification = classification
        self.domain = domain


# A leading ordinal label the source tables prefix onto domain names -- "A. ",
# "1) ", "iv. ". Stripped ONLY when deriving the comparison key; the original is
# never altered. The trailing \s+ requires a separator so a real one-word domain
# like "Sleep" is never mistaken for a "S" + "leep" prefix.
_ORDINAL_PREFIX = re.compile(r"^\s*[A-Za-z0-9]+[.)]\s+")


def domain_key(value: object) -> Optional[str]:
    """Throwaway canonical key for matching a domain name -- NEVER written to any
    output. Applied to BOTH sides (mapping-table domain and incoming domain).

    None/non-str -> None (no match). Otherwise: NFKC normalize (folds fullwidth
    and other compatibility forms, as severity_filter._normalize does), strip a
    leading ordinal prefix, collapse whitespace, and casefold (the Unicode-correct
    caseless match). "A. Sensory Processing" and "sensory   PROCESSING" both key
    to "sensory processing".
    """
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize("NFKC", value)
    text = _ORDINAL_PREFIX.sub("", text)
    key = " ".join(text.split()).casefold()
    return key or None


class _DomainGroup:
    """A matched domain's therapies, in mapping-table order. Local and mutable
    while the index is being built; its `rows` reference the loader's frozen
    ModalityRow objects by reference -- they are never mutated."""

    __slots__ = ("display_name", "rows")

    def __init__(self, display_name: str) -> None:
        self.display_name = display_name  # verbatim, e.g. "A. Sensory Processing"
        self.rows: list = []


def _build_domain_index(
    dataset: MappingDataset,
) -> tuple[dict[str, _DomainGroup], list[str]]:
    """Forward-fill the merged Domain column into a read-only key -> group index.

    Walks `dataset.rows` ONCE in file order, carrying the last non-blank domain
    forward so continuation rows (domain=None) join the domain above them. A
    therapy row that appears before any domain header is an orphan -- it cannot be
    attributed, so it is warned and skipped. Returns (index, warnings). The
    loaded rows are only READ and appended by reference; nothing is mutated.
    """
    index: dict[str, _DomainGroup] = {}
    warnings: list[str] = []
    current_key: Optional[str] = None

    for row in dataset.rows:
        if row.domain is not None and row.domain.strip() != "":
            current_key = domain_key(row.domain)
            if current_key is not None and current_key not in index:
                index[current_key] = _DomainGroup(display_name=row.domain)
        if current_key is None:
            msg = f"row {row.source_row}: therapy {row.modality!r} before any domain header -- skipped"
            warnings.append(msg)
            logger.warning("[%s] orphan therapy row skipped: row=%d", dataset.source, row.source_row)
            continue
        index[current_key].rows.append(row)

    return index, warnings


def map_domains_to_therapies(
    filtered: FilteredRoadmapResult,
    bundle: MappingBundle,
    *,
    strict: bool = False,
) -> DomainTherapyResult:
    """Map each actionable domain to its therapies using the loaded mapping tables.

    `filtered` is the severity filter's output (High/Moderate domains only);
    `bundle` is the mapping loader's output (both workbooks). Selects the ND or NT
    table by `filtered.classification`, resolves the merged Domain column, and
    returns every therapy for each matched domain in mapping-table order, with
    `relevance` preserved verbatim.

    strict=False (production): an unknown domain / empty dataset is recorded and
      warned, never raised -- a completed assessment must not 5xx because one
      domain label drifted.
    strict=True (contract tests / batch): the same conditions raise
      `TherapyMappingError`.

    Raises `TypeError` for wrong-typed arguments (a caller bug), and
    `TherapyMappingError` for a classification outside {ND, NT} (always) or, in
    strict mode, an empty dataset / unmatched domain.
    """
    if not isinstance(filtered, FilteredRoadmapResult):
        raise TypeError(
            f"map_domains_to_therapies expects a FilteredRoadmapResult (the severity "
            f"filter's output); got {type(filtered).__name__}. Do not pass raw JSON or "
            f"an unfiltered RoadmapResult."
        )
    if not isinstance(bundle, MappingBundle):
        raise TypeError(
            f"map_domains_to_therapies expects a MappingBundle (the mapping loader's "
            f"output); got {type(bundle).__name__}. Load it via mapping_loader and pass "
            f"it in -- this module never opens an .xlsx."
        )

    classification = filtered.classification
    logger.info(
        "mapping started: user_id=%s classification=%s domains=%d",
        filtered.user_id,
        classification,
        len(filtered.filtered_scores),
    )

    # ---- Dataset selection (S9.1). ----
    if classification == "ND":
        dataset = bundle.neurodivergent
        logger.info("ND dataset selected: rows=%d", dataset.row_count)
    elif classification == "NT":
        dataset = bundle.neurotypical
        logger.info("NT dataset selected: rows=%d", dataset.row_count)
    else:
        # Defensive: FilteredRoadmapResult.classification is Literal["ND","NT"], so
        # this is unreachable in normal flow -- but a bad selector can yield no
        # correct answer, so we never guess.
        logger.error("mapping failed: code=unknown_classification classification=%r", classification)
        raise TherapyMappingError(
            "unknown_classification",
            f"classification {classification!r} is not one of ND/NT.",
            classification=str(classification),
        )

    try:
        index, warnings = _build_domain_index(dataset)
        logger.debug("domain index built: keys=%d source=%s", len(index), dataset.source)

        if not index:
            logger.warning("empty mapping dataset: source=%s", dataset.source)
            if strict:
                raise TherapyMappingError(
                    "empty_dataset",
                    f"mapping dataset {dataset.source} produced no domains.",
                    classification=classification,
                )

        # A legitimate, non-error outcome: the user scored Low everywhere. Return
        # an empty result (callers MUST handle it) rather than an error.
        if filtered.is_empty:
            logger.info(
                "mapping skipped: user_id=%s no actionable domains", filtered.user_id
            )
            return _result(filtered, dataset, [], [], warnings)

        mappings: list[DomainTherapyMapping] = []
        unmapped: list[UnmappedDomain] = []

        for score in filtered.filtered_scores:
            key = domain_key(score.domain)
            group = index.get(key) if key is not None else None

            if group is None:
                reason = "empty_dataset" if not index else "domain_not_found"
                logger.warning(
                    "domain not found: user_id=%s domain=%r source=%s",
                    filtered.user_id,
                    score.domain,
                    dataset.source,
                )
                if strict and reason == "domain_not_found":
                    raise TherapyMappingError(
                        "domain_not_found",
                        f"domain {score.domain!r} has no mapping in dataset {dataset.source}.",
                        classification=classification,
                        domain=score.domain,
                    )
                unmapped.append(
                    UnmappedDomain(
                        domain=score.domain,
                        domain_type=score.domain_type,
                        severity=score.severity,
                        reason=reason,
                    )
                )
                continue

            # Every row in the group, in mapping-table order, VERBATIM. No dedup,
            # no sort, no ranking; relevance (incl. None) carried through.
            therapies = tuple(
                TherapyRef(
                    therapy=row.modality,
                    relevance=row.relevance,
                    source_row=row.source_row,
                )
                for row in group.rows
            )
            mappings.append(
                DomainTherapyMapping(
                    domain=score.domain,
                    domain_type=score.domain_type,
                    severity=score.severity,
                    matched_domain=group.display_name,
                    therapies=therapies,
                )
            )
            logger.debug(
                "domain matched: user_id=%s domain=%r therapies=%d",
                filtered.user_id,
                score.domain,
                len(therapies),
            )

        result = _result(filtered, dataset, mappings, unmapped, warnings)
        logger.info(
            "mapping complete: user_id=%s mapped=%d unmapped=%d therapies=%d",
            filtered.user_id,
            result.diagnostics.total_mapped,
            result.diagnostics.total_unmapped,
            result.diagnostics.total_therapies,
        )
        return result
    except TherapyMappingError:
        raise
    except Exception as exc:  # never leak a raw traceback as the module's contract
        logger.error("mapping failed: code=internal_error: %s", exc)
        raise TherapyMappingError(
            "internal_error", f"unexpected mapping failure: {exc}", classification=classification
        ) from exc


def _result(
    filtered: FilteredRoadmapResult,
    dataset: MappingDataset,
    mappings: list[DomainTherapyMapping],
    unmapped: list[UnmappedDomain],
    warnings: list[str],
) -> DomainTherapyResult:
    total_therapies = sum(len(m.therapies) for m in mappings)
    diagnostics = TherapyMappingDiagnostics(
        classification=filtered.classification,
        dataset_source=dataset.source,
        total_domains=len(filtered.filtered_scores),
        total_mapped=len(mappings),
        total_unmapped=len(unmapped),
        total_therapies=total_therapies,
        warnings=tuple(warnings),
    )
    return DomainTherapyResult(
        user_id=filtered.user_id,
        classification=filtered.classification,
        mappings=tuple(mappings),
        unmapped=tuple(unmapped),
        diagnostics=diagnostics,
    )
