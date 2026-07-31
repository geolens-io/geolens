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


async def _resolve_layer_dataset(
    session: AsyncSession,
    layer: ChatMapLayer,
    user: Identity,
    user_roles: set[str],
    *,
    port: "ProcessingPort",
    what: str = "layer",
):
    """Resolve one layer's dataset and authorize it, or return a tool error.

    Returns the dataset on success and an ``{"error": ...}`` dict otherwise,
    so callers stay linear. Shared by the source layer and (feat(#683)) the
    clip mask layer, because BOTH need the Rule-1 check: the layer list is
    client-supplied, so neither its dataset_id nor its table name is evidence
    of access.
    """
    try:
        dataset_id = UUID(str(layer.dataset_id))
    except ValueError:
        # Malformed client-supplied id — same user-facing outcome as a miss.
        return {"error": f"That {what}'s dataset is no longer available."}
    dataset = await port.get_dataset(session, dataset_id)
    if dataset is None:
        return {"error": f"That {what}'s dataset is no longer available."}

    try:
        await port.check_dataset_access(
            session, dataset, dataset.id, user, user_roles=user_roles
        )
    except HTTPException:
        # check_dataset_access signals denial with a 404 — anything else is a
        # real failure and belongs in the generic handler, not reported to the
        # user as an access problem.
        logger.info(
            "run_analysis.access_denied", dataset_id=str(dataset.id), which=what
        )
        return {"error": f"You don't have access to that {what}'s dataset."}
    return dataset


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

    dataset = await _resolve_layer_dataset(session, layer, user, user_roles, port=port)
    if isinstance(dataset, dict):
        return dataset

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

    # feat(#683): the mask layer is resolved and authorized SEPARATELY. Rule 1
    # applies to both datasets of a two-layer operation, and the layer list is
    # client-supplied either way, so seeing the source buys no claim on the
    # mask. The port checks the mask's shape but never its visibility.
    mask_dataset = None
    if operation == "clip":
        mask_layer = next(
            (lyr for lyr in layers if lyr.id == tool_input.get("mask_layer_id")), None
        )
        if mask_layer is None:
            return {
                "error": (
                    "Clipping needs a mask layer from this map — name one of "
                    "the listed layers as mask_layer_id."
                )
            }
        if mask_layer.id == layer.id:
            # Clipping a layer by itself is a no-op that costs a real query.
            return {"error": "The mask layer has to be a different layer."}
        mask_dataset = await _resolve_layer_dataset(
            session, mask_layer, user, user_roles, port=port, what="mask layer"
        )
        if isinstance(mask_dataset, dict):
            return mask_dataset
        # fix(#683 codex P2): distinct layer ids are NOT distinct data. A
        # duplicated rendering is two layers over one dataset, so the id check
        # above lets that pair through — and clipping a table by itself is an
        # expensive way to return the input. Identity is the DATASET.
        if mask_dataset.id == dataset.id:
            return {
                "error": (
                    "That mask layer shows the same dataset as the layer being "
                    "clipped. Pick a layer with different data."
                )
            }

    # fix(#683 codex P1): mask_dataset rides along only when set. A separately
    # distributed overlay that implements the pre-clip ProcessingPort rejects
    # the unknown keyword, and passing an unconditional None would break EVERY
    # chat analysis against such an overlay rather than only the new operation.
    # Same reasoning, same shape as the materialize defer in
    # router_analysis._defer. EXTENSION_API_VERSION is bumped alongside this,
    # so an overlay that DECLARES its version fails loudly at load instead;
    # this guard is for the legacy undeclared ones, which only warn.
    mask_kwargs = {"mask_dataset": mask_dataset} if mask_dataset is not None else {}

    try:
        result = await port.run_analysis_preview(
            session,
            dataset,
            operation,
            user_id=user.id,
            distance_meters=distance_meters,
            **mask_kwargs,
            # fix(#716): release_session is deliberately NOT passed. The
            # rollback that returns the pooled connection expires every ORM
            # instance on the session, the authenticated User included, and
            # both chat paths read `user.id` after this returns — a sync
            # refresh on an expired instance raises MissingGreenlet. The REST
            # endpoint passes it because it reads nothing afterwards; copying
            # that call site verbatim is the natural mistake here.
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
        # than presenting a capped preview as the whole result. The service
        # computes it (1:1 ops only) — same field the HTTP preview now returns.
        out["source_feature_count"] = result.source_feature_count
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
    # fix(#683 codex P2): the truncation flag no longer depends on knowing the
    # total. clip filters rows, so run_analysis_preview returns no
    # source_feature_count for it — the clipped total is genuinely unknown —
    # and requiring one dropped the disclosure entirely, presenting a capped
    # clip preview as the whole result. Report the cap; name the total only
    # when there is one.
    total = result.get("source_feature_count")
    if result.get("truncated"):
        action["truncated"] = True
        if total:
            action["row_count"] = total
    return action
