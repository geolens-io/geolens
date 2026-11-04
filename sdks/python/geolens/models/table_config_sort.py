from typing import Literal, cast

TableConfigSort = Literal["asc", "desc"]

TABLE_CONFIG_SORT_VALUES: set[TableConfigSort] = {
    "asc",
    "desc",
}


def check_table_config_sort(value: str) -> TableConfigSort:
    if value in TABLE_CONFIG_SORT_VALUES:
        return cast(TableConfigSort, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {TABLE_CONFIG_SORT_VALUES!r}"
    )
