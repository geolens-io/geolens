from typing import Literal, cast

GroupByRequestDateBucketType0 = Literal["day", "month", "week", "year"]

GROUP_BY_REQUEST_DATE_BUCKET_TYPE_0_VALUES: set[GroupByRequestDateBucketType0] = {
    "day",
    "month",
    "week",
    "year",
}


def check_group_by_request_date_bucket_type_0(
    value: str,
) -> GroupByRequestDateBucketType0:
    if value in GROUP_BY_REQUEST_DATE_BUCKET_TYPE_0_VALUES:
        return cast(GroupByRequestDateBucketType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {GROUP_BY_REQUEST_DATE_BUCKET_TYPE_0_VALUES!r}"
    )
