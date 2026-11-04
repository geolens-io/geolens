from typing import Literal, cast

GroupStatStat = Literal["avg", "count", "max", "min", "sum"]

GROUP_STAT_STAT_VALUES: set[GroupStatStat] = {
    "avg",
    "count",
    "max",
    "min",
    "sum",
}


def check_group_stat_stat(value: str) -> GroupStatStat:
    if value in GROUP_STAT_STAT_VALUES:
        return cast(GroupStatStat, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GROUP_STAT_STAT_VALUES!r}"
    )
