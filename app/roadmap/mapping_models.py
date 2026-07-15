"""Immutable, verbatim data models for the roadmap Excel mapping loader.

These carry the contents of the two therapy-mapping workbooks
(Neurodivergent_map.xlsx / Neurotypical_map.xlsx) exactly as they appear on the
sheet -- no coercion, no forward-fill, no re-casing. They are the ONLY shape any
downstream module (therapy mapping, filtering, roadmap generation) is allowed to
read; nothing else re-opens an .xlsx file.

All three models are frozen: once the loader has built them, no caller can mutate
the loaded reference data (spec S3.3 -- the immutability guarantee).
"""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ModalityRow(BaseModel):
    """One row of a mapping sheet, VERBATIM.

    `domain`, `track`, and `relevance` are Optional because the source sheet uses
    merged / visually-grouped cells: a domain that suggests several modalities
    occupies several rows, and those columns are filled on the FIRST row only --
    on continuation rows they arrive as None. That None is preserved here (never
    forward-filled -- that is a mapping-step concern, out of scope for the loader).

    `modality` is the only always-present field: a row with no modality is not a
    content row and is never stored. `source_row` is the 1-based sheet row number,
    kept so a downstream module can forward-fill / cite provenance without this
    loader having interpreted anything.
    """

    model_config = ConfigDict(frozen=True)

    domain: Optional[str] = None
    track: Optional[str] = None
    modality: str
    relevance: Optional[str] = None
    source_row: int


class MappingDataset(BaseModel):
    """The fully-loaded contents of ONE workbook.

    `rows` are in file order, verbatim; no business meaning is attached to them by
    the loader. `warnings` is non-empty only in non-strict mode, when individual
    malformed rows were dropped rather than failing the whole load.
    """

    model_config = ConfigDict(frozen=True)

    source: Literal["ND", "NT"]
    path: str
    sheet_name: str
    header_row: int  # 1-based sheet row where the header was discovered
    rows: tuple[ModalityRow, ...]
    warnings: tuple[str, ...] = ()

    @property
    def row_count(self) -> int:
        return len(self.rows)


class MappingBundle(BaseModel):
    """What load_mappings() returns: both datasets, side by side.

    Deliberately NOT a dict keyed by a stringly-typed label -- the two paths are
    named fields so callers get autocompletion and cannot typo the key.
    """

    model_config = ConfigDict(frozen=True)

    neurodivergent: MappingDataset
    neurotypical: MappingDataset
