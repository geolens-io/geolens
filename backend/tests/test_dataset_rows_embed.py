"""GET /datasets/{id}/rows/ for embed viewers, single rows, row boxes and the view.

An embed token reads rows only while its map has ``show_attribute_table`` on,
and a request only the token authorizes keeps to the dataset's tile column
allowlist. Requires the Docker test database.
"""

import hashlib
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.api import router_data
from app.modules.embed_tokens.service import revoke_embed_tokens_by_map
from tests.factories import set_tile_columns
from tests.test_dataset_aggregate import FIRST_THREE, _dropped

pytestmark = pytest.mark.anyio

ROW_COLUMNS = {"gid", "kind", "pop", "note"}


@pytest.fixture
async def points(client, test_db_session):
    async with _dropped(test_db_session) as dataset:
        yield dataset


@pytest.fixture
async def private_points(client, test_db_session):
    async with _dropped(test_db_session, visibility="private") as dataset:
        yield dataset


async def _rows(client: AsyncClient, dataset_id, headers=None, **params):
    return await client.get(
        f"/datasets/{dataset_id}/rows/", params=params, headers=headers or {}
    )


def _token_hash(headers: dict) -> str:
    return hashlib.sha256(headers["X-Embed-Token"].encode()).hexdigest()


async def _token_map_id(session: AsyncSession, headers: dict):
    return (
        await session.execute(
            text(
                "SELECT map_id FROM catalog.embed_tokens WHERE token_hash = :hash"
            ).bindparams(hash=_token_hash(headers))
        )
    ).scalar_one()


async def _set_table_setting(session: AsyncSession, headers: dict, value: bool):
    """Set show_attribute_table on the map the embed token belongs to."""
    await session.execute(
        text(
            "UPDATE catalog.maps SET show_attribute_table = :value WHERE id = :id"
        ).bindparams(value=value, id=await _token_map_id(session, headers))
    )
    await session.commit()


@pytest.fixture
async def narrowed_headers(test_db_session, private_points, embed_headers):
    """Embed headers for ``private_points`` with tile_columns ["kind"]."""
    await set_tile_columns(test_db_session, private_points.id, ["kind"])
    return await embed_headers(private_points.id)


def _box(minx, miny, maxx, maxy) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]
        ],
    }


IN_VIEW = json.dumps(
    {"op": "s_intersects", "args": [{"property": "geometry"}, _box(*FIRST_THREE)]}
)


def _gids(resp) -> list[int]:
    return [row["gid"] for row in resp.json()["rows"]]


