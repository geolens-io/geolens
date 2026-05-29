from typing import Literal, cast

RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0 = Literal[
    "minmax", "percentile", "stddev"
]

RASTER_TILE_PROXY_TILES_RASTER_PROXY_DATASET_ID_ZXY_FMT_GET_STRETCH_TYPE_0_VALUES: set[
    RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0
] = {
    "minmax",
    "percentile",
    "stddev",
}


def check_raster_tile_proxy_tiles_raster_proxy_dataset_id_zxy_fmt_get_stretch_type_0(
    value: str,
) -> RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0:
    if (
        value
        in RASTER_TILE_PROXY_TILES_RASTER_PROXY_DATASET_ID_ZXY_FMT_GET_STRETCH_TYPE_0_VALUES
    ):
        return cast(
            RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0, value
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {RASTER_TILE_PROXY_TILES_RASTER_PROXY_DATASET_ID_ZXY_FMT_GET_STRETCH_TYPE_0_VALUES!r}"
    )
