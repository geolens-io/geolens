from typing import Literal, cast

UserResponseStatus = Literal["active", "deactivated", "pending", "suspended"]

USER_RESPONSE_STATUS_VALUES: set[UserResponseStatus] = {
    "active",
    "deactivated",
    "pending",
    "suspended",
}


def check_user_response_status(value: str) -> UserResponseStatus:
    if value in USER_RESPONSE_STATUS_VALUES:
        return cast(UserResponseStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {USER_RESPONSE_STATUS_VALUES!r}"
    )
