from typing import Literal, cast

ServiceAuthRequestMethod = Literal["basic", "bearer", "header"]

SERVICE_AUTH_REQUEST_METHOD_VALUES: set[ServiceAuthRequestMethod] = {
    "basic",
    "bearer",
    "header",
}


def check_service_auth_request_method(value: str) -> ServiceAuthRequestMethod:
    if value in SERVICE_AUTH_REQUEST_METHOD_VALUES:
        return cast(ServiceAuthRequestMethod, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {SERVICE_AUTH_REQUEST_METHOD_VALUES!r}"
    )
