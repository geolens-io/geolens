from typing import Literal, cast

RowsRequestSort = Literal["asc", "desc"]

ROWS_REQUEST_SORT_VALUES: set[RowsRequestSort] = {
    "asc",
    "desc",
}


def check_rows_request_sort(value: str) -> RowsRequestSort:
    if value in ROWS_REQUEST_SORT_VALUES:
        return cast(RowsRequestSort, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {ROWS_REQUEST_SORT_VALUES!r}"
    )
