from typing import Literal, cast

TableStatStat = Literal["count", "max", "mean", "min", "sum"]

TABLE_STAT_STAT_VALUES: set[TableStatStat] = {
    "count",
    "max",
    "mean",
    "min",
    "sum",
}


def check_table_stat_stat(value: str) -> TableStatStat:
    if value in TABLE_STAT_STAT_VALUES:
        return cast(TableStatStat, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {TABLE_STAT_STAT_VALUES!r}"
    )
