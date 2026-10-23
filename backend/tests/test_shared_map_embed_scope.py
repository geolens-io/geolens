"""shared-map embed-token scope + tile_version.

Covers:
  - GET /maps/shared/{token} honors X-Embed-Token — layers backed
    by the token's scoped private datasets are included (the tile path always
    honored the token; the metadata payload now matches, per the embed
    token's capability posture).
  - POST /tiles/tokens/ accepts X-Embed-Token as fallback authorization
    so embed viewers obtain the same tile/DEM descriptors as viewers.
  - MapLayerResponse + SharedLayerResponse carry ``tile_version``
    (Dataset.current_version) for the client `_v=` cache-buster.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.datasets.domain.models import (
    AttributeMetadata,
    Dataset,
    Record,
)
from app.modules.embed_tokens.models import EmbedToken
from app.modules.embed_tokens.service import (
    create_embed_token,
    resolve_embed_scope_for_map,
)

from tests.factories import create_dataset, get_user_id


async def _downgrade_to_private(session, dataset: Dataset) -> None:
    """Flip a dataset private AFTER map publish — the exact scenario
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
            test_db_session,
            created_by=admin_id,
            visibility="public",
            spatial_extent_wkt="POLYGON((-10 40, -10 45, -5 45, -5 40, -10 40))",
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
        layers = resp.json()["layers"]
        dataset_ids = {layer["dataset_id"] for layer in layers}
        assert str(public_ds.id) in dataset_ids
        assert str(private_ds.id) not in dataset_ids
        public_layer = next(
            layer for layer in layers if layer["dataset_id"] == str(public_ds.id)
        )
        assert public_layer["dataset_extent_bbox"] == pytest.approx(
            [-10.0, 40.0, -5.0, 45.0]
        )

    async def test_valid_embed_token_includes_scoped_private_layer(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        public_ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        private_ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            spatial_extent_wkt="POLYGON((-10 40, -10 45, -5 45, -5 40, -10 40))",
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
        private_layer = next(
            layer
            for layer in data["layers"]
            if layer["dataset_id"] == str(private_ds.id)
        )
        assert private_layer["dataset_extent_bbox"] == pytest.approx(
            [-10.0, 40.0, -5.0, 45.0]
        )

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


class TestDatasetExtentBboxField:
    async def test_the_shared_layer_carries_the_records_extent_as_a_bbox(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            spatial_extent_wkt="POLYGON((-10 40, -10 45, -5 45, -5 40, -10 40))",
        )
        _map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(ds.id)]
        )

        resp = await client.get(f"/maps/shared/{share_token}")
        assert resp.status_code == 200
        assert resp.json()["layers"][0]["dataset_extent_bbox"] == pytest.approx(
            [-10.0, 40.0, -5.0, 45.0]
        )

    async def test_a_layer_with_no_recorded_extent_returns_a_null_bbox(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        _map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(ds.id)]
        )

        resp = await client.get(f"/maps/shared/{share_token}")
        assert resp.status_code == 200
        assert resp.json()["layers"][0]["dataset_extent_bbox"] is None

    async def test_an_antimeridian_crossing_bbox_matches_the_builder_layer(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """west > east on a crossing extent, and both response shapes agree."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            spatial_extent_wkt=(
                "MULTIPOLYGON(((150 -10,180 -10,180 10,150 10,150 -10)),"
                "((-180 -10,-110 -10,-110 10,-180 10,-180 -10)))"
            ),
        )
        map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(ds.id)]
        )

        builder_resp = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert builder_resp.status_code == 200
        builder_bbox = builder_resp.json()["layers"][0]["dataset_extent_bbox"]

        shared_resp = await client.get(f"/maps/shared/{share_token}")
        assert shared_resp.status_code == 200
        shared_bbox = shared_resp.json()["layers"][0]["dataset_extent_bbox"]

        expected = pytest.approx([150.0, -10.0, -110.0, 10.0])
        assert builder_bbox == expected
        assert shared_bbox == expected
        assert shared_bbox[0] > shared_bbox[2]


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
        """Tile_version must roll on content mutations that
        don't create a DatasetVersion row. It previously read current_version
        (bumped on reupload only), so feature edits / column DDL / tile_columns
        changes purged Valkey but left the ``_v=`` tile URL unchanged — CDN and
        browser caches kept serving stale tiles until max-age expiry.
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
        """The viewer's bounded-GeoJSON path sends
        X-Embed-Token, and the union exposes embed-scoped private layers
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
        # anon on a private dataset now 404s (non-leaking) rather
        # than 401; the embed token remains the only anon authorization path.
        assert anon.status_code == 404

        with_token = await client.get(
            f"/datasets/{private_ds.id}/features.geojson",
            headers={"X-Embed-Token": raw_token},
        )
        assert with_token.status_code not in (401, 403, 404), with_token.text


class TestSharedMapColumnTitles:
    async def test_embed_payload_carries_titles_only_for_exposed_columns(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            column_info=[
                {"name": "pop", "type": "integer"},
                {"name": "plain", "type": "text"},
            ],
        )
        test_db_session.add_all(
            [
                AttributeMetadata(
                    dataset_id=ds.id, field_name="pop", title="Population"
                ),
                AttributeMetadata(dataset_id=ds.id, field_name="plain", title=None),
                AttributeMetadata(
                    dataset_id=ds.id, field_name="not_exposed", title="Internal"
                ),
                AttributeMetadata(
                    dataset_id=ds.id,
                    field_name="pop_old",
                    title="Removed",
                    is_current=False,
                ),
            ]
        )
        await test_db_session.commit()
        map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(ds.id)]
        )
        _token_obj, raw_token = await create_embed_token(
            test_db_session, uuid.UUID(map_id), admin_id
        )
        await test_db_session.commit()
        await _downgrade_to_private(test_db_session, ds)

        anon = await client.get(f"/maps/shared/{share_token}")
        assert anon.status_code == 200
        assert anon.json()["layers"] == []

        resp = await client.get(
            f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
        )
        assert resp.status_code == 200, resp.text
        column_info = resp.json()["layers"][0]["column_info"]
        assert column_info == [
            {"name": "pop", "type": "integer", "title": "Population"},
            {"name": "plain", "type": "text"},
        ]


class TestSharedMapValueLabels:
    async def _embed_map(self, client, admin_auth_header, session, labels):
        admin_id = await get_user_id(session, "admin")
        ds = await create_dataset(
            session,
            created_by=admin_id,
            visibility="public",
            column_info=[
                {"name": "status", "type": "integer"},
                {"name": "plain", "type": "text"},
            ],
        )
        session.add_all(
            [
                AttributeMetadata(
                    dataset_id=ds.id, field_name="status", value_labels=labels
                ),
                AttributeMetadata(
                    dataset_id=ds.id,
                    field_name="not_exposed",
                    value_labels={"1": "Internal"},
                ),
                AttributeMetadata(
                    dataset_id=ds.id,
                    field_name="status_old",
                    value_labels={"1": "Removed"},
                    is_current=False,
                ),
            ]
        )
        await session.commit()
        map_id, share_token, _ = await _make_public_shared_map(
            client, admin_auth_header, [str(ds.id)]
        )
        _token_obj, raw_token = await create_embed_token(
            session, uuid.UUID(map_id), admin_id
        )
        await session.commit()
        await _downgrade_to_private(session, ds)
        return share_token, raw_token

    async def test_an_embed_viewer_gets_labels_for_exposed_columns_only(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        share_token, raw_token = await self._embed_map(
            client, admin_auth_header, test_db_session, {"1": "Active"}
        )

        resp = await client.get(
            f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["layers"][0]["column_info"] == [
            {"name": "status", "type": "integer", "value_labels": {"1": "Active"}},
            {"name": "plain", "type": "text"},
        ]
        assert "Internal" not in resp.text
        assert "Removed" not in resp.text

    async def test_a_viewer_without_access_to_the_dataset_gets_no_labels(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        share_token, _raw_token = await self._embed_map(
            client, admin_auth_header, test_db_session, {"1": "Active"}
        )

        resp = await client.get(f"/maps/shared/{share_token}")

        assert resp.status_code == 200
        assert resp.json()["layers"] == []
        assert "Active" not in resp.text

    async def test_labels_over_the_layer_budget_are_left_out(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        from app.modules.catalog.maps import service_public

        labels = {str(i): f"label {i}" for i in range(50)}
        share_token, raw_token = await self._embed_map(
            client, admin_auth_header, test_db_session, labels
        )
        monkeypatch.setattr(service_public, "SHARED_VALUE_LABELS_MAX_BYTES", 100)

        resp = await client.get(
            f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["layers"][0]["column_info"][0] == {
            "name": "status",
            "type": "integer",
        }

    @staticmethod
    def _attribute_statements(captured, fetched_labels: bool):
        """Statements on attribute_metadata that read the labels themselves, or only their size."""
        return [
            (sql, params)
            for sql, params in captured
            if "attribute_metadata" in sql
            and "value_labels" in sql
            and ("octet_length" not in sql) == fetched_labels
        ]

    async def test_labels_of_unexposed_columns_are_never_selected(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        share_token, raw_token = await self._embed_map(
            client, admin_auth_header, test_db_session, {"1": "Active"}
        )
        captured: list = []

        def record(conn, cursor, statement, parameters, context, executemany):
            captured.append((statement, repr(parameters)))

        event.listen(Engine, "before_cursor_execute", record)
        try:
            resp = await client.get(
                f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
            )
        finally:
            event.remove(Engine, "before_cursor_execute", record)

        assert resp.status_code == 200, resp.text
        reads = self._attribute_statements(captured, fetched_labels=True)
        sizes = self._attribute_statements(captured, fetched_labels=False)
        assert len(reads) == 1 and len(sizes) == 1
        for _sql, params in reads + sizes:
            assert "status" in params
            assert "not_exposed" not in params

    async def test_an_over_budget_layer_never_reads_its_labels_but_keeps_its_titles(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        from sqlalchemy import event, update
        from sqlalchemy.engine import Engine

        from app.modules.catalog.maps import service_public

        labels = {str(i): f"label {i}" for i in range(50)}
        share_token, raw_token = await self._embed_map(
            client, admin_auth_header, test_db_session, labels
        )
        await test_db_session.execute(
            update(AttributeMetadata)
            .where(AttributeMetadata.field_name == "status")
            .values(title="Status")
        )
        await test_db_session.commit()
        monkeypatch.setattr(service_public, "SHARED_VALUE_LABELS_MAX_BYTES", 100)
        captured: list = []

        def record(conn, cursor, statement, parameters, context, executemany):
            captured.append((statement, repr(parameters)))

        event.listen(Engine, "before_cursor_execute", record)
        try:
            resp = await client.get(
                f"/maps/shared/{share_token}", headers={"X-Embed-Token": raw_token}
            )
        finally:
            event.remove(Engine, "before_cursor_execute", record)

        assert resp.status_code == 200, resp.text
        assert self._attribute_statements(captured, fetched_labels=True) == []
        assert resp.json()["layers"][0]["column_info"][0] == {
            "name": "status",
            "type": "integer",
            "title": "Status",
        }

    async def test_the_exposed_pair_filter_uses_a_constant_number_of_parameters(
        self, test_db_session
    ):
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        from app.modules.catalog.maps.service_public import (
            _attribute_display_by_dataset,
        )

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        test_db_session.add(
            AttributeMetadata(
                dataset_id=ds.id, field_name="status", value_labels={"1": "Active"}
            )
        )
        await test_db_session.commit()
        exposed = {ds.id: {"status"}} | {
            uuid.uuid4(): {f"col_{i}" for i in range(10)} for _ in range(300)
        }
        counts: list[int] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if "attribute_metadata" in statement:
                counts.append(len(parameters))

        event.listen(Engine, "before_cursor_execute", record)
        try:
            display = await _attribute_display_by_dataset(test_db_session, exposed)
        finally:
            event.remove(Engine, "before_cursor_execute", record)

        assert display == {ds.id: {"status": {"value_labels": {"1": "Active"}}}}
        assert len(counts) == 2
        assert max(counts) <= 4

    def test_the_layer_budget_is_64_kb(self):
        from app.modules.catalog.maps.service_public import (
            SHARED_VALUE_LABELS_MAX_BYTES,
        )

        assert SHARED_VALUE_LABELS_MAX_BYTES == 64 * 1024
