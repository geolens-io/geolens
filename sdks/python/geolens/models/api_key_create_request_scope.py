from typing import Literal, cast

ApiKeyCreateRequestScope = Literal["full", "read_only"]

API_KEY_CREATE_REQUEST_SCOPE_VALUES: set[ApiKeyCreateRequestScope] = {
    "full",
    "read_only",
}


def check_api_key_create_request_scope(value: str) -> ApiKeyCreateRequestScope:
    if value in API_KEY_CREATE_REQUEST_SCOPE_VALUES:
        return cast(ApiKeyCreateRequestScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {API_KEY_CREATE_REQUEST_SCOPE_VALUES!r}"
    )
