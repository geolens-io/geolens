from typing import Literal, cast

ShareTokenRequestExpiresInDaysType0 = Literal[1, 7, 30, 90]

SHARE_TOKEN_REQUEST_EXPIRES_IN_DAYS_TYPE_0_VALUES: set[
    ShareTokenRequestExpiresInDaysType0
] = {
    1,
    7,
    30,
    90,
}


def check_share_token_request_expires_in_days_type_0(
    value: int,
) -> ShareTokenRequestExpiresInDaysType0:
    if value in SHARE_TOKEN_REQUEST_EXPIRES_IN_DAYS_TYPE_0_VALUES:
        return cast(ShareTokenRequestExpiresInDaysType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {SHARE_TOKEN_REQUEST_EXPIRES_IN_DAYS_TYPE_0_VALUES!r}"
    )
