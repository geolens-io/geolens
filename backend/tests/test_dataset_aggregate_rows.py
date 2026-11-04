"""The aggregate endpoint's feature list, date buckets and several statistics per group."""

import base64
import contextlib
import json
import uuid

import pytest
import sqlalchemy
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.catalog.datasets.domain import aggregate, aggregate_schemas
from tests.factories import create_dataset, get_user_id, set_tile_columns
from tests.test_dataset_aggregate import FIRST_THREE, KEEP, _aggregate, _dropped
from tests.test_ogc_features_filter import _freeze_rate_limit_window

pytestmark = pytest.mark.anyio

FIRST_SEVEN = [0.0005, -1, 0.0075, 1]
AT_LEAST_20 = {"op": ">=", "args": [{"property": "pop"}, 20]}
PICK_KEEP = {"op": "=", "args": [{"property": "kind"}, "keep"]}


@pytest.fixture
async def points(client, test_db_session):
    async with _dropped(test_db_session) as dataset:
        yield dataset


@pytest.fixture
async def private_points(client, test_db_session):
    async with _dropped(test_db_session, visibility="private") as dataset:
        yield dataset


@contextlib.asynccontextmanager
async def _dated(session: AsyncSession):
    """A table without geometry: five rows around a month, week and year boundary.

    ``at`` (timestamptz), ``ts`` (timestamp) and ``d`` (date) hold the same UTC
    moments; ``v`` is 1, 2, 4, 8 and 16, and row 5 has no date. ``shape`` is
    a geometry column the dataset does not map; ``Label`` has a mixed-case name.
    """
    admin_id = await get_user_id(session, "admin")
    table = f"aggd_{uuid.uuid4().hex[:10]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table} (gid SERIAL PRIMARY KEY, at TIMESTAMPTZ,"
            " ts TIMESTAMP, d DATE, v INTEGER, kind TEXT, meta JSONB,"
            ' shape geometry(Point, 4326), "Label" TEXT)'
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table} TO geolens_reader"))
    await session.execute(
        text(
            f"INSERT INTO data.{table} (at, ts, d, v, kind, meta)"  # noqa: S608
            " SELECT x::timestamptz, (x::timestamptz AT TIME ZONE 'UTC'),"
            " (x::timestamptz AT TIME ZONE 'UTC')::date, v, 'k', '{}'::jsonb"
            " FROM (VALUES ('2026-02-28T23:59:59Z', 1), ('2026-03-01T00:00:00Z', 2),"
            " ('2026-03-02T00:00:00Z', 4), ('2025-12-31T23:59:59Z', 8),"
            " (NULL, 16)) AS r(x, v)"
        )
    )
    await session.commit()
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        geometry_type=None,
        feature_count=5,
        column_info=[{"name": "v", "type": "integer"}],
    )
    yield dataset
    await session.execute(text(f"DROP TABLE data.{table}"))
    await session.commit()


@pytest.fixture
async def dated(client, test_db_session):
    async with _dated(test_db_session) as dataset:
        yield dataset


async def _sql(session: AsyncSession, sql: str) -> list[tuple]:
    rows = (await session.execute(text(sql))).all()
    await session.commit()
    return [tuple(row) for row in rows]


def _rows(body: dict) -> dict:
    return {"op": "rows", **body}


def _cursor(payload) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


