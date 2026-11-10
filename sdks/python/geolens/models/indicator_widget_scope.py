from typing import Literal, cast

IndicatorWidgetScope = Literal["layer", "view"]

INDICATOR_WIDGET_SCOPE_VALUES: set[IndicatorWidgetScope] = {
    "layer",
    "view",
}


def check_indicator_widget_scope(value: str) -> IndicatorWidgetScope:
    if value in INDICATOR_WIDGET_SCOPE_VALUES:
        return cast(IndicatorWidgetScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {INDICATOR_WIDGET_SCOPE_VALUES!r}"
    )
