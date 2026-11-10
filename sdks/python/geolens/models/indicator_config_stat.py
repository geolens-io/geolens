from typing import Literal, cast

IndicatorConfigStat = Literal["count", "max", "mean", "min", "sum"]

INDICATOR_CONFIG_STAT_VALUES: set[IndicatorConfigStat] = {
    "count",
    "max",
    "mean",
    "min",
    "sum",
}


def check_indicator_config_stat(value: str) -> IndicatorConfigStat:
    if value in INDICATOR_CONFIG_STAT_VALUES:
        return cast(IndicatorConfigStat, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {INDICATOR_CONFIG_STAT_VALUES!r}"
    )
