from typing import Literal, cast

BasemapSublayerVisibility = Literal["full", "hidden", "subtle"]

BASEMAP_SUBLAYER_VISIBILITY_VALUES: set[BasemapSublayerVisibility] = {
    "full",
    "hidden",
    "subtle",
}


def check_basemap_sublayer_visibility(value: str) -> BasemapSublayerVisibility:
    if value in BASEMAP_SUBLAYER_VISIBILITY_VALUES:
        return cast(BasemapSublayerVisibility, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BASEMAP_SUBLAYER_VISIBILITY_VALUES!r}"
    )
