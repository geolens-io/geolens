from typing import Literal, cast

PieChartConfigStat = Literal["count", "max", "mean", "min", "sum"]

PIE_CHART_CONFIG_STAT_VALUES: set[PieChartConfigStat] = {
    "count",
    "max",
    "mean",
    "min",
    "sum",
}


def check_pie_chart_config_stat(value: str) -> PieChartConfigStat:
    if value in PIE_CHART_CONFIG_STAT_VALUES:
        return cast(PieChartConfigStat, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {PIE_CHART_CONFIG_STAT_VALUES!r}"
    )
