from typing import Literal, cast

GroupByRequestSortType0 = Literal["asc", "desc"]

GROUP_BY_REQUEST_SORT_TYPE_0_VALUES: set[GroupByRequestSortType0] = {
    "asc",
    "desc",
}


def check_group_by_request_sort_type_0(value: str) -> GroupByRequestSortType0:
    if value in GROUP_BY_REQUEST_SORT_TYPE_0_VALUES:
        return cast(GroupByRequestSortType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GROUP_BY_REQUEST_SORT_TYPE_0_VALUES!r}"
    )
