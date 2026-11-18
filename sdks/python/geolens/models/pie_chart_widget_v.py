from typing import Literal, cast

PieChartWidgetV = Literal[1, 2]

PIE_CHART_WIDGET_V_VALUES: set[PieChartWidgetV] = {
    1,
    2,
}


def check_pie_chart_widget_v(value: int) -> PieChartWidgetV:
    if value in PIE_CHART_WIDGET_V_VALUES:
        return cast(PieChartWidgetV, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {PIE_CHART_WIDGET_V_VALUES!r}"
    )
