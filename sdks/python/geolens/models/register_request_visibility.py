from typing import Literal, cast

RegisterRequestVisibility = Literal["internal", "private", "public", "restricted"]

REGISTER_REQUEST_VISIBILITY_VALUES: set[RegisterRequestVisibility] = {
    "internal",
    "private",
    "public",
    "restricted",
}


def check_register_request_visibility(value: str) -> RegisterRequestVisibility:
    if value in REGISTER_REQUEST_VISIBILITY_VALUES:
        return cast(RegisterRequestVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {REGISTER_REQUEST_VISIBILITY_VALUES!r}"
    )
