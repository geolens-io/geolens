from typing import Literal, cast

GroupByRequestStat = Literal["avg", "count", "max", "min", "sum"]

GROUP_BY_REQUEST_STAT_VALUES: set[GroupByRequestStat] = {
    "avg",
    "count",
    "max",
    "min",
    "sum",
}


def check_group_by_request_stat(value: str) -> GroupByRequestStat:
    if value in GROUP_BY_REQUEST_STAT_VALUES:
        return cast(GroupByRequestStat, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GROUP_BY_REQUEST_STAT_VALUES!r}"
    )
