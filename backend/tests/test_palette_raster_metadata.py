"""An indexed-colour raster is recognised from the band data stored at import."""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.core.raster_bands import is_palette_raster
from app.processing.raster.cog import extract_raster_metadata


def _write(path, dtype: str, *, palette: bool) -> None:
    data = np.tile(np.array([1, 2, 3], dtype=dtype), (8, 1)).repeat(8, axis=1)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype=dtype,
        crs="EPSG:3857",
        transform=from_origin(0, 8, 1, 1),
    ) as dst:
        dst.write(data, 1)
        if palette:
            dst.write_colormap(1, {1: (255, 0, 0), 2: (0, 255, 0), 3: (0, 0, 255)})


@pytest.mark.parametrize("dtype", ["uint8", "uint16"])
def test_imported_palette_raster_is_recognised(tmp_path, dtype) -> None:
    path = tmp_path / "classes.tif"
    _write(path, dtype, palette=True)
    assert is_palette_raster(extract_raster_metadata(str(path))["band_info"])


def test_imported_plain_raster_is_not_a_palette(tmp_path) -> None:
    path = tmp_path / "plain.tif"
    _write(path, "uint16", palette=False)
    assert not is_palette_raster(extract_raster_metadata(str(path))["band_info"])


@pytest.mark.parametrize("band_info", [None, [], [None], [{"min": 0, "max": 1}]])
def test_missing_colour_interpretation_is_not_a_palette(band_info) -> None:
    assert not is_palette_raster(band_info)
