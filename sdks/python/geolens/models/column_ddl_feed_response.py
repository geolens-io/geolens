from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.column_ddl_entry import ColumnDdlEntry


T = TypeVar("T", bound="ColumnDdlFeedResponse")


@_attrs_define
class ColumnDdlFeedResponse:
    """Paginated response for GET /api/audit/datasets/{dataset_id}/column-ddl.

    Attributes:
        items (list[ColumnDdlEntry]):
        limit (int):
        offset (int):
        total (int):
    """

    items: list[ColumnDdlEntry]
    limit: int
    offset: int
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        items = []
        for items_item_data in self.items:
            items_item = items_item_data.to_dict()
            items.append(items_item)

        limit = self.limit

        offset = self.offset

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "items": items,
                "limit": limit,
                "offset": offset,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_ddl_entry import ColumnDdlEntry

        d = dict(src_dict)
        items = []
        _items = d.pop("items")
        for items_item_data in _items:
            items_item = ColumnDdlEntry.from_dict(items_item_data)

            items.append(items_item)

        limit = d.pop("limit")

        offset = d.pop("offset")

        total = d.pop("total")

        column_ddl_feed_response = cls(
            items=items,
            limit=limit,
            offset=offset,
            total=total,
        )

        column_ddl_feed_response.additional_properties = d
        return column_ddl_feed_response

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
