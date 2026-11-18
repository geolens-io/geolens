from typing import Literal, cast

IndicatorWidgetV = Literal[1, 2, 3]

INDICATOR_WIDGET_V_VALUES: set[IndicatorWidgetV] = {
    1,
    2,
    3,
}


def check_indicator_widget_v(value: int) -> IndicatorWidgetV:
    if value in INDICATOR_WIDGET_V_VALUES:
        return cast(IndicatorWidgetV, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {INDICATOR_WIDGET_V_VALUES!r}"
    )
