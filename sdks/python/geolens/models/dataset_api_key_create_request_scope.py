from typing import Literal, cast

DatasetApiKeyCreateRequestScope = Literal["dataset_append", "dataset_write"]

DATASET_API_KEY_CREATE_REQUEST_SCOPE_VALUES: set[DatasetApiKeyCreateRequestScope] = {
    "dataset_append",
    "dataset_write",
}


def check_dataset_api_key_create_request_scope(
    value: str,
) -> DatasetApiKeyCreateRequestScope:
    if value in DATASET_API_KEY_CREATE_REQUEST_SCOPE_VALUES:
        return cast(DatasetApiKeyCreateRequestScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DATASET_API_KEY_CREATE_REQUEST_SCOPE_VALUES!r}"
    )
