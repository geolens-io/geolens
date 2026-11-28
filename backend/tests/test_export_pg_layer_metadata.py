"""ogr2ogr exports disable reading GDAL layer metadata from the database.

GDAL's PostgreSQL driver reads layer metadata from the ogr_system_tables
schema when it exists. Nothing reads this metadata during export, and the
runtime role may not have USAGE on that schema; passing
--config OGR_PG_ENABLE_METADATA NO avoids the lookup and its permission
warning.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.processing.export.ogr import run_ogr2ogr_export


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("format_key", "driver"),
    [
        ("kml", "KML"),
        ("kmz", "LIBKML"),
        ("geojson", "GeoJSON"),
        ("gpkg", "GPKG"),
        ("csv", "CSV"),
        ("shp", "ESRI Shapefile"),
        ("pmtiles", "PMTiles"),
    ],
)
async def test_export_disables_pg_layer_metadata(tmp_path, format_key, driver):
    argv: list[str] = []

    async def _fake_exec(*args, **kwargs):
        argv.extend(args)
        if len(args) > 3:
            Path(args[3]).touch()
        proc = MagicMock()
        proc.returncode = 0
        return proc

    async def _fake_communicate(proc, timeout, tool_name):
        return (b"", b"")

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_exec),
        patch(
            "app.processing.export.ogr._communicate_with_timeout",
            new=_fake_communicate,
        ),
    ):
        await run_ogr2ogr_export(
            "test_table",
            str(tmp_path / f"out.{format_key}"),
            driver,
            schema="data",
            format_key=format_key,
        )

    config = {
        argv[i + 1]: argv[i + 2] for i, arg in enumerate(argv) if arg == "--config"
    }
    assert config.get("OGR_PG_ENABLE_METADATA") == "NO"
