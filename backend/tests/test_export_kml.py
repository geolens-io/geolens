"""KML and KMZ exports written by LIBKML, read back with OGR."""

import json
import os
from pathlib import Path
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


# GDAL's default LIBKML column names for the elements GeoLens leaves unmapped.
_CONTROL_COLUMNS = (
    "id timestamp begin end altitudeMode tessellate extrude visibility icon "
    "drawOrder snippet heading tilt roll model scale_x scale_y scale_z "
    "networklink networklink_refreshvisibility networklink_flytoview "
    "networklink_refreshmode networklink_refreshinterval "
    "networklink_viewrefreshmode networklink_viewrefreshtime "
    "networklink_viewboundscale networklink_viewformat networklink_httpquery "
    "camera_longitude camera_latitude camera_altitude camera_altitudemode "
    "photooverlay leftfov rightfov bottomfov topfov near shape "
    "imagepyramid_tilesize imagepyramid_maxwidth imagepyramid_maxheight "
    "imagepyramid_gridorigin"
).split()


def _simple_data(path) -> tuple[dict[str, str], dict[str, str | None], dict[str, str]]:
    """SimpleData values and the placemark's own name/description, from raw XML."""
    import xml.etree.ElementTree as ET
    import zipfile

    raw = path.read_bytes()
    if str(path).endswith(".kmz"):
        with zipfile.ZipFile(path) as archive:
            layer = next(
                n
                for n in archive.namelist()
                if n.startswith("layers/") and n.endswith(".kml")
            )
            raw = archive.read(layer)
    root = ET.fromstring(raw)
    ns = {"k": "http://www.opengis.net/kml/2.2"}
    placemark = root.find(".//k:Placemark", ns)
    data = {el.get("name"): el.text for el in placemark.findall(".//k:SimpleData", ns)}
    own = {
        tag: (
            placemark.find(f"k:{tag}", ns).text
            if placemark.find(f"k:{tag}", ns) is not None
            else None
        )
        for tag in ("name", "description")
    }
    types = {
        el.get("name"): el.get("type") for el in root.findall(".//k:SimpleField", ns)
    }
    return data, own, types


@pytest.mark.anyio
@pytest.mark.parametrize("fmt", ["kml", "kmz"])
async def test_columns_named_like_kml_elements_stay_attributes(
    test_db_session, monkeypatch, tmp_path, fmt
):
    from app.processing.export import service as export_service

    monkeypatch.setattr(export_service.settings, "upload_staging_dir", str(tmp_path))
    table = await _make_table(test_db_session, "Point", 4326, [("pm", "POINT (1 2)")])
    columns = ", ".join(f'ADD COLUMN "{c}" text' for c in _CONTROL_COLUMNS)
    await test_db_session.execute(
        text(
            f"ALTER TABLE data.{table} {columns}, ADD COLUMN description text, "
            "ADD COLUMN ints integer[], ADD COLUMN reals double precision[], "
            "ADD COLUMN words text[]"
        )
    )
    values = {c: f"v-{c}" for c in _CONTROL_COLUMNS}
    values["visibility"] = "7"
    values["altitudeMode"] = "land"
    sets = ", ".join(f'"{c}" = :{i}' for i, c in enumerate(values))
    await test_db_session.execute(
        text(
            f"UPDATE data.{table} SET {sets}, description = 'a note', "
            "ints = '{1,2,3}', reals = '{1.5,2.5}', words = '{x,y}'"
        ),
        {str(i): v for i, v in enumerate(values.values())},
    )
    await test_db_session.commit()
    try:
        path, _name, _media = await export_service.export_dataset(
            table, "Seeds", fmt, schema="data"
        )
        data, own, schema_types = _simple_data(Path(path))
    finally:
        await _drop_table(test_db_session, table)

    assert own == {"name": "pm", "description": "a note"}
    for column, value in values.items():
        assert data[column] == value, column
    # A list under an int or float SimpleField reads back as 0, so each must be
    # declared a string. The value is OGR's list notation: (count:item,item).
    assert schema_types["ints"] == schema_types["reals"] == "string"
    assert schema_types["words"] == "string"
    assert data["ints"] == "(3:1,2,3)"
    assert data["reals"] == "(2:1.5,2.5)"
    assert data["words"] == "(2:x,y)"


@pytest.mark.anyio
@pytest.mark.parametrize("fmt", ["geojson", "shp"])
async def test_export_of_a_very_long_title_still_writes_and_keeps_the_download_name(
    test_db_session, monkeypatch, tmp_path, fmt
):
    from app.processing.export import service as export_service

    monkeypatch.setattr(export_service.settings, "upload_staging_dir", str(tmp_path))
    table = await _make_table(test_db_session, "Point", 4326, _ROWS)
    title = "東京都の公園と緑地の分布データ" * 6
    try:
        path, filename, _media = await export_service.export_dataset(
            table, title, fmt, schema="data"
        )
    finally:
        await _drop_table(test_db_session, table)

    assert len(os.path.basename(path).encode()) <= 255
    assert os.path.getsize(path) > 0
    assert filename.startswith("東京都")
    assert len(export_service.safe_content_disposition(filename)) < 1024


@pytest.mark.anyio
async def test_pmtiles_export_names_the_tileset_after_the_dataset(
    test_db_session, monkeypatch, tmp_path
):
    from app.processing.export import service as export_service

    monkeypatch.setattr(export_service.settings, "upload_staging_dir", str(tmp_path))
    table = await _make_table(test_db_session, "Point", 3857, _ROWS)
    try:
        path, filename, _media = await export_service.export_dataset(
            table, "Seeds", "pmtiles", schema="data"
        )
    finally:
        await _drop_table(test_db_session, table)

    assert filename == "Seeds.pmtiles"
    info = subprocess.run(
        ["ogrinfo", "-so", "-al", path], check=True, capture_output=True, text=True
    ).stdout
    assert "name=Seeds" in info


@pytest.mark.parametrize("fmt", ["geojson", "shp", "parquet", "pmtiles"])
def test_download_header_stays_small_for_a_500_character_cjk_title(fmt):
    from app.processing.export.service import (
        export_descriptor,
        safe_content_disposition,
    )

    filename, _media = export_descriptor("東" * 500, fmt)

    assert len(safe_content_disposition(filename)) < 1024
    assert filename.startswith("東")
    assert filename.endswith((".geojson", ".zip", ".parquet", ".pmtiles"))
