from typing import Literal, cast

BasemapReliefContrast = Literal["soft", "standard", "strong"]

BASEMAP_RELIEF_CONTRAST_VALUES: set[BasemapReliefContrast] = {
    "soft",
    "standard",
    "strong",
}


def check_basemap_relief_contrast(value: str) -> BasemapReliefContrast:
    if value in BASEMAP_RELIEF_CONTRAST_VALUES:
        return cast(BasemapReliefContrast, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BASEMAP_RELIEF_CONTRAST_VALUES!r}"
    )
