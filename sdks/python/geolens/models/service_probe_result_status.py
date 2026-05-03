from typing import Literal, cast

ServiceProbeResultStatus = Literal["error", "ok"]

SERVICE_PROBE_RESULT_STATUS_VALUES: set[ServiceProbeResultStatus] = {
    "error",
    "ok",
}


def check_service_probe_result_status(value: str) -> ServiceProbeResultStatus:
    if value in SERVICE_PROBE_RESULT_STATUS_VALUES:
        return cast(ServiceProbeResultStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {SERVICE_PROBE_RESULT_STATUS_VALUES!r}"
    )
