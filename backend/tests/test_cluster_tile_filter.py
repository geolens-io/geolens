"""The cluster tile route clusters only the points a CQL2 ``filter`` keeps."""

import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

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
            f'  flag BOOLEAN, seen DATE, ts TIMESTAMPTZ, uid UUID, r REAL, "Mixed" TEXT,'
            f"  geom_4326 GEOMETRY(Point, 4326))"
        )
    )
    for name, score, yr in _ROWS:
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} "  # noqa: S608
                f'(name, score, yr, flag, seen, ts, uid, r, "Mixed", geom_4326) VALUES '
                f"(:name, :score, :yr, :flag, make_date(:yr, 1, 1), "
                f"make_timestamptz(:yr, 1, 1, 0, 0, 0, 'UTC'), :uid, :r, :name, "
                f"ST_SetSRID(ST_MakePoint(0.1, 0.1), 4326))"
            ),
            {
                "name": name,
                "score": score,
                "yr": yr,
                "flag": name == "a",
                "r": score,
                "uid": uuid.uuid5(uuid.NAMESPACE_DNS, str(yr)),
            },
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


_TYPED = [
    ({"op": "=", "args": [{"property": "flag"}, True]}, "3"),
    ({"op": ">=", "args": [{"property": "seen"}, {"date": "2004-01-01"}]}, "2"),
    (
        {
            "op": "<",
            "args": [{"property": "ts"}, {"timestamp": "2003-06-01T00:00:00Z"}],
        },
        "3",
    ),
    (
        {
            "op": "=",
            "args": [{"property": "uid"}, str(uuid.uuid5(uuid.NAMESPACE_DNS, "2001"))],
        },
        None,
    ),
    ({"op": ">", "args": [{"property": "r"}, 3.5]}, "2"),
    ({"op": "=", "args": [{"property": "Mixed"}, "a"]}, "3"),
]


@pytest.mark.parametrize(("flt", "expected"), _TYPED)
async def test_filter_on_each_column_type(client, cluster_table, flt, expected):
    assert await _cluster_count(client, cluster_table, flt) == expected


async def test_incomparable_columns_are_a_400_not_a_503(client, cluster_table):
    flt = {"op": "=", "args": [{"property": "name"}, {"property": "yr"}]}
    resp = await client.get(
        f"/tiles/clusters/data.{cluster_table}/0/0/0.pbf",
        params={"filter": json.dumps(flt)},
    )
    assert resp.status_code == 400


@pytest.mark.parametrize(
    "bad", [json.dumps(_cmp("=", "no_such_column", "a")), "not json"]
)
async def test_an_invalid_filter_does_not_reveal_a_private_dataset(
    client, cluster_table, test_db_session, bad
):
    dataset = (
        await test_db_session.execute(
            select(Dataset).where(Dataset.table_name == cluster_table)
        )
    ).scalar_one()
    record = await test_db_session.get(Record, dataset.record_id)
    record.visibility = "private"
    await test_db_session.commit()

    resp = await client.get(
        f"/tiles/clusters/data.{cluster_table}/0/0/0.pbf",
        params={"filter": bad},
    )

    assert resp.status_code in (401, 403, 404)


@pytest.mark.parametrize(
    ("tile_columns", "column", "expected_status"),
    [(["name"], "name", 200), (["name"], "score", 400), ([], "name", 400)],
)
async def test_filter_reads_only_the_columns_the_dataset_exposes(
    client, cluster_table, test_db_session, tile_columns, column, expected_status
):
    dataset = (
        await test_db_session.execute(
            select(Dataset).where(Dataset.table_name == cluster_table)
        )
    ).scalar_one()
    dataset.tile_columns = tile_columns
    await test_db_session.commit()
    value = "a" if column == "name" else 1.0

    resp = await client.get(
        f"/tiles/clusters/data.{cluster_table}/0/0/0.pbf",
        params={"filter": json.dumps(_cmp("=", column, value))},
    )

    assert resp.status_code == expected_status


class _RecordingCache:
    def __init__(self):
        self.keys = []

    async def get(self, key, *args, **kwargs):
        self.keys.append(key)

    async def set(self, key, *args, **kwargs):
        pass


async def test_the_route_keys_filtered_tiles_apart_from_unfiltered(
    client, cluster_table, monkeypatch
):
    cache = _RecordingCache()
    monkeypatch.setattr("app.processing.tiles.router.get_tile_cache", lambda: cache)
    flt = json.dumps(_cmp("=", "name", "a"))

    await client.get(f"/tiles/clusters/data.{cluster_table}/0/0/0.pbf")
    await client.get(
        f"/tiles/clusters/data.{cluster_table}/0/0/0.pbf", params={"filter": flt}
    )

    plain, filtered = cache.keys
    assert ":f" not in plain.rsplit(":cluster:", 1)[1]
    assert filtered.endswith(f":f{validated_digest(flt)}")


@pytest.mark.parametrize(
    ("flt", "expected"),
    [
        (_cmp(">=", "seen", "2004-01-01"), "2"),
        (_cmp("<", "ts", "2003-06-01"), "3"),
        (_cmp("<", "ts", "2003-06-01T00:00:00Z"), "3"),
        (
            {"op": "in", "args": [{"property": "seen"}, ["2001-01-01", "2005-01-01"]]},
            "2",
        ),
        (
            {
                "op": "between",
                "args": [{"property": "seen"}, "2002-01-01", "2004-01-01"],
            },
            "3",
        ),
    ],
)
async def test_plain_string_dates_are_typed_by_the_server(
    client, cluster_table, flt, expected
):
    assert await _cluster_count(client, cluster_table, flt) == expected
