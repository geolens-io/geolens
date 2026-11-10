from typing import Literal, cast

StatsRequestStatsItem = Literal["avg", "count", "max", "min", "sum"]

STATS_REQUEST_STATS_ITEM_VALUES: set[StatsRequestStatsItem] = {
    "avg",
    "count",
    "max",
    "min",
    "sum",
}


def check_stats_request_stats_item(value: str) -> StatsRequestStatsItem:
    if value in STATS_REQUEST_STATS_ITEM_VALUES:
        return cast(StatsRequestStatsItem, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {STATS_REQUEST_STATS_ITEM_VALUES!r}"
    )
