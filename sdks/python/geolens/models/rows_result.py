from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast

if TYPE_CHECKING:
    from ..models.aggregate_row import AggregateRow


T = TypeVar("T", bound="RowsResult")


@_attrs_define
class RowsResult:
    """
    Attributes:
        rows (list[AggregateRow]):
        next_cursor (None | str): Pass as `cursor` for the next page.
        has_more (bool):
    """

    rows: list[AggregateRow]
    next_cursor: None | str
    has_more: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        rows = []
        for rows_item_data in self.rows:
            rows_item = rows_item_data.to_dict()
            rows.append(rows_item)

        next_cursor: None | str
        next_cursor = self.next_cursor

        has_more = self.has_more

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "rows": rows,
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.aggregate_row import AggregateRow

        d = dict(src_dict)
        rows = []
        _rows = d.pop("rows")
        for rows_item_data in _rows:
            rows_item = AggregateRow.from_dict(rows_item_data)

            rows.append(rows_item)

        def _parse_next_cursor(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        next_cursor = _parse_next_cursor(d.pop("next_cursor"))

        has_more = d.pop("has_more")

        rows_result = cls(
            rows=rows,
            next_cursor=next_cursor,
            has_more=has_more,
        )

        rows_result.additional_properties = d
        return rows_result

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
