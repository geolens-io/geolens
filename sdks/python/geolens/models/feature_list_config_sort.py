from typing import Literal, cast

FeatureListConfigSort = Literal["asc", "desc"]

FEATURE_LIST_CONFIG_SORT_VALUES: set[FeatureListConfigSort] = {
    "asc",
    "desc",
}


def check_feature_list_config_sort(value: str) -> FeatureListConfigSort:
    if value in FEATURE_LIST_CONFIG_SORT_VALUES:
        return cast(FeatureListConfigSort, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {FEATURE_LIST_CONFIG_SORT_VALUES!r}"
    )
