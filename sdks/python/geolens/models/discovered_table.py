from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="DiscoveredTable")


@_attrs_define
class DiscoveredTable:
    """
    Attributes:
        table_name (str): PostgreSQL table name in the `data` schema.
        geometry_type (None | str): Detected geometry type, or null for non-spatial tables.
        srid (int | None): Coordinate reference system EPSG code, if defined.
        estimated_rows (int | None): PostgreSQL row count estimate from `pg_class.reltuples`.
        refusal_reason (None | str | Unset): Why registration would refuse this table, as one of a fixed set of GeoLens
            codes: source_srid_undeclared. Null when discovery finds none, though registration can still refuse a table for
            a reason discovery does not check.
    """

    table_name: str
    geometry_type: None | str
    srid: int | None
    estimated_rows: int | None
    refusal_reason: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        table_name = self.table_name

        geometry_type: None | str
        geometry_type = self.geometry_type

        srid: int | None
        srid = self.srid

        estimated_rows: int | None
        estimated_rows = self.estimated_rows

        refusal_reason: None | str | Unset
        if isinstance(self.refusal_reason, Unset):
            refusal_reason = UNSET
        else:
            refusal_reason = self.refusal_reason

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "table_name": table_name,
                "geometry_type": geometry_type,
                "srid": srid,
                "estimated_rows": estimated_rows,
            }
        )
        if refusal_reason is not UNSET:
            field_dict["refusal_reason"] = refusal_reason

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        table_name = d.pop("table_name")

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

        def _parse_estimated_rows(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        estimated_rows = _parse_estimated_rows(d.pop("estimated_rows"))

        def _parse_refusal_reason(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        refusal_reason = _parse_refusal_reason(d.pop("refusal_reason", UNSET))

        discovered_table = cls(
            table_name=table_name,
            geometry_type=geometry_type,
            srid=srid,
            estimated_rows=estimated_rows,
            refusal_reason=refusal_reason,
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
