from typing import Literal, cast

VrtStatusResponseStatus = Literal["failed", "ready", "regenerating"]

VRT_STATUS_RESPONSE_STATUS_VALUES: set[VrtStatusResponseStatus] = {
    "failed",
    "ready",
    "regenerating",
}


def check_vrt_status_response_status(value: str) -> VrtStatusResponseStatus:
    if value in VRT_STATUS_RESPONSE_STATUS_VALUES:
        return cast(VrtStatusResponseStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {VRT_STATUS_RESPONSE_STATUS_VALUES!r}"
    )
