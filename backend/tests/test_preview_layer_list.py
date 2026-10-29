"""A preview that names one layer of a multi-layer source still lists them all."""

import shutil

import pytest

from app.processing.ingest import ogr
from tests.test_file_replacement_review import _gpkg

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="needs ogr2ogr"),
]


async def test_a_targeted_preview_describes_its_layer_and_lists_every_layer(
    tmp_path,
):
    path = _gpkg(tmp_path, "two_layers.gpkg", {"name": "n", "lanes": 2})

    info = await ogr.run_ogrinfo_preview(str(path), layer_name="other")

    assert info["layer_name"] == "other"
    assert info["feature_count"] == 3
    assert [c["name"] for c in info["columns"]] == ["other"]
    assert [row["other"] for row in info["sample_rows"]] == ["o0", "o1", "o2"]
    assert sorted(info["all_layers"], key=lambda lyr: lyr["name"]) == [
        {"name": "other", "feature_count": 3, "field_count": 1},
        {"name": "roads", "feature_count": 3, "field_count": 2},
    ]


async def test_a_targeted_preview_of_a_missing_layer_still_fails(tmp_path):
    path = _gpkg(tmp_path, "two_layers.gpkg", {"name": "n"})

    with pytest.raises(ogr.IngestionError):
        await ogr.run_ogrinfo_preview(str(path), layer_name="parcels")
