from typing import Literal, cast

BarChartWidgetV = Literal[1, 2]

BAR_CHART_WIDGET_V_VALUES: set[BarChartWidgetV] = {
    1,
    2,
}


def check_bar_chart_widget_v(value: int) -> BarChartWidgetV:
    if value in BAR_CHART_WIDGET_V_VALUES:
        return cast(BarChartWidgetV, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BAR_CHART_WIDGET_V_VALUES!r}"
    )
