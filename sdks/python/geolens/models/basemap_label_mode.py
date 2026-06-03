from typing import Literal, cast

BasemapLabelMode = Literal["full", "hidden", "subtle"]

BASEMAP_LABEL_MODE_VALUES: set[BasemapLabelMode] = {
    "full",
    "hidden",
    "subtle",
}


def check_basemap_label_mode(value: str) -> BasemapLabelMode:
    if value in BASEMAP_LABEL_MODE_VALUES:
        return cast(BasemapLabelMode, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BASEMAP_LABEL_MODE_VALUES!r}"
    )
