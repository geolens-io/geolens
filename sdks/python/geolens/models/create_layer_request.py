from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.column_def import ColumnDef


T = TypeVar("T", bound="CreateLayerRequest")


@_attrs_define
class CreateLayerRequest:
    """
    Attributes:
        geometry_type (str): OGC geometry type: Point, MultiPoint, LineString, MultiLineString, Polygon, or MultiPolygon
            Example: Point.
        title (str): Display name for the new layer Example: Survey Points.
        columns (list[ColumnDef] | None | Unset): Optional initial column definitions
        summary (None | str | Unset): Optional text description of the layer
    """

    geometry_type: str
    title: str
    columns: list[ColumnDef] | None | Unset = UNSET
    summary: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        geometry_type = self.geometry_type

        title = self.title

        columns: list[dict[str, Any]] | None | Unset
        if isinstance(self.columns, Unset):
            columns = UNSET
        elif isinstance(self.columns, list):
            columns = []
            for columns_type_0_item_data in self.columns:
                columns_type_0_item = columns_type_0_item_data.to_dict()
                columns.append(columns_type_0_item)

        else:
            columns = self.columns

        summary: None | str | Unset
        if isinstance(self.summary, Unset):
            summary = UNSET
        else:
            summary = self.summary

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "geometry_type": geometry_type,
                "title": title,
            }
        )
        if columns is not UNSET:
            field_dict["columns"] = columns
        if summary is not UNSET:
            field_dict["summary"] = summary

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_def import ColumnDef

        d = dict(src_dict)
        geometry_type = d.pop("geometry_type")

        title = d.pop("title")

        def _parse_columns(data: object) -> list[ColumnDef] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                columns_type_0 = []
                _columns_type_0 = data
                for columns_type_0_item_data in _columns_type_0:
                    columns_type_0_item = ColumnDef.from_dict(columns_type_0_item_data)

                    columns_type_0.append(columns_type_0_item)

                return columns_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ColumnDef] | None | Unset, data)

        columns = _parse_columns(d.pop("columns", UNSET))

        def _parse_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        summary = _parse_summary(d.pop("summary", UNSET))

        create_layer_request = cls(
            geometry_type=geometry_type,
            title=title,
            columns=columns,
            summary=summary,
        )

        create_layer_request.additional_properties = d
        return create_layer_request

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
