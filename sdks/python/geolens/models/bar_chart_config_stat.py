from typing import Literal, cast

BarChartConfigStat = Literal["count", "max", "mean", "min", "sum"]

BAR_CHART_CONFIG_STAT_VALUES: set[BarChartConfigStat] = {
    "count",
    "max",
    "mean",
    "min",
    "sum",
}


def check_bar_chart_config_stat(value: str) -> BarChartConfigStat:
    if value in BAR_CHART_CONFIG_STAT_VALUES:
        return cast(BarChartConfigStat, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BAR_CHART_CONFIG_STAT_VALUES!r}"
    )
