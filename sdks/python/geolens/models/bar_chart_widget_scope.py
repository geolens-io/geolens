from typing import Literal, cast

BarChartWidgetScope = Literal["layer", "view"]

BAR_CHART_WIDGET_SCOPE_VALUES: set[BarChartWidgetScope] = {
    "layer",
    "view",
}


def check_bar_chart_widget_scope(value: str) -> BarChartWidgetScope:
    if value in BAR_CHART_WIDGET_SCOPE_VALUES:
        return cast(BarChartWidgetScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BAR_CHART_WIDGET_SCOPE_VALUES!r}"
    )
