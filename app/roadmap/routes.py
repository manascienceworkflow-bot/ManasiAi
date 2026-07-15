import logging

from fastapi import APIRouter, HTTPException, Request

from app.db import supabase
from app.roadmap.mapping_loader import MappingLoadError
from app.roadmap.models import RoadmapSubmitResponse
from app.roadmap.roadmap_loader import RoadmapValidationError
from app.roadmap.serializers import MappedTherapyResponse
from app.roadmap.services import map_roadmap_therapies, submit_roadmap
from app.roadmap.therapy_mapper import TherapyMappingError

logger = logging.getLogger("app.roadmap.routes")

router = APIRouter(prefix="/roadmap", tags=["roadmap"])


@router.post("/submit", response_model=RoadmapSubmitResponse)
async def submit(request: Request) -> RoadmapSubmitResponse:
    """Receive the frontend roadmap score JSON, validate + normalize it, and
    persist it against the user. The raw body is read here and handed straight
    to the service/loader -- FastAPI does no schema coercion, so the loader stays
    the single owner of the wire format (spec P2). Validation failures become a
    422 naming the offending field; a persistence failure becomes a 503."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON.") from exc

    try:
        ack = submit_roadmap(payload, supabase)
    except RoadmapValidationError as exc:
        logger.info("roadmap submit rejected: code=%s field=%s", exc.code, exc.field)
        # An oversized score array is a payload-size problem, not a schema one --
        # a 422 would tell the frontend to fix fields that are perfectly valid.
        status_code = 413 if exc.code == "payload_too_large" else 422
        raise HTTPException(
            status_code=status_code,
            detail={"status": "rejected", "error": {"code": exc.code, "message": exc.message, "field": exc.field}},
        ) from exc
    except Exception as exc:
        logger.error("roadmap submit persistence failure: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "error": {"code": "persistence_unavailable", "message": "Roadmap store is temporarily unavailable."}},
        ) from exc

    return RoadmapSubmitResponse(**ack)


@router.post("/mapped-therapies", response_model=MappedTherapyResponse)
async def mapped_therapies(request: Request) -> MappedTherapyResponse:
    """Run the completed Domain -> Therapy mapping pipeline on the frontend roadmap
    JSON and return the mapped therapies as flat JSON for the dashboard. This is the
    frontend's only integration point for therapies -- the internal Pydantic/frozen
    models never cross the wire (the serialization layer flattens them).

    Stateless: no persistence, pure function of the body, safe to retry. The raw
    body is read here and handed straight to the loader (like /submit) so the loader
    stays the single owner of the wire format -- no FastAPI request-schema coercion.
    Errors reuse the pipeline's exception types: a bad payload becomes 422 (or 413
    for an oversized score array); missing Excel data or a mapping fault becomes 500.
    An empty actionable set is a SUCCESS (200 with mapped_domains: []), not an error."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Request body is not valid JSON.") from exc

    try:
        return map_roadmap_therapies(payload)
    except RoadmapValidationError as exc:
        logger.info("mapped-therapies rejected: code=%s field=%s", exc.code, exc.field)
        # An oversized score array is a payload-size problem, not a schema one.
        status_code = 413 if exc.code == "payload_too_large" else 422
        raise HTTPException(
            status_code=status_code,
            detail={"status": "rejected", "error": {"code": exc.code, "message": exc.message, "field": exc.field}},
        ) from exc
    except MappingLoadError as exc:
        logger.error("mapped-therapies mapping data unavailable: code=%s source=%s", exc.code, exc.source)
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "error": {"code": "mapping_data_unavailable", "message": "Therapy mapping data is temporarily unavailable."}},
        ) from exc
    except TherapyMappingError as exc:
        logger.error("mapped-therapies mapping failed: code=%s domain=%s", exc.code, exc.domain)
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "error": {"code": "therapy_mapping_failed", "message": "Could not map domains to therapies."}},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("mapped-therapies unexpected error")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "error": {"code": "internal_error", "message": "An unexpected error occurred."}},
        ) from exc
