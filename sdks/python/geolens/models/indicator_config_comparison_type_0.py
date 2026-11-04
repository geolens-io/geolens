from typing import Literal, cast

IndicatorConfigComparisonType0 = Literal["both", "percent", "value"]

INDICATOR_CONFIG_COMPARISON_TYPE_0_VALUES: set[IndicatorConfigComparisonType0] = {
    "both",
    "percent",
    "value",
}


def check_indicator_config_comparison_type_0(
    value: str,
) -> IndicatorConfigComparisonType0:
    if value in INDICATOR_CONFIG_COMPARISON_TYPE_0_VALUES:
        return cast(IndicatorConfigComparisonType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {INDICATOR_CONFIG_COMPARISON_TYPE_0_VALUES!r}"
    )
