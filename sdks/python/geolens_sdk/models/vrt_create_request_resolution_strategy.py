from typing import Literal, cast

VrtCreateRequestResolutionStrategy = Literal["average", "coarsest", "finest"]

VRT_CREATE_REQUEST_RESOLUTION_STRATEGY_VALUES: set[
    VrtCreateRequestResolutionStrategy
] = {
    "average",
    "coarsest",
    "finest",
}


def check_vrt_create_request_resolution_strategy(
    value: str,
) -> VrtCreateRequestResolutionStrategy:
    if value in VRT_CREATE_REQUEST_RESOLUTION_STRATEGY_VALUES:
        return cast(VrtCreateRequestResolutionStrategy, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {VRT_CREATE_REQUEST_RESOLUTION_STRATEGY_VALUES!r}"
    )
