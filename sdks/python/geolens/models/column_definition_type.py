from typing import Literal, cast

ColumnDefinitionType = Literal["boolean", "date", "float", "integer", "text"]

COLUMN_DEFINITION_TYPE_VALUES: set[ColumnDefinitionType] = {
    "boolean",
    "date",
    "float",
    "integer",
    "text",
}


def check_column_definition_type(value: str) -> ColumnDefinitionType:
    if value in COLUMN_DEFINITION_TYPE_VALUES:
        return cast(ColumnDefinitionType, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {COLUMN_DEFINITION_TYPE_VALUES!r}"
    )
