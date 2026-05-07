"""Filter / action validation helpers for chat-edit.

Phase 276 CODE-02 — extracted from chat_service.py.
"""

from uuid import UUID

import structlog

from app.processing.ai.schemas import ChatAction, ChatMapLayer

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


def _validate_actions(
    actions: list[ChatAction], layers: list[ChatMapLayer]
) -> tuple[list[ChatAction], list[str]]:
    """Validate layer_id references in actions. Filter out invalid ones."""
    valid_layer_ids = {layer.id for layer in layers}
    layer_map = {layer.id: layer for layer in layers}
    validated = []
    dropped: list[str] = []
    for action in actions:
        # add_layer: validate dataset_id is present (actual RBAC check happens on the frontend add)
        if action.type == "add_layer":
            if not action.dataset_id:
                dropped.append("add_layer (missing dataset_id)")
                continue
            try:
                UUID(action.dataset_id)
            except (ValueError, AttributeError):
                dropped.append(f"add_layer (invalid dataset_id: {action.dataset_id})")
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
