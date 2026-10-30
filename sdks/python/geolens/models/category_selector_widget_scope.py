from typing import Literal, cast

CategorySelectorWidgetScope = Literal["layer", "view"]

CATEGORY_SELECTOR_WIDGET_SCOPE_VALUES: set[CategorySelectorWidgetScope] = {
    "layer",
    "view",
}


def check_category_selector_widget_scope(value: str) -> CategorySelectorWidgetScope:
    if value in CATEGORY_SELECTOR_WIDGET_SCOPE_VALUES:
        return cast(CategorySelectorWidgetScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {CATEGORY_SELECTOR_WIDGET_SCOPE_VALUES!r}"
    )
