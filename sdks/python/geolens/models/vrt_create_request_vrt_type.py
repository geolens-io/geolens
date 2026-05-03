from typing import Literal, cast

VrtCreateRequestVrtType = Literal["band_stack", "mosaic"]

VRT_CREATE_REQUEST_VRT_TYPE_VALUES: set[VrtCreateRequestVrtType] = {
    "band_stack",
    "mosaic",
}


def check_vrt_create_request_vrt_type(value: str) -> VrtCreateRequestVrtType:
    if value in VRT_CREATE_REQUEST_VRT_TYPE_VALUES:
        return cast(VrtCreateRequestVrtType, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {VRT_CREATE_REQUEST_VRT_TYPE_VALUES!r}"
    )
