"""fix(#394) 2026-07-03 builder-audit: shared-map embed-token scope + tile_version.

Covers:
  - B-023/SH-01: GET /maps/shared/{token} honors X-Embed-Token — layers backed
    by the token's scoped private datasets are included (the tile path always
    honored the token; the metadata payload now matches, per the SEC-022
    capability posture).
  - SH-04: POST /tiles/tokens/ accepts X-Embed-Token as fallback authorization
    so embed viewers obtain the same tile/DEM descriptors as viewers.
  - VT-02/B-026: MapLayerResponse + SharedLayerResponse carry ``tile_version``
    (Dataset.current_version) for the client `_v=` cache-buster.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.service import (
    create_embed_token,
    resolve_embed_scope_for_map,
)

from tests.factories import create_dataset, get_user_id


async def _downgrade_to_private(session, dataset: Dataset) -> None:
    """Flip a dataset private AFTER map publish — the exact SH-01 scenario
    (publishing a map with a non-public dataset is rejected up front, so the
    gap only exists for post-publish downgrades)."""
    await session.execute(
        update(Record)
        .where(Record.id == dataset.record_id)
        .values(visibility="private")
    )
    await session.commit()


async def _make_public_shared_map(
    client: AsyncClient,
    headers: dict,
    dataset_ids: list[str],
) -> tuple[str, str, list[str]]:
    """Create a map with layers, publish it, share it. Returns (map_id, share_token, layer_ids)."""
    create_resp = await client.post(
        "/maps/",
        json={"name": f"Embed Scope Map {uuid.uuid4().hex[:6]}"},
        headers=headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    map_id = create_resp.json()["id"]

    layer_ids = []
    for ds_id in dataset_ids:
        layer_resp = await client.post(
            f"/maps/{map_id}/layers", json={"dataset_id": ds_id}, headers=headers
        )
        assert layer_resp.status_code == 201, layer_resp.text
        layer_ids.append(layer_resp.json()["id"])

    put_resp = await client.put(
        f"/maps/{map_id}", json={"visibility": "public"}, headers=headers
    )
    assert put_resp.status_code == 200, put_resp.text

    share_resp = await client.post(f"/maps/{map_id}/share/", headers=headers)
    assert share_resp.status_code in (200, 201), share_resp.text
    return map_id, share_resp.json()["token"], layer_ids


class TestSharedMapEmbedScope:
    async def test_anonymous_excludes_private_layer(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        public_ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        private_ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        _map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(public_ds.id), str(private_ds.id)]
        )
        await _downgrade_to_private(test_db_session, private_ds)

        resp = await client.get(f"/maps/shared/{share_token}")
        assert resp.status_code == 200
        dataset_ids = {layer["dataset_id"] for layer in resp.json()["layers"]}
        assert str(public_ds.id) in dataset_ids
        assert str(private_ds.id) not in dataset_ids

    async def test_valid_embed_token_includes_scoped_private_layer(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        public_ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        private_ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(public_ds.id), str(private_ds.id)]
        )

        _token_obj, raw_token = await create_embed_token(
            test_db_session, uuid.UUID(map_id), admin_id
        )
        await test_db_session.commit()
        await _downgrade_to_private(test_db_session, private_ds)

        resp = await client.get(
            f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
        )
        assert resp.status_code == 200
        data = resp.json()
        dataset_ids = {layer["dataset_id"] for layer in data["layers"]}
        assert str(private_ds.id) in dataset_ids
        assert data["has_non_public_layers"] is True
        # Layers stay sort-ordered after the embed-scope union.
        sort_orders = [layer["sort_order"] for layer in data["layers"]]
        assert sort_orders == sorted(sort_orders)

    async def test_revoked_embed_token_excludes_private_layer(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        private_ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(private_ds.id)]
        )
        _token_obj, raw_token = await create_embed_token(
            test_db_session, uuid.UUID(map_id), admin_id
        )
        await test_db_session.execute(
            update(EmbedToken)
            .where(EmbedToken.map_id == uuid.UUID(map_id))
            .values(is_active=False)
        )
        await test_db_session.commit()
        await _downgrade_to_private(test_db_session, private_ds)

        resp = await client.get(
            f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
        )
        assert resp.status_code == 200
        assert resp.json()["layers"] == []

    async def test_embed_token_for_other_map_resolves_empty_scope(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds_a = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        ds_b = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        map_a, _share_a, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(ds_a.id)]
        )
        map_b, _share_b, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(ds_b.id)]
        )
        _token_obj, raw_token = await create_embed_token(
            test_db_session, uuid.UUID(map_a), admin_id
        )
        await test_db_session.commit()

        scope = await resolve_embed_scope_for_map(
            test_db_session, raw_token, uuid.UUID(map_b)
        )
        assert scope == set()
        scope_a = await resolve_embed_scope_for_map(
            test_db_session, raw_token, uuid.UUID(map_a)
        )
        assert scope_a == {ds_a.id}


class TestBatchTokensEmbedFallback:
    async def test_anonymous_batch_denied_without_embed_token(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        private_ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        await _make_public_shared_map(client, admin_auth_header, [str(private_ds.id)])
        await _downgrade_to_private(test_db_session, private_ds)

        resp = await client.post(
            "/tiles/tokens/", json={"dataset_ids": [str(private_ds.id)]}
        )
        assert resp.status_code == 200
        assert "error" in resp.json()["tokens"][str(private_ds.id)]

    async def test_anonymous_batch_authorized_with_embed_token(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        private_ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        map_id, _share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(private_ds.id)]
        )
        _token_obj, raw_token = await create_embed_token(
            test_db_session, uuid.UUID(map_id), admin_id
        )
        await test_db_session.commit()
        await _downgrade_to_private(test_db_session, private_ds)

        resp = await client.post(
            "/tiles/tokens/",
            json={"dataset_ids": [str(private_ds.id)]},
            headers={"X-Embed-Token": raw_token},
        )
        assert resp.status_code == 200
        entry = resp.json()["tokens"][str(private_ds.id)]
        assert entry.get("kind") == "vector", entry
        assert entry["scope"]


class TestTileVersionField:
    async def test_map_layers_carry_tile_version(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(ds.id)]
        )

        builder_resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert builder_resp.status_code == 200
        assert builder_resp.json()["layers"][0]["tile_version"] == 1

        shared_resp = await client.get(f"/maps/shared/{share_token}")
        assert shared_resp.status_code == 200
        assert shared_resp.json()["layers"][0]["tile_version"] == 1

    async def test_tile_version_bumps_on_content_mutation(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """fix(#525 B-038): tile_version must roll on content mutations that
        don't create a DatasetVersion row. It previously read current_version
        (bumped on reupload only), so feature edits / column DDL / tile_columns
        changes purged Valkey but left the ``_v=`` tile URL unchanged — CDN and
        browser caches kept serving stale tiles until max-age expiry (T-01).
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            column_info=[{"name": "name", "type": "text"}],
        )
        map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(ds.id)]
        )

        # A tile_columns change alters the attribute set embedded in vector
        # tiles — the PATCH handler must bump the dedicated cache-buster.
        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={"tile_columns": ["name"]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

        builder_resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert builder_resp.status_code == 200
        assert builder_resp.json()["layers"][0]["tile_version"] == 2

        shared_resp = await client.get(f"/maps/shared/{share_token}")
        assert shared_resp.status_code == 200
        assert shared_resp.json()["layers"][0]["tile_version"] == 2


class TestGeojsonZEmbedFallback:
    async def test_geojson_z_accepts_embed_token_for_scoped_dataset(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """fix(#394) codex P2: the viewer's bounded-GeoJSON path sends
        X-Embed-Token, and the B-023 union exposes embed-scoped private layers
        to embeds — the endpoint must honor the token or those layers 401.

        Asserts the AUTH contract only: anonymous → 401; valid scoped token →
        past the auth gate (200 with a backing data table, 503 without one —
        never 401/403/404).
        """
        admin_id = await get_user_id(test_db_session, "admin")
        private_ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        map_id, _share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(private_ds.id)]
        )
        _token_obj, raw_token = await create_embed_token(
            test_db_session, uuid.UUID(map_id), admin_id
        )
        await test_db_session.commit()
        await _downgrade_to_private(test_db_session, private_ds)

        anon = await client.get(f"/datasets/{private_ds.id}/features.geojson")
        # fix(#390): anon on a private dataset now 404s (non-leaking) rather
        # than 401; the embed token remains the only anon authorization path.
        assert anon.status_code == 404

        with_token = await client.get(
            f"/datasets/{private_ds.id}/features.geojson",
            headers={"X-Embed-Token": raw_token},
        )
        assert with_token.status_code not in (401, 403, 404), with_token.text
