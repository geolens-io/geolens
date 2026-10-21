"""Checks that keep Ask AI from reporting styles the builder cannot show."""

import functools

from app.processing.ai.chat_constants import is_known_ramp
from app.processing.ai.schemas import ChatMapLayer, validate_paint_with_feedback


def polygon_fill_disabled(layer: ChatMapLayer) -> bool:
    builder = (layer.style_config or {}).get("builder") or {}
    flag = builder.get("fillDisabled", (layer.paint or {}).get("_fill-disabled"))
    return flag is True or flag == "true"


def outline_only_error(layer: ChatMapLayer, color_prop: str) -> str | None:
    if color_prop == "fill-color" and polygon_fill_disabled(layer):
        return (
            "This polygon layer is outline only, so a fill colour would not show. "
            "Switch it to fill or fill-stroke with set_render_as first."
        )
    return None


def annotate_data_driven_result(build):
    """Decorate the data-driven style builder: add what the model must tell the user,
    and record the paint on the layer for later edits in the turn."""

    @functools.wraps(build)
    async def wrapper(tool_input, session, layers, **kwargs):
        result = await build(tool_input, session, layers, **kwargs)
        if "error" in result:
            return result
        paint = result.get("paint") or {}
        target = next((lyr for lyr in layers if lyr.id == result.get("layer_id")), None)
        if target is not None:
            target.paint = {**(target.paint or {}), **paint}
        ramp = tool_input.get("ramp") or (
            "Set2" if tool_input.get("mode") == "categorical" else "YlOrRd"
        )
        notes = _data_driven_notes(ramp, "fill-color" in paint)
        return {**result, "notes": notes} if notes else result

    return wrapper


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


def validate_paint_keeping_fill(
    paint: dict, layer: ChatMapLayer, render_mode: str | None
) -> tuple[dict, list[str]]:
    """Validate set_style paint; drop a fill-opacity of 0 while a column colours the fill."""
    validated, warnings = validate_paint_with_feedback(
        paint, layer.geometry_type, render_mode
    )
    kept, hidden = _keep_data_driven_fill_visible(validated or {}, layer)
    return kept, warnings + hidden


def _keep_data_driven_fill_visible(
    paint: dict, layer: ChatMapLayer
) -> tuple[dict, list[str]]:
    opacity = paint.get("fill-opacity")
    if (
        not isinstance(opacity, (int, float))
        or isinstance(opacity, bool)
        or opacity > 0
    ):
        return paint, []
    fill_color = paint.get("fill-color", (layer.paint or {}).get("fill-color"))
    if not isinstance(fill_color, list):
        return paint, []
    kept = {k: v for k, v in paint.items() if k != "fill-opacity"}
    return kept, [
        "Removed 'fill-opacity': 0 would hide the colours this layer's fill gets "
        "from a column. For outlines only, use set_render_as stroke instead."
    ]
