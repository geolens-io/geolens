from typing import Literal, cast

DatasetRowsResponseTotalKind = Literal["at_least", "estimate", "exact"]

DATASET_ROWS_RESPONSE_TOTAL_KIND_VALUES: set[DatasetRowsResponseTotalKind] = {
    "at_least",
    "estimate",
    "exact",
}


def check_dataset_rows_response_total_kind(value: str) -> DatasetRowsResponseTotalKind:
    if value in DATASET_ROWS_RESPONSE_TOTAL_KIND_VALUES:
        return cast(DatasetRowsResponseTotalKind, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DATASET_ROWS_RESPONSE_TOTAL_KIND_VALUES!r}"
    )
