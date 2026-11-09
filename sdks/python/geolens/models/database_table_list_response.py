from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.database_table import DatabaseTable


T = TypeVar("T", bound="DatabaseTableListResponse")


@_attrs_define
class DatabaseTableListResponse:
    """
    Attributes:
        connection (str): Connection name from the deployment.
        database (str): Database the connection reads.
        tables (list[DatabaseTable]): One entry per spatial column, ordered by schema, table and column.
        limit (int): Most entries one listing returns.
        truncated (bool): True when the connection has more spatial columns than `limit`.
    """

    connection: str
    database: str
    tables: list[DatabaseTable]
    limit: int
    truncated: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        connection = self.connection

        database = self.database

        tables = []
        for tables_item_data in self.tables:
            tables_item = tables_item_data.to_dict()
            tables.append(tables_item)

        limit = self.limit

        truncated = self.truncated

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "connection": connection,
                "database": database,
                "tables": tables,
                "limit": limit,
                "truncated": truncated,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.database_table import DatabaseTable

        d = dict(src_dict)
        connection = d.pop("connection")

        database = d.pop("database")

        tables = []
        _tables = d.pop("tables")
        for tables_item_data in _tables:
            tables_item = DatabaseTable.from_dict(tables_item_data)

            tables.append(tables_item)

        limit = d.pop("limit")

        truncated = d.pop("truncated")

        database_table_list_response = cls(
            connection=connection,
            database=database,
            tables=tables,
            limit=limit,
            truncated=truncated,
        )

        database_table_list_response.additional_properties = d
        return database_table_list_response

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
