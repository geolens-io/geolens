"""The export route refuses a ``where`` with text after its condition, on GET and HEAD."""

import csv
import io
import shutil
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from tests.factories import create_dataset, get_user_id

# Only the tests that convert a file are marked for ogr2ogr; a refusal and the
# database reads happen before any conversion.

# Known columns, so a refusal comes from the single-condition rule.
_KEYWORD_COLUMNS = ("limit", "offset", "order", "by", "group", "having")

_TRAILING = [
    "name = 'a' LIMIT 0",
    "name = 'a' OFFSET 1",
    "name = 'a' ORDER BY name",
    "name = 'a' GROUP BY name",
    "name = 'a' GROUP BY name HAVING name = 'a'",
]

_FORMATS = [
    ({"format": "csv"}),
    ({"format": "csv", "xy": "true"}),
    ({"format": "geojson"}),
    ({"format": "gpkg"}),
    ({"format": "fgb"}),
    ({"format": "parquet"}),
]


# GeoParquet reads PostgreSQL itself; every other format converts with ogr2ogr.
_EXPORTING = [
    params
    if params["format"] == "parquet"
    else pytest.param(
        params,
        marks=[
            pytest.mark.requires_ogr2ogr,
            pytest.mark.skipif(
                shutil.which("ogr2ogr") is None, reason="ogr2ogr not available"
            ),
        ],
    )
    for params in _FORMATS
]


@pytest.fixture
async def keyword_dataset(test_db_session, monkeypatch, tmp_path):
    from app.processing.export import service as export_service

    monkeypatch.setattr(export_service.settings, "upload_staging_dir", str(tmp_path))
    table = f"exp_kw_{uuid.uuid4().hex[:12]}"
    extra = ", ".join(f'"{c}" text' for c in _KEYWORD_COLUMNS)
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table} (gid serial PRIMARY KEY, name text, {extra}, "
            "geom geometry(Point, 4326), geom_4326 geometry(Point, 4326) "
            "GENERATED ALWAYS AS (geom) STORED)"
        )
    )
    await test_db_session.execute(
        text(
            f"INSERT INTO data.{table} (name, geom) VALUES "
            "('a', ST_SetSRID(ST_MakePoint(-74.5, 41.25), 4326)), "
            "('b', ST_SetSRID(ST_MakePoint(10, -20), 4326))"
        )
    )
    await test_db_session.commit()
    admin_id = await get_user_id(test_db_session, "admin")
    columns = [{"name": "gid", "type": "integer"}, {"name": "name", "type": "text"}]
    columns += [{"name": c, "type": "text"} for c in _KEYWORD_COLUMNS]
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Keywords {table}",
        table_name=table,
        geometry_type="Point",
        feature_count=2,
        column_info=columns,
    )
    record_id, dataset_id = ds.record_id, ds.id
    yield ds
    await test_db_session.rollback()
    await test_db_session.execute(
        text("DELETE FROM catalog.datasets WHERE id = :id"), {"id": dataset_id}
    )
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
    )
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await test_db_session.commit()


@pytest.mark.anyio
@pytest.mark.parametrize("params", _FORMATS, ids=lambda p: "-".join(p.values()))
async def test_text_after_the_condition_is_refused(
    client: AsyncClient, admin_auth_header: dict, keyword_dataset, params
):
    url = f"/datasets/{keyword_dataset.id}/export"
    for where in _TRAILING:
        for method in ("GET", "HEAD"):
            resp = await client.request(
                method,
                url,
                params={**params, "where": where},
                headers=admin_auth_header,
            )
            assert resp.status_code == 400, (method, where, resp.status_code)


