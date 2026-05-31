from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.chat_action_type import ChatActionType
from ..models.chat_action_type import check_chat_action_type
from typing import cast

if TYPE_CHECKING:
    from ..models.chat_action_label_config_type_0 import ChatActionLabelConfigType0
    from ..models.chat_action_paint_type_0 import ChatActionPaintType0
    from ..models.chat_action_style_config_type_0 import ChatActionStyleConfigType0
    from ..models.geo_json_feature_collection import GeoJSONFeatureCollection


T = TypeVar("T", bound="ChatAction")


@_attrs_define
class ChatAction:
    """
    Attributes:
        type_ (ChatActionType):
        bbox (list[float] | None | Unset):
        clear_paint (list[str] | None | Unset):
        columns (list[str] | None | Unset):
        dataset_id (None | str | Unset):
        dataset_name (None | str | Unset):
        expression (list[Any] | None | Unset):
        geojson (GeoJSONFeatureCollection | None | Unset):
        label_config (ChatActionLabelConfigType0 | None | Unset):
        layer_id (None | str | Unset):
        opacity (float | None | Unset):
        paint (ChatActionPaintType0 | None | Unset):
        replace_paint (bool | None | Unset):
        row_count (int | None | Unset):
        rows (list[list[Any]] | None | Unset):
        style_config (ChatActionStyleConfigType0 | None | Unset):
        truncated (bool | None | Unset):
        visible (bool | None | Unset):
    """

    type_: ChatActionType
    bbox: list[float] | None | Unset = UNSET
    clear_paint: list[str] | None | Unset = UNSET
    columns: list[str] | None | Unset = UNSET
    dataset_id: None | str | Unset = UNSET
    dataset_name: None | str | Unset = UNSET
    expression: list[Any] | None | Unset = UNSET
    geojson: GeoJSONFeatureCollection | None | Unset = UNSET
    label_config: ChatActionLabelConfigType0 | None | Unset = UNSET
    layer_id: None | str | Unset = UNSET
    opacity: float | None | Unset = UNSET
    paint: ChatActionPaintType0 | None | Unset = UNSET
    replace_paint: bool | None | Unset = UNSET
    row_count: int | None | Unset = UNSET
    rows: list[list[Any]] | None | Unset = UNSET
    style_config: ChatActionStyleConfigType0 | None | Unset = UNSET
    truncated: bool | None | Unset = UNSET
    visible: bool | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.chat_action_label_config_type_0 import ChatActionLabelConfigType0
        from ..models.chat_action_paint_type_0 import ChatActionPaintType0
        from ..models.chat_action_style_config_type_0 import ChatActionStyleConfigType0
        from ..models.geo_json_feature_collection import GeoJSONFeatureCollection

        type_: str = self.type_

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        clear_paint: list[str] | None | Unset
        if isinstance(self.clear_paint, Unset):
            clear_paint = UNSET
        elif isinstance(self.clear_paint, list):
            clear_paint = self.clear_paint

        else:
            clear_paint = self.clear_paint

        columns: list[str] | None | Unset
        if isinstance(self.columns, Unset):
            columns = UNSET
        elif isinstance(self.columns, list):
            columns = self.columns

        else:
            columns = self.columns

        dataset_id: None | str | Unset
        if isinstance(self.dataset_id, Unset):
            dataset_id = UNSET
        else:
            dataset_id = self.dataset_id

        dataset_name: None | str | Unset
        if isinstance(self.dataset_name, Unset):
            dataset_name = UNSET
        else:
            dataset_name = self.dataset_name

        expression: list[Any] | None | Unset
        if isinstance(self.expression, Unset):
            expression = UNSET
        elif isinstance(self.expression, list):
            expression = self.expression

        else:
            expression = self.expression

        geojson: dict[str, Any] | None | Unset
        if isinstance(self.geojson, Unset):
            geojson = UNSET
        elif isinstance(self.geojson, GeoJSONFeatureCollection):
            geojson = self.geojson.to_dict()
        else:
            geojson = self.geojson

        label_config: dict[str, Any] | None | Unset
        if isinstance(self.label_config, Unset):
            label_config = UNSET
        elif isinstance(self.label_config, ChatActionLabelConfigType0):
            label_config = self.label_config.to_dict()
        else:
            label_config = self.label_config

        layer_id: None | str | Unset
        if isinstance(self.layer_id, Unset):
            layer_id = UNSET
        else:
            layer_id = self.layer_id

        opacity: float | None | Unset
        if isinstance(self.opacity, Unset):
            opacity = UNSET
        else:
            opacity = self.opacity

        paint: dict[str, Any] | None | Unset
        if isinstance(self.paint, Unset):
            paint = UNSET
        elif isinstance(self.paint, ChatActionPaintType0):
            paint = self.paint.to_dict()
        else:
            paint = self.paint

        replace_paint: bool | None | Unset
        if isinstance(self.replace_paint, Unset):
            replace_paint = UNSET
        else:
            replace_paint = self.replace_paint

        row_count: int | None | Unset
        if isinstance(self.row_count, Unset):
            row_count = UNSET
        else:
            row_count = self.row_count

        rows: list[list[Any]] | None | Unset
        if isinstance(self.rows, Unset):
            rows = UNSET
        elif isinstance(self.rows, list):
            rows = []
            for rows_type_0_item_data in self.rows:
                rows_type_0_item = rows_type_0_item_data

                rows.append(rows_type_0_item)

        else:
            rows = self.rows

        style_config: dict[str, Any] | None | Unset
        if isinstance(self.style_config, Unset):
            style_config = UNSET
        elif isinstance(self.style_config, ChatActionStyleConfigType0):
            style_config = self.style_config.to_dict()
        else:
            style_config = self.style_config

        truncated: bool | None | Unset
        if isinstance(self.truncated, Unset):
            truncated = UNSET
        else:
            truncated = self.truncated

        visible: bool | None | Unset
        if isinstance(self.visible, Unset):
            visible = UNSET
        else:
            visible = self.visible

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
            }
        )
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if clear_paint is not UNSET:
            field_dict["clear_paint"] = clear_paint
        if columns is not UNSET:
            field_dict["columns"] = columns
        if dataset_id is not UNSET:
            field_dict["dataset_id"] = dataset_id
        if dataset_name is not UNSET:
            field_dict["dataset_name"] = dataset_name
        if expression is not UNSET:
            field_dict["expression"] = expression
        if geojson is not UNSET:
            field_dict["geojson"] = geojson
        if label_config is not UNSET:
            field_dict["label_config"] = label_config
        if layer_id is not UNSET:
            field_dict["layer_id"] = layer_id
        if opacity is not UNSET:
            field_dict["opacity"] = opacity
        if paint is not UNSET:
            field_dict["paint"] = paint
        if replace_paint is not UNSET:
            field_dict["replace_paint"] = replace_paint
        if row_count is not UNSET:
            field_dict["row_count"] = row_count
        if rows is not UNSET:
            field_dict["rows"] = rows
        if style_config is not UNSET:
            field_dict["style_config"] = style_config
        if truncated is not UNSET:
            field_dict["truncated"] = truncated
        if visible is not UNSET:
            field_dict["visible"] = visible

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.chat_action_label_config_type_0 import ChatActionLabelConfigType0
        from ..models.chat_action_paint_type_0 import ChatActionPaintType0
        from ..models.chat_action_style_config_type_0 import ChatActionStyleConfigType0
        from ..models.geo_json_feature_collection import GeoJSONFeatureCollection

        d = dict(src_dict)
        type_ = check_chat_action_type(d.pop("type"))

        def _parse_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                bbox_type_0 = cast(list[float], data)

                return bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        bbox = _parse_bbox(d.pop("bbox", UNSET))

        def _parse_clear_paint(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                clear_paint_type_0 = cast(list[str], data)

                return clear_paint_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        clear_paint = _parse_clear_paint(d.pop("clear_paint", UNSET))

        def _parse_columns(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                columns_type_0 = cast(list[str], data)

                return columns_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        columns = _parse_columns(d.pop("columns", UNSET))

        def _parse_dataset_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dataset_id = _parse_dataset_id(d.pop("dataset_id", UNSET))

        def _parse_dataset_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        dataset_name = _parse_dataset_name(d.pop("dataset_name", UNSET))

        def _parse_expression(data: object) -> list[Any] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                expression_type_0 = cast(list[Any], data)

                return expression_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[Any] | None | Unset, data)

        expression = _parse_expression(d.pop("expression", UNSET))

        def _parse_geojson(data: object) -> GeoJSONFeatureCollection | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geojson_type_0 = GeoJSONFeatureCollection.from_dict(data)

                return geojson_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GeoJSONFeatureCollection | None | Unset, data)

        geojson = _parse_geojson(d.pop("geojson", UNSET))

        def _parse_label_config(
            data: object,
        ) -> ChatActionLabelConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                label_config_type_0 = ChatActionLabelConfigType0.from_dict(data)

                return label_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ChatActionLabelConfigType0 | None | Unset, data)

        label_config = _parse_label_config(d.pop("label_config", UNSET))

        def _parse_layer_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        layer_id = _parse_layer_id(d.pop("layer_id", UNSET))

        def _parse_opacity(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        opacity = _parse_opacity(d.pop("opacity", UNSET))

        def _parse_paint(data: object) -> ChatActionPaintType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                paint_type_0 = ChatActionPaintType0.from_dict(data)

                return paint_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ChatActionPaintType0 | None | Unset, data)

        paint = _parse_paint(d.pop("paint", UNSET))

        def _parse_replace_paint(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        replace_paint = _parse_replace_paint(d.pop("replace_paint", UNSET))

        def _parse_row_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        row_count = _parse_row_count(d.pop("row_count", UNSET))

        def _parse_rows(data: object) -> list[list[Any]] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                rows_type_0 = []
                _rows_type_0 = data
                for rows_type_0_item_data in _rows_type_0:
                    rows_type_0_item = cast(list[Any], rows_type_0_item_data)

                    rows_type_0.append(rows_type_0_item)

                return rows_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[list[Any]] | None | Unset, data)

        rows = _parse_rows(d.pop("rows", UNSET))

        def _parse_style_config(
            data: object,
        ) -> ChatActionStyleConfigType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                style_config_type_0 = ChatActionStyleConfigType0.from_dict(data)

                return style_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ChatActionStyleConfigType0 | None | Unset, data)

        style_config = _parse_style_config(d.pop("style_config", UNSET))

        def _parse_truncated(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        truncated = _parse_truncated(d.pop("truncated", UNSET))

        def _parse_visible(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        visible = _parse_visible(d.pop("visible", UNSET))

        chat_action = cls(
            type_=type_,
            bbox=bbox,
            clear_paint=clear_paint,
            columns=columns,
            dataset_id=dataset_id,
            dataset_name=dataset_name,
            expression=expression,
            geojson=geojson,
            label_config=label_config,
            layer_id=layer_id,
            opacity=opacity,
            paint=paint,
            replace_paint=replace_paint,
            row_count=row_count,
            rows=rows,
            style_config=style_config,
            truncated=truncated,
            visible=visible,
        )

        chat_action.additional_properties = d
        return chat_action

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
