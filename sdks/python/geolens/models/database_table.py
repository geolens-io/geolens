from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.database_table_column_type import check_database_table_column_type
from ..models.database_table_column_type import DatabaseTableColumnType
from ..models.database_table_object_type import check_database_table_object_type
from ..models.database_table_object_type import DatabaseTableObjectType
from typing import cast


T = TypeVar("T", bound="DatabaseTable")


@_attrs_define
class DatabaseTable:
    """
    Attributes:
        schema_name (str): Schema that holds the table or view.
        table_name (str): Table or view name.
        object_type (DatabaseTableObjectType): Table or view.
        geometry_column (str): Spatial column.
        column_type (DatabaseTableColumnType): SQL Server spatial type of the column.
        srid (int | None): SRID of the column's first non-null value, or null when it is 0, the table has no rows, or it
            couldn't be read.
        importable (bool): False when the schema or table name has characters an import refuses; such an entry is listed
            but can't be imported.
    """

    schema_name: str
    table_name: str
    object_type: DatabaseTableObjectType
    geometry_column: str
    column_type: DatabaseTableColumnType
    srid: int | None
    importable: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        schema_name = self.schema_name

        table_name = self.table_name

        object_type: str = self.object_type

        geometry_column = self.geometry_column

        column_type: str = self.column_type

        srid: int | None
        srid = self.srid

        importable = self.importable

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "schema_name": schema_name,
                "table_name": table_name,
                "object_type": object_type,
                "geometry_column": geometry_column,
                "column_type": column_type,
                "srid": srid,
                "importable": importable,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        schema_name = d.pop("schema_name")

        table_name = d.pop("table_name")

        object_type = check_database_table_object_type(d.pop("object_type"))

        geometry_column = d.pop("geometry_column")

        column_type = check_database_table_column_type(d.pop("column_type"))

        def _parse_srid(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        srid = _parse_srid(d.pop("srid"))

        importable = d.pop("importable")

        database_table = cls(
            schema_name=schema_name,
            table_name=table_name,
            object_type=object_type,
            geometry_column=geometry_column,
            column_type=column_type,
            srid=srid,
            importable=importable,
        )

        database_table.additional_properties = d
        return database_table

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
