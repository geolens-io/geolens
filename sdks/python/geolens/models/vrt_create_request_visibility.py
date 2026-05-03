from typing import Literal, cast

VrtCreateRequestVisibility = Literal["internal", "private", "public", "restricted"]

VRT_CREATE_REQUEST_VISIBILITY_VALUES: set[VrtCreateRequestVisibility] = {
    "internal",
    "private",
    "public",
    "restricted",
}


def check_vrt_create_request_visibility(value: str) -> VrtCreateRequestVisibility:
    if value in VRT_CREATE_REQUEST_VISIBILITY_VALUES:
        return cast(VrtCreateRequestVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {VRT_CREATE_REQUEST_VISIBILITY_VALUES!r}"
    )
