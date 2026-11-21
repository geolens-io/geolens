from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.manifest_map_layer_label_config_type_0 import (
        ManifestMapLayerLabelConfigType0,
    )
    from ..models.manifest_map_layer_layout_type_0 import ManifestMapLayerLayoutType0
    from ..models.manifest_map_layer_paint_type_0 import ManifestMapLayerPaintType0
    from ..models.manifest_map_layer_popup_config_type_0 import (
        ManifestMapLayerPopupConfigType0,
    )
    from ..models.manifest_map_layer_style_config_type_0 import (
        ManifestMapLayerStyleConfigType0,
    )


T = TypeVar("T", bound="ManifestMapLayer")


@_attrs_define
class ManifestMapLayer:
    """One map layer. Column names in its styling are the uploaded file's.

    Attributes:
        key (str): Stable layer identity key, unique within its map.
        dataset_key (None | str | Unset): A dataset the caller published under this key. Exactly one of dataset_key and
            dataset_id.
        dataset_id (None | Unset | UUID): A dataset already in GeoLens that the caller can read.
        display_name (None | str | Unset):
        visible (bool | Unset):  Default: True.
        opacity (float | Unset):  Default: 1.0.
        min_zoom (float | None | Unset):
        max_zoom (float | None | Unset):
        style_config (ManifestMapLayerStyleConfigType0 | None | Unset): The builder's style description. Unknown top-
            level keys are dropped with info A062.
        paint (ManifestMapLayerPaintType0 | None | Unset):
        layout (ManifestMapLayerLayoutType0 | None | Unset):
        filter_ (list[Any] | None | Unset):
        label_config (ManifestMapLayerLabelConfigType0 | None | Unset): Text labels. Unknown keys are dropped with info
            A062.
        popup_config (ManifestMapLayerPopupConfigType0 | None | Unset):
        show_in_legend (bool | Unset):  Default: True.
    """

    key: str
    dataset_key: None | str | Unset = UNSET
    dataset_id: None | Unset | UUID = UNSET
    display_name: None | str | Unset = UNSET
    visible: bool | Unset = True
    opacity: float | Unset = 1.0
    min_zoom: float | None | Unset = UNSET
    max_zoom: float | None | Unset = UNSET
    style_config: ManifestMapLayerStyleConfigType0 | None | Unset = UNSET
    paint: ManifestMapLayerPaintType0 | None | Unset = UNSET
    layout: ManifestMapLayerLayoutType0 | None | Unset = UNSET
    filter_: list[Any] | None | Unset = UNSET
    label_config: ManifestMapLayerLabelConfigType0 | None | Unset = UNSET
    popup_config: ManifestMapLayerPopupConfigType0 | None | Unset = UNSET
    show_in_legend: bool | Unset = True

    def to_dict(self) -> dict[str, Any]:
        from ..models.manifest_map_layer_label_config_type_0 import (
            ManifestMapLayerLabelConfigType0,
        )
        from ..models.manifest_map_layer_layout_type_0 import (
            ManifestMapLayerLayoutType0,
        )
        from ..models.manifest_map_layer_paint_type_0 import ManifestMapLayerPaintType0
        from ..models.manifest_map_layer_popup_config_type_0 import (
            ManifestMapLayerPopupConfigType0,
        )
        from ..models.manifest_map_layer_style_config_type_0 import (
            ManifestMapLayerStyleConfigType0,
        )

        key = self.key

        dataset_key: None | str | Unset
        if isinstance(self.dataset_key, Unset):
            dataset_key = UNSET
        else:
            dataset_key = self.dataset_key

        dataset_id: None | str | Unset
        if isinstance(self.dataset_id, Unset):
            dataset_id = UNSET
        elif isinstance(self.dataset_id, UUID):
            dataset_id = str(self.dataset_id)
        else:
            dataset_id = self.dataset_id

        display_name: None | str | Unset
        if isinstance(self.display_name, Unset):
            display_name = UNSET
        else:
            display_name = self.display_name

        visible = self.visible

        opacity = self.opacity

        min_zoom: float | None | Unset
        if isinstance(self.min_zoom, Unset):
            min_zoom = UNSET
        else:
            min_zoom = self.min_zoom

        max_zoom: float | None | Unset
        if isinstance(self.max_zoom, Unset):
            max_zoom = UNSET
        else:
            max_zoom = self.max_zoom

        style_config: dict[str, Any] | None | Unset
        if isinstance(self.style_config, Unset):
            style_config = UNSET
        elif isinstance(self.style_config, ManifestMapLayerStyleConfigType0):
            style_config = self.style_config.to_dict()
        else:
            style_config = self.style_config

        paint: dict[str, Any] | None | Unset
        if isinstance(self.paint, Unset):
            paint = UNSET
        elif isinstance(self.paint, ManifestMapLayerPaintType0):
            paint = self.paint.to_dict()
        else:
            paint = self.paint

        layout: dict[str, Any] | None | Unset
        if isinstance(self.layout, Unset):
            layout = UNSET
        elif isinstance(self.layout, ManifestMapLayerLayoutType0):
            layout = self.layout.to_dict()
        else:
            layout = self.layout

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
        elif isinstance(self.label_config, ManifestMapLayerLabelConfigType0):
            label_config = self.label_config.to_dict()
        else:
            label_config = self.label_config

        popup_config: dict[str, Any] | None | Unset
        if isinstance(self.popup_config, Unset):
            popup_config = UNSET
        elif isinstance(self.popup_config, ManifestMapLayerPopupConfigType0):
            popup_config = self.popup_config.to_dict()
        else:
            popup_config = self.popup_config

        show_in_legend = self.show_in_legend

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "key": key,
            }
        )
        if dataset_key is not UNSET:
            field_dict["dataset_key"] = dataset_key
        if dataset_id is not UNSET:
            field_dict["dataset_id"] = dataset_id
        if display_name is not UNSET:
            field_dict["display_name"] = display_name
        if visible is not UNSET:
            field_dict["visible"] = visible
        if opacity is not UNSET:
            field_dict["opacity"] = opacity
        if min_zoom is not UNSET:
            field_dict["min_zoom"] = min_zoom
        if max_zoom is not UNSET:
            field_dict["max_zoom"] = max_zoom
        if style_config is not UNSET:
            field_dict["style_config"] = style_config
        if paint is not UNSET:
            field_dict["paint"] = paint
        if layout is not UNSET:
            field_dict["layout"] = layout
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if label_config is not UNSET:
            field_dict["label_config"] = label_config
        if popup_config is not UNSET:
            field_dict["popup_config"] = popup_config
        if show_in_legend is not UNSET:
            field_dict["show_in_legend"] = show_in_legend

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_map_layer_label_config_type_0 import (
            ManifestMapLayerLabelConfigType0,
        )
        from ..models.manifest_map_layer_layout_type_0 import (
            ManifestMapLayerLayoutType0,
        )
        from ..models.manifest_map_layer_paint_type_0 import ManifestMapLayerPaintType0
        from ..models.manifest_map_layer_popup_config_type_0 import (
            ManifestMapLayerPopupConfigType0,
        )
        from ..models.manifest_map_layer_style_config_type_0 import (
            ManifestMapLayerStyleConfigType0,
        )

        d = dict(src_dict)
        key = d.pop("key")

        def _parse_dataset_key(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dataset_key = _parse_dataset_key(d.pop("dataset_key", UNSET))

        def _parse_dataset_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                dataset_id_type_0 = UUID(data)

                return dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        dataset_id = _parse_dataset_id(d.pop("dataset_id", UNSET))

        def _parse_display_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        display_name = _parse_display_name(d.pop("display_name", UNSET))

        visible = d.pop("visible", UNSET)

        opacity = d.pop("opacity", UNSET)

        def _parse_min_zoom(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        min_zoom = _parse_min_zoom(d.pop("min_zoom", UNSET))

        def _parse_max_zoom(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        max_zoom = _parse_max_zoom(d.pop("max_zoom", UNSET))

        def _parse_style_config(
            data: object,
        ) -> ManifestMapLayerStyleConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                style_config_type_0 = ManifestMapLayerStyleConfigType0.from_dict(data)

                return style_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestMapLayerStyleConfigType0 | None | Unset, data)

        style_config = _parse_style_config(d.pop("style_config", UNSET))

        def _parse_paint(data: object) -> ManifestMapLayerPaintType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                paint_type_0 = ManifestMapLayerPaintType0.from_dict(data)

                return paint_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestMapLayerPaintType0 | None | Unset, data)

        paint = _parse_paint(d.pop("paint", UNSET))

        def _parse_layout(data: object) -> ManifestMapLayerLayoutType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                layout_type_0 = ManifestMapLayerLayoutType0.from_dict(data)

                return layout_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestMapLayerLayoutType0 | None | Unset, data)

        layout = _parse_layout(d.pop("layout", UNSET))

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
        ) -> ManifestMapLayerLabelConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                label_config_type_0 = ManifestMapLayerLabelConfigType0.from_dict(data)

                return label_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestMapLayerLabelConfigType0 | None | Unset, data)

        label_config = _parse_label_config(d.pop("label_config", UNSET))

        def _parse_popup_config(
            data: object,
        ) -> ManifestMapLayerPopupConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                popup_config_type_0 = ManifestMapLayerPopupConfigType0.from_dict(data)

                return popup_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestMapLayerPopupConfigType0 | None | Unset, data)

        popup_config = _parse_popup_config(d.pop("popup_config", UNSET))

        show_in_legend = d.pop("show_in_legend", UNSET)

        manifest_map_layer = cls(
            key=key,
            dataset_key=dataset_key,
            dataset_id=dataset_id,
            display_name=display_name,
            visible=visible,
            opacity=opacity,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            style_config=style_config,
            paint=paint,
            layout=layout,
            filter_=filter_,
            label_config=label_config,
            popup_config=popup_config,
            show_in_legend=show_in_legend,
        )

        return manifest_map_layer
