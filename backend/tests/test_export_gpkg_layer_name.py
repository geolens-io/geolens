"""A GeoPackage export names its table after the source table, without the schema."""

import shutil
import sqlite3
import uuid

import pytest
from sqlalchemy import text


class TestGpkgLayerNameArgv:
    @pytest.fixture
    def captured(self, monkeypatch):
        from app.processing.export import ogr as export_ogr

        commands: list[tuple[str, ...]] = []

        async def _capture(*args, **kwargs):
            commands.append(args)

            class _Proc:
                returncode = 0

            return _Proc()

        async def _communicate(*args, **kwargs):
            return b"", b""

        monkeypatch.setattr(export_ogr.asyncio, "create_subprocess_exec", _capture)
        monkeypatch.setattr(export_ogr, "_communicate_with_timeout", _communicate)
        return commands

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("format_key", "driver", "expects_nln"),
        [
            ("gpkg", "GPKG", True),
            ("geojson", "GeoJSON", False),
            ("shp", "ESRI Shapefile", False),
            ("fgb", "FlatGeobuf", False),
            ("pmtiles", "PMTiles", False),
        ],
    )
    async def test_only_gpkg_sets_the_layer_name(
        self, captured, tmp_path, format_key, driver, expects_nln
    ):
        from app.processing.export.ogr import run_ogr2ogr_export

        await run_ogr2ogr_export(
            "roads",
            str(tmp_path / "out"),
            driver,
            schema="data",
            format_key=format_key,
        )
        cmd = captured[0]
        assert ("-nln" in cmd) is expects_nln
        if expects_nln:
            assert cmd[cmd.index("-nln") + 1] == "roads"

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("table", "layer"),
        [
            ("gpkg_roads", "export_gpkg_roads"),
            ("sqlite_roads", "export_sqlite_roads"),
            ("roads_gpkg", "roads_gpkg"),
        ],
    )
    async def test_reserved_prefixes_are_renamed(
        self, captured, tmp_path, table, layer
    ):
        from app.processing.export.ogr import run_ogr2ogr_export

        await run_ogr2ogr_export(
            table, str(tmp_path / "out"), "GPKG", schema="data", format_key="gpkg"
        )
        cmd = captured[0]
        assert cmd[cmd.index("-nln") + 1] == layer


@pytest.mark.skipif(shutil.which("ogr2ogr") is None, reason="ogr2ogr not available")
@pytest.mark.requires_ogr2ogr
class TestGpkgLayerNameEndToEnd:
    @pytest.mark.anyio
    @pytest.mark.parametrize(
        ("prefix", "expected_prefix"),
        [("exp_gl_", ""), ("gpkg_", "export_"), ("sqlite_", "export_")],
    )
    async def test_exported_table_has_no_schema_prefix(
        self, test_db_session, monkeypatch, tmp_path, prefix, expected_prefix
    ):
        from app.processing.export import service as export_service

        monkeypatch.setattr(
            export_service.settings, "upload_staging_dir", str(tmp_path)
        )
        table = f"{prefix}{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, name varchar, "
                "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table} (name, geom, geom_4326) VALUES "
                "('a', ST_SetSRID(ST_MakePoint(1, 2), 4326), "
                "ST_SetSRID(ST_MakePoint(1, 2), 4326))"
            )
        )
        await test_db_session.commit()
        try:
            path, _name, _media = await export_service.export_dataset(
                table, "Layer Name", "gpkg", schema="data"
            )
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                contents = [
                    r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")
                ]
                names = [r[0] for r in con.execute("SELECT name FROM sqlite_master")]
                rows = con.execute(f'SELECT count(*) FROM "{expected_prefix}{table}"')
                row_count = rows.fetchone()[0]
            finally:
                con.close()
        finally:
            await test_db_session.rollback()
            await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
            await test_db_session.commit()
        assert contents == [f"{expected_prefix}{table}"]
        assert row_count == 1
        assert not [n for n in names if "data." in n]
