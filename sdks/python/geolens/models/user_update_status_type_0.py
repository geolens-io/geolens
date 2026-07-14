from typing import Literal, cast

UserUpdateStatusType0 = Literal["active", "deactivated", "suspended"]

USER_UPDATE_STATUS_TYPE_0_VALUES: set[UserUpdateStatusType0] = {
    "active",
    "deactivated",
    "suspended",
}


def check_user_update_status_type_0(value: str) -> UserUpdateStatusType0:
    if value in USER_UPDATE_STATUS_TYPE_0_VALUES:
        return cast(UserUpdateStatusType0, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {USER_UPDATE_STATUS_TYPE_0_VALUES!r}"
    )
