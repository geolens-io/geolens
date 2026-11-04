from typing import Literal, cast

BarChartConfigSort = Literal["asc", "desc"]

BAR_CHART_CONFIG_SORT_VALUES: set[BarChartConfigSort] = {
    "asc",
    "desc",
}


def check_bar_chart_config_sort(value: str) -> BarChartConfigSort:
    if value in BAR_CHART_CONFIG_SORT_VALUES:
        return cast(BarChartConfigSort, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BAR_CHART_CONFIG_SORT_VALUES!r}"
    )
