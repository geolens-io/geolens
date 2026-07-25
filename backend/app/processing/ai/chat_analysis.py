"""AI-chat ``run_analysis`` tool: parameterized PostGIS previews (M4 Phase 5).

Split out of ``chat_actions.py`` to keep that module inside its line budget
(test_layering.test_decomposed_service_modules_stay_within_size_budgets),
following the existing ``chat_styles`` / ``chat_geojson`` sibling pattern.

Reuses the catalog analysis service through ``ProcessingPort`` — the same
server-built SQL, Pydantic param validation, and read-only sandbox rails as
the ``/datasets/{id}/analysis/preview/`` endpoint. No LLM-authored SQL is
involved anywhere on this path: the model only picks an operation enum and a
bounded number.
"""

from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.platform.sandbox import SandboxError
from app.processing.ai.chat_constants import ERROR_MESSAGES
from app.processing.ai.schemas import ChatMapLayer

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)


async def handle_run_analysis(
    tool_input: dict,
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    layers: list[ChatMapLayer],
    *,
    port: "ProcessingPort",
) -> dict:
    """Run one parameterized PostGIS operation on a layer and return a preview.

    Always returns a tool-result dict — never raises — so a failed analysis
    degrades to a message the model can react to instead of breaking the turn.
    """
    try:
        return await _run_analysis(
            tool_input, session, user, user_roles, layers, port=port
        )
    except Exception as e:  # broad: analysis/sandbox layer can throw varied DB errors; map to user-facing fallback
        logger.warning("run_analysis.failed", error=str(e), error_type=type(e).__name__)
        return {"error": "Could not run that analysis."}


async def _run_analysis(
    tool_input: dict,
    session: AsyncSession,
    user: Identity,
    user_roles: set[str],
    layers: list[ChatMapLayer],
    *,
    port: "ProcessingPort",
) -> dict:
    """Resolve the layer's dataset, authorize it, and run the preview.

    The dataset is resolved from ``layer.dataset_id`` and then re-checked with
    ``check_dataset_access`` (AGENTS.md Rule 1) — the layer list is
    client-supplied, so neither its dataset_id nor its table name may be
    trusted as evidence of access.
    """
    layer = next((lyr for lyr in layers if lyr.id == tool_input.get("layer_id")), None)
    if layer is None:
        return {
            "error": "That layer is not on this map — pick one of the listed layers."
        }

    try:
        dataset_id = UUID(str(layer.dataset_id))
    except ValueError:
        # Malformed client-supplied id — same user-facing outcome as a miss.
        return {"error": "That layer's dataset is no longer available."}
    dataset = await port.get_dataset(session, dataset_id)
    if dataset is None:
        return {"error": "That layer's dataset is no longer available."}

    try:
        await port.check_dataset_access(
            session, dataset, dataset.id, user, user_roles=user_roles
        )
    except HTTPException:
        # check_dataset_access signals denial with a 404 — anything else is a
        # real failure and belongs in the generic handler, not reported to the
        # user as an access problem.
        logger.info("run_analysis.access_denied", dataset_id=str(dataset.id))
        return {"error": "You don't have access to that layer's dataset."}

    if not dataset.geometry_type or not dataset.table_name:
        return {"error": "That layer has no geometry to analyze."}

    # fix(#674 review P2): only buffer consumes distance_meters. The tool schema
    # calls it "ignored otherwise", so a model may well send a placeholder 0 on a
    # centroid call — forwarding that would trip AnalysisPreviewRequest's gt=0
    # bound and fail a perfectly valid preview. Drop it for every other op.
    operation = tool_input.get("operation")
    distance_meters = (
        tool_input.get("distance_meters") if operation == "buffer" else None
    )

    try:
        result = await port.run_analysis_preview(
            session,
            dataset,
            operation,
            user_id=user.id,
            distance_meters=distance_meters,
        )
    except ValueError as exc:
        # Pydantic/param validation (bad enum, missing or out-of-range
        # distance) — hand the reason back so the model can retry correctly.
        return {"error": str(exc)}
    except SandboxError as exc:
        return {
            "error": ERROR_MESSAGES.get(
                exc.category, "The analysis could not be completed."
            ),
            "category": exc.category,
        }

    out: dict = {
        "operation": operation,
        "layer_id": layer.id,
        "feature_count": result.feature_count,
        "truncated": result.truncated,
    }
    if distance_meters is not None:
        # feat(#675): ride the sanitized buffer distance along so the action
        # collector can hand the preview off to the Analysis panel prefilled.
        out["distance_meters"] = distance_meters
    if result.feature_count == 0:
        out["note"] = "The operation produced no geometry for this layer."
        return out
    out["geojson"] = result.geojson
    out["bbox"] = result.bbox
    if result.truncated:
        # Surface the source total so the map badge can say "500 of N" rather
        # than presenting a capped preview as the whole result. buffer and
        # centroid are 1:1 per feature, so the source count IS the output total.
        out["source_feature_count"] = getattr(dataset, "feature_count", None)
    # Deliberately surface-neutral: view-only callers get this tool too (it is
    # read-only), and they land on the public viewer, which has no Analysis
    # rail — BuilderRail is rendered by MapBuilderPage alone. Naming the panel
    # here told half the audience to use something they cannot reach.
    out["note"] = "This preview is temporary and is not saved."
    return out


def collect_run_analysis_action(result: dict) -> dict | None:
    """Build the map action for a run_analysis result, or None when there is none.

    run_analysis reuses ``show_query_result`` purely as the ephemeral-overlay
    carrier: geojson + bbox (+ the truncation pair), never columns/rows. Every
    chat surface already renders geojson+bbox (fly-to + overlay) and skips the
    inline data table when ``rows`` is absent — a gid-only table would be noise.

    ``truncated``/``row_count`` ride along only when the 500-feature cap
    actually bit, so EphemeralBadge can say "500 of 10,651 features" instead of
    presenting a capped preview as the complete result.
    """
    if "error" in result:
        return None
    if not (result.get("bbox") and "geojson" in result):
        # fix(#676): an empty preview still emits a geometry-less marker so the
        # frontend clears a stale overlay from an earlier turn — with no action
        # at all, the previous overlay (and its badge) keeps describing a
        # result the chat text has moved past.
        return {"type": "show_query_result", "row_count": 0}
    action = {
        "type": "show_query_result",
        "geojson": result["geojson"],
        "bbox": result["bbox"],
    }
    # feat(#675): carry the params needed to reconstruct the request so the
    # builder can offer a one-click "Save as dataset" handoff into the
    # Analysis panel. The viewer surface ignores them (no Analysis rail).
    if result.get("operation") and result.get("layer_id"):
        action["operation"] = result["operation"]
        action["layer_id"] = result["layer_id"]
        if result.get("distance_meters") is not None:
            action["distance_meters"] = result["distance_meters"]
    total = result.get("source_feature_count")
    if result.get("truncated") and total:
        action["truncated"] = True
        action["row_count"] = total
    return action
