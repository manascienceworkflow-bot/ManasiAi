import logging

from app.roadmap.context_builder import build_context, empty_context, render_context_text
from app.roadmap.mapping_loader import get_mappings
from app.roadmap.roadmap_loader import load_roadmap
from app.roadmap.serializers import MappedTherapyResponse, build_mapped_response
from app.roadmap.severity_filter import filter_by_severity
from app.roadmap.therapy_mapper import map_domains_to_therapies

logger = logging.getLogger("app.roadmap.services")

ROADMAP_TABLE = "user_roadmap_results"


def submit_roadmap(payload, supabase) -> dict:
    """Orchestrate a roadmap submission: validate + normalize via the loader
    (Step 1), narrow to the actionable High/Moderate domains via the severity
    filter (Step 2), then upsert the result against the user (last write wins).
    Returns the ack dict shaped like RoadmapSubmitResponse. Raises
    RoadmapValidationError on a bad payload (the route maps it to 422/413); a
    persistence failure propagates so the route can surface a 503 -- an
    accepted-but-not-stored result would be a silent data-loss bug, so this path
    deliberately does NOT swallow it."""
    result = load_roadmap(payload)

    # Fail LOUD on the write path: a payload we cannot filter is a payload we do
    # not persist, so this runs BEFORE the upsert. The full result is still what
    # gets stored -- the filtered view is derived, not a replacement.
    filtered = filter_by_severity(result)

    supabase.table(ROADMAP_TABLE).upsert(
        {
            "user_id": result.user_id,
            "classification": result.classification,
            "result": result.model_dump(),
            "raw": result.raw,
            "updated_at": "now()",
        }
    ).execute()

    logger.info(
        "submit_roadmap stored: user_id=%s classification=%s domains=%d actionable=%d",
        result.user_id,
        result.classification,
        len(result.scores),
        filtered.diagnostics.total_kept,
    )
    return {
        "status": "accepted",
        "user_id": result.user_id,
        "classification": result.classification,
        "domains_received": len(result.scores),
        "context_ready": True,
        "domains_actionable": filtered.diagnostics.total_kept,
        "domains_filtered_out": filtered.diagnostics.total_dropped,
        "filter_warnings": filtered.diagnostics.warnings,
    }


def map_roadmap_therapies(payload) -> MappedTherapyResponse:
    """Run the completed Domain -> Therapy pipeline on a frontend payload and
    return the serialized response for the dashboard.

    Composes the EXISTING pipeline in order and adds no business logic:
      load_roadmap -> filter_by_severity -> get_mappings -> map_domains_to_therapies
    then flattens the result via the serialization layer. STATELESS -- unlike
    submit_roadmap this neither reads nor writes Supabase; it is a pure function of
    the request body, safe to retry.

    Both the severity filter and the therapy mapper run in their non-strict
    (production) posture: unknown/missing severities and unmatched domains are
    dropped/recorded, never raised. `get_mappings()` (not `load_mappings()`) is
    used so the Excel workbooks are read once and cached at module level.

    Raises RoadmapValidationError (bad payload -> 422/413), MappingLoadError
    (Excel data unavailable -> 500), or TherapyMappingError (-> 500); the route is
    the single place these map to HTTP status codes."""
    result = load_roadmap(payload)                          # Step 1
    filtered = filter_by_severity(result)                   # Step 2 (strict=False)
    bundle = get_mappings()                                 # cached Excel load
    mapped = map_domains_to_therapies(filtered, bundle)     # Step 3 (strict=False)

    logger.info(
        "map_roadmap_therapies: user_id=%s classification=%s actionable=%d mapped=%d unmapped=%d",
        result.user_id,
        result.classification,
        filtered.diagnostics.total_kept,
        mapped.diagnostics.total_mapped,
        mapped.diagnostics.total_unmapped,
    )
    return build_mapped_response(filtered, mapped)


def get_roadmap_context_text(user_id: str, supabase) -> str:
    """Fetch the user's active roadmap and render it for the chat chain. Fails
    SAFE: a missing roadmap, a malformed stored row, or any Supabase error all
    resolve to "" (empty context) so a chat turn is never broken by roadmap
    lookup. This is the read side's counterpart to submit's fail-loud posture."""
    try:
        response = (
            supabase.table(ROADMAP_TABLE)
            .select("result")
            .eq("user_id", user_id)
            .execute()
        )
        rows = response.data or []
        if not rows:
            return render_context_text(empty_context())

        stored = rows[0].get("result")
        # The stored result is already a validated RoadmapResult dump; re-run it
        # through the loader so a manually-edited or schema-drifted row can't feed
        # a malformed context downstream. `raw` is what load_roadmap needs.
        result = load_roadmap(stored.get("raw", stored))
        return render_context_text(build_context(result))
    except Exception as exc:
        logger.warning("get_roadmap_context_text fail-safe for user_id=%s: %s", user_id, exc)
        return render_context_text(empty_context())
