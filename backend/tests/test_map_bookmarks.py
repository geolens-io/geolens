"""A map's bookmarks: validation, saves, reads by audience, duplicate and import."""

import json

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy import text

from app.modules.catalog.maps.bookmarks import MAX_MAP_BOOKMARKS, MapBookmark
from tests.factories import create_dataset, get_user_id
from tests.test_embed_token_creator_access import _embed
from tests.test_map_dashboard_config import _map_with_layers


def _bm(name="Harbor", extent=(-74.1, 40.6, -73.9, 40.8), **extra) -> dict:
    return {"name": name, "extent": list(extent), **extra}


async def _create(client, headers, **body) -> dict:
    resp = await client.post("/maps/", json={"name": "M", **body}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _stored(session, map_id):
    return await session.scalar(
        text("SELECT bookmarks FROM catalog.maps WHERE id = :m"), {"m": map_id}
    )


class TestMapBookmarkModel:
    def test_name_is_stripped_and_extent_kept_in_order(self):
        bookmark = MapBookmark.model_validate(_bm(name="  Harbor  "))
        assert bookmark.name == "Harbor"
        assert bookmark.extent == [-74.1, 40.6, -73.9, 40.8]
        assert bookmark.bearing is None and bookmark.pitch is None

    def test_west_greater_than_east_crosses_the_antimeridian(self):
        assert MapBookmark.model_validate(_bm(extent=(170, -10, -170, 10)))

    @pytest.mark.parametrize(
        "bad",
        [
            _bm(name="   "),
            _bm(name="x" * 121),
            _bm(extent=(float("nan"), 0, 1, 1)),
            _bm(extent=(0, 0, float("inf"), 1)),
            _bm(extent=(-181, 0, 1, 1)),
            _bm(extent=(0, 0, 181, 1)),
            _bm(extent=(0, -91, 1, 1)),
            _bm(extent=(0, 0, 1, 91)),
            _bm(extent=(0, 10, 1, 5)),
            _bm(extent=(0, 0, 1)),
            _bm(bearing=181),
            _bm(bearing=-181),
            _bm(pitch=-1),
            _bm(pitch=86),
            {**_bm(), "id": "x"},
        ],
    )
    def test_refuses(self, bad):
        with pytest.raises(ValidationError):
            MapBookmark.model_validate(bad)

    def test_accepts_the_bounds(self):
        MapBookmark.model_validate(
            _bm(extent=(-180, -90, 180, 90), bearing=-180, pitch=85)
        )
        MapBookmark.model_validate(_bm(name="x" * 120, bearing=180, pitch=0))


class TestBookmarksApi:
    async def test_create_keeps_order_and_reads_back(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        sent = [_bm("B"), _bm("A", bearing=45.5, pitch=60), _bm("C")]
        created = await _create(client, admin_auth_header, bookmarks=sent)
        assert [b["name"] for b in created["bookmarks"]] == ["B", "A", "C"]
        assert created["bookmarks"][1]["bearing"] == 45.5
        got = (
            await client.get(f"/maps/{created['id']}", headers=admin_auth_header)
        ).json()
        assert got["bookmarks"] == created["bookmarks"]

    async def test_a_map_without_bookmarks_answers_an_empty_list(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        created = await _create(client, admin_auth_header)
        assert created["bookmarks"] == []
        assert await _stored(test_db_session, created["id"]) is None

    async def test_update_omitting_the_field_keeps_them_and_empty_or_null_clears(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        created = await _create(client, admin_auth_header, bookmarks=[_bm("A")])
        map_id = created["id"]

        resp = await client.put(
            f"/maps/{map_id}", json={"name": "Renamed"}, headers=admin_auth_header
        )
        assert [b["name"] for b in resp.json()["bookmarks"]] == ["A"]

        resp = await client.put(
            f"/maps/{map_id}",
            json={"bookmarks": [_bm("Z"), _bm("Y")]},
            headers=admin_auth_header,
        )
        assert [b["name"] for b in resp.json()["bookmarks"]] == ["Z", "Y"]

        for cleared in ([], None):
            resp = await client.put(
                f"/maps/{map_id}",
                json={"bookmarks": [_bm("A")]},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, resp.text
            resp = await client.put(
                f"/maps/{map_id}",
                json={"bookmarks": cleared},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["bookmarks"] == []
            assert await _stored(test_db_session, map_id) is None

    async def test_a_bookmark_change_is_recorded_as_a_settings_update(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        created = await _create(client, admin_auth_header)
        await client.put(
            f"/maps/{created['id']}",
            json={"bookmarks": [_bm()]},
            headers=admin_auth_header,
        )
        history = (
            await client.get(
                f"/maps/{created['id']}/history", headers=admin_auth_header
            )
        ).json()["events"]
        assert any(
            e["action"] == "map.config_update"
            and e["details"]["changed_fields"] == ["bookmarks"]
            for e in history
        )

    @pytest.mark.parametrize(
        "bad",
        [
            [_bm(name=" ")],
            [_bm(name="x" * 121)],
            [_bm(extent=(0, 0, 1, 91))],
            [_bm(extent=(0, 5, 1, 1))],
            [_bm(bearing=200)],
            [_bm(pitch=90)],
            [_bm()] * (MAX_MAP_BOOKMARKS + 1),
        ],
    )
    async def test_refuses_invalid_lists_on_create_and_update(
        self, client: AsyncClient, admin_auth_header: dict, bad
    ):
        resp = await client.post(
            "/maps/", json={"name": "M", "bookmarks": bad}, headers=admin_auth_header
        )
        assert resp.status_code == 422
        created = await _create(client, admin_auth_header)
        resp = await client.put(
            f"/maps/{created['id']}", json={"bookmarks": bad}, headers=admin_auth_header
        )
        assert resp.status_code == 422

    async def test_the_limit_itself_is_accepted(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        created = await _create(
            client, admin_auth_header, bookmarks=[_bm()] * MAX_MAP_BOOKMARKS
        )
        assert len(created["bookmarks"]) == MAX_MAP_BOOKMARKS

    async def test_a_westward_extent_is_stored_as_sent(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        created = await _create(
            client, admin_auth_header, bookmarks=[_bm(extent=(170, -10, -170, 10))]
        )
        assert created["bookmarks"][0]["extent"] == [170, -10, -170, 10]

    async def test_duplicate_copies_the_list(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        created = await _create(
            client, admin_auth_header, bookmarks=[_bm("B"), _bm("A", pitch=10)]
        )
        resp = await client.post(
            f"/maps/{created['id']}/duplicate/", headers=admin_auth_header
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["bookmarks"] == created["bookmarks"]

    async def test_the_shared_map_carries_them(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        map_id, _ = await _map_with_layers(
            client, admin_auth_header, dataset, visibility="public"
        )
        resp = await client.put(
            f"/maps/{map_id}",
            json={"bookmarks": [_bm("B"), _bm("A")]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        share = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        assert share.status_code in (200, 201), share.text
        shared = (await client.get(f"/maps/shared/{share.json()['token']}")).json()
        assert [b["name"] for b in shared["bookmarks"]] == ["B", "A"]

    async def test_a_shared_map_without_bookmarks_answers_an_empty_list(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(test_db_session, created_by=admin_id)
        map_id, _ = await _map_with_layers(
            client, admin_auth_header, dataset, visibility="public"
        )
        share = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
        shared = (await client.get(f"/maps/shared/{share.json()['token']}")).json()
        assert shared["bookmarks"] == []

    async def test_an_embed_token_read_carries_them(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        scoped = await create_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        raw_token, share_token = await _embed(
            client, test_db_session, admin_auth_header, admin_id, scoped.id
        )
        await test_db_session.execute(
            text(
                "UPDATE catalog.maps SET bookmarks = CAST(:b AS jsonb) WHERE id = "
                "(SELECT map_id FROM catalog.map_layers WHERE dataset_id = :d)"
            ),
            {"b": json.dumps([_bm("Harbor")]), "d": scoped.id},
        )
        await test_db_session.commit()
        embedded = await client.get(
            f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
        )
        assert embedded.status_code == 200, embedded.text
        assert [b["name"] for b in embedded.json()["bookmarks"]] == ["Harbor"]

    async def test_a_reader_sees_them_and_a_non_editor_cannot_write_them(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
    ):
        created = await _create(client, admin_auth_header, bookmarks=[_bm("A")])
        map_id = created["id"]
        resp = await client.put(
            f"/maps/{map_id}",
            json={"visibility": "internal"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        read = await client.get(f"/maps/{map_id}", headers=viewer_auth_header)
        assert [b["name"] for b in read.json()["bookmarks"]] == ["A"]

        write = await client.put(
            f"/maps/{map_id}", json={"bookmarks": []}, headers=viewer_auth_header
        )
        assert write.status_code in (403, 404)
        got = (await client.get(f"/maps/{map_id}", headers=admin_auth_header)).json()
        assert [b["name"] for b in got["bookmarks"]] == ["A"]
