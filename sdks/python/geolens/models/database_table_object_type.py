from typing import Literal, cast

DatabaseTableObjectType = Literal["table", "view"]

DATABASE_TABLE_OBJECT_TYPE_VALUES: set[DatabaseTableObjectType] = {
    "table",
    "view",
}


def check_database_table_object_type(value: str) -> DatabaseTableObjectType:
    if value in DATABASE_TABLE_OBJECT_TYPE_VALUES:
        return cast(DatabaseTableObjectType, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DATABASE_TABLE_OBJECT_TYPE_VALUES!r}"
    )