class TestRows:
    async def test_a_filtered_view_matches_direct_sql(
        self, client: AsyncClient, test_db_session, points
    ):
        resp = await _aggregate(
            client,
            points.id,
            _rows(
                {
                    "columns": ["kind", "pop"],
                    "sort_column": "pop",
                    "sort": "desc",
                    "filter": KEEP,
                    "bbox": FIRST_THREE,
                }
            ),
        )
        expected = await _sql(
            test_db_session,
            f"SELECT gid, kind, pop, ST_X(geom_4326) FROM data.{points.table_name}"
            " WHERE kind = 'keep' AND ST_Intersects(geom_4326,"
            " ST_MakeEnvelope(0.0005, -1, 0.0035, 1, 4326)) ORDER BY pop DESC, gid",
        )

        assert resp.status_code == 200, resp.text
        result = resp.json()["result"]
        assert len(expected) == 3
        assert result["rows"] == [
            {
                "gid": gid,
                "values": {"kind": kind, "pop": pop},
                "bbox": [round(x, 6), 0.0, round(x, 6), 0.0],
            }
            for gid, kind, pop, x in expected
        ]
        assert result["has_more"] is False
        assert result["next_cursor"] is None

    async def test_values_keep_their_precision(self, client: AsyncClient, points):
        resp = await _aggregate(
            client,
            points.id,
            _rows({"columns": ["score", "big", "big"], "limit": 2}),
        )

        assert resp.status_code == 200, resp.text
        assert [row["values"] for row in resp.json()["result"]["rows"]] == [
            {"score": "NaN", "big": "9007199254740992"},
            {"score": None, "big": "9007199254740993"},
        ]

    @pytest.mark.parametrize(
        ("sort_column", "sort"),
        [
            (None, "asc"),
            (None, "desc"),
            ("kind", "asc"),
            ("kind", "desc"),
            ("score", "asc"),
            ("score", "desc"),
        ],
    )
    async def test_paging_lists_every_row_once_in_order(
        self, client: AsyncClient, test_db_session, points, sort_column, sort
    ):
        """Ties on the sort value, a NaN and a null each page cleanly."""
        order = (
            f"gid {sort}"
            if sort_column is None
            else f"{sort_column} {sort} NULLS LAST, gid"
        )
        expected = [
            gid
            for (gid,) in await _sql(
                test_db_session,
                f"SELECT gid FROM data.{points.table_name} ORDER BY {order}",  # noqa: S608
            )
        ]
        body = _rows(
            {"columns": ["kind"], "sort_column": sort_column, "sort": sort, "limit": 3}
        )

        listed: list[int] = []
        pages = 0
        cursor = None
        while True:
            resp = await _aggregate(client, points.id, body | {"cursor": cursor})
            assert resp.status_code == 200, resp.text
            result = resp.json()["result"]
            listed += [row["gid"] for row in result["rows"]]
            pages += 1
            if not result["has_more"]:
                assert result["next_cursor"] is None
                break
            cursor = result["next_cursor"]

        assert listed == expected
        assert pages == 3

    async def test_a_page_holds_at_most_its_limit(self, client: AsyncClient, points):
        two = await _aggregate(
            client, points.id, _rows({"columns": ["kind"], "limit": 2})
        )
        most = await _aggregate(
            client, points.id, _rows({"columns": ["kind"], "limit": 100})
        )
        over = await _aggregate(
            client, points.id, _rows({"columns": ["kind"], "limit": 101})
        )
        wide = await _aggregate(
            client, points.id, _rows({"columns": [f"c{i}" for i in range(21)]})
        )

        assert [row["gid"] for row in two.json()["result"]["rows"]] == [1, 2]
        assert two.json()["result"]["has_more"] is True
        assert len(most.json()["result"]["rows"]) == 8
        assert most.json()["result"]["has_more"] is False
        assert over.status_code == 422
        assert wide.status_code == 422

    @pytest.mark.parametrize(
        "cursor",
        [
            "not a cursor",
            _cursor([1, None, "asc"]),
            _cursor([1, "kind", "desc"]),
            _cursor(["1", None, "desc"]),
            _cursor([True, None, "desc"]),
            _cursor([2**63, None, "desc"]),
            _cursor({"gid": 1}),
        ],
        ids=[
            "text",
            "other_direction",
            "other_column",
            "text_gid",
            "bool_gid",
            "past_int8",
            "object",
        ],
    )
    async def test_a_cursor_this_order_did_not_issue_is_refused(
        self, client: AsyncClient, points, cursor
    ):
        resp = await _aggregate(
            client,
            points.id,
            _rows({"columns": ["kind"], "sort": "desc", "cursor": cursor}),
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "invalid_cursor"

    async def test_an_unknown_unsortable_or_geometry_column_is_refused(
        self, client: AsyncClient, points, dated
    ):
        unknown = await _aggregate(client, points.id, _rows({"columns": ["nope"]}))
        unsortable = await _aggregate(
            client, dated.id, _rows({"columns": ["v"], "sort_column": "meta"})
        )
        shape = await _aggregate(client, dated.id, _rows({"columns": ["v", "shape"]}))
        mixed_case = await _aggregate(
            client, dated.id, _rows({"columns": ["Label"], "sort_column": "Label"})
        )

        assert unknown.json()["detail"] == {
            "code": "invalid_column",
            "message": "Unknown column: 'nope'",
        }
        assert unsortable.json()["detail"] == {
            "code": "invalid_column",
            "message": "Column 'meta' cannot be sorted (jsonb)",
        }
        assert shape.json()["detail"] == {
            "code": "invalid_column",
            "message": "Column 'shape' cannot be listed (user-defined)",
        }
        assert mixed_case.json()["detail"] == {
            "code": "invalid_column",
            "message": "Column 'Label' cannot be sorted (text)",
        }

    async def test_a_layer_without_geometry_lists_rows_without_a_bbox(
        self, client: AsyncClient, dated
    ):
        resp = await _aggregate(
            client, dated.id, _rows({"columns": ["at", "v"], "sort_column": "at"})
        )
        bounded = await _aggregate(
            client, dated.id, _rows({"columns": ["v"], "bbox": FIRST_THREE})
        )

        assert resp.status_code == 200, resp.text
        rows = resp.json()["result"]["rows"]
        assert all(set(row) == {"gid", "values"} for row in rows)
        assert [row["values"]["at"] for row in rows] == [
            "2025-12-31T23:59:59+00:00",
            "2026-02-28T23:59:59+00:00",
            "2026-03-01T00:00:00+00:00",
            "2026-03-02T00:00:00+00:00",
            None,
        ]
        assert bounded.json()["detail"]["code"] == "no_geometry"

    async def test_a_feature_without_a_shape_has_a_null_bbox(
        self, client: AsyncClient, test_db_session, points
    ):
        await test_db_session.execute(
            text(f"UPDATE data.{points.table_name} SET geom_4326 = NULL WHERE gid = 1")
        )
        await test_db_session.commit()

        resp = await _aggregate(client, points.id, _rows({"columns": ["kind"]}))

        assert resp.json()["result"]["rows"][0] == {
            "gid": 1,
            "values": {"kind": "keep"},
            "bbox": None,
        }

    async def test_a_repeat_is_cached(self, client: AsyncClient, points):
        body = _rows({"columns": ["kind"], "limit": 2})

        first = await _aggregate(client, points.id, body)
        again = await _aggregate(client, points.id, body)

        assert first.json()["cached"] is False
        assert again.json()["cached"] is True
        assert again.json()["result"] == first.json()["result"]

    async def test_a_page_that_runs_too_long_is_a_query_timeout(
        self, client: AsyncClient, points, monkeypatch
    ):
        """An exclusive lock on the table holds the page query past its timeout."""
        monkeypatch.setattr(aggregate, "AGGREGATE_TIMEOUT_MS", 200)
        engine = sqlalchemy.create_engine(settings.test_database_url_sync)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        f"LOCK TABLE data.{points.table_name} IN ACCESS EXCLUSIVE MODE"
                    )
                )
                resp = await _aggregate(client, points.id, _rows({"columns": ["kind"]}))
        finally:
            engine.dispose()

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "query_timeout"

    async def test_rows_too_large_to_return_together_are_refused(
        self, client: AsyncClient, points, monkeypatch
    ):
        monkeypatch.setattr(aggregate, "_MAX_KEYED_RESULT_BYTES", 4096)

        resp = await _aggregate(client, points.id, _rows({"columns": ["note"]}))

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"]["code"] == "result_too_large"


