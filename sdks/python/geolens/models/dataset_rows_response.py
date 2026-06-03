from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.column_change import ColumnChange
    from ..models.dataset_rows_response_rows_item import DatasetRowsResponseRowsItem


T = TypeVar("T", bound="DatasetRowsResponse")


@_attrs_define
class DatasetRowsResponse:
    """
    Attributes:
        approximate_total (int): Estimated total row count (may use pg stats)
        columns (list[ColumnChange]):
        rows (list[DatasetRowsResponseRowsItem]):
        next_cursor (int | None | Unset): Cursor value for the next page, null if last
    """

    approximate_total: int
    columns: list[ColumnChange]
    rows: list[DatasetRowsResponseRowsItem]
    next_cursor: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        approximate_total = self.approximate_total

        columns = []
        for columns_item_data in self.columns:
            columns_item = columns_item_data.to_dict()
            columns.append(columns_item)

        rows = []
        for rows_item_data in self.rows:
            rows_item = rows_item_data.to_dict()
            rows.append(rows_item)

        next_cursor: int | None | Unset
        if isinstance(self.next_cursor, Unset):
            next_cursor = UNSET
        else:
            next_cursor = self.next_cursor

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "approximate_total": approximate_total,
                "columns": columns,
                "rows": rows,
            }
        )
        if next_cursor is not UNSET:
            field_dict["next_cursor"] = next_cursor

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_change import ColumnChange
        from ..models.dataset_rows_response_rows_item import DatasetRowsResponseRowsItem

        d = dict(src_dict)
        approximate_total = d.pop("approximate_total")

        columns = []
        _columns = d.pop("columns")
        for columns_item_data in _columns:
            columns_item = ColumnChange.from_dict(columns_item_data)

            columns.append(columns_item)

        rows = []
        _rows = d.pop("rows")
        for rows_item_data in _rows:
            rows_item = DatasetRowsResponseRowsItem.from_dict(rows_item_data)

            rows.append(rows_item)

        def _parse_next_cursor(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        next_cursor = _parse_next_cursor(d.pop("next_cursor", UNSET))

        dataset_rows_response = cls(
            approximate_total=approximate_total,
            columns=columns,
            rows=rows,
            next_cursor=next_cursor,
        )

        dataset_rows_response.additional_properties = d
        return dataset_rows_response

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
