from typing import Literal, cast

LayerInfoKind = Literal["raster", "vector"]

LAYER_INFO_KIND_VALUES: set[LayerInfoKind] = {
    "raster",
    "vector",
}


def check_layer_info_kind(value: str) -> LayerInfoKind:
    if value in LAYER_INFO_KIND_VALUES:
        return cast(LayerInfoKind, value)
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {LAYER_INFO_KIND_VALUES!r}"
    )
