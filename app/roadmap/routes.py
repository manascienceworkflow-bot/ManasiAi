import logging

from fastapi import APIRouter, HTTPException, Request

from app.db import supabase
from app.roadmap.models import RoadmapSubmitResponse
from app.roadmap.roadmap_loader import RoadmapValidationError
from app.roadmap.services import submit_roadmap

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
        raise HTTPException(
            status_code=422,
            detail={"status": "rejected", "error": {"code": exc.code, "message": exc.message, "field": exc.field}},
        ) from exc
    except Exception as exc:
        logger.error("roadmap submit persistence failure: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"status": "error", "error": {"code": "persistence_unavailable", "message": "Roadmap store is temporarily unavailable."}},
        ) from exc

    return RoadmapSubmitResponse(**ack)
