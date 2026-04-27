from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.popup_config import PopupConfig
    from ..models.shared_layer_response_column_info_type_0_item import (
        SharedLayerResponseColumnInfoType0Item,
    )
    from ..models.shared_layer_response_label_config_type_0 import (
        SharedLayerResponseLabelConfigType0,
    )
    from ..models.shared_layer_response_layout import SharedLayerResponseLayout
    from ..models.shared_layer_response_paint import SharedLayerResponsePaint
    from ..models.shared_layer_response_style_config_type_0 import (
        SharedLayerResponseStyleConfigType0,
    )


T = TypeVar("T", bound="SharedLayerResponse")


@_attrs_define
class SharedLayerResponse:
    """
    Attributes:
        dataset_id (str):
        dataset_name (str):
        geometry_type (None | str):
        layout (SharedLayerResponseLayout):
        opacity (float):
        paint (SharedLayerResponsePaint):
        sort_order (int):
        table_name (str):
        tile_url (str):
        visible (bool):
        column_info (list[SharedLayerResponseColumnInfoType0Item] | None | Unset):
        dataset_record_type (None | str | Unset):
        display_name (None | str | Unset):
        feature_count (int | None | Unset):
        filter_ (list[Any] | None | Unset):
        is_3d (bool | None | Unset):
        is_dem (bool | None | Unset):
        label_config (None | SharedLayerResponseLabelConfigType0 | Unset):
        layer_type (str | Unset):  Default: 'vector_geolens'.
        popup_config (None | PopupConfig | Unset):
        show_in_legend (bool | Unset):  Default: True.
        style_config (None | SharedLayerResponseStyleConfigType0 | Unset):
    """

    dataset_id: str
    dataset_name: str
    geometry_type: None | str
    layout: SharedLayerResponseLayout
    opacity: float
    paint: SharedLayerResponsePaint
    sort_order: int
    table_name: str
    tile_url: str
    visible: bool
    column_info: list[SharedLayerResponseColumnInfoType0Item] | None | Unset = UNSET
    dataset_record_type: None | str | Unset = UNSET
    display_name: None | str | Unset = UNSET
    feature_count: int | None | Unset = UNSET
    filter_: list[Any] | None | Unset = UNSET
    is_3d: bool | None | Unset = UNSET
    is_dem: bool | None | Unset = UNSET
    label_config: None | SharedLayerResponseLabelConfigType0 | Unset = UNSET
    layer_type: str | Unset = "vector_geolens"
    popup_config: None | PopupConfig | Unset = UNSET
    show_in_legend: bool | Unset = True
    style_config: None | SharedLayerResponseStyleConfigType0 | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.popup_config import PopupConfig
        from ..models.shared_layer_response_label_config_type_0 import (
            SharedLayerResponseLabelConfigType0,
        )
        from ..models.shared_layer_response_style_config_type_0 import (
            SharedLayerResponseStyleConfigType0,
        )

        dataset_id = self.dataset_id

        dataset_name = self.dataset_name

        geometry_type: None | str
        geometry_type = self.geometry_type

        layout = self.layout.to_dict()

        opacity = self.opacity

        paint = self.paint.to_dict()

        sort_order = self.sort_order

        table_name = self.table_name

        tile_url = self.tile_url

        visible = self.visible

        column_info: list[dict[str, Any]] | None | Unset
        if isinstance(self.column_info, Unset):
            column_info = UNSET
        elif isinstance(self.column_info, list):
            column_info = []
            for column_info_type_0_item_data in self.column_info:
                column_info_type_0_item = column_info_type_0_item_data.to_dict()
                column_info.append(column_info_type_0_item)

        else:
            column_info = self.column_info

        dataset_record_type: None | str | Unset
        if isinstance(self.dataset_record_type, Unset):
            dataset_record_type = UNSET
        else:
            dataset_record_type = self.dataset_record_type

        display_name: None | str | Unset
        if isinstance(self.display_name, Unset):
            display_name = UNSET
        else:
            display_name = self.display_name

        feature_count: int | None | Unset
        if isinstance(self.feature_count, Unset):
            feature_count = UNSET
        else:
            feature_count = self.feature_count

        filter_: list[Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, list):
            filter_ = self.filter_

        else:
            filter_ = self.filter_

        is_3d: bool | None | Unset
        if isinstance(self.is_3d, Unset):
            is_3d = UNSET
        else:
            is_3d = self.is_3d

        is_dem: bool | None | Unset
        if isinstance(self.is_dem, Unset):
            is_dem = UNSET
        else:
            is_dem = self.is_dem

        label_config: dict[str, Any] | None | Unset
        if isinstance(self.label_config, Unset):
            label_config = UNSET
        elif isinstance(self.label_config, SharedLayerResponseLabelConfigType0):
            label_config = self.label_config.to_dict()
        else:
            label_config = self.label_config

        layer_type = self.layer_type

        popup_config: dict[str, Any] | None | Unset
        if isinstance(self.popup_config, Unset):
            popup_config = UNSET
        elif isinstance(self.popup_config, PopupConfig):
            popup_config = self.popup_config.to_dict()
        else:
            popup_config = self.popup_config

        show_in_legend = self.show_in_legend

        style_config: dict[str, Any] | None | Unset
        if isinstance(self.style_config, Unset):
            style_config = UNSET
        elif isinstance(self.style_config, SharedLayerResponseStyleConfigType0):
            style_config = self.style_config.to_dict()
        else:
            style_config = self.style_config

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "geometry_type": geometry_type,
                "layout": layout,
                "opacity": opacity,
                "paint": paint,
                "sort_order": sort_order,
                "table_name": table_name,
                "tile_url": tile_url,
                "visible": visible,
            }
        )
        if column_info is not UNSET:
            field_dict["column_info"] = column_info
        if dataset_record_type is not UNSET:
            field_dict["dataset_record_type"] = dataset_record_type
        if display_name is not UNSET:
            field_dict["display_name"] = display_name
        if feature_count is not UNSET:
            field_dict["feature_count"] = feature_count
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if is_3d is not UNSET:
            field_dict["is_3d"] = is_3d
        if is_dem is not UNSET:
            field_dict["is_dem"] = is_dem
        if label_config is not UNSET:
            field_dict["label_config"] = label_config
        if layer_type is not UNSET:
            field_dict["layer_type"] = layer_type
        if popup_config is not UNSET:
            field_dict["popup_config"] = popup_config
        if show_in_legend is not UNSET:
            field_dict["show_in_legend"] = show_in_legend
        if style_config is not UNSET:
            field_dict["style_config"] = style_config

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.popup_config import PopupConfig
        from ..models.shared_layer_response_column_info_type_0_item import (
            SharedLayerResponseColumnInfoType0Item,
        )
        from ..models.shared_layer_response_label_config_type_0 import (
            SharedLayerResponseLabelConfigType0,
        )
        from ..models.shared_layer_response_layout import SharedLayerResponseLayout
        from ..models.shared_layer_response_paint import SharedLayerResponsePaint
        from ..models.shared_layer_response_style_config_type_0 import (
            SharedLayerResponseStyleConfigType0,
        )

        d = dict(src_dict)
        dataset_id = d.pop("dataset_id")

        dataset_name = d.pop("dataset_name")

        def _parse_geometry_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type"))

        layout = SharedLayerResponseLayout.from_dict(d.pop("layout"))

        opacity = d.pop("opacity")

        paint = SharedLayerResponsePaint.from_dict(d.pop("paint"))

        sort_order = d.pop("sort_order")

        table_name = d.pop("table_name")

        tile_url = d.pop("tile_url")

        visible = d.pop("visible")

        def _parse_column_info(
            data: object,
        ) -> list[SharedLayerResponseColumnInfoType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                column_info_type_0 = []
                _column_info_type_0 = data
                for column_info_type_0_item_data in _column_info_type_0:
                    column_info_type_0_item = (
                        SharedLayerResponseColumnInfoType0Item.from_dict(
                            column_info_type_0_item_data
                        )
                    )

                    column_info_type_0.append(column_info_type_0_item)

                return column_info_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                list[SharedLayerResponseColumnInfoType0Item] | None | Unset, data
            )

        column_info = _parse_column_info(d.pop("column_info", UNSET))

        def _parse_dataset_record_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dataset_record_type = _parse_dataset_record_type(
            d.pop("dataset_record_type", UNSET)
        )

        def _parse_display_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        display_name = _parse_display_name(d.pop("display_name", UNSET))

        def _parse_feature_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count = _parse_feature_count(d.pop("feature_count", UNSET))

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

        def _parse_is_3d(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_3d = _parse_is_3d(d.pop("is_3d", UNSET))

        def _parse_is_dem(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_dem = _parse_is_dem(d.pop("is_dem", UNSET))

        def _parse_label_config(
            data: object,
        ) -> None | SharedLayerResponseLabelConfigType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                label_config_type_0 = SharedLayerResponseLabelConfigType0.from_dict(
                    data
                )

                return label_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SharedLayerResponseLabelConfigType0 | Unset, data)

        label_config = _parse_label_config(d.pop("label_config", UNSET))

        layer_type = d.pop("layer_type", UNSET)

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

        show_in_legend = d.pop("show_in_legend", UNSET)

        def _parse_style_config(
            data: object,
        ) -> None | SharedLayerResponseStyleConfigType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                style_config_type_0 = SharedLayerResponseStyleConfigType0.from_dict(
                    data
                )

                return style_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SharedLayerResponseStyleConfigType0 | Unset, data)

        style_config = _parse_style_config(d.pop("style_config", UNSET))

        shared_layer_response = cls(
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            geometry_type=geometry_type,
            layout=layout,
            opacity=opacity,
            paint=paint,
            sort_order=sort_order,
            table_name=table_name,
            tile_url=tile_url,
            visible=visible,
            column_info=column_info,
            dataset_record_type=dataset_record_type,
            display_name=display_name,
            feature_count=feature_count,
            filter_=filter_,
            is_3d=is_3d,
            is_dem=is_dem,
            label_config=label_config,
            layer_type=layer_type,
            popup_config=popup_config,
            show_in_legend=show_in_legend,
            style_config=style_config,
        )

        shared_layer_response.additional_properties = d
        return shared_layer_response

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
