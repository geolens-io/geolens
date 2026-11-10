"""Stored columns record the source field they came from."""

import json
import shutil
import uuid

import pytest
from sqlalchemy import text

from app.processing.ingest.tasks_staging import _stored_to_source_names

requires_ogr = pytest.mark.skipif(
    shutil.which("ogr2ogr") is None, reason="ogr2ogr binary not available"
)


def _geojson(tmp_path, properties: dict, coordinates=(1, 2)):
    path = tmp_path / "source.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": list(coordinates)},
                        "properties": properties,
                    }
                ],
            }
        )
    )
    return str(path)


async def _stage(tmp_path, path: str, *, spatial: bool = True) -> dict[str, str | None]:
    """Stage ``path`` the way the ingest door does; return stored -> source name."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.platform.jobs.models import IngestJob
    from app.processing.ingest.ogr import run_ogrinfo
    from app.processing.ingest.tasks import _ingest_vector_into_staging

    info = await run_ogrinfo(path)
    table = f"test_srcnames_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine(settings.test_database_url, pool_size=2)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            job = IngestJob(
                source_filename="source", status="running", user_metadata={}
            )
            session.add(job)
            await session.flush()
            try:
                staging = await _ingest_vector_into_staging(
                    session,
                    job=job,
                    file_path=path,
                    target_table=table,
                    source_srid=info.get("srid") or 4326,
                    ogr_geometry_type=info.get("geometry_type"),
                    has_geometry=spatial,
                    effective_srid=4326 if spatial else None,
                    ogrinfo_columns=info["columns"],
                )
                return {
                    c["name"]: c["source_name"] for c in staging.metadata["column_info"]
                }
            finally:
                await session.execute(
                    text(f'DROP TABLE IF EXISTS data."{table}" CASCADE')
                )
                await session.commit()
    finally:
        await engine.dispose()


@requires_ogr
@pytest.mark.requires_ogr2ogr
@pytest.mark.asyncio
class TestSourceNames:
    async def test_geojson_reports_each_source_field(self, tmp_path):
        path = _geojson(tmp_path, {"Name": "a", "POP 2020": 5})
        assert await _stage(tmp_path, path) == {
            "name": "Name",
            "pop 2020": "POP 2020",
        }

    async def test_names_that_collide_after_lowercasing_keep_their_own_source(
        self, tmp_path
    ):
        path = _geojson(tmp_path, {"Name": "a", "name": "b"})
        mapping = await _stage(tmp_path, path)
        assert sorted(mapping.values()) == ["Name", "name"]
        assert len(mapping) == 2

    @pytest.mark.parametrize("key", ["gid", "GID", "Gid"])
    async def test_source_field_named_gid_does_not_shift_the_others(
        self, tmp_path, key
    ):
        path = _geojson(tmp_path, {key: 7, "Label": "x"})
        assert await _stage(tmp_path, path) == {"label": "Label"}

    async def test_reserved_names_map_to_their_renamed_column(self, tmp_path):
        path = _geojson(tmp_path, {"geom": 7, "Label": "x"})
        assert await _stage(tmp_path, path) == {
            "src_geom": "geom",
            "label": "Label",
        }

    async def test_names_survive_the_elev_column_a_3d_point_table_gains(self, tmp_path):
        path = _geojson(tmp_path, {"Name": "a"}, coordinates=(1, 2, 3))
        assert await _stage(tmp_path, path) == {"name": "Name", "elev": None}

    async def test_csv_header_names_are_recorded(self, tmp_path):
        path = tmp_path / "rows.csv"
        path.write_text("Site Name,Count\nA,1\nB,2\n")
        assert await _stage(tmp_path, str(path), spatial=False) == {
            "site name": "Site Name",
            "count": "Count",
        }


def test_counts_that_differ_map_nothing():
    stored = [{"name": "a"}, {"name": "b"}]
    source = [{"name": "A"}, {"name": "B"}]
    assert _stored_to_source_names(stored, source[:1]) == {}
    assert _stored_to_source_names(stored, None) == {}
    assert _stored_to_source_names(stored, source) == {"a": "A", "b": "B"}
    assert _stored_to_source_names(stored, [{"name": "gid"}, *source]) == {
        "a": "A",
        "b": "B",
    }


@pytest.mark.anyio
async def test_dataset_response_carries_source_names(
    client, test_db_session, admin_auth_header
):
    from tests.factories import create_dataset, get_user_id

    dataset = await create_dataset(
        test_db_session,
        created_by=await get_user_id(test_db_session, "admin"),
        column_info=[
            {"name": "pop 2020", "type": "integer", "source_name": "POP 2020"},
            {"name": "legacy", "type": "text"},
        ],
    )
    body = (
        await client.get(f"/datasets/{dataset.id}", headers=admin_auth_header)
    ).json()
    by_name = {c["name"]: c.get("source_name") for c in body["column_info"]}
    assert by_name == {"pop 2020": "POP 2020", "legacy": None}


def test_a_multi_layer_source_without_a_chosen_layer_has_no_source_columns():
    from app.processing.ingest.tasks_staging import source_columns_for

    columns = [{"name": "A", "type": "String"}]
    single = {"columns": columns, "all_layers": None}
    multi = {"columns": columns, "all_layers": [{"name": "a"}, {"name": "b"}]}
    assert source_columns_for(single, None) == columns
    assert source_columns_for(multi, "a") == columns
    assert source_columns_for(multi, None) is None


def test_the_layer_left_after_omitting_attachment_tables_is_named_for_the_loader():
    from app.processing.ingest.tasks_staging import layer_to_load

    omitted = {"attachments_omitted": True, "layer_name": "sites"}
    assert layer_to_load(omitted, None) == "sites"
    assert layer_to_load(omitted, "chosen") == "chosen"
    assert (
        layer_to_load({"attachments_omitted": False, "layer_name": "x"}, None) is None
    )
