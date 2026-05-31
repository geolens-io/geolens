from typing import Literal, cast

BasemapPosition = Literal["bottom", "top"]

BASEMAP_POSITION_VALUES: set[BasemapPosition] = {
    "bottom",
    "top",
}


def check_basemap_position(value: str) -> BasemapPosition:
    if value in BASEMAP_POSITION_VALUES:
        return cast(BasemapPosition, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BASEMAP_POSITION_VALUES!r}"
    )
