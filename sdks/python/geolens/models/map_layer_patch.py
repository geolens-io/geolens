from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.map_layer_patch_label_config_type_0 import (
        MapLayerPatchLabelConfigType0,
    )
    from ..models.map_layer_patch_layout_type_0 import MapLayerPatchLayoutType0
    from ..models.map_layer_patch_paint_type_0 import MapLayerPatchPaintType0
    from ..models.map_layer_patch_style_config_type_0 import (
        MapLayerPatchStyleConfigType0,
    )
    from ..models.popup_config import PopupConfig


T = TypeVar("T", bound="MapLayerPatch")


@_attrs_define
class MapLayerPatch:
    """
    Attributes:
        id (UUID):
        display_name (None | str | Unset):
        filter_ (list[Any] | None | Unset): MapLibre filter expression
        label_config (MapLayerPatchLabelConfigType0 | None | Unset): Text label configuration
        layer_type (None | str | Unset):
        layout (MapLayerPatchLayoutType0 | None | Unset): MapLibre layout properties override
        opacity (float | None | Unset):
        paint (MapLayerPatchPaintType0 | None | Unset): MapLibre paint properties override
        popup_config (None | PopupConfig | Unset):
        show_in_legend (bool | None | Unset):
        sort_order (int | None | Unset):
        style_config (MapLayerPatchStyleConfigType0 | None | Unset):
        visible (bool | None | Unset):
    """

    id: UUID
    display_name: None | str | Unset = UNSET
    filter_: list[Any] | None | Unset = UNSET
    label_config: MapLayerPatchLabelConfigType0 | None | Unset = UNSET
    layer_type: None | str | Unset = UNSET
    layout: MapLayerPatchLayoutType0 | None | Unset = UNSET
    opacity: float | None | Unset = UNSET
    paint: MapLayerPatchPaintType0 | None | Unset = UNSET
    popup_config: None | PopupConfig | Unset = UNSET
    show_in_legend: bool | None | Unset = UNSET
    sort_order: int | None | Unset = UNSET
    style_config: MapLayerPatchStyleConfigType0 | None | Unset = UNSET
    visible: bool | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.map_layer_patch_label_config_type_0 import (
            MapLayerPatchLabelConfigType0,
        )
        from ..models.map_layer_patch_layout_type_0 import MapLayerPatchLayoutType0
        from ..models.map_layer_patch_paint_type_0 import MapLayerPatchPaintType0
        from ..models.map_layer_patch_style_config_type_0 import (
            MapLayerPatchStyleConfigType0,
        )
        from ..models.popup_config import PopupConfig

        id = str(self.id)

        display_name: None | str | Unset
        if isinstance(self.display_name, Unset):
            display_name = UNSET
        else:
            display_name = self.display_name

        filter_: list[Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, list):
            filter_ = self.filter_

        else:
            filter_ = self.filter_

        label_config: dict[str, Any] | None | Unset
        if isinstance(self.label_config, Unset):
            label_config = UNSET
        elif isinstance(self.label_config, MapLayerPatchLabelConfigType0):
            label_config = self.label_config.to_dict()
        else:
            label_config = self.label_config

        layer_type: None | str | Unset
        if isinstance(self.layer_type, Unset):
            layer_type = UNSET
        else:
            layer_type = self.layer_type

        layout: dict[str, Any] | None | Unset
        if isinstance(self.layout, Unset):
            layout = UNSET
        elif isinstance(self.layout, MapLayerPatchLayoutType0):
            layout = self.layout.to_dict()
        else:
            layout = self.layout

        opacity: float | None | Unset
        if isinstance(self.opacity, Unset):
            opacity = UNSET
        else:
            opacity = self.opacity

        paint: dict[str, Any] | None | Unset
        if isinstance(self.paint, Unset):
            paint = UNSET
        elif isinstance(self.paint, MapLayerPatchPaintType0):
            paint = self.paint.to_dict()
        else:
            paint = self.paint

        popup_config: dict[str, Any] | None | Unset
        if isinstance(self.popup_config, Unset):
            popup_config = UNSET
        elif isinstance(self.popup_config, PopupConfig):
            popup_config = self.popup_config.to_dict()
        else:
            popup_config = self.popup_config

        show_in_legend: bool | None | Unset
        if isinstance(self.show_in_legend, Unset):
            show_in_legend = UNSET
        else:
            show_in_legend = self.show_in_legend

        sort_order: int | None | Unset
        if isinstance(self.sort_order, Unset):
            sort_order = UNSET
        else:
            sort_order = self.sort_order

        style_config: dict[str, Any] | None | Unset
        if isinstance(self.style_config, Unset):
            style_config = UNSET
        elif isinstance(self.style_config, MapLayerPatchStyleConfigType0):
            style_config = self.style_config.to_dict()
        else:
            style_config = self.style_config

        visible: bool | None | Unset
        if isinstance(self.visible, Unset):
            visible = UNSET
        else:
            visible = self.visible

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
            }
        )
        if display_name is not UNSET:
            field_dict["display_name"] = display_name
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if label_config is not UNSET:
            field_dict["label_config"] = label_config
        if layer_type is not UNSET:
            field_dict["layer_type"] = layer_type
        if layout is not UNSET:
            field_dict["layout"] = layout
        if opacity is not UNSET:
            field_dict["opacity"] = opacity
        if paint is not UNSET:
            field_dict["paint"] = paint
        if popup_config is not UNSET:
            field_dict["popup_config"] = popup_config
        if show_in_legend is not UNSET:
            field_dict["show_in_legend"] = show_in_legend
        if sort_order is not UNSET:
            field_dict["sort_order"] = sort_order
        if style_config is not UNSET:
            field_dict["style_config"] = style_config
        if visible is not UNSET:
            field_dict["visible"] = visible

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_layer_patch_label_config_type_0 import (
            MapLayerPatchLabelConfigType0,
        )
        from ..models.map_layer_patch_layout_type_0 import MapLayerPatchLayoutType0
        from ..models.map_layer_patch_paint_type_0 import MapLayerPatchPaintType0
        from ..models.map_layer_patch_style_config_type_0 import (
            MapLayerPatchStyleConfigType0,
        )
        from ..models.popup_config import PopupConfig

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        def _parse_display_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        display_name = _parse_display_name(d.pop("display_name", UNSET))

        def _parse_filter_(data: object) -> list[Any] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                filter_type_0 = cast(list[Any], data)

                return filter_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[Any] | None | Unset, data)

        filter_ = _parse_filter_(d.pop("filter", UNSET))

        def _parse_label_config(
            data: object,
        ) -> MapLayerPatchLabelConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                label_config_type_0 = MapLayerPatchLabelConfigType0.from_dict(data)

                return label_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapLayerPatchLabelConfigType0 | None | Unset, data)

        label_config = _parse_label_config(d.pop("label_config", UNSET))

        def _parse_layer_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        layer_type = _parse_layer_type(d.pop("layer_type", UNSET))

        def _parse_layout(data: object) -> MapLayerPatchLayoutType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                layout_type_0 = MapLayerPatchLayoutType0.from_dict(data)

                return layout_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapLayerPatchLayoutType0 | None | Unset, data)

        layout = _parse_layout(d.pop("layout", UNSET))

        def _parse_opacity(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        opacity = _parse_opacity(d.pop("opacity", UNSET))

        def _parse_paint(data: object) -> MapLayerPatchPaintType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                paint_type_0 = MapLayerPatchPaintType0.from_dict(data)

                return paint_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapLayerPatchPaintType0 | None | Unset, data)

        paint = _parse_paint(d.pop("paint", UNSET))

        def _parse_popup_config(data: object) -> None | PopupConfig | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                popup_config_type_0 = PopupConfig.from_dict(data)

                return popup_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | PopupConfig | Unset, data)

        popup_config = _parse_popup_config(d.pop("popup_config", UNSET))

        def _parse_show_in_legend(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        show_in_legend = _parse_show_in_legend(d.pop("show_in_legend", UNSET))

        def _parse_sort_order(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        sort_order = _parse_sort_order(d.pop("sort_order", UNSET))

        def _parse_style_config(
            data: object,
        ) -> MapLayerPatchStyleConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                style_config_type_0 = MapLayerPatchStyleConfigType0.from_dict(data)

                return style_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapLayerPatchStyleConfigType0 | None | Unset, data)

        style_config = _parse_style_config(d.pop("style_config", UNSET))

        def _parse_visible(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        visible = _parse_visible(d.pop("visible", UNSET))

        map_layer_patch = cls(
            id=id,
            display_name=display_name,
            filter_=filter_,
            label_config=label_config,
            layer_type=layer_type,
            layout=layout,
            opacity=opacity,
            paint=paint,
            popup_config=popup_config,
            show_in_legend=show_in_legend,
            sort_order=sort_order,
            style_config=style_config,
            visible=visible,
        )

        map_layer_patch.additional_properties = d
        return map_layer_patch

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
