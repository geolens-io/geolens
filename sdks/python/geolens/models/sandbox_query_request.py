from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="SandboxQueryRequest")


@_attrs_define
class SandboxQueryRequest:
    """One read-only SELECT plus its mandatory table scope.

    Attributes:
        sql (str): A single SELECT statement over `data.*` tables.
        restrict_tables (list[str]): Table names (without the `data.` prefix) the query may touch. Required and non-
            empty; intersected with your access — it can only narrow what you already see, never widen it.
        row_limit (int | Unset): Maximum rows to return. Default: 100.
    """

    sql: str
    restrict_tables: list[str]
    row_limit: int | Unset = 100
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        sql = self.sql

        restrict_tables = self.restrict_tables

        row_limit = self.row_limit

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "sql": sql,
                "restrict_tables": restrict_tables,
            }
        )
        if row_limit is not UNSET:
            field_dict["row_limit"] = row_limit

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        sql = d.pop("sql")

        restrict_tables = cast(list[str], d.pop("restrict_tables"))

        row_limit = d.pop("row_limit", UNSET)

        sandbox_query_request = cls(
            sql=sql,
            restrict_tables=restrict_tables,
            row_limit=row_limit,
        )

        sandbox_query_request.additional_properties = d
        return sandbox_query_request

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
