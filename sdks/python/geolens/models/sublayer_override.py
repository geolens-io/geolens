from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="SublayerOverride")


@_attrs_define
class SublayerOverride:
    """Per-sublayer style override for a single basemap sublayer.

    All fields are nullable — a ``None`` value means "use the basemap default".
    Only ``#RRGGBB`` hex strings are accepted for color fields; ``None`` means
    the basemap default color is preserved.  Numeric ranges are clamped at
    validation time (Pydantic ``ge``/``le`` constraints).

    The key set of ``BasemapConfig.sublayer_overrides`` is treated as opaque
    (forward-compatible with future sublayer IDs) — see CONTEXT.md D-01.

    Security:
        extra="forbid" locks the D-14 scope guardrail: unknown style axes such
        as dash patterns, line caps, halo blur, and text-font are rejected at
        validation time (T-1059A-03).

        Attributes:
            casing_color (None | str | Unset): Casing color in #RRGGBB hex format, or null to use the basemap default.
            casing_width (float | None | Unset): Casing width in pixels (0-20), or null to use the basemap default.
            max_zoom (float | None | Unset): Maximum zoom level at which the sublayer is visible (0-24), or null for
                default.
            min_zoom (float | None | Unset): Minimum zoom level at which the sublayer is visible (0-24), or null for
                default.
            opacity (float | None | Unset): Per-sublayer opacity (0-1), or null to use the basemap default. Additive on top
                of BasemapConfig.opacity (the whole-basemap master opacity). IN-02 (Phase 1059 code review): this field is
                populated via API or a future Phase milestone. The current UI opacity slider in BasemapSublayerEditorScene
                routes through the legacy sublayerState path (MapBuilderPage.tsx handleSublayerOpacityChange) per D-09 ('OPACITY
                — existing slider untouched') and does not call updateSublayerOverride. See TODO(BUILDER-SUBLAYER-PERSIST)
                comment at MapBuilderPage.tsx for the deferral rationale.
            stroke_color (None | str | Unset): Stroke color in #RRGGBB hex format, or null to use the basemap default.
            stroke_width (float | None | Unset): Stroke width in pixels (0-20), or null to use the basemap default.
    """

    casing_color: None | str | Unset = UNSET
    casing_width: float | None | Unset = UNSET
    max_zoom: float | None | Unset = UNSET
    min_zoom: float | None | Unset = UNSET
    opacity: float | None | Unset = UNSET
    stroke_color: None | str | Unset = UNSET
    stroke_width: float | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        casing_color: None | str | Unset
        if isinstance(self.casing_color, Unset):
            casing_color = UNSET
        else:
            casing_color = self.casing_color

        casing_width: float | None | Unset
        if isinstance(self.casing_width, Unset):
            casing_width = UNSET
        else:
            casing_width = self.casing_width

        max_zoom: float | None | Unset
        if isinstance(self.max_zoom, Unset):
            max_zoom = UNSET
        else:
            max_zoom = self.max_zoom

        min_zoom: float | None | Unset
        if isinstance(self.min_zoom, Unset):
            min_zoom = UNSET
        else:
            min_zoom = self.min_zoom

        opacity: float | None | Unset
        if isinstance(self.opacity, Unset):
            opacity = UNSET
        else:
            opacity = self.opacity

        stroke_color: None | str | Unset
        if isinstance(self.stroke_color, Unset):
            stroke_color = UNSET
        else:
            stroke_color = self.stroke_color

        stroke_width: float | None | Unset
        if isinstance(self.stroke_width, Unset):
            stroke_width = UNSET
        else:
            stroke_width = self.stroke_width

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if casing_color is not UNSET:
            field_dict["casing_color"] = casing_color
        if casing_width is not UNSET:
            field_dict["casing_width"] = casing_width
        if max_zoom is not UNSET:
            field_dict["max_zoom"] = max_zoom
        if min_zoom is not UNSET:
            field_dict["min_zoom"] = min_zoom
        if opacity is not UNSET:
            field_dict["opacity"] = opacity
        if stroke_color is not UNSET:
            field_dict["stroke_color"] = stroke_color
        if stroke_width is not UNSET:
            field_dict["stroke_width"] = stroke_width

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_casing_color(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        casing_color = _parse_casing_color(d.pop("casing_color", UNSET))

        def _parse_casing_width(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        casing_width = _parse_casing_width(d.pop("casing_width", UNSET))

        def _parse_max_zoom(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        max_zoom = _parse_max_zoom(d.pop("max_zoom", UNSET))

        def _parse_min_zoom(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        min_zoom = _parse_min_zoom(d.pop("min_zoom", UNSET))

        def _parse_opacity(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        opacity = _parse_opacity(d.pop("opacity", UNSET))

        def _parse_stroke_color(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        stroke_color = _parse_stroke_color(d.pop("stroke_color", UNSET))

        def _parse_stroke_width(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        stroke_width = _parse_stroke_width(d.pop("stroke_width", UNSET))

        sublayer_override = cls(
            casing_color=casing_color,
            casing_width=casing_width,
            max_zoom=max_zoom,
            min_zoom=min_zoom,
            opacity=opacity,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
        )

        return sublayer_override
