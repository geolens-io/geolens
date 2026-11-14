from typing import Literal, cast

HistogramWidgetV = Literal[1, 2]

HISTOGRAM_WIDGET_V_VALUES: set[HistogramWidgetV] = {
    1,
    2,
}


def check_histogram_widget_v(value: int) -> HistogramWidgetV:
    if value in HISTOGRAM_WIDGET_V_VALUES:
        return cast(HistogramWidgetV, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {HISTOGRAM_WIDGET_V_VALUES!r}"
    )
