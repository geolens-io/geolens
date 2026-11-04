from typing import Literal, cast

FeatureListWidgetScope = Literal["layer", "view"]

FEATURE_LIST_WIDGET_SCOPE_VALUES: set[FeatureListWidgetScope] = {
    "layer",
    "view",
}


def check_feature_list_widget_scope(value: str) -> FeatureListWidgetScope:
    if value in FEATURE_LIST_WIDGET_SCOPE_VALUES:
        return cast(FeatureListWidgetScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {FEATURE_LIST_WIDGET_SCOPE_VALUES!r}"
    )