class TestRowsUnderEmbed:
    async def test_only_allowlisted_columns_are_listed_or_sorted(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        await set_tile_columns(test_db_session, private_points.id, ["kind"])
        headers = await embed_headers(private_points.id)

        allowed = await _aggregate(
            client, private_points.id, _rows({"columns": ["kind"], "limit": 1}), headers
        )
        listed = await _aggregate(
            client, private_points.id, _rows({"columns": ["kind", "pop"]}), headers
        )
        sorted_by = await _aggregate(
            client,
            private_points.id,
            _rows({"columns": ["kind"], "sort_column": "pop"}),
            headers,
        )

        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["result"]["rows"][0]["values"] == {"kind": "keep"}
        for refused in (listed, sorted_by):
            assert refused.status_code == 422, refused.text
            assert refused.json()["detail"] == {
                "code": "invalid_column",
                "message": "Unknown column: 'pop'",
            }

    async def test_rows_share_the_rate_limit(
        self, client: AsyncClient, points, monkeypatch
    ):
        from app.modules.catalog.datasets.api.router_aggregate import (
            _AGGREGATE_RATE_LIMIT,
        )
        from app.platform.ratelimit import limiter

        _freeze_rate_limit_window(monkeypatch)
        budget = int(_AGGREGATE_RATE_LIMIT.split("/")[0])
        body = _rows({"columns": ["kind"], "limit": 1})
        original = limiter.enabled
        try:
            limiter.enabled = True
            limiter._storage.reset()
            codes = [
                (await _aggregate(client, points.id, body)).status_code
                for _ in range(budget + 1)
            ]
        finally:
            limiter.enabled = original
            limiter._storage.reset()

        assert codes == [200] * budget + [429], codes


def _months(key: str) -> str:
    return f"{key}-01T00:00:00Z"


class TestDateBuckets:
    @pytest.mark.parametrize("column", ["at", "ts", "d"])
    async def test_a_month_boundary_splits_two_buckets(
        self, client: AsyncClient, dated, column
    ):
        resp = await _aggregate(
            client,
            dated.id,
            {
                "op": "group_by",
                "group_column": column,
                "date_bucket": "month",
                "stats": [{"stat": "count"}, {"stat": "sum", "column": "v"}],
            },
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["result"] == {
            "groups": [
                {"key": _months("2025-12"), "value": 1, "values": [1, 8]},
                {"key": _months("2026-02"), "value": 1, "values": [1, 1]},
                {"key": _months("2026-03"), "value": 2, "values": [2, 6]},
                {"key": None, "value": 1, "values": [1, 16]},
            ],
            "truncated": False,
        }

    @pytest.mark.parametrize(
        ("bucket", "expected"),
        [
            (
                "week",
                [
                    ("2025-12-29T00:00:00Z", 8),
                    ("2026-02-23T00:00:00Z", 3),
                    ("2026-03-02T00:00:00Z", 4),
                    (None, 16),
                ],
            ),
            (
                "year",
                [
                    ("2025-01-01T00:00:00Z", 8),
                    ("2026-01-01T00:00:00Z", 7),
                    (None, 16),
                ],
            ),
            (
                "day",
                [
                    ("2025-12-31T00:00:00Z", 8),
                    ("2026-02-28T00:00:00Z", 1),
                    ("2026-03-01T00:00:00Z", 2),
                    ("2026-03-02T00:00:00Z", 4),
                    (None, 16),
                ],
            ),
        ],
    )
    async def test_weeks_start_on_monday_and_years_on_january_first(
        self, client: AsyncClient, dated, bucket, expected
    ):
        resp = await _aggregate(
            client,
            dated.id,
            {
                "op": "group_by",
                "group_column": "at",
                "date_bucket": bucket,
                "stat": "sum",
                "column": "v",
            },
        )

        assert resp.status_code == 200, resp.text
        groups = resp.json()["result"]["groups"]
        assert [(g["key"], g["value"]) for g in groups] == expected

    async def test_buckets_ignore_the_session_time_zone(self, test_db_session, dated):
        request = aggregate_schemas.GroupByRequest(
            op="group_by", group_column="at", stat="count", date_bucket="day"
        )
        sql = aggregate.build_aggregate_sql(
            request,
            f"data.{dated.table_name}",
            [],
            {"at": "timestamp with time zone", "v": "integer"},
        )

        await test_db_session.execute(text("SET LOCAL TIME ZONE 'Pacific/Kiritimati'"))
        keys = [row[0] for row in (await test_db_session.execute(text(sql))).all()]
        await test_db_session.commit()

        assert keys == [
            "2025-12-31T00:00:00Z",
            "2026-02-28T00:00:00Z",
            "2026-03-01T00:00:00Z",
            "2026-03-02T00:00:00Z",
            None,
        ]

    async def test_buckets_past_the_limit_are_cut_and_flagged(
        self, client: AsyncClient, dated
    ):
        body = {
            "op": "group_by",
            "group_column": "d",
            "date_bucket": "month",
            "stat": "count",
        }

        cut = await _aggregate(client, dated.id, body | {"limit": 2})
        whole = await _aggregate(client, dated.id, body | {"limit": 4})

        assert [g["key"] for g in cut.json()["result"]["groups"]] == [
            _months("2025-12"),
            _months("2026-02"),
        ]
        assert cut.json()["result"]["truncated"] is True
        assert whole.json()["result"]["truncated"] is False

    async def test_a_column_that_is_not_a_date_is_refused(
        self, client: AsyncClient, dated
    ):
        resp = await _aggregate(
            client,
            dated.id,
            {
                "op": "group_by",
                "group_column": "kind",
                "date_bucket": "month",
                "stat": "count",
            },
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == {
            "code": "invalid_column",
            "message": "Column 'kind' is not a date (text)",
        }


class TestGroupStats:
    @pytest.mark.parametrize(
        "pick", [None, PICK_KEEP], ids=["layer_filter", "layer_filter_and_pick"]
    )
    async def test_several_statistics_match_direct_sql(
        self, client: AsyncClient, test_db_session, points, pick
    ):
        filter_ = (
            AT_LEAST_20 if pick is None else {"op": "and", "args": [AT_LEAST_20, pick]}
        )
        resp = await _aggregate(
            client,
            points.id,
            {
                "op": "group_by",
                "group_column": "kind",
                "stats": [
                    {"stat": "count"},
                    {"stat": "sum", "column": "pop"},
                    {"stat": "avg", "column": "pop"},
                    {"stat": "min", "column": "big"},
                    {"stat": "count", "column": "score"},
                ],
                "filter": filter_,
                "bbox": FIRST_SEVEN,
            },
        )
        picked = "" if pick is None else " AND kind = 'keep'"
        expected = await _sql(
            test_db_session,
            f"SELECT kind, count(*), sum(pop), avg(pop)::float8, min(big)::int,"  # noqa: S608
            f" count(score) FROM data.{points.table_name} WHERE pop >= 20{picked}"
            " AND ST_Intersects(geom_4326, ST_MakeEnvelope(0.0005, -1, 0.0075, 1, 4326))"
            " GROUP BY kind ORDER BY count(*) DESC, kind",
        )

        assert resp.status_code == 200, resp.text
        assert len(expected) == (1 if pick else 2)
        assert resp.json()["result"]["groups"] == [
            {"key": key, "value": count, "values": [count, total, mean, low, scored]}
            for key, count, total, mean, low, scored in expected
        ]

    async def test_the_single_statistic_form_keeps_its_shape(
        self, client: AsyncClient, points
    ):
        resp = await _aggregate(
            client,
            points.id,
            {
                "op": "group_by",
                "group_column": "kind",
                "stat": "count",
                "column": "pop",
            },
        )

        assert resp.json()["result"] == {
            "groups": [{"key": "keep", "value": 6}, {"key": "drop", "value": 2}],
            "truncated": False,
        }

    @pytest.mark.parametrize(
        ("order", "expected"),
        [
            ({"sort_by": "group", "sort": "asc"}, ["drop", "keep"]),
            ({"sort_by": "group", "sort": "desc"}, ["keep", "drop"]),
            ({"sort_by": 1, "sort": "desc"}, ["drop", "keep"]),
            ({"sort_by": 0, "sort": "asc"}, ["drop", "keep"]),
            ({"sort_by": 1, "sort": "asc", "limit": 1}, ["keep"]),
        ],
    )
    async def test_groups_follow_the_requested_order(
        self, client: AsyncClient, points, order, expected
    ):
        resp = await _aggregate(
            client,
            points.id,
            {
                "op": "group_by",
                "group_column": "kind",
                "stats": [{"stat": "count"}, {"stat": "avg", "column": "pop"}],
                **order,
            },
        )

        assert resp.status_code == 200, resp.text
        assert [g["key"] for g in resp.json()["result"]["groups"]] == expected

    @pytest.mark.parametrize(
        "body",
        [
            {"stat": "count", "sort_by": 1},
            {"stats": [{"stat": "count"}], "sort_by": 1},
            {"stat": "count", "stats": [{"stat": "count"}]},
            {"column": "pop", "stats": [{"stat": "count"}]},
            {"stats": [{"stat": "sum"}]},
            {"stats": [{"stat": "count"}] * 6},
            {},
        ],
        ids=[
            "sort_by_past_stat",
            "sort_by_past_stats",
            "both_forms",
            "column_with_stats",
            "stat_without_column",
            "six_stats",
            "no_stat",
        ],
    )
    async def test_a_malformed_request_is_refused(
        self, client: AsyncClient, points, body
    ):
        resp = await _aggregate(
            client, points.id, {"op": "group_by", "group_column": "kind", **body}
        )

        assert resp.status_code == 422, resp.text

    async def test_a_statistic_column_outside_the_allowlist_is_refused(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        await set_tile_columns(test_db_session, private_points.id, ["kind"])
        headers = await embed_headers(private_points.id)

        resp = await _aggregate(
            client,
            private_points.id,
            {
                "op": "group_by",
                "group_column": "kind",
                "stats": [{"stat": "count"}, {"stat": "count", "column": "pop"}],
            },
            headers,
        )

        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == {
            "code": "invalid_column",
            "message": "Unknown column: 'pop'",
        }

    async def test_each_form_reads_its_own_shape_from_a_warm_cache(
        self, client: AsyncClient, points
    ):
        single = {"op": "group_by", "group_column": "kind", "stat": "count"}
        listed = {
            "op": "group_by",
            "group_column": "kind",
            "stats": [{"stat": "count"}],
        }

        warm = await _aggregate(client, points.id, single)
        as_list = await _aggregate(client, points.id, listed)
        again = await _aggregate(client, points.id, single)

        assert warm.json()["result"]["groups"][0] == {"key": "keep", "value": 6}
        assert as_list.json()["result"]["groups"][0] == {
            "key": "keep",
            "value": 6,
            "values": [6],
        }
        assert again.json()["cached"] is True
        assert again.json()["result"] == warm.json()["result"]

    async def test_a_group_by_cached_before_the_truncated_flag_is_not_read(
        self, client: AsyncClient, points
    ):
        body = {"op": "group_by", "group_column": "kind", "stat": "count"}
        request = aggregate_schemas.GroupByRequest.model_validate(body)
        old_key = aggregate._cache_key(
            "aggregate",
            points,
            request.model_dump(mode="json")
            | {"bbox": None, "covered": False, "format": 3},
        )
        await aggregate.get_cache().set(
            old_key, {"groups": [{"key": "stale", "value": 1}]}, ttl=300
        )

        resp = await _aggregate(client, points.id, body)

        assert resp.json()["cached"] is False
        assert resp.json()["result"]["groups"][0]["key"] == "keep"
