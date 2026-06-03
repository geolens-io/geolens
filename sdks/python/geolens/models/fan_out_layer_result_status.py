from typing import Literal, cast

FanOutLayerResultStatus = Literal["failed", "queued"]

FAN_OUT_LAYER_RESULT_STATUS_VALUES: set[FanOutLayerResultStatus] = {
    "failed",
    "queued",
}


def check_fan_out_layer_result_status(value: str) -> FanOutLayerResultStatus:
    if value in FAN_OUT_LAYER_RESULT_STATUS_VALUES:
        return cast(FanOutLayerResultStatus, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {FAN_OUT_LAYER_RESULT_STATUS_VALUES!r}"
    )
