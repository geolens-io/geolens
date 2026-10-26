from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.dataset_rows_response_total_kind import (
    check_dataset_rows_response_total_kind,
)
from ..models.dataset_rows_response_total_kind import DatasetRowsResponseTotalKind
from typing import cast

if TYPE_CHECKING:
    from ..models.column_change import ColumnChange
    from ..models.dataset_rows_response_rows_item import DatasetRowsResponseRowsItem


T = TypeVar("T", bound="DatasetRowsResponse")


@_attrs_define
class DatasetRowsResponse:
    """
    Attributes:
        columns (list[ColumnChange]):
        rows (list[DatasetRowsResponseRowsItem]):
        approximate_total (int): Total row count, or with `filter[...]` or the CQL2 `filter` the matching rows;
            `total_kind` says how exact it is.
        total_kind (DatasetRowsResponseTotalKind | Unset): `estimate` for the table's planner statistics (no filter),
            `exact` for counted matches, `at_least` when more rows match than the 10,000 that are counted. Default:
            'estimate'.
        next_cursor (int | None | Unset): Cursor value for the next page, null if last
        sortable_columns (list[str] | Unset): Columns the rows endpoint accepts as `sort`.
        table_id (None | str | Unset): Opaque id of the data table these rows were read from. Send it as the `table_id`
            query parameter of a feature write or batch delete to have it refused if a reupload or overwrite replaced the
            table since.
    """

    columns: list[ColumnChange]
    rows: list[DatasetRowsResponseRowsItem]
    approximate_total: int
    total_kind: DatasetRowsResponseTotalKind | Unset = "estimate"
    next_cursor: int | None | Unset = UNSET
    sortable_columns: list[str] | Unset = UNSET
    table_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        columns = []
        for columns_item_data in self.columns:
            columns_item = columns_item_data.to_dict()
            columns.append(columns_item)

        rows = []
        for rows_item_data in self.rows:
            rows_item = rows_item_data.to_dict()
            rows.append(rows_item)

        approximate_total = self.approximate_total

        total_kind: str | Unset = UNSET
        if not isinstance(self.total_kind, Unset):
            total_kind = self.total_kind

        next_cursor: int | None | Unset
        if isinstance(self.next_cursor, Unset):
            next_cursor = UNSET
        else:
            next_cursor = self.next_cursor

        sortable_columns: list[str] | Unset = UNSET
        if not isinstance(self.sortable_columns, Unset):
            sortable_columns = self.sortable_columns

        table_id: None | str | Unset
        if isinstance(self.table_id, Unset):
            table_id = UNSET
        else:
            table_id = self.table_id

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "columns": columns,
                "rows": rows,
                "approximate_total": approximate_total,
            }
        )
        if total_kind is not UNSET:
            field_dict["total_kind"] = total_kind
        if next_cursor is not UNSET:
            field_dict["next_cursor"] = next_cursor
        if sortable_columns is not UNSET:
            field_dict["sortable_columns"] = sortable_columns
        if table_id is not UNSET:
            field_dict["table_id"] = table_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_change import ColumnChange
        from ..models.dataset_rows_response_rows_item import DatasetRowsResponseRowsItem

        d = dict(src_dict)
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

        approximate_total = d.pop("approximate_total")

        _total_kind = d.pop("total_kind", UNSET)
        total_kind: DatasetRowsResponseTotalKind | Unset
        if isinstance(_total_kind, Unset):
            total_kind = UNSET
        else:
            total_kind = check_dataset_rows_response_total_kind(_total_kind)

        def _parse_next_cursor(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        next_cursor = _parse_next_cursor(d.pop("next_cursor", UNSET))

        sortable_columns = cast(list[str], d.pop("sortable_columns", UNSET))

        def _parse_table_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        table_id = _parse_table_id(d.pop("table_id", UNSET))

        dataset_rows_response = cls(
            columns=columns,
            rows=rows,
            approximate_total=approximate_total,
            total_kind=total_kind,
            next_cursor=next_cursor,
            sortable_columns=sortable_columns,
            table_id=table_id,
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
