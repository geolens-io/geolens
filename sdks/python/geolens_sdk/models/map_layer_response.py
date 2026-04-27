from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.map_layer_response_dataset_column_info_type_0_item import (
        MapLayerResponseDatasetColumnInfoType0Item,
    )
    from ..models.map_layer_response_dataset_sample_values_type_0 import (
        MapLayerResponseDatasetSampleValuesType0,
    )
    from ..models.map_layer_response_label_config_type_0 import (
        MapLayerResponseLabelConfigType0,
    )
    from ..models.map_layer_response_layout import MapLayerResponseLayout
    from ..models.map_layer_response_paint import MapLayerResponsePaint
    from ..models.map_layer_response_style_config_type_0 import (
        MapLayerResponseStyleConfigType0,
    )
    from ..models.popup_config import PopupConfig


T = TypeVar("T", bound="MapLayerResponse")


@_attrs_define
class MapLayerResponse:
    """
    Attributes:
        dataset_extent_bbox (list[float] | None):
        dataset_geometry_type (None | str):
        dataset_id (UUID):
        dataset_name (str):
        dataset_table_name (str):
        id (UUID):
        layout (MapLayerResponseLayout):
        opacity (float):
        paint (MapLayerResponsePaint):
        sort_order (int):
        visible (bool):
        dataset_column_info (list[MapLayerResponseDatasetColumnInfoType0Item] | None | Unset):
        dataset_feature_count (int | None | Unset):
        dataset_record_type (None | str | Unset):
        dataset_sample_values (MapLayerResponseDatasetSampleValuesType0 | None | Unset):
        display_name (None | str | Unset):
        filter_ (list[Any] | None | Unset):
        is_3d (bool | None | Unset):
        label_config (MapLayerResponseLabelConfigType0 | None | Unset):
        layer_type (str | Unset):  Default: 'vector_geolens'.
        popup_config (None | PopupConfig | Unset):
        show_in_legend (bool | Unset):  Default: True.
        style_config (MapLayerResponseStyleConfigType0 | None | Unset):
    """

    dataset_extent_bbox: list[float] | None
    dataset_geometry_type: None | str
    dataset_id: UUID
    dataset_name: str
    dataset_table_name: str
    id: UUID
    layout: MapLayerResponseLayout
    opacity: float
    paint: MapLayerResponsePaint
    sort_order: int
    visible: bool
    dataset_column_info: (
        list[MapLayerResponseDatasetColumnInfoType0Item] | None | Unset
    ) = UNSET
    dataset_feature_count: int | None | Unset = UNSET
    dataset_record_type: None | str | Unset = UNSET
    dataset_sample_values: MapLayerResponseDatasetSampleValuesType0 | None | Unset = (
        UNSET
    )
    display_name: None | str | Unset = UNSET
    filter_: list[Any] | None | Unset = UNSET
    is_3d: bool | None | Unset = UNSET
    label_config: MapLayerResponseLabelConfigType0 | None | Unset = UNSET
    layer_type: str | Unset = "vector_geolens"
    popup_config: None | PopupConfig | Unset = UNSET
    show_in_legend: bool | Unset = True
    style_config: MapLayerResponseStyleConfigType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.map_layer_response_dataset_sample_values_type_0 import (
            MapLayerResponseDatasetSampleValuesType0,
        )
        from ..models.map_layer_response_label_config_type_0 import (
            MapLayerResponseLabelConfigType0,
        )
        from ..models.map_layer_response_style_config_type_0 import (
            MapLayerResponseStyleConfigType0,
        )
        from ..models.popup_config import PopupConfig

        dataset_extent_bbox: list[float] | None
        if isinstance(self.dataset_extent_bbox, list):
            dataset_extent_bbox = self.dataset_extent_bbox

        else:
            dataset_extent_bbox = self.dataset_extent_bbox

        dataset_geometry_type: None | str
        dataset_geometry_type = self.dataset_geometry_type

        dataset_id = str(self.dataset_id)

        dataset_name = self.dataset_name

        dataset_table_name = self.dataset_table_name

        id = str(self.id)

        layout = self.layout.to_dict()

        opacity = self.opacity

        paint = self.paint.to_dict()

        sort_order = self.sort_order

        visible = self.visible

        dataset_column_info: list[dict[str, Any]] | None | Unset
        if isinstance(self.dataset_column_info, Unset):
            dataset_column_info = UNSET
        elif isinstance(self.dataset_column_info, list):
            dataset_column_info = []
            for dataset_column_info_type_0_item_data in self.dataset_column_info:
                dataset_column_info_type_0_item = (
                    dataset_column_info_type_0_item_data.to_dict()
                )
                dataset_column_info.append(dataset_column_info_type_0_item)

        else:
            dataset_column_info = self.dataset_column_info

        dataset_feature_count: int | None | Unset
        if isinstance(self.dataset_feature_count, Unset):
            dataset_feature_count = UNSET
        else:
            dataset_feature_count = self.dataset_feature_count

        dataset_record_type: None | str | Unset
        if isinstance(self.dataset_record_type, Unset):
            dataset_record_type = UNSET
        else:
            dataset_record_type = self.dataset_record_type

        dataset_sample_values: dict[str, Any] | None | Unset
        if isinstance(self.dataset_sample_values, Unset):
            dataset_sample_values = UNSET
        elif isinstance(
            self.dataset_sample_values, MapLayerResponseDatasetSampleValuesType0
        ):
            dataset_sample_values = self.dataset_sample_values.to_dict()
        else:
            dataset_sample_values = self.dataset_sample_values

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

        is_3d: bool | None | Unset
        if isinstance(self.is_3d, Unset):
            is_3d = UNSET
        else:
            is_3d = self.is_3d

        label_config: dict[str, Any] | None | Unset
        if isinstance(self.label_config, Unset):
            label_config = UNSET
        elif isinstance(self.label_config, MapLayerResponseLabelConfigType0):
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
        elif isinstance(self.style_config, MapLayerResponseStyleConfigType0):
            style_config = self.style_config.to_dict()
        else:
            style_config = self.style_config

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_extent_bbox": dataset_extent_bbox,
                "dataset_geometry_type": dataset_geometry_type,
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "dataset_table_name": dataset_table_name,
                "id": id,
                "layout": layout,
                "opacity": opacity,
                "paint": paint,
                "sort_order": sort_order,
                "visible": visible,
            }
        )
        if dataset_column_info is not UNSET:
            field_dict["dataset_column_info"] = dataset_column_info
        if dataset_feature_count is not UNSET:
            field_dict["dataset_feature_count"] = dataset_feature_count
        if dataset_record_type is not UNSET:
            field_dict["dataset_record_type"] = dataset_record_type
        if dataset_sample_values is not UNSET:
            field_dict["dataset_sample_values"] = dataset_sample_values
        if display_name is not UNSET:
            field_dict["display_name"] = display_name
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if is_3d is not UNSET:
            field_dict["is_3d"] = is_3d
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
        from ..models.map_layer_response_dataset_column_info_type_0_item import (
            MapLayerResponseDatasetColumnInfoType0Item,
        )
        from ..models.map_layer_response_dataset_sample_values_type_0 import (
            MapLayerResponseDatasetSampleValuesType0,
        )
        from ..models.map_layer_response_label_config_type_0 import (
            MapLayerResponseLabelConfigType0,
        )
        from ..models.map_layer_response_layout import MapLayerResponseLayout
        from ..models.map_layer_response_paint import MapLayerResponsePaint
        from ..models.map_layer_response_style_config_type_0 import (
            MapLayerResponseStyleConfigType0,
        )
        from ..models.popup_config import PopupConfig

        d = dict(src_dict)

        def _parse_dataset_extent_bbox(data: object) -> list[float] | None:
            if data is None:
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                dataset_extent_bbox_type_0 = cast(list[float], data)

                return dataset_extent_bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None, data)

        dataset_extent_bbox = _parse_dataset_extent_bbox(d.pop("dataset_extent_bbox"))

        def _parse_dataset_geometry_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        dataset_geometry_type = _parse_dataset_geometry_type(
            d.pop("dataset_geometry_type")
        )

        dataset_id = UUID(d.pop("dataset_id"))

        dataset_name = d.pop("dataset_name")

        dataset_table_name = d.pop("dataset_table_name")

        id = UUID(d.pop("id"))

        layout = MapLayerResponseLayout.from_dict(d.pop("layout"))

        opacity = d.pop("opacity")

        paint = MapLayerResponsePaint.from_dict(d.pop("paint"))

        sort_order = d.pop("sort_order")

        visible = d.pop("visible")

        def _parse_dataset_column_info(
            data: object,
        ) -> list[MapLayerResponseDatasetColumnInfoType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                dataset_column_info_type_0 = []
                _dataset_column_info_type_0 = data
                for dataset_column_info_type_0_item_data in _dataset_column_info_type_0:
                    dataset_column_info_type_0_item = (
                        MapLayerResponseDatasetColumnInfoType0Item.from_dict(
                            dataset_column_info_type_0_item_data
                        )
                    )

                    dataset_column_info_type_0.append(dataset_column_info_type_0_item)

                return dataset_column_info_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                list[MapLayerResponseDatasetColumnInfoType0Item] | None | Unset, data
            )

        dataset_column_info = _parse_dataset_column_info(
            d.pop("dataset_column_info", UNSET)
        )

        def _parse_dataset_feature_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        dataset_feature_count = _parse_dataset_feature_count(
            d.pop("dataset_feature_count", UNSET)
        )

        def _parse_dataset_record_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dataset_record_type = _parse_dataset_record_type(
            d.pop("dataset_record_type", UNSET)
        )

        def _parse_dataset_sample_values(
            data: object,
        ) -> MapLayerResponseDatasetSampleValuesType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                dataset_sample_values_type_0 = (
                    MapLayerResponseDatasetSampleValuesType0.from_dict(data)
                )

                return dataset_sample_values_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapLayerResponseDatasetSampleValuesType0 | None | Unset, data)

        dataset_sample_values = _parse_dataset_sample_values(
            d.pop("dataset_sample_values", UNSET)
        )

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

        def _parse_is_3d(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_3d = _parse_is_3d(d.pop("is_3d", UNSET))

        def _parse_label_config(
            data: object,
        ) -> MapLayerResponseLabelConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                label_config_type_0 = MapLayerResponseLabelConfigType0.from_dict(data)

                return label_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapLayerResponseLabelConfigType0 | None | Unset, data)

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
        ) -> MapLayerResponseStyleConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                style_config_type_0 = MapLayerResponseStyleConfigType0.from_dict(data)

                return style_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(MapLayerResponseStyleConfigType0 | None | Unset, data)

        style_config = _parse_style_config(d.pop("style_config", UNSET))

        map_layer_response = cls(
            dataset_extent_bbox=dataset_extent_bbox,
            dataset_geometry_type=dataset_geometry_type,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            dataset_table_name=dataset_table_name,
            id=id,
            layout=layout,
            opacity=opacity,
            paint=paint,
            sort_order=sort_order,
            visible=visible,
            dataset_column_info=dataset_column_info,
            dataset_feature_count=dataset_feature_count,
            dataset_record_type=dataset_record_type,
            dataset_sample_values=dataset_sample_values,
            display_name=display_name,
            filter_=filter_,
            is_3d=is_3d,
            label_config=label_config,
            layer_type=layer_type,
            popup_config=popup_config,
            show_in_legend=show_in_legend,
            style_config=style_config,
        )

        map_layer_response.additional_properties = d
        return map_layer_response

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
