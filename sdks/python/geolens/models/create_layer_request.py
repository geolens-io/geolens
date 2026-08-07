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
        title (str): Display name for the new layer Example: Survey Points.
        geometry_type (str): OGC geometry type: Point, MultiPoint, LineString, MultiLineString, Polygon, or MultiPolygon
            Example: Point.
        summary (None | str | Unset): Optional text description of the layer
        columns (list[ColumnDef] | None | Unset): Optional initial column definitions
    """

    title: str
    geometry_type: str
    summary: None | str | Unset = UNSET
    columns: list[ColumnDef] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        title = self.title

        geometry_type = self.geometry_type

        summary: None | str | Unset
        if isinstance(self.summary, Unset):
            summary = UNSET
        else:
            summary = self.summary

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

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "title": title,
                "geometry_type": geometry_type,
            }
        )
        if summary is not UNSET:
            field_dict["summary"] = summary
        if columns is not UNSET:
            field_dict["columns"] = columns

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_def import ColumnDef

        d = dict(src_dict)
        title = d.pop("title")

        geometry_type = d.pop("geometry_type")

        def _parse_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        summary = _parse_summary(d.pop("summary", UNSET))

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

        create_layer_request = cls(
            title=title,
            geometry_type=geometry_type,
            summary=summary,
            columns=columns,
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
