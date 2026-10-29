from typing import Literal, cast

HistogramWidgetScope = Literal["layer", "view"]

HISTOGRAM_WIDGET_SCOPE_VALUES: set[HistogramWidgetScope] = {
    "layer",
    "view",
}


def check_histogram_widget_scope(value: str) -> HistogramWidgetScope:
    if value in HISTOGRAM_WIDGET_SCOPE_VALUES:
        return cast(HistogramWidgetScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {HISTOGRAM_WIDGET_SCOPE_VALUES!r}"
    )
