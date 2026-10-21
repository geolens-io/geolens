"""The cluster tile route clusters only the points a CQL2 ``filter`` keeps."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.tiles.cluster_filter import validated_digest
from app.processing.tiles.router import _cluster_cache_table_key

from tests.factories import get_user_id
from tests.test_tile_mixed_case_columns import _keys_and_strings

pytest_plugins = ["tests.test_tiles"]

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")

# Every point sits at one spot, so at a low zoom they form a single cluster.
_ROWS = [
    ("a", 1.0, 2001),
    ("a", 2.0, 2002),
    ("a", 3.0, 2003),
    ("b", 4.0, 2004),
    ("b", 5.0, 2005),
]


@pytest.fixture
async def cluster_table(test_db_session):
    table_name = f"cluster_filter_{uuid.uuid4().hex[:8]}"
    user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
    await test_db_session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY, name TEXT, score DOUBLE PRECISION, yr INTEGER,"
            f"  geom_4326 GEOMETRY(Point, 4326))"
        )
    )
    for name, score, yr in _ROWS:
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (name, score, yr, geom_4326) VALUES "  # noqa: S608
                f"(:name, :score, :yr, ST_SetSRID(ST_MakePoint(0.1, 0.1), 4326))"
            ),
            {"name": name, "score": score, "yr": yr},
        )
    record = Record(
        title="Cluster filter test",
        visibility="public",
        record_status="published",
        created_by=user_id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    test_db_session.add(
        Dataset(
            record_id=record.id,
            table_name=table_name,
            srid=4326,
            geometry_type="Point",
            feature_count=len(_ROWS),
            source_format="geojson",
            source_filename="test.geojson",
            column_info=[
                {"name": "gid", "type": "integer"},
                {"name": "name", "type": "text"},
                {"name": "score", "type": "double precision"},
                {"name": "yr", "type": "integer"},
                {"name": "geom_4326", "type": "geometry"},
            ],
        )
    )
    await test_db_session.commit()
    yield table_name
    await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await test_db_session.commit()


async def _cluster_count(
    client: AsyncClient, table: str, flt: dict | None
) -> str | None:
    """The cluster's point_count_abbreviated at z0, None when no cluster formed."""
    params = {"filter": json.dumps(flt)} if flt is not None else None
    resp = await client.get(f"/tiles/clusters/data.{table}/0/0/0.pbf", params=params)
    if resp.status_code == 204:
        return None
    assert resp.status_code == 200, resp.text
    keys, strings = _keys_and_strings(resp.content)
    return (
        next((s for s in strings if s.isdigit()), None)
        if "point_count" in keys
        else None
    )


def _cmp(op: str, prop: str, value) -> dict:
    return {"op": op, "args": [{"property": prop}, value]}


async def test_filter_narrows_the_clustered_points(client, cluster_table):
    assert await _cluster_count(client, cluster_table, None) == "5"
    assert await _cluster_count(client, cluster_table, _cmp("=", "name", "a")) == "3"
    assert await _cluster_count(client, cluster_table, _cmp(">=", "score", 4.0)) == "2"
    assert (
        await _cluster_count(
            client,
            cluster_table,
            {"op": "in", "args": [{"property": "yr"}, [2001, 2005]]},
        )
        == "2"
    )


async def test_filter_leaving_one_point_forms_no_cluster(client, cluster_table):
    assert await _cluster_count(client, cluster_table, _cmp("=", "yr", 2004)) is None


async def test_filter_matching_nothing_yields_an_empty_tile(client, cluster_table):
    resp = await client.get(
        f"/tiles/clusters/data.{cluster_table}/0/0/0.pbf",
        params={"filter": json.dumps(_cmp("=", "name", "zzz"))},
    )
    assert resp.status_code == 204


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        json.dumps(_cmp("=", "no_such_column", "a")),
        json.dumps(
            {
                "op": "s_intersects",
                "args": [
                    {"property": "geometry"},
                    {"type": "Point", "coordinates": [0, 0]},
                ],
            }
        ),
        json.dumps({"op": "bogus", "args": []}),
    ],
)
async def test_invalid_filter_is_a_400(client, cluster_table, bad):
    resp = await client.get(
        f"/tiles/clusters/data.{cluster_table}/0/0/0.pbf", params={"filter": bad}
    )
    assert resp.status_code == 400


async def test_values_are_binds_not_sql(client, cluster_table):
    hostile = _cmp("=", "name", "a' OR '1'='1")
    assert await _cluster_count(client, cluster_table, hostile) is None


async def test_the_filter_is_part_of_the_cache_key():
    kwargs = dict(
        dataset_id=uuid.uuid4(),
        publication_version=1,
        tile_cache_version=1,
        cluster_radius=48,
        cluster_max_zoom=14,
    )
    one = validated_digest(json.dumps(_cmp("=", "name", "a")))
    two = validated_digest(json.dumps(_cmp("=", "name", "b")))
    reordered = validated_digest(
        json.dumps({"args": [{"property": "name"}, "a"], "op": "="})
    )
    keys = {
        _cluster_cache_table_key("t", filter_digest=digest, **kwargs)
        for digest in (None, one, two)
    }
    assert len(keys) == 3
    assert one == reordered
