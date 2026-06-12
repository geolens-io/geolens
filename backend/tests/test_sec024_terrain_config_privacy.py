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
