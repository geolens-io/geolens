from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.discovered_table import DiscoveredTable


T = TypeVar("T", bound="DiscoverResponse")


@_attrs_define
class DiscoverResponse:
    """
    Attributes:
        tables (list[DiscoveredTable]): Tables in the `data` schema that are eligible for registration as datasets.
    """

    tables: list[DiscoveredTable]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tables = []
        for tables_item_data in self.tables:
            tables_item = tables_item_data.to_dict()
            tables.append(tables_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "tables": tables,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.discovered_table import DiscoveredTable

        d = dict(src_dict)
        tables = []
        _tables = d.pop("tables")
        for tables_item_data in _tables:
            tables_item = DiscoveredTable.from_dict(tables_item_data)

            tables.append(tables_item)

        discover_response = cls(
            tables=tables,
        )

        discover_response.additional_properties = d
        return discover_response

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
