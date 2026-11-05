from typing import Literal, cast

GroupByRequestStatType0 = Literal["avg", "count", "max", "min", "sum"]

GROUP_BY_REQUEST_STAT_TYPE_0_VALUES: set[GroupByRequestStatType0] = {
    "avg",
    "count",
    "max",
    "min",
    "sum",
}


def check_group_by_request_stat_type_0(value: str) -> GroupByRequestStatType0:
    if value in GROUP_BY_REQUEST_STAT_TYPE_0_VALUES:
        return cast(GroupByRequestStatType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GROUP_BY_REQUEST_STAT_TYPE_0_VALUES!r}"
    )
