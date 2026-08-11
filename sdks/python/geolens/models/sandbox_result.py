from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar("T", bound="SandboxResult")


@_attrs_define
class SandboxResult:
    """Structured result from sandbox query execution.

    Uses list-of-lists for rows (not list-of-dicts) for serialization performance.

        Attributes:
            rows (list[list[Any]]):
            columns (list[str]):
            row_count (int):
            truncated (bool):
    """

    rows: list[list[Any]]
    columns: list[str]
    row_count: int
    truncated: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        rows = []
        for rows_item_data in self.rows:
            rows_item = rows_item_data

            rows.append(rows_item)

        columns = self.columns

        row_count = self.row_count

        truncated = self.truncated

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "rows": rows,
                "columns": columns,
                "row_count": row_count,
                "truncated": truncated,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        rows = []
        _rows = d.pop("rows")
        for rows_item_data in _rows:
            rows_item = cast(list[Any], rows_item_data)

            rows.append(rows_item)

        columns = cast(list[str], d.pop("columns"))

        row_count = d.pop("row_count")

        truncated = d.pop("truncated")

        sandbox_result = cls(
            rows=rows,
            columns=columns,
            row_count=row_count,
            truncated=truncated,
        )

        sandbox_result.additional_properties = d
        return sandbox_result

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
