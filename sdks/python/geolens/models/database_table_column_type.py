from typing import Literal, cast

DatabaseTableColumnType = Literal["geography", "geometry"]

DATABASE_TABLE_COLUMN_TYPE_VALUES: set[DatabaseTableColumnType] = {
    "geography",
    "geometry",
}


def check_database_table_column_type(value: str) -> DatabaseTableColumnType:
    if value in DATABASE_TABLE_COLUMN_TYPE_VALUES:
        return cast(DatabaseTableColumnType, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DATABASE_TABLE_COLUMN_TYPE_VALUES!r}"
    )
