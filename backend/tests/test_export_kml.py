"""KML and KMZ exports written by LIBKML, read back with OGR."""

import json
import shutil
import subprocess

import pytest
from sqlalchemy import text

from tests.test_export_text_formats import _drop_table, _make_table

pytestmark = [
    pytest.mark.requires_ogr2ogr,
    pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="ogr2ogr not available"),
]

_ROWS = [
    ("alpha", "POINT (-74.5 41.25)"),
    ("beta", "POINT (10 -20)"),
]


def _read_back(path, tmp_path) -> list[dict]:
    out = tmp_path / "readback.geojson"
    subprocess.run(
        ["ogr2ogr", "-f", "GeoJSON", str(out), str(path)],
        check=True,
        capture_output=True,
    )
    return json.loads(out.read_text())["features"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("fmt", "media"),
    [
        ("kml", "application/vnd.google-earth.kml+xml"),
        ("kmz", "application/vnd.google-earth.kmz"),
    ],
)
@pytest.mark.parametrize("srid", [4326, 3857])
async def test_round_trip_keeps_features_and_lands_in_wgs84(
    test_db_session, monkeypatch, tmp_path, fmt, media, srid
):
    from app.processing.export import service as export_service

    monkeypatch.setattr(export_service.settings, "upload_staging_dir", str(tmp_path))
    table = await _make_table(test_db_session, "Point", srid, _ROWS)
    await test_db_session.execute(
        text(f"ALTER TABLE data.{table} ADD COLUMN pop integer")
    )
    await test_db_session.execute(
        text(f"UPDATE data.{table} SET pop = CASE name WHEN 'alpha' THEN 7 ELSE 9 END")
    )
    await test_db_session.commit()
    try:
        path, filename, got_media = await export_service.export_dataset(
            table, "Seeds", fmt, schema="data"
        )
        assert filename == f"Seeds.{fmt}"
        assert got_media == media
        features = _read_back(path, tmp_path)
    finally:
        await _drop_table(test_db_session, table)

    by_name = {f["properties"]["Name"]: f for f in features}
    assert set(by_name) == {"alpha", "beta"}
    assert by_name["alpha"]["properties"]["pop"] == 7
    assert by_name["beta"]["properties"]["pop"] == 9
    assert by_name["alpha"]["geometry"]["coordinates"][:2] == pytest.approx(
        [-74.5, 41.25], abs=1e-6
    )
    assert by_name["beta"]["geometry"]["coordinates"][:2] == pytest.approx(
        [10, -20], abs=1e-6
    )


@pytest.mark.anyio
async def test_target_srs_is_overridden_to_wgs84(
    test_db_session, monkeypatch, tmp_path
):
    from app.processing.export import service as export_service

    monkeypatch.setattr(export_service.settings, "upload_staging_dir", str(tmp_path))
    table = await _make_table(test_db_session, "Point", 3857, _ROWS[:1])
    try:
        path, _name, _media = await export_service.export_dataset(
            table, "Seeds", "kml", schema="data", target_srs="EPSG:3857"
        )
        features = _read_back(path, tmp_path)
    finally:
        await _drop_table(test_db_session, table)
    assert features[0]["geometry"]["coordinates"][:2] == pytest.approx(
        [-74.5, 41.25], abs=1e-6
    )
