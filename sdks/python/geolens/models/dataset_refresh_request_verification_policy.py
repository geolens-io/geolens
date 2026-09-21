from typing import Literal, cast

DatasetRefreshRequestVerificationPolicy = Literal["arcgis_id_set_v1", "standard"]

DATASET_REFRESH_REQUEST_VERIFICATION_POLICY_VALUES: set[
    DatasetRefreshRequestVerificationPolicy
] = {
    "arcgis_id_set_v1",
    "standard",
}


def check_dataset_refresh_request_verification_policy(
    value: str,
) -> DatasetRefreshRequestVerificationPolicy:
    if value in DATASET_REFRESH_REQUEST_VERIFICATION_POLICY_VALUES:
        return cast(DatasetRefreshRequestVerificationPolicy, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {DATASET_REFRESH_REQUEST_VERIFICATION_POLICY_VALUES!r}"
    )
