from typing import Literal, cast

RefreshVerificationCountStatus = Literal["matched", "mismatched", "unavailable"]

REFRESH_VERIFICATION_COUNT_STATUS_VALUES: set[RefreshVerificationCountStatus] = {
    "matched",
    "mismatched",
    "unavailable",
}


def check_refresh_verification_count_status(
    value: str,
) -> RefreshVerificationCountStatus:
    if value in REFRESH_VERIFICATION_COUNT_STATUS_VALUES:
        return cast(RefreshVerificationCountStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REFRESH_VERIFICATION_COUNT_STATUS_VALUES!r}"
    )