class TestAccess:
    async def test_anonymous_callers_read_public_rows_only(
        self, client: AsyncClient, points, private_points
    ):
        public = await _rows(client, points.id)
        private = await _rows(client, private_points.id)

        assert public.status_code == 200, public.text
        assert len(public.json()["rows"]) == 8
        assert private.status_code == 404, private.text

    async def test_a_signed_in_reader_reads_private_rows(
        self, client: AsyncClient, admin_auth_header, private_points
    ):
        resp = await _rows(client, private_points.id, admin_auth_header)

        assert resp.status_code == 200, resp.text
        assert len(resp.json()["rows"]) == 8

    async def test_an_embed_token_reads_rows_while_its_map_shows_the_table(
        self, client: AsyncClient, private_points, embed_headers
    ):
        headers = await embed_headers(private_points.id)

        resp = await _rows(client, private_points.id, headers)

        assert resp.status_code == 200, resp.text
        assert _gids(resp) == list(range(1, 9))

    async def test_an_embed_token_is_refused_when_its_map_hides_the_table(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        headers = await embed_headers(private_points.id)
        await _set_table_setting(test_db_session, headers, False)

        resp = await _rows(client, private_points.id, headers)
        anonymous = await _rows(client, private_points.id)

        assert resp.status_code == 404, resp.text
        assert resp.json() == anonymous.json()

    async def test_a_revoked_token_is_refused(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        headers = await embed_headers(private_points.id)
        assert (await _rows(client, private_points.id, headers)).status_code == 200
        await revoke_embed_tokens_by_map(
            test_db_session, await _token_map_id(test_db_session, headers)
        )
        await test_db_session.commit()

        resp = await _rows(client, private_points.id, headers)

        assert resp.status_code == 404, resp.text

    async def test_an_expired_token_gets_the_anonymous_answer(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        headers = await embed_headers(private_points.id)
        await test_db_session.execute(
            text(
                "UPDATE catalog.embed_tokens SET expires_at = now() - interval '1 minute'"
                " WHERE token_hash = :hash"
            ).bindparams(hash=_token_hash(headers))
        )
        await test_db_session.commit()

        resp = await _rows(client, private_points.id, headers)
        anonymous = await _rows(client, private_points.id)

        assert resp.status_code == 404, resp.text
        assert resp.json() == anonymous.json()

    async def test_a_domain_locked_token_is_refused_from_another_origin(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        headers = await embed_headers(private_points.id)
        await test_db_session.execute(
            text(
                "UPDATE catalog.embed_tokens SET allowed_origins ="
                " CAST(:origins AS jsonb) WHERE token_hash = :hash"
            ).bindparams(
                origins='["https://customer.example.com"]', hash=_token_hash(headers)
            )
        )
        await test_db_session.commit()

        allowed = await _rows(
            client,
            private_points.id,
            headers | {"Origin": "https://customer.example.com"},
        )
        elsewhere = await _rows(
            client, private_points.id, headers | {"Origin": "https://elsewhere.example"}
        )

        assert allowed.status_code == 200, allowed.text
        assert elsewhere.status_code == 404, elsewhere.text

    async def test_a_token_for_another_dataset_is_refused(
        self, client: AsyncClient, points, private_points, embed_headers
    ):
        headers = await embed_headers(points.id)

        resp = await _rows(client, private_points.id, headers)

        assert resp.status_code == 404, resp.text

    async def test_a_dead_bearer_beside_a_token_the_map_refuses_gets_401(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        headers = await embed_headers(private_points.id)
        stale = headers | {"Authorization": "Bearer not-a-real-token"}

        served = await _rows(client, private_points.id, stale)
        await _set_table_setting(test_db_session, headers, False)
        refused = await _rows(client, private_points.id, stale)

        assert served.status_code == 200, served.text
        assert refused.status_code == 401, refused.text


class TestEmbedColumns:
    """A request only the embed token authorizes keeps to the allowlist."""

    async def test_rows_and_columns_keep_to_the_allowlist(
        self, client: AsyncClient, private_points, narrowed_headers
    ):
        resp = await _rows(client, private_points.id, narrowed_headers)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert {key for row in body["rows"] for key in row} == {"gid", "kind"}
        assert [col["name"] for col in body["columns"]] == ["kind"]
        assert body["sortable_columns"] == ["gid", "kind"]

    @pytest.mark.parametrize(
        ("hidden", "missing"),
        [
            ({"sort": "pop"}, {"sort": "nope"}),
            ({"filter[pop]": "10"}, {"filter[nope]": "10"}),
        ],
        ids=["sort", "column_filter"],
    )
    async def test_a_hidden_column_is_treated_as_a_missing_one(
        self, client: AsyncClient, private_points, narrowed_headers, hidden, missing
    ):
        on_hidden = await _rows(client, private_points.id, narrowed_headers, **hidden)
        on_missing = await _rows(client, private_points.id, narrowed_headers, **missing)

        assert on_hidden.status_code == on_missing.status_code, on_hidden.text
        assert on_hidden.json() == on_missing.json()

    async def test_a_filter_on_a_hidden_column_is_refused_as_unknown(
        self, client: AsyncClient, private_points, narrowed_headers
    ):
        def on(column):
            return json.dumps({"op": "=", "args": [{"property": column}, 10]})

        hidden = await _rows(
            client, private_points.id, narrowed_headers, filter=on("pop")
        )
        missing = await _rows(
            client, private_points.id, narrowed_headers, filter=on("nope")
        )

        assert hidden.status_code == 400, hidden.text
        assert hidden.json()["detail"] == missing.json()["detail"].replace(
            "'nope'", "'pop'"
        )
        assert "'pop'" in hidden.json()["detail"]

    async def test_a_signed_in_non_reader_with_a_token_is_narrowed(
        self, client: AsyncClient, viewer_auth_header, private_points, narrowed_headers
    ):
        headers = narrowed_headers | viewer_auth_header

        resp = await _rows(client, private_points.id, headers)
        hidden = await _rows(client, private_points.id, headers, sort="pop")
        missing = await _rows(client, private_points.id, headers, sort="nope")

        assert resp.status_code == 200, resp.text
        assert {key for row in resp.json()["rows"] for key in row} == {"gid", "kind"}
        assert hidden.status_code == 400, hidden.text
        assert hidden.json() == missing.json()

    async def test_gid_reads_a_row_within_the_allowlist(
        self, client: AsyncClient, private_points, narrowed_headers
    ):
        resp = await _rows(client, private_points.id, narrowed_headers, gid=4)

        assert resp.status_code == 200, resp.text
        assert resp.json()["rows"] == [{"gid": 4, "kind": "keep"}]

    async def test_a_token_on_a_dataset_the_caller_could_read_anyway_is_not_narrowed(
        self, client: AsyncClient, test_db_session, points, embed_headers
    ):
        await set_tile_columns(test_db_session, points.id, ["kind"])
        headers = await embed_headers(points.id)

        resp = await _rows(client, points.id, headers, sort="pop")

        assert resp.status_code == 200, resp.text
        assert set(resp.json()["rows"][0]) == ROW_COLUMNS

    @pytest.mark.parametrize(
        ("allowlist", "caller"),
        [(["kind"], "signed_in"), (None, "embed")],
        ids=["signed_in_with_allowlist", "embed_without_allowlist"],
    )
    async def test_these_callers_read_every_column(
        self,
        client: AsyncClient,
        admin_auth_header,
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

        resp = await _rows(
            client, private_points.id, headers, sort="pop", **{"filter[pop]": "10"}
        )

        assert resp.status_code == 200, resp.text
        assert set(resp.json()["rows"][0]) == ROW_COLUMNS
        assert _gids(resp) == [1]


class TestSingleRow:
    async def test_gid_returns_that_row(self, client: AsyncClient, points):
        resp = await _rows(client, points.id, gid=3)

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert _gids(resp) == [3]
        assert (body["approximate_total"], body["total_kind"]) == (1, "exact")

    @pytest.mark.parametrize(
        "params",
        [
            {"filter": json.dumps({"op": "=", "args": [{"property": "kind"}, "drop"]})},
            {"filter[kind]": "drop"},
        ],
        ids=["cql2", "column_filter"],
    )
    async def test_gid_ands_with_the_filters(self, client: AsyncClient, points, params):
        kept = await _rows(client, points.id, gid=7, **params)
        excluded = await _rows(client, points.id, gid=3, **params)

        assert _gids(kept) == [7]
        assert excluded.status_code == 200, excluded.text
        assert _gids(excluded) == []
        assert excluded.json()["approximate_total"] == 0

    async def test_an_unknown_gid_returns_no_rows(self, client: AsyncClient, points):
        resp = await _rows(client, points.id, gid=2**62)

        assert resp.status_code == 200, resp.text
        assert _gids(resp) == []


class TestRowBoxes:
    async def test_with_bbox_returns_each_rows_box_in_order(
        self, client: AsyncClient, test_db_session, points
    ):
        await test_db_session.execute(
            text(
                f"UPDATE data.{points.table_name} SET geom = NULL, geom_4326 = NULL"  # noqa: S608
                " WHERE gid = 2"
            )
        )
        await test_db_session.commit()

        resp = await _rows(
            client, points.id, with_bbox="true", sort="pop", order="desc", limit=3
        )

        assert resp.status_code == 200, resp.text
        assert _gids(resp) == [8, 7, 6]
        assert resp.json()["bboxes"] == [
            [0.008, 0.0, 0.008, 0.0],
            [0.007, 0.0, 0.007, 0.0],
            [0.006, 0.0, 0.006, 0.0],
        ]
        null_geometry = await _rows(client, points.id, with_bbox="true", gid=2)
        assert null_geometry.json()["bboxes"] == [None]

    async def test_boxes_are_rounded_to_six_decimals(
        self, client: AsyncClient, test_db_session, points
    ):
        await test_db_session.execute(
            text(
                f"UPDATE data.{points.table_name} SET geom_4326 ="  # noqa: S608
                " ST_SetSRID(ST_MakePoint(1.23456789, -2.3456789), 4326) WHERE gid = 1"
            )
        )
        await test_db_session.commit()

        resp = await _rows(client, points.id, with_bbox="true", gid=1)

        assert resp.json()["bboxes"] == [[1.234568, -2.345679, 1.234568, -2.345679]]

    async def test_without_with_bbox_no_boxes_are_read(
        self, client: AsyncClient, points, monkeypatch
    ):
        async def _unexpected(*_args, **_kwargs):
            raise AssertionError("row boxes read without with_bbox")

        monkeypatch.setattr(router_data, "get_row_bboxes", _unexpected)

        resp = await _rows(client, points.id)

        assert resp.status_code == 200, resp.text
        assert resp.json()["bboxes"] is None

    async def test_an_embed_reader_gets_boxes_too(
        self, client: AsyncClient, test_db_session, private_points, embed_headers
    ):
        await set_tile_columns(test_db_session, private_points.id, [])
        headers = await embed_headers(private_points.id)

        resp = await _rows(client, private_points.id, headers, with_bbox="true", gid=5)

        assert resp.status_code == 200, resp.text
        assert resp.json()["rows"] == [{"gid": 5}]
        assert resp.json()["bboxes"] == [[0.005, 0.0, 0.005, 0.0]]


class TestInView:
    async def test_a_spatial_filter_keeps_rows_in_the_box(
        self, client: AsyncClient, points
    ):
        resp = await _rows(client, points.id, filter=IN_VIEW)

        assert resp.status_code == 200, resp.text
        assert _gids(resp) == [1, 2, 3]

    async def test_a_narrowed_embed_reader_filters_by_the_view_too(
        self, client: AsyncClient, private_points, narrowed_headers
    ):
        resp = await _rows(client, private_points.id, narrowed_headers, filter=IN_VIEW)

        assert resp.status_code == 200, resp.text
        assert _gids(resp) == [1, 2, 3]


class TestMapSetting:
    async def test_a_map_stored_without_the_setting_shows_the_table(
        self, client: AsyncClient, test_db_session
    ):
        map_id = (
            await test_db_session.execute(
                text(
                    "INSERT INTO catalog.maps (id, name) VALUES"
                    " (gen_random_uuid(), 'Stored before the setting') RETURNING id"
                )
            )
        ).scalar_one()
        await test_db_session.commit()

        stored = (
            await test_db_session.execute(
                text(
                    "SELECT show_attribute_table FROM catalog.maps WHERE id = :id"
                ).bindparams(id=map_id)
            )
        ).scalar_one()
        await test_db_session.execute(
            text("DELETE FROM catalog.maps WHERE id = :id").bindparams(id=map_id)
        )
        await test_db_session.commit()

        assert stored is True

    async def test_owners_set_it_and_shared_and_forked_maps_carry_it(
        self, client: AsyncClient, admin_auth_header
    ):
        created = await client.post(
            "/maps/", json={"name": "Reader table"}, headers=admin_auth_header
        )
        assert created.status_code == 201, created.text
        map_id = created.json()["id"]
        assert created.json()["show_attribute_table"] is True

        updated = await client.put(
            f"/maps/{map_id}",
            json={"show_attribute_table": False, "visibility": "public"},
            headers=admin_auth_header,
        )
        share = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        shared = await client.get(f"/maps/shared/{share.json()['token']}")
        fork = await client.post(
            f"/maps/{map_id}/duplicate/", headers=admin_auth_header
        )

        assert updated.status_code == 200, updated.text
        assert updated.json()["show_attribute_table"] is False
        assert shared.status_code == 200, shared.text
        assert shared.json()["show_attribute_table"] is False
        assert fork.status_code == 201, fork.text
        assert fork.json()["show_attribute_table"] is False

    async def test_a_shared_map_with_layers_reports_it(
        self,
        client: AsyncClient,
        admin_auth_header,
        test_db_session,
        points,
        embed_headers,
    ):
        headers = await embed_headers(points.id)
        await _set_table_setting(test_db_session, headers, False)
        map_id = await _token_map_id(test_db_session, headers)

        share = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        shared = await client.get(f"/maps/shared/{share.json()['token']}")

        assert shared.status_code == 200, shared.text
        assert len(shared.json()["layers"]) == 1
        assert shared.json()["show_attribute_table"] is False
