"""Filter / action validation helpers for chat-edit.

Phase 276 CODE-02 — extracted from chat_service.py.
"""

from typing import TYPE_CHECKING
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.identity import Identity
from app.processing.ai.schemas import ChatAction, ChatMapLayer

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)


def _extract_get_refs(expr: list | None) -> set[str]:
    """Recursively extract column names from ["get", "col"] expression nodes."""
    if not isinstance(expr, list) or len(expr) == 0:
        return set()
    refs: set[str] = set()
    if len(expr) >= 2 and expr[0] == "get" and isinstance(expr[1], str):
        refs.add(expr[1])
    for item in expr:
        if isinstance(item, list):
            refs.update(_extract_get_refs(item))
    return refs


def _validate_filter_columns(
    expression: list | None, layer: ChatMapLayer | None
) -> list | None:
    """Validate column refs in a filter expression against layer column_info.

    Returns the expression unchanged if valid, or None if invalid refs found.
    """
    if expression is None or layer is None:
        return expression
    col_names = {c.get("name") for c in (layer.column_info or []) if c.get("name")}
    if not col_names:
        return expression  # no column_info to validate against
    refs = _extract_get_refs(expression)
    invalid = refs - col_names
    if invalid:
        logger.warning(
            "Filter references non-existent columns, clearing filter",
            invalid_columns=list(invalid),
            layer_id=layer.id,
        )
        return None
    return expression


async def _resolve_add_layer_visibility(
    actions: list[ChatAction],
    *,
    session: AsyncSession,
    user: Identity | None,
    port: "ProcessingPort",
) -> set[str]:
    """Return the set of add_layer dataset_ids the user can actually access.

    Performs ONE batched RBAC check for all add_layer actions in a single turn,
    rather than per-action. Result is the intersection of: (a) dataset rows
    that exist, and (b) datasets whose table_name is in the user's
    build_table_allowlist set. Datasets that don't exist or aren't visible
    are simply omitted from the returned set; the caller treats absence as
    "not accessible" and drops the action.
    """
    # Lazy import to avoid pulling sandbox into the chat-validation module
    # at import time (it has heavier deps via SQL parser).
    from app.platform.sandbox.validator import build_table_allowlist

    raw_ids = [a.dataset_id for a in actions if a.type == "add_layer" and a.dataset_id]
    if not raw_ids:
        return set()

    valid_uuids: list = []
    for did in raw_ids:
        try:
            valid_uuids.append(UUID(did))
        except (ValueError, AttributeError):
            continue  # handled by the per-action UUID check in _validate_actions

    if not valid_uuids:
        return set()

    try:
        allowed_tables = await build_table_allowlist(session, user)
        rows = await port.get_datasets_meta_by_ids(session, valid_uuids)
        # rows: list[tuple[UUID, table_name, geometry_type]]
        return {str(row[0]) for row in rows if row[1] in allowed_tables}
    except (
        Exception
    ):  # broad: RBAC lookup is non-fatal — degrade to "deny all add_layer"
        logger.warning("add_layer RBAC check failed; denying all", exc_info=True)
        return set()


async def _validate_actions(
    actions: list[ChatAction],
    layers: list[ChatMapLayer],
    *,
    session: AsyncSession,
    user: Identity | None,
    port: "ProcessingPort",
) -> tuple[list[ChatAction], list[str]]:
    """Validate layer_id and add_layer dataset RBAC. Filter out invalid actions."""
    valid_layer_ids = {layer.id for layer in layers}
    layer_map = {layer.id: layer for layer in layers}
    validated = []
    dropped: list[str] = []

    # Batch RBAC check once per turn for all add_layer dataset_ids
    accessible_add_dataset_ids = await _resolve_add_layer_visibility(
        actions, session=session, user=user, port=port
    )

    for action in actions:
        # add_layer: validate dataset_id presence, UUID shape, AND RBAC visibility
        if action.type == "add_layer":
            if not action.dataset_id:
                dropped.append("add_layer (missing dataset_id)")
                continue
            try:
                UUID(action.dataset_id)
            except (ValueError, AttributeError):
                dropped.append(f"add_layer (invalid dataset_id: {action.dataset_id})")
                continue
            if action.dataset_id not in accessible_add_dataset_ids:
                logger.warning(
                    "add_layer references inaccessible or unknown dataset",
                    dataset_id=action.dataset_id,
                    user_id=str(user.id) if user is not None else None,
                )
                dropped.append("add_layer (dataset not accessible)")
                continue
            validated.append(action)
            continue
        if action.layer_id and action.layer_id not in valid_layer_ids:
            logger.warning(
                "Invalid layer_id in chat action, skipping",
                action_type=action.type,
                layer_id=action.layer_id,
            )
            dropped.append(f"{action.type} (invalid layer_id: {action.layer_id})")
            continue
        # Validate column refs in filter expressions
        if action.type == "set_filter" and action.expression is not None:
            target_layer = layer_map.get(action.layer_id) if action.layer_id else None
            validated_expr = _validate_filter_columns(action.expression, target_layer)
            if validated_expr is None:
                dropped.append(
                    f"{action.type} (invalid column refs in filter expression)"
                )
                continue  # skip action with invalid column refs
            action.expression = validated_expr
        validated.append(action)
    return validated, dropped
