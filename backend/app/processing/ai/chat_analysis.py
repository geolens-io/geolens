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
    layers: list[ChatMapLayer],
    *,
    port: "ProcessingPort",
) -> dict:
    """Run one parameterized PostGIS operation on a layer and return a preview.

    Always returns a tool-result dict — never raises — so a failed analysis
    degrades to a message the model can react to instead of breaking the turn.
    """
    try:
        return await _run_analysis(tool_input, session, user, layers, port=port)
    except Exception as e:  # broad: analysis/sandbox layer can throw varied DB errors; map to user-facing fallback
        logger.warning("run_analysis.failed", error=str(e), error_type=type(e).__name__)
        return {"error": "Could not run that analysis."}


async def _run_analysis(
    tool_input: dict,
    session: AsyncSession,
    user: Identity,
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
        dataset = await port.get_dataset(session, UUID(str(layer.dataset_id)))
    except (ValueError, AttributeError, TypeError):
        dataset = None
    if dataset is None:
        return {"error": "That layer's dataset is no longer available."}

    try:
        await port.check_dataset_access(session, dataset, dataset.id, user)
    except Exception:  # broad: access denial arrives as HTTPException(404) — must not break the chat turn
        logger.info("run_analysis.access_denied", dataset_id=str(dataset.id))
        return {"error": "You don't have access to that layer's dataset."}

    if not getattr(dataset, "geometry_type", None) or not getattr(
        dataset, "table_name", None
    ):
        return {"error": "That layer has no geometry to analyze."}

    try:
        result = await port.run_analysis_preview(
            session,
            dataset,
            tool_input.get("operation"),
            user_id=user.id,
            distance_meters=tool_input.get("distance_meters"),
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
        "operation": tool_input.get("operation"),
        "layer_id": layer.id,
        "feature_count": result.feature_count,
        "truncated": result.truncated,
    }
    if result.feature_count == 0:
        out["note"] = "The operation produced no geometry for this layer."
        return out
    out["geojson"] = result.geojson
    out["bbox"] = result.bbox
    out["note"] = (
        "Preview only — it is not saved. The user can save it as a dataset "
        "from the Analysis panel."
    )
    return out


def collect_run_analysis_action(result: dict) -> dict | None:
    """Build the map action for a run_analysis result, or None when there is none.

    run_analysis reuses ``show_query_result`` purely as the ephemeral-overlay
    carrier: geojson + bbox only, no columns/rows. Every chat surface already
    renders that pair (fly-to + overlay) and skips the inline data table when
    ``rows`` is absent — a gid-only table would be noise.
    """
    if result.get("bbox") and "geojson" in result:
        return {
            "type": "show_query_result",
            "geojson": result["geojson"],
            "bbox": result["bbox"],
        }
    return None
