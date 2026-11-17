from typing import Literal, cast

CategorySelectorWidgetV = Literal[1, 2]

CATEGORY_SELECTOR_WIDGET_V_VALUES: set[CategorySelectorWidgetV] = {
    1,
    2,
}


def check_category_selector_widget_v(value: int) -> CategorySelectorWidgetV:
    if value in CATEGORY_SELECTOR_WIDGET_V_VALUES:
        return cast(CategorySelectorWidgetV, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {CATEGORY_SELECTOR_WIDGET_V_VALUES!r}"
    )
