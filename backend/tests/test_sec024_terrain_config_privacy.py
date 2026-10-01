"""Regression tests for SEC-024: private DEM dataset_id disclosure in shared map.

get_shared_map used to pass terrain_config verbatim even when the referenced
source_dataset_id was private (not visible in the shared/public response).
This test verifies:
  - A public map with a PRIVATE DEM in terrain_config returns terrain_config=None
    (or stripped source_dataset_id) for anonymous viewers.
  - A public map with a PUBLIC DEM layer still returns terrain_config intact.

Fail-before / pass-after protocol: these tests MUST FAIL on unpatched code.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import RasterAsset
from tests.factories import create_dataset, get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_raster_dem_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "private",
    record_status: str = "published",
) -> Dataset:
    """Create a raster DEM dataset with given visibility."""
    table_name = f"dem_{uuid.uuid4().hex[:10]}"
    record = Record(
        title=f"DEM {table_name}",
        summary="Terrain DEM for SEC-024 tests",
        visibility=visibility,
        record_status=record_status,
        created_by=created_by,
        record_type="raster_dataset",
        theme_category=["test"],
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type=None,
        source_format="geotiff",
        source_filename="dem.tif",
    )
    session.add(dataset)
    await session.flush()

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/source.cog.tif",
        storage_backend="local",
        is_dem=True,
        band_count=1,
    )
    session.add(raster_asset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_public_vector_dataset(session, *, created_by: uuid.UUID) -> Dataset:
    return await create_dataset(
        session,
        created_by=created_by,
        name=f"Vector {uuid.uuid4().hex[:6]}",
        visibility="public",
        record_status="published",
    )


async def _set_map_terrain_config(
    session, map_id: uuid.UUID, terrain_config: dict | None
) -> None:
    """Directly set terrain_config on a map row (bypasses API schema restrictions)."""
    import json

    if terrain_config is None:
        await session.execute(
            text(
                "UPDATE catalog.maps SET terrain_config = NULL"
                " WHERE id = cast(:map_id as uuid)"
            ).bindparams(map_id=str(map_id)),
        )
    else:
        await session.execute(
            text(
                "UPDATE catalog.maps SET terrain_config = cast(:tc as jsonb)"
                " WHERE id = cast(:map_id as uuid)"
            ).bindparams(map_id=str(map_id), tc=json.dumps(terrain_config)),
        )
    await session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSec024TerrainConfigPrivacy:
    """SEC-024: terrain_config.source_dataset_id must not leak private DEM ids."""

    async def test_private_dem_terrain_config_stripped_for_anon(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Anonymous shared-map access must NOT expose a private DEM's dataset id.

        Pre-fix: terrain_config is returned verbatim (source_dataset_id leaks).
        Post-fix: terrain_config is None (or source_dataset_id absent) when the DEM
        dataset is not among the visible layers.
        """
        admin_id = await get_user_id(test_db_session, "admin")

        # Create a PRIVATE DEM (not a layer in the map).
        private_dem = await _create_raster_dem_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
        )

        # Create a PUBLIC vector layer for the map.
        vector_ds = await _create_public_vector_dataset(
            test_db_session, created_by=admin_id
        )

        # Create a public map and add the public vector layer.
        create_resp = await client.post(
            "/maps/",
            json={"name": "SEC-024 Private DEM Map"},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        map_id = uuid.UUID(create_resp.json()["id"])

        layer_resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(vector_ds.id)},
            headers=admin_auth_header,
        )
        assert layer_resp.status_code == 201

        # Set the map public.
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )

        # Inject terrain_config pointing to the PRIVATE DEM directly in DB.
        await _set_map_terrain_config(
            test_db_session,
            map_id,
            {
                "enabled": True,
                "source_dataset_id": str(private_dem.id),
                "exaggeration": 1.5,
            },
        )

        # Create a share token.
        share_resp = await client.post(
            f"/maps/{map_id}/share/", headers=admin_auth_header
        )
        assert share_resp.status_code in (200, 201)
        token = share_resp.json()["token"]

        # Anonymous access to the shared map.
        resp = await client.get(f"/maps/shared/{token}")
        assert resp.status_code == 200

        data = resp.json()
        terrain = data.get("terrain_config")
        # SEC-024: the private DEM id must not be disclosed.
        assert terrain is None or terrain.get("source_dataset_id") is None, (
            f"SEC-024 FAIL: terrain_config discloses private DEM id: {terrain}"
        )

    async def test_public_dem_terrain_config_preserved(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """When the DEM dataset is public AND is a visible layer, terrain_config
        must be returned intact so the viewer can render terrain.
        """
        admin_id = await get_user_id(test_db_session, "admin")

        # Create a PUBLIC DEM.
        public_dem = await _create_raster_dem_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
        )

        # Create a public map and add the DEM layer.
        create_resp = await client.post(
            "/maps/",
            json={"name": "SEC-024 Public DEM Map"},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        map_id = uuid.UUID(create_resp.json()["id"])

        layer_resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(public_dem.id)},
            headers=admin_auth_header,
        )
        assert layer_resp.status_code == 201

        # Set public.
        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )

        # Inject terrain_config pointing to the PUBLIC DEM.
        await _set_map_terrain_config(
            test_db_session,
            map_id,
            {
                "enabled": True,
                "source_dataset_id": str(public_dem.id),
                "exaggeration": 1.0,
            },
        )

        share_resp = await client.post(
            f"/maps/{map_id}/share/", headers=admin_auth_header
        )
        assert share_resp.status_code in (200, 201)
        token = share_resp.json()["token"]

        resp = await client.get(f"/maps/shared/{token}")
        assert resp.status_code == 200

        data = resp.json()
        terrain = data.get("terrain_config")
        # Public DEM layer is visible — terrain_config must be intact.
        assert terrain is not None, "terrain_config must not be stripped for public DEM"
        assert terrain.get("source_dataset_id") == str(public_dem.id), (
            f"Expected public DEM id in terrain_config, got: {terrain}"
        )

    async def test_no_layers_fallback_private_dem_stripped(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Fallback path (map with no visible layers): terrain_config with private DEM
        must also be stripped.
        """
        admin_id = await get_user_id(test_db_session, "admin")

        private_dem = await _create_raster_dem_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="private",
        )

        # Create a public map with NO layers (triggers fallback path).
        create_resp = await client.post(
            "/maps/",
            json={"name": "SEC-024 Empty Map Fallback"},
            headers=admin_auth_header,
        )
        assert create_resp.status_code == 201
        map_id = uuid.UUID(create_resp.json()["id"])

        await client.put(
            f"/maps/{map_id}",
            json={"visibility": "public"},
            headers=admin_auth_header,
        )

        # Inject terrain_config with private DEM.
        await _set_map_terrain_config(
            test_db_session,
            map_id,
            {
                "enabled": True,
                "source_dataset_id": str(private_dem.id),
                "exaggeration": 1.0,
            },
        )

        share_resp = await client.post(
            f"/maps/{map_id}/share/", headers=admin_auth_header
        )
        assert share_resp.status_code in (200, 201)
        token = share_resp.json()["token"]

        resp = await client.get(f"/maps/shared/{token}")
        assert resp.status_code == 200

        data = resp.json()
        terrain = data.get("terrain_config")
        assert terrain is None or terrain.get("source_dataset_id") is None, (
            f"SEC-024 FAIL (fallback path): private DEM id disclosed: {terrain}"
        )


# ---------------------------------------------------------------------------
# One projection across map detail, style export and the shared-token read
# ---------------------------------------------------------------------------


async def _publish_map_with_terrain(
    client: AsyncClient,
    admin_auth_header: dict,
    session,
    *,
    layer_dataset_ids: list[uuid.UUID],
    terrain_dataset_id: uuid.UUID,
) -> tuple[uuid.UUID, str]:
    """A public map drawing ``layer_dataset_ids`` with terrain bound to a DEM."""
    create_resp = await client.post(
        "/maps/",
        json={"name": f"Terrain privacy {uuid.uuid4().hex[:6]}"},
        headers=admin_auth_header,
    )
    assert create_resp.status_code == 201
    map_id = uuid.UUID(create_resp.json()["id"])
    for dataset_id in layer_dataset_ids:
        layer_resp = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(dataset_id)},
            headers=admin_auth_header,
        )
        assert layer_resp.status_code == 201
    visibility_resp = await client.put(
        f"/maps/{map_id}",
        json={"visibility": "public"},
        headers=admin_auth_header,
    )
    assert visibility_resp.status_code == 200
    await _set_map_terrain_config(
        session,
        map_id,
        {
            "enabled": True,
            "source_dataset_id": str(terrain_dataset_id),
            "exaggeration": 1.5,
        },
    )
    share_resp = await client.post(f"/maps/{map_id}/share/", headers=admin_auth_header)
    assert share_resp.status_code in (200, 201)
    return map_id, share_resp.json()["token"]


async def _read_map_three_ways(
    client: AsyncClient, map_id: uuid.UUID, token: str, headers: dict | None = None
) -> dict[str, tuple[dict, str]]:
    """Terrain binding and raw body of each read that can carry it."""
    detail = await client.get(f"/maps/{map_id}", headers=headers)
    style = await client.get(f"/maps/{map_id}/style.json", headers=headers)
    shared = await client.get(f"/maps/shared/{token}")
    for resp in (detail, style, shared):
        assert resp.status_code == 200, resp.text
    return {
        "detail": (detail.json()["terrain_config"], detail.text),
        "style": (style.json()["metadata"]["geolens"]["terrain_config"], style.text),
        "shared": (shared.json()["terrain_config"], shared.text),
    }


async def _make_dataset_private(session, dataset: Dataset) -> None:
    await session.execute(
        text(
            "UPDATE catalog.records SET visibility = 'private'"
            " WHERE id = cast(:record_id as uuid)"
        ).bindparams(record_id=str(dataset.record_id))
    )
    await session.commit()


class TestTerrainBindingProjectedForEveryReader:
    async def test_hidden_dem_id_is_not_echoed_by_any_read(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        private_dem = await _create_raster_dem_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        vector_ds = await _create_public_vector_dataset(
            test_db_session, created_by=admin_id
        )
        map_id, token = await _publish_map_with_terrain(
            client,
            admin_auth_header,
            test_db_session,
            layer_dataset_ids=[vector_ds.id],
            terrain_dataset_id=private_dem.id,
        )

        reads = await _read_map_three_ways(client, map_id, token)

        for name, (terrain, body) in reads.items():
            assert terrain is None, f"{name} returned a terrain binding: {terrain}"
            assert str(private_dem.id) not in body, f"{name} discloses the DEM id"

    async def test_dem_made_private_after_the_map_was_saved_is_hidden(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dem = await _create_raster_dem_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        map_id, token = await _publish_map_with_terrain(
            client,
            admin_auth_header,
            test_db_session,
            layer_dataset_ids=[dem.id],
            terrain_dataset_id=dem.id,
        )

        before = await _read_map_three_ways(client, map_id, token)
        # Control: a visible DEM keeps its binding on every read.
        for name, (terrain, _body) in before.items():
            assert terrain is not None, f"{name} lost a visible DEM's binding"
            assert terrain["source_dataset_id"] == str(dem.id)

        await _make_dataset_private(test_db_session, dem)

        after = await _read_map_three_ways(client, map_id, token)
        for name, (terrain, body) in after.items():
            assert terrain is None, f"{name} returned a terrain binding: {terrain}"
            assert str(dem.id) not in body, f"{name} discloses the DEM id"

    async def test_caller_who_can_see_the_dem_keeps_the_full_binding(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dem = await _create_raster_dem_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        map_id, token = await _publish_map_with_terrain(
            client,
            admin_auth_header,
            test_db_session,
            layer_dataset_ids=[dem.id],
            terrain_dataset_id=dem.id,
        )
        await _make_dataset_private(test_db_session, dem)

        reads = await _read_map_three_ways(
            client, map_id, token, headers=admin_auth_header
        )

        for name in ("detail", "style"):
            terrain, _body = reads[name]
            assert terrain == {
                "enabled": True,
                "source_dataset_id": str(dem.id),
                "exaggeration": 1.5,
            }, f"{name} dropped the binding for a caller who can see the DEM"


class TestDanglingTerrainBinding:
    """A binding whose DEM is not a layer stays readable as a missing source."""

    async def _detail_and_style(self, client, map_id, token):
        reads = await _read_map_three_ways(client, map_id, token)
        return {name: reads[name][0] for name in ("detail", "style")}

    async def test_a_visible_dem_outside_the_layers_keeps_its_binding(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dem = await _create_raster_dem_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        vector_ds = await _create_public_vector_dataset(
            test_db_session, created_by=admin_id
        )
        map_id, token = await _publish_map_with_terrain(
            client,
            admin_auth_header,
            test_db_session,
            layer_dataset_ids=[vector_ds.id],
            terrain_dataset_id=dem.id,
        )

        for name, terrain in (
            await self._detail_and_style(client, map_id, token)
        ).items():
            assert terrain is not None, f"{name} dropped a visible DEM's binding"
            assert terrain["source_dataset_id"] == str(dem.id)

    async def test_a_deleted_dem_keeps_its_binding(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        vector_ds = await _create_public_vector_dataset(
            test_db_session, created_by=admin_id
        )
        missing_dem_id = uuid.uuid4()
        map_id, token = await _publish_map_with_terrain(
            client,
            admin_auth_header,
            test_db_session,
            layer_dataset_ids=[vector_ds.id],
            terrain_dataset_id=missing_dem_id,
        )

        for name, terrain in (
            await self._detail_and_style(client, map_id, token)
        ).items():
            assert terrain is not None, f"{name} dropped a deleted DEM's binding"
            assert terrain["source_dataset_id"] == str(missing_dem_id)


class TestForkedTerrainBinding:
    async def test_a_fork_never_stores_a_dem_id_its_owner_cannot_see(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dem = await _create_raster_dem_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        map_id, _token = await _publish_map_with_terrain(
            client,
            admin_auth_header,
            test_db_session,
            layer_dataset_ids=[dem.id],
            terrain_dataset_id=dem.id,
        )

        visible_fork = await client.post(
            f"/maps/{map_id}/duplicate/", headers=editor_auth_header
        )
        # Control: a fork that keeps the DEM layer keeps the binding.
        assert visible_fork.status_code == 201
        assert visible_fork.json()["terrain_config"]["source_dataset_id"] == str(dem.id)

        await _make_dataset_private(test_db_session, dem)
        hidden_fork = await client.post(
            f"/maps/{map_id}/duplicate/", headers=editor_auth_header
        )
        assert hidden_fork.status_code == 201
        fork_id = hidden_fork.json()["id"]
        renamed = await client.put(
            f"/maps/{fork_id}",
            json={"name": "Renamed fork"},
            headers=editor_auth_header,
        )
        reshuffled = await client.patch(
            f"/maps/{fork_id}/layers",
            json={"order": []},
            headers=editor_auth_header,
        )
        detail = await client.get(f"/maps/{fork_id}", headers=editor_auth_header)

        assert hidden_fork.json()["excluded_layer_count"] == 1
        assert renamed.status_code == 200
        assert reshuffled.status_code == 200
        assert detail.status_code == 200
        for name, resp in (
            ("duplicate", hidden_fork),
            ("rename", renamed),
            ("layer patch", reshuffled),
            ("detail", detail),
        ):
            assert resp.json()["terrain_config"] is None, name
            assert str(dem.id) not in resp.text, f"{name} discloses the DEM id"
        stored = (
            await test_db_session.execute(
                text(
                    "SELECT CAST(terrain_config AS text) FROM catalog.maps"
                    " WHERE id = cast(:id as uuid)"
                ).bindparams(id=fork_id)
            )
        ).scalar_one()
        assert stored in (None, "null")

    async def test_a_fork_keeps_a_binding_its_owner_can_see_outside_the_layers(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        editor_auth_header: dict,
        test_db_session,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        dem = await _create_raster_dem_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        vector_ds = await _create_public_vector_dataset(
            test_db_session, created_by=admin_id
        )
        missing_dem_id = uuid.uuid4()
        for terrain_dataset_id in (dem.id, missing_dem_id):
            map_id, _token = await _publish_map_with_terrain(
                client,
                admin_auth_header,
                test_db_session,
                layer_dataset_ids=[vector_ds.id],
                terrain_dataset_id=terrain_dataset_id,
            )

            fork = await client.post(
                f"/maps/{map_id}/duplicate/", headers=editor_auth_header
            )

            assert fork.status_code == 201
            terrain = fork.json()["terrain_config"]
            assert terrain is not None
            assert terrain["source_dataset_id"] == str(terrain_dataset_id)
