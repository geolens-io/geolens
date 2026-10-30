"""POST /datasets/{id}/aggregate/ computes exact widget aggregates under Rule 1 and cost bounds."""

import asyncio
import contextlib
import sys
import uuid
from pathlib import Path

import httpx
import pytest
import sqlalchemy
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.catalog.datasets.domain import aggregate
from tests.factories import (
    create_dataset,
    create_raster_dataset,
    create_user,
    get_user_id,
    set_tile_columns,
)
from tests.test_api_key_publish_scope import _mint
from tests.test_api_key_scope_875 import _remove_keys_minted_by_the_test  # noqa: F401
from tests.test_embed_token_creator_access import _embed

pytestmark = pytest.mark.anyio

KEEP = {"op": "=", "args": [{"property": "kind"}, "keep"]}
# The eight points sit on the equator at x = 0.001 .. 0.008.
EXTENT = (
    "POLYGON((0.001 -0.0001, 0.008 -0.0001, 0.008 0.0001, 0.001 0.0001, 0.001 -0.0001))"
)
FIRST_THREE = [0.0005, -1, 0.0035, 1]
FIRST_TWO = [0.0005, -1, 0.0025, 1]
WHOLE_WORLD = [-180, -90, 180, 90]


async def _points(session: AsyncSession, **dataset_fields):
    """Points 1-8 with pop = 10 * i; 1-6 are ``keep`` and 7-8 ``drop``.

    ``note`` holds a 3,000-character value per row; ``score`` is NaN on point
    1, null on point 2 and ``i`` elsewhere; ``big`` is 2^53 on point 1,
    2^53 + 1 on point 2 and ``i`` elsewhere.
    """
    admin_id = await get_user_id(session, "admin")
    table = f"agg_{uuid.uuid4().hex[:10]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table} (gid SERIAL PRIMARY KEY, kind TEXT,"
            " pop INTEGER, note TEXT, score DOUBLE PRECISION, big NUMERIC,"
            " geom geometry(Point, 4326),"
            " geom_4326 geometry(Point, 4326))"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table} TO geolens_reader"))
    await session.execute(
        text(
            f"INSERT INTO data.{table}"  # noqa: S608
            " (kind, pop, note, score, big, geom, geom_4326)"
            " SELECT CASE WHEN i <= 6 THEN 'keep' ELSE 'drop' END, i * 10,"
            " repeat('x', 3000) || i,"
            " CASE i WHEN 1 THEN 'NaN'::float8 WHEN 2 THEN NULL ELSE i END,"
            " CASE i WHEN 1 THEN 9007199254740992 WHEN 2 THEN 9007199254740993"
            " ELSE i END,"
            " ST_SetSRID(ST_MakePoint(i * 0.001, 0), 4326),"
            " ST_SetSRID(ST_MakePoint(i * 0.001, 0), 4326)"
            " FROM generate_series(1, 8) AS i"
        )
    )
    await session.commit()
    fields = {"visibility": "public", "feature_count": 8, **dataset_fields}
    return await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        geometry_type="POINT",
        spatial_extent_wkt=EXTENT,
        column_info=[
            {"name": "kind", "type": "text"},
            {"name": "pop", "type": "integer"},
            {"name": "note", "type": "text"},
        ],
        **fields,
    )


async def _aggregate(client: AsyncClient, dataset_id, body: dict, headers=None):
    return await client.post(
        f"/datasets/{dataset_id}/aggregate/", json=body, headers=headers or {}
    )


@contextlib.asynccontextmanager
async def _dropped(session: AsyncSession, **dataset_fields):
    dataset = await _points(session, **dataset_fields)
    yield dataset
    await session.execute(text(f"DROP TABLE data.{dataset.table_name}"))
    await session.commit()


@pytest.fixture
async def points(client, test_db_session):
    async with _dropped(test_db_session) as dataset:
        yield dataset


@pytest.fixture
async def private_points(client, test_db_session):
    async with _dropped(test_db_session, visibility="private") as dataset:
        yield dataset


OPERATIONS = [
    ({"op": "count", "filter": KEEP}, {"count": 6}),
    (
        {"op": "stats", "column": "pop", "stats": ["count", "sum", "max"]},
        {"count": 8, "sum": 360.0, "avg": None, "min": None, "max": 80.0},
    ),
    (
        {"op": "value_counts", "column": "kind", "limit": 1},
        {"values": [{"value": "keep", "count": 6}], "other_count": 2},
    ),
    (
        {"op": "histogram", "column": "pop", "bins": 2},
        {
            "bins": [
                {"lower": 10.0, "upper": 46.0, "count": 4},
                {"lower": 46.0, "upper": 81.0, "count": 4},
            ]
        },
    ),
    (
        {"op": "group_by", "group_column": "kind", "stat": "sum", "column": "pop"},
        {"groups": [{"key": "keep", "value": 210.0}, {"key": "drop", "value": 150.0}]},
    ),
]


