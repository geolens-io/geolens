from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar("T", bound="DiscoveredTable")


@_attrs_define
class DiscoveredTable:
    """
    Attributes:
        estimated_rows (int | None): PostgreSQL row count estimate from `pg_class.reltuples`.
        geometry_type (None | str): Detected geometry type, or null for non-spatial tables.
        srid (int | None): Coordinate reference system EPSG code, if defined.
        table_name (str): PostgreSQL table name in the `data` schema.
    """

    estimated_rows: int | None
    geometry_type: None | str
    srid: int | None
    table_name: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        estimated_rows: int | None
        estimated_rows = self.estimated_rows

        geometry_type: None | str
        geometry_type = self.geometry_type

        srid: int | None
        srid = self.srid

        table_name = self.table_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "estimated_rows": estimated_rows,
                "geometry_type": geometry_type,
                "srid": srid,
                "table_name": table_name,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_estimated_rows(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        estimated_rows = _parse_estimated_rows(d.pop("estimated_rows"))

        def _parse_geometry_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type"))

        def _parse_srid(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        srid = _parse_srid(d.pop("srid"))

        table_name = d.pop("table_name")

        discovered_table = cls(
            estimated_rows=estimated_rows,
            geometry_type=geometry_type,
            srid=srid,
            table_name=table_name,
        )

        discovered_table.additional_properties = d
        return discovered_table

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
