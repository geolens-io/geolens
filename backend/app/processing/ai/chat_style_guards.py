"""Checks that keep Ask AI from reporting styles the builder cannot show."""

from app.processing.ai.chat_constants import is_known_ramp
from app.processing.ai.schemas import (
    ChatMapLayer,
    validate_paint_property_names_with_feedback,
    validate_paint_with_feedback,
)


_OUTLINE_COLOR_KEYS = ("_outline-color", "fill-outline-color")


def _builder(layer: ChatMapLayer) -> dict:
    return (layer.style_config or {}).get("builder") or {}


def polygon_fill_disabled(layer: ChatMapLayer) -> bool:
    builder = _builder(layer)
    flag = builder.get("fillDisabled", (layer.paint or {}).get("_fill-disabled"))
    return flag is True or flag == "true"


def record_polygon_mode(
    layer: ChatMapLayer, style: dict, render_as: str, height_column: str | None
) -> None:
    """Record a polygon render switch on the style, so later edits in the turn see the new mode."""
    builder = dict(style.get("builder") or {})
    builder["fillDisabled"] = render_as == "stroke"
    builder["strokeDisabled"] = render_as == "fill"
    if render_as != "extrusion-3d":
        builder.pop("heightColumn", None)
        layer.paint = {
            k: v for k, v in (layer.paint or {}).items() if k != "_height_column"
        }
    elif height_column:
        builder["heightColumn"] = height_column
    style["builder"] = builder


def outline_only_error(layer: ChatMapLayer, color_prop: str) -> str | None:
    if color_prop == "fill-color" and polygon_fill_disabled(layer):
        return (
            "This polygon layer is outline only, so a fill colour would not show. "
            "Switch it to fill or fill-stroke with set_render_as first."
        )
    return None


def finish_data_driven_result(result: dict, layers: list[ChatMapLayer]) -> dict:
    """Add what the model must tell the user about a built style.

    The paint is also recorded on the layer: later edits in the same turn
    are checked against it, before the client has applied anything.
    """
    if "error" in result:
        return result
    paint = result.get("paint") or {}
    target = next((lyr for lyr in layers if lyr.id == result.get("layer_id")), None)
    if target is not None:
        target.paint = {**(target.paint or {}), **paint}
    notes = _data_driven_notes(result["style_config"]["ramp"], "fill-color" in paint)
    return {**result, "notes": notes} if notes else result


def _data_driven_notes(ramp: str, on_fill: bool) -> list[str]:
    notes = []
    if not is_known_ramp(ramp):
        notes.append(
            f"'{ramp}' is not a ramp in the style editor, so YlOrRd was used. "
            "Tell the user, and name the ramp you applied."
        )
    if on_fill:
        notes.append(
            "The colours are on the polygon fill. Outlines cannot be coloured by a "
            "column, so do not say they are."
        )
    return notes


def _drop(paint: dict, warnings: list[str], key: str, reason: str) -> None:
    del paint[key]
    warnings.append(f"Removed '{key}': {reason}")


def validate_set_style(
    tool_input: dict, layer: ChatMapLayer, render_mode: str | None
) -> tuple[dict, list[str]]:
    """Validate a set_style call against the layer, and record it on the layer.

    Later calls in the same turn are checked against the recorded paint, before
    the client has applied anything.
    """
    next_input = {**tool_input}
    warnings: list[str] = []
    if tool_input.get("paint"):
        next_input["paint"], warnings = _validate_paint(
            tool_input["paint"], layer, render_mode
        )
    if tool_input.get("clear_paint"):
        next_input["clear_paint"], clear_warnings = (
            validate_paint_property_names_with_feedback(
                tool_input["clear_paint"], layer.geometry_type, render_mode
            )
        )
        warnings.extend(clear_warnings)
    base = {} if tool_input.get("replace_paint") else layer.paint or {}
    recorded = {**base, **(next_input.get("paint") or {})}
    layer.paint = {
        k: v for k, v in recorded.items() if k not in next_input.get("clear_paint", [])
    }
    return next_input, warnings


def _validate_paint(
    paint: dict, layer: ChatMapLayer, render_mode: str | None
) -> tuple[dict, list[str]]:
    """Validate set_style paint, dropping edits the builder would ignore or that hide a column's colours."""
    validated, warnings = validate_paint_with_feedback(
        paint, layer.geometry_type, render_mode
    )
    kept = dict(validated or {})
    for key in _OUTLINE_COLOR_KEYS:
        if isinstance(kept.get(key), list):
            _drop(
                kept, warnings, key, "outlines take one colour, not a column's colours."
            )
    if "fill-opacity" in kept and _is_extrusion(layer):
        _drop(
            kept,
            warnings,
            "fill-opacity",
            "a 3D layer draws with its extrusion opacity. Use set_opacity to change it.",
        )
    if _data_driven_fill_hidden(kept, layer):
        _drop(
            kept,
            warnings,
            "fill-opacity",
            "0 would hide the colours this layer's fill gets from a column. "
            "For outlines only, use set_render_as stroke instead.",
        )
    return kept, warnings


def _is_extrusion(layer: ChatMapLayer) -> bool:
    return bool(
        _builder(layer).get("heightColumn") or (layer.paint or {}).get("_height_column")
    )


def _data_driven_fill_hidden(paint: dict, layer: ChatMapLayer) -> bool:
    opacity = paint.get("fill-opacity")
    if (
        not isinstance(opacity, (int, float))
        or isinstance(opacity, bool)
        or opacity > 0
    ):
        return False
    return isinstance(
        paint.get("fill-color", (layer.paint or {}).get("fill-color")), list
    )
