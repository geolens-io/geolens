from typing import Literal, cast

AdminApiKeyCreateRequestScope = Literal["full", "read_only"]

ADMIN_API_KEY_CREATE_REQUEST_SCOPE_VALUES: set[AdminApiKeyCreateRequestScope] = {
    "full",
    "read_only",
}


def check_admin_api_key_create_request_scope(
    value: str,
) -> AdminApiKeyCreateRequestScope:
    if value in ADMIN_API_KEY_CREATE_REQUEST_SCOPE_VALUES:
        return cast(AdminApiKeyCreateRequestScope, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {ADMIN_API_KEY_CREATE_REQUEST_SCOPE_VALUES!r}"
    )
