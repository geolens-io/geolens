from typing import Literal, cast

BarChartConfigMode = Literal["by_feature", "by_fields", "category", "date"]

BAR_CHART_CONFIG_MODE_VALUES: set[BarChartConfigMode] = {
    "by_feature",
    "by_fields",
    "category",
    "date",
}


def check_bar_chart_config_mode(value: str) -> BarChartConfigMode:
    if value in BAR_CHART_CONFIG_MODE_VALUES:
        return cast(BarChartConfigMode, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BAR_CHART_CONFIG_MODE_VALUES!r}"
    )
