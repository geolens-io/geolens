from typing import Literal, cast

FeatureListWidgetV = Literal[1, 2]

FEATURE_LIST_WIDGET_V_VALUES: set[FeatureListWidgetV] = {
    1,
    2,
}


def check_feature_list_widget_v(value: int) -> FeatureListWidgetV:
    if value in FEATURE_LIST_WIDGET_V_VALUES:
        return cast(FeatureListWidgetV, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {FEATURE_LIST_WIDGET_V_VALUES!r}"
    )
