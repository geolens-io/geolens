from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.chat_map_layer_column_info_type_0_item import (
        ChatMapLayerColumnInfoType0Item,
    )
    from ..models.chat_map_layer_filter_type_1 import ChatMapLayerFilterType1
    from ..models.chat_map_layer_label_config_type_0 import ChatMapLayerLabelConfigType0
    from ..models.chat_map_layer_paint_type_0 import ChatMapLayerPaintType0
    from ..models.chat_map_layer_sample_values_type_0 import (
        ChatMapLayerSampleValuesType0,
    )
    from ..models.chat_map_layer_style_config_type_0 import ChatMapLayerStyleConfigType0


T = TypeVar("T", bound="ChatMapLayer")


@_attrs_define
class ChatMapLayer:
    """Layer state sent from frontend for chat context.

    Attributes:
        dataset_id (str):
        dataset_table_name (str):
        id (str):
        name (str):
        column_info (list[ChatMapLayerColumnInfoType0Item] | None | Unset):
        dataset_title (None | str | Unset):
        feature_count (int | None | Unset):
        filter_ (ChatMapLayerFilterType1 | list[Any] | None | Unset):
        geometry_type (None | str | Unset):
        label_config (ChatMapLayerLabelConfigType0 | None | Unset):
        layer_type (None | str | Unset):
        paint (ChatMapLayerPaintType0 | None | Unset):
        sample_values (ChatMapLayerSampleValuesType0 | None | Unset):
        style_config (ChatMapLayerStyleConfigType0 | None | Unset):
        visible (bool | Unset):  Default: True.
    """

    dataset_id: str
    dataset_table_name: str
    id: str
    name: str
    column_info: list[ChatMapLayerColumnInfoType0Item] | None | Unset = UNSET
    dataset_title: None | str | Unset = UNSET
    feature_count: int | None | Unset = UNSET
    filter_: ChatMapLayerFilterType1 | list[Any] | None | Unset = UNSET
    geometry_type: None | str | Unset = UNSET
    label_config: ChatMapLayerLabelConfigType0 | None | Unset = UNSET
    layer_type: None | str | Unset = UNSET
    paint: ChatMapLayerPaintType0 | None | Unset = UNSET
    sample_values: ChatMapLayerSampleValuesType0 | None | Unset = UNSET
    style_config: ChatMapLayerStyleConfigType0 | None | Unset = UNSET
    visible: bool | Unset = True
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.chat_map_layer_filter_type_1 import ChatMapLayerFilterType1
        from ..models.chat_map_layer_label_config_type_0 import (
            ChatMapLayerLabelConfigType0,
        )
        from ..models.chat_map_layer_paint_type_0 import ChatMapLayerPaintType0
        from ..models.chat_map_layer_sample_values_type_0 import (
            ChatMapLayerSampleValuesType0,
        )
        from ..models.chat_map_layer_style_config_type_0 import (
            ChatMapLayerStyleConfigType0,
        )

        dataset_id = self.dataset_id

        dataset_table_name = self.dataset_table_name

        id = self.id

        name = self.name

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

        dataset_title: None | str | Unset
        if isinstance(self.dataset_title, Unset):
            dataset_title = UNSET
        else:
            dataset_title = self.dataset_title

        feature_count: int | None | Unset
        if isinstance(self.feature_count, Unset):
            feature_count = UNSET
        else:
            feature_count = self.feature_count

        filter_: dict[str, Any] | list[Any] | None | Unset
        if isinstance(self.filter_, Unset):
            filter_ = UNSET
        elif isinstance(self.filter_, list):
            filter_ = self.filter_

        elif isinstance(self.filter_, ChatMapLayerFilterType1):
            filter_ = self.filter_.to_dict()
        else:
            filter_ = self.filter_

        geometry_type: None | str | Unset
        if isinstance(self.geometry_type, Unset):
            geometry_type = UNSET
        else:
            geometry_type = self.geometry_type

        label_config: dict[str, Any] | None | Unset
        if isinstance(self.label_config, Unset):
            label_config = UNSET
        elif isinstance(self.label_config, ChatMapLayerLabelConfigType0):
            label_config = self.label_config.to_dict()
        else:
            label_config = self.label_config

        layer_type: None | str | Unset
        if isinstance(self.layer_type, Unset):
            layer_type = UNSET
        else:
            layer_type = self.layer_type

        paint: dict[str, Any] | None | Unset
        if isinstance(self.paint, Unset):
            paint = UNSET
        elif isinstance(self.paint, ChatMapLayerPaintType0):
            paint = self.paint.to_dict()
        else:
            paint = self.paint

        sample_values: dict[str, Any] | None | Unset
        if isinstance(self.sample_values, Unset):
            sample_values = UNSET
        elif isinstance(self.sample_values, ChatMapLayerSampleValuesType0):
            sample_values = self.sample_values.to_dict()
        else:
            sample_values = self.sample_values

        style_config: dict[str, Any] | None | Unset
        if isinstance(self.style_config, Unset):
            style_config = UNSET
        elif isinstance(self.style_config, ChatMapLayerStyleConfigType0):
            style_config = self.style_config.to_dict()
        else:
            style_config = self.style_config

        visible = self.visible

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_id": dataset_id,
                "dataset_table_name": dataset_table_name,
                "id": id,
                "name": name,
            }
        )
        if column_info is not UNSET:
            field_dict["column_info"] = column_info
        if dataset_title is not UNSET:
            field_dict["dataset_title"] = dataset_title
        if feature_count is not UNSET:
            field_dict["feature_count"] = feature_count
        if filter_ is not UNSET:
            field_dict["filter"] = filter_
        if geometry_type is not UNSET:
            field_dict["geometry_type"] = geometry_type
        if label_config is not UNSET:
            field_dict["label_config"] = label_config
        if layer_type is not UNSET:
            field_dict["layer_type"] = layer_type
        if paint is not UNSET:
            field_dict["paint"] = paint
        if sample_values is not UNSET:
            field_dict["sample_values"] = sample_values
        if style_config is not UNSET:
            field_dict["style_config"] = style_config
        if visible is not UNSET:
            field_dict["visible"] = visible

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.chat_map_layer_column_info_type_0_item import (
            ChatMapLayerColumnInfoType0Item,
        )
        from ..models.chat_map_layer_filter_type_1 import ChatMapLayerFilterType1
        from ..models.chat_map_layer_label_config_type_0 import (
            ChatMapLayerLabelConfigType0,
        )
        from ..models.chat_map_layer_paint_type_0 import ChatMapLayerPaintType0
        from ..models.chat_map_layer_sample_values_type_0 import (
            ChatMapLayerSampleValuesType0,
        )
        from ..models.chat_map_layer_style_config_type_0 import (
            ChatMapLayerStyleConfigType0,
        )

        d = dict(src_dict)
        dataset_id = d.pop("dataset_id")

        dataset_table_name = d.pop("dataset_table_name")

        id = d.pop("id")

        name = d.pop("name")

        def _parse_column_info(
            data: object,
        ) -> list[ChatMapLayerColumnInfoType0Item] | None | Unset:
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
                    column_info_type_0_item = ChatMapLayerColumnInfoType0Item.from_dict(
                        column_info_type_0_item_data
                    )

                    column_info_type_0.append(column_info_type_0_item)

                return column_info_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ChatMapLayerColumnInfoType0Item] | None | Unset, data)

        column_info = _parse_column_info(d.pop("column_info", UNSET))

        def _parse_dataset_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dataset_title = _parse_dataset_title(d.pop("dataset_title", UNSET))

        def _parse_feature_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count = _parse_feature_count(d.pop("feature_count", UNSET))

        def _parse_filter_(
            data: object,
        ) -> ChatMapLayerFilterType1 | list[Any] | None | Unset:
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
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                filter_type_1 = ChatMapLayerFilterType1.from_dict(data)

                return filter_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ChatMapLayerFilterType1 | list[Any] | None | Unset, data)

        filter_ = _parse_filter_(d.pop("filter", UNSET))

        def _parse_geometry_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type", UNSET))

        def _parse_label_config(
            data: object,
        ) -> ChatMapLayerLabelConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                label_config_type_0 = ChatMapLayerLabelConfigType0.from_dict(data)

                return label_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ChatMapLayerLabelConfigType0 | None | Unset, data)

        label_config = _parse_label_config(d.pop("label_config", UNSET))

        def _parse_layer_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        layer_type = _parse_layer_type(d.pop("layer_type", UNSET))

        def _parse_paint(data: object) -> ChatMapLayerPaintType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                paint_type_0 = ChatMapLayerPaintType0.from_dict(data)

                return paint_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ChatMapLayerPaintType0 | None | Unset, data)

        paint = _parse_paint(d.pop("paint", UNSET))

        def _parse_sample_values(
            data: object,
        ) -> ChatMapLayerSampleValuesType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                sample_values_type_0 = ChatMapLayerSampleValuesType0.from_dict(data)

                return sample_values_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ChatMapLayerSampleValuesType0 | None | Unset, data)

        sample_values = _parse_sample_values(d.pop("sample_values", UNSET))

        def _parse_style_config(
            data: object,
        ) -> ChatMapLayerStyleConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                style_config_type_0 = ChatMapLayerStyleConfigType0.from_dict(data)

                return style_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ChatMapLayerStyleConfigType0 | None | Unset, data)

        style_config = _parse_style_config(d.pop("style_config", UNSET))

        visible = d.pop("visible", UNSET)

        chat_map_layer = cls(
            dataset_id=dataset_id,
            dataset_table_name=dataset_table_name,
            id=id,
            name=name,
            column_info=column_info,
            dataset_title=dataset_title,
            feature_count=feature_count,
            filter_=filter_,
            geometry_type=geometry_type,
            label_config=label_config,
            layer_type=layer_type,
            paint=paint,
            sample_values=sample_values,
            style_config=style_config,
            visible=visible,
        )

        chat_map_layer.additional_properties = d
        return chat_map_layer

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