@pytest.mark.anyio
@pytest.mark.parametrize("params", _EXPORTING, ids=lambda p: "-".join(p.values()))
async def test_a_plain_condition_still_exports(
    client: AsyncClient, admin_auth_header: dict, keyword_dataset, params
):
    resp = await client.get(
        f"/datasets/{keyword_dataset.id}/export",
        params={**params, "where": "name = 'a'"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.content
    if params["format"] == "csv":
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert [r["name"] for r in rows] == ["a"]
    elif params["format"] == "geojson":
        features = resp.json()["features"]
        assert [f["properties"]["name"] for f in features] == ["a"]
        assert features[0]["geometry"]["type"] == "Point"
        assert features[0]["geometry"]["coordinates"] == [-74.5, 41.25]


@pytest.mark.anyio
@pytest.mark.parametrize("params", _EXPORTING, ids=lambda p: "-".join(p.values()))
async def test_the_deepest_filter_head_accepts_also_exports(
    client: AsyncClient, admin_auth_header: dict, keyword_dataset, params
):
    from app.processing.export.where_grammar import MAX_RENDER_DEPTH

    where = "NOT " * (MAX_RENDER_DEPTH - 1) + "name = 'a'"
    for method in ("HEAD", "GET"):
        resp = await client.request(
            method,
            f"/datasets/{keyword_dataset.id}/export",
            params={**params, "where": where},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, (method, resp.text)
    if params["format"] == "csv":
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert [r["name"] for r in rows] == ["b"]


# With standard_conforming_strings off PostgreSQL reads ``\'`` as a quote, so
# this is one comparison with a long literal, which matches no row. As written
# it is two comparisons, which together match every row with a name.
_BACKSLASH_FILTER = r"name = '\' OR name <> '\'"


_LEGACY_ESCAPES = text("SET standard_conforming_strings = off")


@pytest.fixture
async def legacy_string_escapes(test_db_session):
    """Each test sets the mode itself, on the connection it is about to use."""
    yield
    await test_db_session.rollback()
    await test_db_session.execute(text("RESET standard_conforming_strings"))
    await test_db_session.commit()


@pytest.mark.anyio
async def test_the_count_reads_a_backslash_as_the_export_does(
    test_db_session, keyword_dataset, legacy_string_escapes
):
    from app.processing.export import selection

    await test_db_session.execute(_LEGACY_ESCAPES)
    count = await selection._count_selected_features(
        test_db_session,
        table_name=keyword_dataset.table_name,
        where=_BACKSLASH_FILTER,
        column_info=[{"name": "name", "type": "text"}],
        bbox=None,
        has_geometry=True,
        schema="data",
    )
    assert count == 2


@pytest.mark.anyio
async def test_the_geoparquet_count_reads_a_backslash_as_the_export_does(
    test_db_session, keyword_dataset, legacy_string_escapes, monkeypatch
):
    from app.processing.export import parquet

    # Both rows match as written and none as an escape, so only the count as
    # written is over a cap of one.
    monkeypatch.setattr(parquet, "_MAX_EXPORT_FEATURES", 1)
    await test_db_session.execute(_LEGACY_ESCAPES)
    with pytest.raises(parquet.ExportTooLargeError):
        await parquet.plan_parquet_export(
            test_db_session,
            keyword_dataset.table_name,
            schema="data",
            where=_BACKSLASH_FILTER,
        )


@pytest.mark.anyio
async def test_the_geoparquet_plan_holds_the_render_not_the_request(
    test_db_session, keyword_dataset
):
    from app.processing.export.parquet import plan_parquet_export

    plan = await plan_parquet_export(
        test_db_session, keyword_dataset.table_name, schema="data", where="NAME='a'"
    )
    assert plan.where_sql == """(("name" = 'a'))"""


@pytest.mark.anyio
async def test_the_geoparquet_stream_reads_a_backslash_as_the_export_does(
    test_db_session, keyword_dataset, legacy_string_escapes
):
    import pyarrow.parquet as pq

    from app.processing.export.parquet import export_parquet, plan_parquet_export

    table = keyword_dataset.table_name
    plan = await plan_parquet_export(
        test_db_session, table, schema="data", where=_BACKSLASH_FILTER
    )
    # The stream runs in a transaction of its own, which may be on another
    # connection, so the mode is set there and not before the plan.
    await test_db_session.commit()
    await test_db_session.execute(_LEGACY_ESCAPES)
    path, _filename, _media_type = await export_parquet(
        test_db_session, table, "Backslash", schema="data", plan=plan
    )
    assert sorted(pq.read_table(path).column("name").to_pylist()) == ["a", "b"]