class TestOperations:
    @pytest.mark.parametrize(
        ("body", "expected"), OPERATIONS, ids=[body["op"] for body, _ in OPERATIONS]
    )
    async def test_each_operation_is_exact(
        self, client: AsyncClient, points, body, expected
    ):
        resp = await _aggregate(client, points.id, body)

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"] == expected
        assert resp.json()["approximate"] is False

    async def test_nan_is_its_own_category_beside_null(
        self, client: AsyncClient, points
    ):
        resp = await _aggregate(
            client, points.id, {"op": "value_counts", "column": "score", "limit": 50}
        )

        assert resp.status_code == 200, resp.text
        values = [entry["value"] for entry in resp.json()["result"]["values"]]
        assert values.count(None) == 1
        assert values.count("NaN") == 1

    async def test_numeric_keys_and_extremes_keep_their_precision(
        self, client: AsyncClient, points
    ):
        counted = await _aggregate(
            client, points.id, {"op": "value_counts", "column": "big", "limit": 50}
        )
        grouped = await _aggregate(
            client,
            points.id,
            {"op": "group_by", "group_column": "big", "stat": "max", "column": "big"},
        )
        stats = await _aggregate(
            client, points.id, {"op": "stats", "column": "big", "stats": ["max", "min"]}
        )

        values = [v["value"] for v in counted.json()["result"]["values"]]
        assert "9007199254740992" in values and "9007199254740993" in values
        assert 3 in values
        top = grouped.json()["result"]["groups"][0]
        assert top == {"key": "9007199254740993", "value": "9007199254740993"}
        assert stats.json()["result"]["max"] == "9007199254740993"
        assert stats.json()["result"]["min"] == 3

    async def test_a_numeric_key_longer_than_python_prints_is_returned(
        self, client: AsyncClient, test_db_session, points
    ):
        await test_db_session.execute(
            text(
                f"UPDATE data.{points.table_name}"  # noqa: S608
                " SET big = ('1' || repeat('0', 5000))::numeric WHERE gid = 3"
            )
        )
        await test_db_session.commit()

        resp = await _aggregate(
            client, points.id, {"op": "stats", "column": "big", "stats": ["max"]}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["max"] == "1" + "0" * 5000

    async def test_a_histogram_over_the_whole_double_range_stays_finite(
        self, client: AsyncClient, test_db_session, points
    ):
        await test_db_session.execute(
            text(
                f"UPDATE data.{points.table_name}"  # noqa: S608
                " SET score = CASE gid WHEN 3 THEN -1e308 ELSE 1e308 END"
                " WHERE gid IN (3, 4)"
            )
        )
        await test_db_session.commit()

        resp = await _aggregate(
            client, points.id, {"op": "histogram", "column": "score", "bins": 2}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["bins"] == [
            {"lower": -1e308, "upper": 0.0, "count": 1},
            {"lower": 0.0, "upper": 1e308, "count": 5},
        ]

    async def test_an_integer_histogram_has_whole_number_bins_over_a_wide_range(
        self, client: AsyncClient, points
    ):
        resp = await _aggregate(
            client, points.id, {"op": "histogram", "column": "pop", "bins": 3}
        )

        assert resp.status_code == 200, resp.text
        # 10 .. 80 is 71 whole numbers; 24 to a bin keeps every edge whole.
        assert resp.json()["result"]["bins"] == [
            {"lower": 10.0, "upper": 34.0, "count": 3},
            {"lower": 34.0, "upper": 58.0, "count": 2},
            {"lower": 58.0, "upper": 81.0, "count": 3},
        ]

    async def test_an_integer_histogram_has_no_empty_bins_between_whole_numbers(
        self, client: AsyncClient, test_db_session, points
    ):
        await test_db_session.execute(
            text(f"UPDATE data.{points.table_name} SET pop = gid")  # noqa: S608
        )
        await test_db_session.commit()

        resp = await _aggregate(
            client, points.id, {"op": "histogram", "column": "pop", "bins": 20}
        )

        # Eight whole numbers fill eight bins, not twenty.
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["bins"] == [
            {"lower": float(i), "upper": float(i + 1), "count": 1} for i in range(1, 9)
        ]

    def test_histogram_edges_never_decrease_over_adjacent_doubles(self):
        low, high = 0.3, 0.30000000000000004

        result = aggregate._histogram([(low, high, 1, 2), (low, high, 10, 3)], 10)

        edges = [result.bins[0].lower] + [b.upper for b in result.bins]
        assert edges == sorted(edges)
        assert (edges[0], edges[-1]) == (low, high)
        assert sum(b.count for b in result.bins) == 5

    async def test_double_values_keep_every_stored_digit(
        self, client: AsyncClient, test_db_session, points
    ):
        await test_db_session.execute(
            text(
                f"UPDATE data.{points.table_name}"  # noqa: S608
                " SET score = CASE gid WHEN 3 THEN 0.30000000000000004::float8"
                " WHEN 4 THEN 1234567.123456789::float8 ELSE 0.3::float8 END"
                " WHERE gid IN (3, 4, 5)"
            )
        )
        await test_db_session.commit()
        filtered = {
            "op": "and",
            "args": [
                {"op": ">=", "args": [{"property": "pop"}, 30]},
                {"op": "<=", "args": [{"property": "pop"}, 40]},
            ],
        }

        stats = await _aggregate(
            client,
            points.id,
            {
                "op": "stats",
                "column": "score",
                "stats": ["min", "max"],
                "filter": filtered,
            },
        )
        grouped = await _aggregate(
            client,
            points.id,
            {
                "op": "group_by",
                "group_column": "kind",
                "stat": "min",
                "column": "score",
                "filter": {"op": "=", "args": [{"property": "pop"}, 30]},
            },
        )

        near = {
            "op": "or",
            "args": [
                {"op": "=", "args": [{"property": "pop"}, 30]},
                {"op": "=", "args": [{"property": "pop"}, 50]},
            ],
        }
        histogram = await _aggregate(
            client,
            points.id,
            {"op": "histogram", "column": "score", "bins": 2, "filter": near},
        )
        counted = await _aggregate(
            client,
            points.id,
            {"op": "value_counts", "column": "score", "filter": near},
        )
        keyed = await _aggregate(
            client,
            points.id,
            {
                "op": "group_by",
                "group_column": "score",
                "stat": "count",
                "filter": near,
            },
        )

        assert stats.json()["result"]["min"] == 0.30000000000000004
        assert stats.json()["result"]["max"] == 1234567.123456789
        assert grouped.json()["result"]["groups"] == [
            {"key": "keep", "value": 0.30000000000000004}
        ]
        bins = histogram.json()["result"]["bins"]
        assert [b["count"] for b in bins] == [1, 1]
        assert (bins[0]["lower"], bins[-1]["upper"]) == (0.3, 0.30000000000000004)
        values = {v["value"] for v in counted.json()["result"]["values"]}
        assert values == {0.3, 0.30000000000000004}
        keys = {g["key"] for g in keyed.json()["result"]["groups"]}
        assert keys == {0.3, 0.30000000000000004}

    async def test_far_future_timestamps_stay_distinct_keys(
        self, client: AsyncClient, test_db_session, points
    ):
        table = points.table_name
        await test_db_session.execute(
            text(f"ALTER TABLE data.{table} ADD COLUMN seen TIMESTAMPTZ")
        )
        await test_db_session.execute(
            text(
                f"UPDATE data.{table} SET seen = CASE gid"  # noqa: S608
                " WHEN 1 THEN '10000-01-01 00:00:00+00'::timestamptz"
                " WHEN 2 THEN '10001-06-01 00:00:00+00'::timestamptz"
                " ELSE 'infinity'::timestamptz END WHERE gid IN (1, 2, 3)"
            )
        )
        await test_db_session.commit()
        expected = {
            "10000-01-01T00:00:00+00:00": 1,
            "10001-06-01T00:00:00+00:00": 1,
            "infinity": 1,
        }

        counted = await _aggregate(
            client, points.id, {"op": "value_counts", "column": "seen"}
        )
        grouped = await _aggregate(
            client,
            points.id,
            {"op": "group_by", "group_column": "seen", "stat": "count"},
        )

        values = counted.json()["result"]["values"]
        groups = grouped.json()["result"]["groups"]
        assert {v["value"]: v["count"] for v in values if v["value"]} == expected
        assert {g["key"]: g["value"] for g in groups if g["key"]} == expected

    async def test_nested_and_or_groups_filter_the_rows(
        self, client: AsyncClient, points
    ):
        def pop(value: int) -> dict:
            return {"op": "=", "args": [{"property": "pop"}, value]}

        nested = {
            "op": "or",
            "args": [
                {
                    "op": "and",
                    "args": [KEEP, {"op": ">=", "args": [{"property": "pop"}, 50]}],
                },
                {
                    "op": "and",
                    "args": [
                        {"op": "or", "args": [pop(70), pop(80)]},
                        {"op": "not", "args": [KEEP]},
                    ],
                },
            ],
        }

        resp = await _aggregate(client, points.id, {"op": "count", "filter": nested})

        # Points 5 and 6 are kept with pop 50 and 60; 7 and 8 are dropped with pop 70 and 80.
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"] == {"count": 4}

    async def test_a_deeply_nested_filter_is_an_invalid_filter(
        self, client: AsyncClient, points
    ):
        nested: dict = KEEP
        for _ in range(300):
            nested = {"op": "not", "args": [nested]}

        resp = await _aggregate(client, points.id, {"op": "count", "filter": nested})

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "invalid_filter"

    async def test_the_live_columns_are_read_once(
        self, client: AsyncClient, points, monkeypatch
    ):
        port = type(aggregate.get_catalog_port())
        reads = []
        original = port.get_column_info

        async def _counted(self, *args, **kwargs):
            reads.append(args)
            return await original(self, *args, **kwargs)

        monkeypatch.setattr(port, "get_column_info", _counted)

        resp = await _aggregate(
            client,
            points.id,
            {"op": "stats", "column": "pop", "stats": ["sum"], "filter": KEEP},
        )

        assert resp.status_code == 200, resp.text
        assert len(reads) == 1

    @pytest.mark.parametrize(
        ("body", "expected"), OPERATIONS, ids=[body["op"] for body, _ in OPERATIONS]
    )
    async def test_the_python_sdk_reads_each_result_as_its_operations(
        self, client: AsyncClient, points, body, expected
    ):
        sdk = Path(__file__).resolve().parents[2] / "sdks" / "python"
        if not (sdk / "geolens" / "client.py").is_file():
            pytest.skip("the Python SDK source tree is not present")
        if str(sdk) not in sys.path:
            sys.path.insert(0, str(sdk))
        from geolens.api.datasets_analysis import (
            aggregate_endpoint_datasets_dataset_id_aggregate_post as endpoint,
        )
        from geolens.client import Client

        resp = await _aggregate(client, points.id, body)
        parsed = endpoint._parse_response(
            client=Client(base_url="http://sdk.test"),
            response=httpx.Response(200, content=resp.content),
        )

        result_type = "".join(part.title() for part in body["op"].split("_"))
        assert type(parsed.result).__name__ == f"{result_type}Result"
        assert parsed.result.to_dict() == expected

    async def test_a_view_counts_only_the_features_inside_it(
        self, client: AsyncClient, points
    ):
        resp = await _aggregate(client, points.id, {"op": "count", "bbox": FIRST_THREE})

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"] == {"count": 3}

    @pytest.mark.parametrize(
        ("body", "code"),
        [
            ({"op": "stats", "column": "missing", "stats": ["sum"]}, "invalid_column"),
            ({"op": "histogram", "column": "kind"}, "invalid_column"),
            (
                {"op": "count", "filter": {"op": "=", "args": [{"property": "x"}, 1]}},
                "invalid_filter",
            ),
        ],
    )
    async def test_a_bad_request_is_refused_with_a_code(
        self, client: AsyncClient, points, body, code
    ):
        resp = await _aggregate(client, points.id, body)

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == code


class TestViewThreshold:
    @pytest.fixture(autouse=True)
    def planned(self, monkeypatch) -> list[str]:
        """Three rows is "too wide", and the planner overstates every view.

        Records the statement timeout each planning call ran under.
        """
        timeouts: list[str] = []

        async def _overstated(db, *_args, **_kwargs):
            shown = await db.execute(text("SHOW statement_timeout"))
            timeouts.append(shown.scalar_one())
            return 10**9

        monkeypatch.setattr(aggregate, "MAX_VIEW_ROWS", 2)
        monkeypatch.setattr(aggregate, "planner_row_estimate", _overstated)
        return timeouts

    async def test_every_widget_on_a_view_shares_one_verdict(
        self, client: AsyncClient, points, planned
    ):
        view = {"filter": KEEP, "bbox": FIRST_THREE}
        first = await _aggregate(client, points.id, {"op": "count", **view})
        second = await _aggregate(
            client,
            points.id,
            {"op": "stats", "column": "pop", "stats": ["sum"], **view},
        )

        assert first.json()["detail"]["code"] == "too_wide"
        assert second.json()["detail"]["code"] == "too_wide"
        assert planned == ["4s"]

    async def test_planning_waits_for_a_slot(
        self, client: AsyncClient, points, planned, monkeypatch
    ):
        monkeypatch.setattr(aggregate, "_aggregate_slots", asyncio.Semaphore(0))

        resp = await _aggregate(
            client, points.id, {"op": "count", "filter": KEEP, "bbox": FIRST_THREE}
        )

        assert resp.status_code == 429, resp.text
        assert resp.json()["detail"]["code"] == "query_at_capacity"
        assert planned == []

    async def test_a_view_over_the_threshold_is_refused_not_approximated(
        self, client: AsyncClient, points
    ):
        resp = await _aggregate(
            client, points.id, {"op": "count", "filter": KEEP, "bbox": FIRST_THREE}
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "too_wide"

    async def test_an_overstated_estimate_is_checked_before_refusing(
        self, client: AsyncClient, points
    ):
        resp = await _aggregate(
            client, points.id, {"op": "count", "filter": KEEP, "bbox": FIRST_TWO}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"] == {"count": 2}

    async def test_a_view_containing_the_dataset_skips_the_view_limit(
        self, client: AsyncClient, points, planned
    ):
        body = {"op": "stats", "column": "pop", "stats": ["sum"], "bbox": WHOLE_WORLD}
        first = await _aggregate(client, points.id, body)
        again = await _aggregate(client, points.id, body)

        assert first.status_code == 200, first.text
        assert first.json()["result"]["sum"] == 360
        assert again.json()["cached"] is True
        assert planned == []

    async def test_a_covering_view_still_leaves_out_rows_without_geometry(
        self, client: AsyncClient, test_db_session, points
    ):
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{points.table_name}"  # noqa: S608
                " (kind, pop, geom, geom_4326) VALUES"
                " ('keep', 90, NULL, NULL),"
                " ('keep', 100, ST_GeomFromText('POINT EMPTY', 4326),"
                " ST_GeomFromText('POINT EMPTY', 4326))"
            )
        )
        await test_db_session.commit()
        body = {"op": "count", "filter": KEEP}

        layer = await _aggregate(client, points.id, body)
        view = await _aggregate(client, points.id, {**body, "bbox": WHOLE_WORLD})

        assert layer.json()["result"] == {"count": 8}
        assert view.json()["result"] == {"count": 6}


class TestCache:
    async def test_a_repeat_is_cached_until_the_data_changes(
        self, client: AsyncClient, admin_auth_header: dict, points
    ):
        body = {"op": "stats", "column": "pop", "stats": ["count"]}
        first = await _aggregate(client, points.id, body)
        again = await _aggregate(client, points.id, body)
        assert first.json()["cached"] is False
        assert again.json()["cached"] is True

        added = await client.post(
            f"/datasets/{points.id}/features/",
            json={
                "geometry": {"type": "Point", "coordinates": [0.0045, 0]},
                "properties": {"kind": "keep", "pop": 5},
            },
            headers=admin_auth_header,
        )
        assert added.status_code == 201, added.text

        after = await _aggregate(client, points.id, body)
        assert after.json()["cached"] is False
        assert after.json()["result"]["count"] == 9

    async def test_a_result_cached_in_an_older_format_is_not_read(
        self, client: AsyncClient, points
    ):
        body = {"op": "stats", "column": "pop", "stats": ["count"]}
        request = aggregate.StatsRequest.model_validate(body)
        old_key = aggregate._cache_key(
            "aggregate",
            points,
            request.model_dump(mode="json") | {"bbox": None, "covered": False},
        )
        await aggregate.get_cache().set(old_key, {"count": 999}, ttl=300)

        resp = await _aggregate(client, points.id, body)

        assert resp.json()["cached"] is False
        assert resp.json()["result"]["count"] == 8


@pytest.fixture
def stored_ttls(monkeypatch) -> list[int]:
    """The TTL of every aggregate result the endpoint writes to the cache."""
    cache = aggregate.get_cache()
    original = cache.set
    ttls: list[int] = []

    async def _recording(key, value, ttl=300, **kwargs):
        if key.startswith("aggregate:"):
            ttls.append(ttl)
        await original(key, value, ttl=ttl, **kwargs)

    monkeypatch.setattr(cache, "set", _recording)
    return ttls


@contextlib.contextmanager
def _holding(*keys: str):
    """Hold the sandbox's advisory locks for ``keys`` from another session."""
    engine = sqlalchemy.create_engine(settings.test_database_url_sync)
    try:
        with engine.connect() as conn:
            for key in keys:
                conn.execute(
                    text("SELECT pg_advisory_lock(hashtextextended(:k, 0))"),
                    {"k": f"geolens:ai-sql:{key}"},
                )
            yield
            conn.execute(text("SELECT pg_advisory_unlock_all()"))
    finally:
        engine.dispose()


class TestConcurrency:
    async def test_a_caller_may_run_two_aggregates_at_once(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, points
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        body = {"op": "count", "filter": KEEP}

        with _holding(f"aggregate:{admin_id}:0"):
            second = await _aggregate(client, points.id, body, admin_auth_header)
        with _holding(f"aggregate:{admin_id}:0", f"aggregate:{admin_id}:1"):
            third = await _aggregate(
                client, points.id, {**body, "bbox": FIRST_THREE}, admin_auth_header
            )

        assert second.status_code == 200, second.text
        assert third.status_code == 429, third.text
        assert third.json()["detail"]["code"] == "query_busy"

    async def test_planning_that_times_out_is_a_query_timeout(
        self, client: AsyncClient, points, monkeypatch
    ):
        """An exclusive lock on the table makes the planner wait past its timeout."""
        monkeypatch.setattr(aggregate, "AGGREGATE_TIMEOUT_MS", 200)
        engine = sqlalchemy.create_engine(settings.test_database_url_sync)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"LOCK TABLE data.{points.table_name} IN ACCESS EXCLUSIVE MODE"
                    )
                )
                resp = await _aggregate(
                    client, points.id, {"op": "count", "bbox": FIRST_THREE}
                )
        finally:
            engine.dispose()

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "query_timeout"


class TestCachePolicy:
    async def test_only_an_unfiltered_whole_layer_result_is_kept_long(
        self, client: AsyncClient, points, stored_ttls
    ):
        body = {"op": "stats", "column": "pop", "stats": ["sum"]}
        await _aggregate(client, points.id, body)
        await _aggregate(client, points.id, {**body, "filter": KEEP})
        await _aggregate(client, points.id, {**body, "bbox": FIRST_THREE})

        assert stored_ttls == [24 * 3600, 300, 300]

    async def test_a_large_result_is_not_cached(self, client: AsyncClient, points):
        body = {"op": "value_counts", "column": "note", "limit": 8}
        first = await _aggregate(client, points.id, body)
        again = await _aggregate(client, points.id, body)

        assert first.status_code == 200, first.text
        assert again.json()["cached"] is False

    async def test_values_cut_by_the_byte_cap_are_refused_not_returned(
        self, client: AsyncClient, points, monkeypatch, stored_ttls
    ):
        """Each ``note`` is about 3 KB, so a 4 KB cap keeps only the first."""
        monkeypatch.setattr(aggregate, "_MAX_KEYED_RESULT_BYTES", 4000)
        body = {"op": "value_counts", "column": "note", "limit": 8}

        resp = await _aggregate(client, points.id, body)

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "result_too_large"
        assert stored_ttls == []

    async def test_a_registered_table_skips_its_stored_count_and_stays_fresh(
        self, client: AsyncClient, test_db_session, stored_ttls
    ):
        """Direct SQL may have changed the table since its count was stored."""
        async with _dropped(
            test_db_session, source_format=None, feature_count=99
        ) as registered:
            resp = await _aggregate(client, registered.id, {"op": "count"})
            stats = await _aggregate(
                client,
                registered.id,
                {"op": "stats", "column": "pop", "stats": ["max"]},
            )

            assert resp.json()["result"] == {"count": 8}
            assert stats.status_code == 200, stats.text
            assert stored_ttls and max(stored_ttls) <= 60


class TestAccess:
    async def test_anonymous_callers_read_public_datasets(
        self, client: AsyncClient, points
    ):
        resp = await _aggregate(client, points.id, {"op": "count", "filter": KEEP})

        assert resp.status_code == 200, resp.text

    async def test_a_private_dataset_is_404_to_anonymous_callers(
        self, client: AsyncClient, admin_auth_header: dict, private_points
    ):
        anonymous = await _aggregate(client, private_points.id, {"op": "count"})
        admin = await _aggregate(
            client, private_points.id, {"op": "count"}, admin_auth_header
        )

        assert anonymous.status_code == 404, anonymous.text
        assert admin.status_code == 200, admin.text

    async def test_a_dead_credential_is_401_not_anonymous(
        self, client: AsyncClient, points
    ):
        resp = await _aggregate(
            client,
            points.id,
            {"op": "count"},
            {"Authorization": "Bearer not-a-real-token"},
        )

        assert resp.status_code == 401, resp.text

    async def test_an_embed_token_authorizes_a_private_dataset_in_its_scope(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        private_points,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        raw, _share = await _embed(
            client, test_db_session, admin_auth_header, admin_id, private_points.id
        )

        resp = await _aggregate(
            client, private_points.id, {"op": "count"}, {"X-Embed-Token": raw}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"] == {"count": 8}

    async def test_an_embed_token_for_another_dataset_is_refused(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        private_points,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        async with _dropped(test_db_session, visibility="private") as other:
            raw, _share = await _embed(
                client, test_db_session, admin_auth_header, admin_id, other.id
            )

            resp = await _aggregate(
                client, private_points.id, {"op": "count"}, {"X-Embed-Token": raw}
            )

            assert resp.status_code == 404, resp.text

    async def test_a_missing_table_is_unavailable_not_its_stored_count(
        self, client: AsyncClient, test_db_session
    ):
        async with _dropped(test_db_session) as dataset:
            await test_db_session.execute(
                text(
                    f"ALTER TABLE data.{dataset.table_name} RENAME TO {dataset.table_name}_x"
                )
            )
            await test_db_session.commit()

            resp = await _aggregate(client, dataset.id, {"op": "count"})

            await test_db_session.execute(
                text(
                    f"ALTER TABLE data.{dataset.table_name}_x RENAME TO {dataset.table_name}"
                )
            )
            await test_db_session.commit()

        assert resp.status_code == 503, resp.text

    async def test_a_raster_has_nothing_to_aggregate(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        raster = await create_raster_dataset(test_db_session, created_by=admin_id)

        resp = await _aggregate(client, raster.id, {"op": "count"}, admin_auth_header)

        assert resp.status_code == 404, resp.text


def _filtered_on(column: str) -> dict:
    return {"op": "count", "filter": {"op": "=", "args": [{"property": column}, 1]}}


class TestEmbedColumnAllowlist:
    """An embed token reads only the columns in the dataset's tile allowlist."""

    async def test_an_allowlisted_column_is_read(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        await set_tile_columns(test_db_session, private_points.id, ["kind"])
        headers = await embed_headers(private_points.id)

        resp = await _aggregate(
            client,
            private_points.id,
            {"op": "value_counts", "column": "kind", "filter": KEEP},
            headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["values"] == [{"value": "keep", "count": 6}]

    @pytest.mark.parametrize(
        ("body", "hidden"),
        [
            ({"op": "stats", "column": "pop", "stats": ["sum"]}, "column"),
            ({"op": "histogram", "column": "pop"}, "column"),
            ({"op": "value_counts", "column": "note"}, "column"),
            (
                {"op": "group_by", "group_column": "note", "stat": "count"},
                "group_column",
            ),
            (
                {
                    "op": "group_by",
                    "group_column": "kind",
                    "stat": "sum",
                    "column": "pop",
                },
                "column",
            ),
        ],
        ids=["stats", "histogram", "value_counts", "group_column", "stat_column"],
    )
    async def test_a_column_outside_the_allowlist_is_refused_as_unknown(
        self,
        client: AsyncClient,
        test_db_session,
        private_points,
        embed_headers,
        body,
        hidden,
    ):
        await set_tile_columns(test_db_session, private_points.id, ["kind"])
        headers = await embed_headers(private_points.id)
        missing = body | {hidden: "nope"}

        resp = await _aggregate(client, private_points.id, body, headers)
        unknown = await _aggregate(client, private_points.id, missing, headers)

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == {
            "code": "invalid_column",
            "message": f"Unknown column: {body[hidden]!r}",
        }
        assert unknown.json()["detail"]["message"] == "Unknown column: 'nope'"

    async def test_a_filter_on_a_column_outside_the_allowlist_is_refused_as_unknown(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        await set_tile_columns(test_db_session, private_points.id, ["kind"])
        headers = await embed_headers(private_points.id)

        resp = await _aggregate(client, private_points.id, _filtered_on("pop"), headers)
        unknown = await _aggregate(
            client, private_points.id, _filtered_on("nope"), headers
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == {
            "code": "invalid_filter",
            "message": (
                "Unsupported CQL2 filter: unknown or non-filterable property 'pop'"
            ),
        }
        assert unknown.json()["detail"]["message"] == (
            "Unsupported CQL2 filter: unknown or non-filterable property 'nope'"
        )

    async def test_a_signed_in_non_reader_with_a_token_is_narrowed(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session,
        private_points,
        embed_headers,
    ):
        await set_tile_columns(test_db_session, private_points.id, ["kind"])
        headers = await embed_headers(private_points.id) | viewer_auth_header
        body = {"op": "stats", "column": "pop", "stats": ["sum"]}

        resp = await _aggregate(client, private_points.id, body, headers)
        unknown = await _aggregate(
            client, private_points.id, body | {"column": "nope"}, headers
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == {
            "code": "invalid_column",
            "message": "Unknown column: 'pop'",
        }
        assert unknown.json()["detail"]["message"] == "Unknown column: 'nope'"

    async def test_an_answer_cached_for_a_full_reader_is_not_served(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        private_points,
        embed_headers,
    ):
        body = {"op": "stats", "column": "pop", "stats": ["sum"]}
        await set_tile_columns(test_db_session, private_points.id, ["kind"])
        headers = await embed_headers(private_points.id)

        admin = await _aggregate(client, private_points.id, body, admin_auth_header)
        cached = await _aggregate(client, private_points.id, body, admin_auth_header)
        resp = await _aggregate(client, private_points.id, body, headers)

        assert admin.status_code == 200, admin.text
        assert cached.json()["cached"] is True, cached.text
        assert resp.status_code == 422, resp.text

    async def test_an_empty_allowlist_refuses_every_column(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        await set_tile_columns(test_db_session, private_points.id, [])
        headers = await embed_headers(private_points.id)

        column = await _aggregate(
            client, private_points.id, {"op": "value_counts", "column": "kind"}, headers
        )
        count = await _aggregate(client, private_points.id, {"op": "count"}, headers)

        assert column.status_code == 422, column.text
        assert count.status_code == 200, count.text

    async def test_an_embed_caller_who_could_read_anyway_reads_every_column(
        self, client: AsyncClient, test_db_session, points, embed_headers
    ):
        await set_tile_columns(test_db_session, points.id, ["kind"])
        headers = await embed_headers(points.id)

        resp = await _aggregate(
            client,
            points.id,
            {"op": "stats", "column": "pop", "stats": ["sum"], "filter": KEEP},
            headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["sum"] == 210

    async def test_a_cached_too_wide_verdict_is_not_served_for_a_hidden_column(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        private_points,
        embed_headers,
        monkeypatch,
    ):
        async def _overstated(*_args, **_kwargs):
            return 10**9

        monkeypatch.setattr(aggregate, "MAX_VIEW_ROWS", 2)
        monkeypatch.setattr(aggregate, "planner_row_estimate", _overstated)
        await set_tile_columns(test_db_session, private_points.id, ["kind"])
        headers = await embed_headers(private_points.id)
        body = {
            "op": "count",
            "filter": {"op": ">", "args": [{"property": "pop"}, 0]},
            "bbox": FIRST_THREE,
        }

        admin = await _aggregate(client, private_points.id, body, admin_auth_header)
        resp = await _aggregate(client, private_points.id, body, headers)

        assert admin.json()["detail"]["code"] == "too_wide", admin.text
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "invalid_filter"

    @pytest.mark.parametrize(
        ("allowlist", "caller"),
        [(["kind"], "signed_in"), (None, "embed")],
        ids=["signed_in_with_allowlist", "embed_without_allowlist"],
    )
    async def test_these_callers_read_every_column(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        private_points,
        embed_headers,
        allowlist,
        caller,
    ):
        await set_tile_columns(test_db_session, private_points.id, allowlist)
        headers = (
            admin_auth_header
            if caller == "signed_in"
            else await embed_headers(private_points.id)
        )

        resp = await _aggregate(
            client,
            private_points.id,
            {"op": "stats", "column": "pop", "stats": ["sum"], "filter": KEEP},
            headers,
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["sum"] == 210


class TestApiKeys:
    @pytest.mark.parametrize("scope", ["read_only", "publish"])
    async def test_a_scoped_key_reads_what_its_user_may_read(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        points,
        private_points,
        scope,
    ):
        """A private dataset its user cannot read stays 404 through the key."""
        headers, _user_id = await create_user(client, admin_auth_header, "editor")
        key = await _mint(client, headers, scope)
        body = {"op": "count", "filter": KEEP}

        public = await _aggregate(client, points.id, body, key)
        private = await _aggregate(client, private_points.id, body, key)

        assert public.status_code == 200, public.text
        assert public.json()["result"] == {"count": 6}
        assert private.status_code == 404, private.text
