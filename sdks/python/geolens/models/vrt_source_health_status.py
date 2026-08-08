from typing import Literal, cast

VrtSourceHealthStatus = Literal["healthy", "inaccessible", "missing", "stale"]

VRT_SOURCE_HEALTH_STATUS_VALUES: set[VrtSourceHealthStatus] = {
    "healthy",
    "inaccessible",
    "missing",
    "stale",
}


def check_vrt_source_health_status(value: str) -> VrtSourceHealthStatus:
    if value in VRT_SOURCE_HEALTH_STATUS_VALUES:
        return cast(VrtSourceHealthStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {VRT_SOURCE_HEALTH_STATUS_VALUES!r}"
    )
