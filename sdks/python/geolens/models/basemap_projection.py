from typing import Literal, cast

BasemapProjection = Literal["globe", "mercator"]

BASEMAP_PROJECTION_VALUES: set[BasemapProjection] = {
    "globe",
    "mercator",
}


def check_basemap_projection(value: str) -> BasemapProjection:
    if value in BASEMAP_PROJECTION_VALUES:
        return cast(BasemapProjection, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {BASEMAP_PROJECTION_VALUES!r}"
    )
