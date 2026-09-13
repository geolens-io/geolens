from typing import Literal, cast

RefreshVerificationIdentityCheck = Literal["content_digest", "unavailable"]

REFRESH_VERIFICATION_IDENTITY_CHECK_VALUES: set[RefreshVerificationIdentityCheck] = {
    "content_digest",
    "unavailable",
}


def check_refresh_verification_identity_check(
    value: str,
) -> RefreshVerificationIdentityCheck:
    if value in REFRESH_VERIFICATION_IDENTITY_CHECK_VALUES:
        return cast(RefreshVerificationIdentityCheck, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REFRESH_VERIFICATION_IDENTITY_CHECK_VALUES!r}"
    )
