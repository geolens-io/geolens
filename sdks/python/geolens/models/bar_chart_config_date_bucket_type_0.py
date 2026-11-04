from typing import Literal, cast

BarChartConfigDateBucketType0 = Literal["day", "month", "week", "year"]

BAR_CHART_CONFIG_DATE_BUCKET_TYPE_0_VALUES: set[BarChartConfigDateBucketType0] = {
    "day",
    "month",
    "week",
    "year",
}


def check_bar_chart_config_date_bucket_type_0(
    value: str,
) -> BarChartConfigDateBucketType0:
    if value in BAR_CHART_CONFIG_DATE_BUCKET_TYPE_0_VALUES:
        return cast(BarChartConfigDateBucketType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BAR_CHART_CONFIG_DATE_BUCKET_TYPE_0_VALUES!r}"
    )
