from typing import Literal, cast

PieChartWidgetScope = Literal["layer", "view"]

PIE_CHART_WIDGET_SCOPE_VALUES: set[PieChartWidgetScope] = {
    "layer",
    "view",
}


def check_pie_chart_widget_scope(value: str) -> PieChartWidgetScope:
    if value in PIE_CHART_WIDGET_SCOPE_VALUES:
        return cast(PieChartWidgetScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {PIE_CHART_WIDGET_SCOPE_VALUES!r}"
    )
