from typing import Literal, cast

RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0 = Literal[
    "bugn", "gray", "inferno", "magma", "plasma", "terrain", "viridis", "ylorrd"
]

RASTER_TILE_PROXY_TILES_RASTER_PROXY_DATASET_ID_ZXY_FMT_GET_COLORMAP_NAME_TYPE_0_VALUES: set[
    RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0
] = {
    "bugn",
    "gray",
    "inferno",
    "magma",
    "plasma",
    "terrain",
    "viridis",
    "ylorrd",
}


def check_raster_tile_proxy_tiles_raster_proxy_dataset_id_zxy_fmt_get_colormap_name_type_0(
    value: str,
) -> RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0:
    if (
        value
        in RASTER_TILE_PROXY_TILES_RASTER_PROXY_DATASET_ID_ZXY_FMT_GET_COLORMAP_NAME_TYPE_0_VALUES
    ):
        return cast(
            RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0, value
        )
    raise TypeError(
        f"Unexpected value {value!r}. Expected one of {RASTER_TILE_PROXY_TILES_RASTER_PROXY_DATASET_ID_ZXY_FMT_GET_COLORMAP_NAME_TYPE_0_VALUES!r}"
    )
