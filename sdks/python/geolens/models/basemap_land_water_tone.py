from typing import Literal, cast

BasemapLandWaterTone = Literal["contrast", "default", "monochrome", "muted"]

BASEMAP_LAND_WATER_TONE_VALUES: set[BasemapLandWaterTone] = {
    "contrast",
    "default",
    "monochrome",
    "muted",
}


def check_basemap_land_water_tone(value: str) -> BasemapLandWaterTone:
    if value in BASEMAP_LAND_WATER_TONE_VALUES:
        return cast(BasemapLandWaterTone, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BASEMAP_LAND_WATER_TONE_VALUES!r}"
    )
