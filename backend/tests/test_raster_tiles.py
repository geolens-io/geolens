"""Integration tests for raster tile auth-check endpoint and raster token branch.

Tests:
  - GET /tiles/raster-auth-check/?dataset_id=... (nginx auth_request target)
  - GET /tiles/token/{dataset_id}/ raster branch

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import RasterAsset
from app.processing.tiles.router import (
    _dem_nodata_param,
    _raster_maxzoom_from_metadata,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one().id


async def _create_raster_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    record_status: str = "published",
    record_type: str = "raster_dataset",
    with_asset: bool = True,
    is_dem: bool = False,
    nodata: str | None = None,
) -> tuple[Record, Dataset, RasterAsset | None]:
    """Create a Record + Dataset (+ optional RasterAsset) for raster tests."""
    record = Record(
        title=f"Raster Tile Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for raster tile tests",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        record_type=record_type,
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"raster_tile_test_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.flush()

    raster_asset = None
    if with_asset:
        raster_asset = RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/abc123/source.cog.tif",
            storage_backend="local",
            is_dem=is_dem,
            nodata=nodata,
        )
        session.add(raster_asset)
        await session.flush()

    await session.commit()
    await session.refresh(dataset)
    if raster_asset:
        await session.refresh(raster_asset)
    return record, dataset, raster_asset


async def _create_vector_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
    record_status: str = "published",
) -> tuple[Record, Dataset]:
    """Create a vector Record + Dataset for contrast tests."""
    record = Record(
        title=f"Vector Tile Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for vector tile contrast tests",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        record_type="vector_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"vector_tile_test_{uuid.uuid4().hex[:8]}",
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return record, dataset


class TestRasterTokenZoomMetadata:
    """Pure unit tests for raster token zoom-range derivation."""

    def test_derives_maxzoom_from_meter_resolution(self):
        asset = RasterAsset(
            dataset_id=uuid.uuid4(),
            asset_uri="rasters/test/dem.tif",
            storage_backend="local",
            epsg=3857,
            res_x=1.39,
            res_y=1.39,
        )

        assert _raster_maxzoom_from_metadata(asset, None) == 17

    def test_derives_maxzoom_from_naip_resolution(self):
        asset = RasterAsset(
            dataset_id=uuid.uuid4(),
            asset_uri="rasters/test/naip.tif",
            storage_backend="local",
            epsg=3857,
            res_x=0.6,
            res_y=0.6,
        )

        assert _raster_maxzoom_from_metadata(asset, None) == 18

    def test_falls_back_to_legacy_maxzoom_without_metadata(self):
        assert _raster_maxzoom_from_metadata(None, None) == 18

    # fix(#939): the degrees-vs-metres decision was `epsg == 4326`, so every
    # other geographic CRS had its degree resolutions read as metres and
    # derived maxzoom 22 instead of 7 (measured on the live ETOPO 9518
    # dataset). Fixtures mirror that raster: 21600x10800 at 1/60 degree.

    _ETOPO_BOUNDS = [-180.0, -90.0, 180.0, 90.0]
    _ETOPO_RES = 1.0 / 60.0

    def _etopo_asset(self, *, epsg: int | None, crs_wkt: str | None) -> RasterAsset:
        return RasterAsset(
            dataset_id=uuid.uuid4(),
            asset_uri="rasters/test/etopo.tif",
            storage_backend="local",
            epsg=epsg,
            crs_wkt=crs_wkt,
            res_x=self._ETOPO_RES,
            res_y=self._ETOPO_RES,
            width=21600,
            height=10800,
        )

    def test_epsg_4326_without_wkt_still_reads_degrees(self):
        asset = self._etopo_asset(epsg=4326, crs_wkt=None)
        assert _raster_maxzoom_from_metadata(asset, self._ETOPO_BOUNDS) == 7

    @pytest.mark.parametrize(
        ("epsg", "crs_wkt"),
        [
            (
                4326,
                'GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",'
                'ELLIPSOID["WGS 84",6378137,298.257223563]],CS[ellipsoidal,2],'
                'AXIS["latitude",north],AXIS["longitude",east],'
                'ANGLEUNIT["degree",0.0174532925199433]]',
            ),
            (
                4269,
                'GEOGCS["NAD83",DATUM["North_American_Datum_1983",'
                'SPHEROID["GRS 1980",6378137,298.257222101]],'
                'UNIT["degree",0.0174532925199433]]',
            ),
            (
                4258,
                'GEOGCS["ETRS89",DATUM["European_Terrestrial_Reference_System_1989",'
                'SPHEROID["GRS 1980",6378137,298.257222101]],'
                'UNIT["degree",0.0174532925199433]]',
            ),
            (
                4979,
                'GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",'
                'ELLIPSOID["WGS 84",6378137,298.257223563]],CS[ellipsoidal,3],'
                'AXIS["latitude",north],AXIS["longitude",east],'
                'AXIS["ellipsoidal height",up],'
                'ANGLEUNIT["degree",0.0174532925199433]]',
            ),
            (
                7912,
                'GEOGCRS["ITRF2014",DYNAMIC[FRAMEEPOCH[2010]],'
                'DATUM["International Terrestrial Reference Frame 2014",'
                'ELLIPSOID["GRS 1980",6378137,298.257222101]],CS[ellipsoidal,3],'
                'AXIS["latitude",north],AXIS["longitude",east],'
                'AXIS["ellipsoidal height",up],'
                'ANGLEUNIT["degree",0.0174532925199433]]',
            ),
            (
                # fix(#939 codex r3): WKT2:2015 spelling — GEODCRS with an
                # ellipsoidal CS, the form rasterio still emits.
                4269,
                'GEODCRS["NAD83",DATUM["North American Datum 1983",'
                'ELLIPSOID["GRS 1980",6378137,298.257222101]],'
                "CS[ellipsoidal,2],"
                'AXIS["geodetic latitude (Lat)",north],'
                'AXIS["geodetic longitude (Lon)",east],'
                'ANGLEUNIT["degree",0.0174532925199433]]',
            ),
            (
                # EPSG:9518-style compound: geographic horizontal + vertical.
                # This is the live ETOPO repro that derived maxzoom 22.
                9518,
                'COMPOUNDCRS["WGS 84 + EGM2008 height",'
                'GEOGCRS["WGS 84",DATUM["World Geodetic System 1984",'
                'ELLIPSOID["WGS 84",6378137,298.257223563]],CS[ellipsoidal,2],'
                'AXIS["latitude",north],AXIS["longitude",east],'
                'ANGLEUNIT["degree",0.0174532925199433]],'
                'VERTCRS["EGM2008 height",VDATUM["EGM2008 geoid"],'
                'CS[vertical,1],AXIS["gravity-related height",up],'
                'LENGTHUNIT["metre",1]]]',
            ),
        ],
    )
    def test_geographic_crs_derives_same_maxzoom_as_4326(self, epsg, crs_wkt):
        # Every wrong answer here is a plausible integer, so assert the exact
        # value the 4326 path derives, not merely "not 22".
        asset = self._etopo_asset(epsg=epsg, crs_wkt=crs_wkt)
        assert _raster_maxzoom_from_metadata(asset, self._ETOPO_BOUNDS) == 7

    def test_grads_geographic_crs_falls_back_to_bounds_estimate(self):
        # fix(#939): a grads GEOGCS (NTF Paris family) is geographic but its
        # stored resolution is neither metres nor degrees. Pinned behavior:
        # skip the stored resolution and use the bounds/width estimate, which
        # for this global fixture also lands on 7 (vs 22 if the grads value
        # were read as metres).
        grads_wkt = (
            'GEOGCS["NTF (Paris)",DATUM["Nouvelle_Triangulation_Francaise_Paris",'
            'SPHEROID["Clarke 1880 (IGN)",6378249.2,293.4660212936265]],'
            'PRIMEM["Paris",2.33722917],UNIT["grad",0.01570796326794897]]'
        )
        asset = self._etopo_asset(epsg=4807, crs_wkt=grads_wkt)
        assert _raster_maxzoom_from_metadata(asset, self._ETOPO_BOUNDS) == 7

    def test_projected_meter_crs_with_wkt_unchanged(self):
        # 3857 and friends keep reading res_x/res_y as metres.
        asset = RasterAsset(
            dataset_id=uuid.uuid4(),
            asset_uri="rasters/test/dem.tif",
            storage_backend="local",
            epsg=3857,
            crs_wkt=(
                'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",'
                'DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                'UNIT["degree",0.0174532925199433]],'
                'PROJECTION["Mercator_1SP"],UNIT["metre",1]]'
            ),
            res_x=1.39,
            res_y=1.39,
        )
        assert _raster_maxzoom_from_metadata(asset, None) == 17


async def _get_auth_header(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Auth-check endpoint tests
# ---------------------------------------------------------------------------


class TestRasterAuthCheck:
    """Tests for GET /tiles/raster-auth-check/?dataset_id=..."""

    async def test_auth_check_returns_open_path_for_public_raster(
        self, client: AsyncClient, test_db_session
    ):
        """Public raster dataset, no auth -> 200 with X-GeoLens-Asset-OpenPath header."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 200
        open_path = resp.headers.get("x-geolens-asset-openpath")
        assert open_path is not None
        assert asset.asset_uri in open_path
        # Path should use the configured staging dir (overridden to tmp in tests)
        assert open_path.endswith(asset.asset_uri)
        assert resp.headers.get("x-geolens-cache-status") == "public"

    async def test_auth_check_returns_open_path_for_authenticated_user(
        self, client: AsyncClient, test_db_session
    ):
        """Private raster, valid JWT for owner -> 200 with X-GeoLens-Asset-OpenPath."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        auth_header = await _get_auth_header(
            client,
            settings.geolens_admin_username,
            settings.geolens_admin_password.get_secret_value(),
        )
        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=auth_header,
        )
        assert resp.status_code == 200
        open_path = resp.headers.get("x-geolens-asset-openpath")
        assert open_path is not None
        assert open_path.endswith(asset.asset_uri)
        assert resp.headers.get("x-geolens-cache-status") == "private"

    async def test_auth_check_owner_of_restricted_raster_keeps_access(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        viewer_auth_header: dict,
        test_db_session,
    ):
        """fix(#929): the raster auth gate mirrors can_access_dataset, so the
        creator exemption applies here too — a non-admin owner of a restricted
        raster gets 200, while another authenticated non-grantee stays 404."""
        from tests.conftest import _create_test_user

        owner_headers, owner_id = await _create_test_user(
            client, admin_auth_header, "editor"
        )
        record, dataset, asset = await _create_raster_dataset(
            test_db_session,
            created_by=uuid.UUID(owner_id),
            visibility="restricted",
        )

        as_owner = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=owner_headers,
        )
        assert as_owner.status_code == 200
        assert as_owner.headers.get("x-geolens-asset-openpath") is not None

        as_other = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=viewer_auth_header,
        )
        assert as_other.status_code == 404

    async def test_auth_check_overlay_denying_creator_wins(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        monkeypatch,
    ):
        """fix(#929 review): the raster gate consults the permission
        extension rather than hard-coding an owner short-circuit, so an
        overlay policy that deliberately denies a dataset's creator
        (revoked clearance, ABAC) is enforced here too."""
        from tests.conftest import _create_test_user

        import app.platform.extensions as extensions

        owner_headers, owner_id = await _create_test_user(
            client, admin_auth_header, "editor"
        )
        record, dataset, asset = await _create_raster_dataset(
            test_db_session,
            created_by=uuid.UUID(owner_id),
            visibility="restricted",
        )

        class _DenyEveryone:
            async def can_access_dataset(self, *args, **kwargs):
                return False

        monkeypatch.setitem(extensions._extensions, "permission", _DenyEveryone())
        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=owner_headers,
        )
        assert resp.status_code == 404

    async def test_auth_check_401_for_unauthenticated_private(
        self, client: AsyncClient, test_db_session
    ):
        """Private raster, no auth -> 401."""
        admin_id = await _get_admin_id(test_db_session)
        await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        # Use a fresh private dataset
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 401

    async def test_auth_check_404_for_nonexistent_dataset(
        self, client: AsyncClient, test_db_session
    ):
        """Random UUID -> 404."""
        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 404

    async def test_auth_check_404_for_vector_dataset(
        self, client: AsyncClient, test_db_session
    ):
        """Vector dataset ID -> 404 (not a raster dataset)."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset = await _create_vector_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 404

    async def test_auth_check_404_for_no_raster_asset(
        self, client: AsyncClient, test_db_session
    ):
        """Raster record type but no raster_assets row -> 404."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, _ = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public", with_asset=False
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 404

    async def test_auth_check_403_for_invalid_embed_token(
        self, client: AsyncClient, test_db_session
    ):
        """X-Embed-Token header with invalid token -> 403."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers={"X-Embed-Token": "invalid_token_xyz"},
        )
        assert resp.status_code == 403

    async def test_auth_check_blocks_unpublished_for_non_owner(
        self, client: AsyncClient, test_db_session, admin_auth_header: dict
    ):
        """Draft raster, different user -> 404."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            record_status="draft",
        )

        # Create a non-owner user
        unique = uuid.uuid4().hex[:8]
        username = f"viewer_{unique}"
        password = "TestPass1234!"
        resp = await client.post(
            "/admin/users/",
            json={"username": username, "password": password, "role": "viewer"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        viewer_header = await _get_auth_header(client, username, password)

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=viewer_header,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Issue #186: DEM nodata masking in terrainrgb encoding
# ---------------------------------------------------------------------------


class TestDemNodataParamUnit:
    """Pure unit tests for the DEM nodata resolution helper (#186)."""

    def test_recorded_integer_nodata_preferred(self):
        assert _dem_nodata_param("-32768") == "-32768"

    def test_recorded_float_nodata_kept_as_float(self):
        assert _dem_nodata_param("-9999.5") == "-9999.5"

    def test_integral_float_recorded_emits_integer_literal(self):
        # "-9999.0" should normalize to "-9999" for a clean URL.
        assert _dem_nodata_param("-9999.0") == "-9999"

    def test_missing_nodata_falls_back_to_default_sentinel(self):
        assert _dem_nodata_param(None) == "-9999"
        assert _dem_nodata_param("") == "-9999"
        assert _dem_nodata_param("   ") == "-9999"

    def test_non_numeric_nodata_returns_none(self):
        # "nan"/garbage → rely on the COG's internal mask, inject nothing.
        assert _dem_nodata_param("nan") is None
        assert _dem_nodata_param("not-a-number") is None
        assert _dem_nodata_param("inf") is None


class TestDemTerrainNodataAuthCheck:
    """raster_auth_check emits a nodata= mask in DEM terrainrgb render params (#186)."""

    async def test_dem_with_recorded_nodata_emits_masked_render_params(
        self, client: AsyncClient, test_db_session
    ):
        """DEM with recorded nodata -> terrainrgb render params include that nodata."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            is_dem=True,
            nodata="-9999",
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 200
        render_params = resp.headers.get("x-geolens-render-params", "")
        assert "algorithm=terrainrgb" in render_params
        # The headline #186 fix: nodata pixels are masked, not encoded as elevation.
        assert "nodata=-9999" in render_params

    async def test_dem_without_recorded_nodata_falls_back_to_sentinel(
        self, client: AsyncClient, test_db_session
    ):
        """DEM with NULL nodata -> render params fall back to the -9999 sentinel."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            is_dem=True,
            nodata=None,
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 200
        render_params = resp.headers.get("x-geolens-render-params", "")
        assert "algorithm=terrainrgb" in render_params
        assert "nodata=-9999" in render_params

    async def test_non_dem_raster_has_no_nodata_terrainrgb_params(
        self, client: AsyncClient, test_db_session
    ):
        """A non-DEM raster must NOT get terrainrgb/nodata masking."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session,
            created_by=admin_id,
            visibility="public",
            is_dem=False,
            nodata="0",
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )
        assert resp.status_code == 200
        render_params = resp.headers.get("x-geolens-render-params", "")
        assert "algorithm=terrainrgb" not in render_params


# ---------------------------------------------------------------------------
# RBAC regression: inline raster auth vs check_dataset_access
# ---------------------------------------------------------------------------


class TestRasterAuthRbacParity:
    """Verify the inline RBAC in raster_auth_check mirrors check_dataset_access."""

    async def test_private_dataset_non_owner_blocked_by_both_paths(
        self, client: AsyncClient, test_db_session
    ):
        """Private dataset: non-owner viewer is blocked by raster auth (inline RBAC)
        AND by the token endpoint (check_dataset_access). Both must agree."""
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        admin_auth_header = await _get_auth_header(
            client,
            settings.geolens_admin_username,
            settings.geolens_admin_password.get_secret_value(),
        )
        username = f"rbac_parity_{uuid.uuid4().hex[:6]}"
        password = "TestPass1234!"
        resp = await client.post(
            "/admin/users/",
            json={"username": username, "password": password, "role": "viewer"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201
        viewer_header = await _get_auth_header(client, username, password)

        # Path A: inline RBAC in raster-auth-check
        auth_check_resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
            headers=viewer_header,
        )

        # Path B: check_dataset_access in token endpoint
        token_resp = await client.get(
            f"/tiles/token/{dataset.id}/",
            headers=viewer_header,
        )

        # Both must block the non-owner viewer
        assert auth_check_resp.status_code in (403, 404), (
            f"raster-auth-check returned {auth_check_resp.status_code}, expected 403/404"
        )
        assert token_resp.status_code in (403, 404), (
            f"token endpoint returned {token_resp.status_code}, expected 403/404"
        )

    async def test_public_dataset_accessible_by_both_paths(
        self, client: AsyncClient, test_db_session
    ):
        """Public dataset: unauthenticated access succeeds on both paths."""
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        # Path A: raster-auth-check (no auth)
        auth_check_resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id)},
        )

        # Path B: token endpoint (no auth)
        token_resp = await client.get(f"/tiles/token/{dataset.id}/")

        # Both must allow access
        assert auth_check_resp.status_code == 200
        assert token_resp.status_code == 200


# ---------------------------------------------------------------------------
# Token endpoint tests
# ---------------------------------------------------------------------------


class TestRasterTokenEndpoint:
    """Tests for GET /tiles/token/{dataset_id}/ raster branch."""

    async def test_raster_token_returns_kind_raster(
        self, client: AsyncClient, test_db_session
    ):
        """Raster dataset -> response has kind=raster, tile_url, bounds, zoom, etc."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "raster"
        assert "tile_url" in data
        assert "{z}" in data["tile_url"]
        assert "{x}" in data["tile_url"]
        assert "{y}" in data["tile_url"]
        assert str(dataset.id) in data["tile_url"]
        assert "bounds" in data
        assert "minzoom" in data
        assert "maxzoom" in data
        assert "tile_size" in data
        assert "format" in data
        assert data["tile_size"] == 256
        assert data["format"] == "png"

    async def test_raster_token_derives_maxzoom_from_raster_metadata(
        self, client: AsyncClient, test_db_session
    ):
        """Raster token source maxzoom follows native COG resolution."""
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        assert asset is not None
        asset.epsg = 3857
        asset.res_x = 1.39
        asset.res_y = 1.39
        await test_db_session.commit()

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200
        data = resp.json()

        assert data["maxzoom"] == 17

    async def test_raster_batch_token_derives_maxzoom_from_raster_metadata(
        self, client: AsyncClient, test_db_session
    ):
        """Batch token endpoint uses the same raster metadata zoom path."""
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        assert asset is not None
        asset.epsg = 3857
        asset.res_x = 0.6
        asset.res_y = 0.6
        await test_db_session.commit()

        resp = await client.post(
            "/tiles/tokens/", json={"dataset_ids": [str(dataset.id)]}
        )
        assert resp.status_code == 200
        data = resp.json()["tokens"][str(dataset.id)]

        assert data["kind"] == "raster"
        assert data["maxzoom"] == 18

    async def test_raster_token_no_credentials_in_response(
        self, client: AsyncClient, test_db_session
    ):
        """Raster token response body contains no COG path, no asset_uri, no titiler URL."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200
        body = resp.text
        # Must not leak internal paths in response body
        assert "titiler" not in body.lower()
        assert "/vsis3" not in body
        assert "source.cog.tif" not in body
        assert "asset_uri" not in body

    async def test_vector_token_returns_kind_vector(
        self, client: AsyncClient, test_db_session
    ):
        """Vector dataset -> existing response fields + kind=vector."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset = await _create_vector_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "vector"
        # Original fields still present
        assert "sig" in data
        assert "exp" in data
        assert "scope" in data
        assert "expires_in" in data

    async def test_raster_token_401_for_private_unauthenticated(
        self, client: AsyncClient, test_db_session
    ):
        """Private raster, no auth -> 401."""
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# HYG-01: _band_stats_cache LRUCache unit tests
# ---------------------------------------------------------------------------


def test_band_stats_cache_eviction():
    """LRU eviction: inserting maxsize+1 entries causes the oldest to be evicted."""
    from cachetools import LRUCache

    # Mirror the same maxsize as router.py
    cache: LRUCache[str, list[dict] | None] = LRUCache(maxsize=256)
    for i in range(257):
        cache[f"path-{i}"] = [{"b1": i}]

    assert len(cache) == 256
    # path-0 (oldest insertion) should have been evicted
    assert "path-0" not in cache
    # path-256 (most recent insertion) should still be present
    assert "path-256" in cache


@pytest.mark.asyncio
async def test_band_stats_cache_hit(monkeypatch):
    """Cached path: _titiler_client.get called exactly once across two calls."""
    from app.processing.tiles.router import _band_stats_cache, _fetch_band_statistics

    _band_stats_cache.clear()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "b1": {
            "percentile_2": 10.0,
            "percentile_98": 250.0,
            "mean": 130.0,
            "std": 40.0,
            "min": 0.0,
            "max": 255.0,
        }
    }
    mock_get = AsyncMock(return_value=mock_response)
    monkeypatch.setattr("app.processing.tiles.router._titiler_client.get", mock_get)

    path = "/data/cache-hit-test.tif"
    # Phase 1153: _fetch_band_statistics now requires pmin/pmax for cache-key isolation
    result1 = await _fetch_band_statistics(path, 2.0, 98.0)
    result2 = await _fetch_band_statistics(path, 2.0, 98.0)

    assert mock_get.call_count == 1, "Second call must be served from cache"
    assert result1 == result2
    assert result1 is not None


@pytest.mark.asyncio
async def test_band_stats_cache_negative(monkeypatch):
    """Negative caching: None is stored and returned without a second Titiler call."""
    from app.processing.tiles.router import _band_stats_cache, _fetch_band_statistics

    _band_stats_cache.clear()

    mock_get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    monkeypatch.setattr("app.processing.tiles.router._titiler_client.get", mock_get)

    path = "/data/timeout-test.tif"
    # Phase 1153: _fetch_band_statistics now requires pmin/pmax for cache-key isolation
    result1 = await _fetch_band_statistics(path, 2.0, 98.0)
    result2 = await _fetch_band_statistics(path, 2.0, 98.0)

    assert result1 is None
    assert result2 is None
    assert mock_get.call_count == 1, (
        "None is cached — second call must not retry Titiler"
    )


# ---------------------------------------------------------------------------
# fix(#688): signed raster tile templates
# ---------------------------------------------------------------------------


class TestSignedRasterTileTemplate:
    """The raster token used to carry no signature at all.

    A client following the API contract literally received an *unauthenticated*
    template for a private raster: MapLibre issues the tile image requests and
    attaches no ``X-Api-Key``, so an API-key-only client could not render one.
    """

    @staticmethod
    def _signed_params(token: dict) -> dict:
        return {"sig": token["sig"], "exp": token["exp"], "scope": token["scope"]}

    async def test_raster_token_mints_a_self_sufficient_signed_template(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The template carries its own credentials and expires."""
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        resp = await client.get(
            f"/tiles/token/{dataset.id}/", headers=admin_auth_header
        )
        assert resp.status_code == 200
        token = resp.json()

        assert token["kind"] == "raster"
        assert token["scope"].endswith(str(dataset.id))
        assert token["expires_in"] > 0
        # The signature travels in the URL, because MapLibre never sends headers.
        assert f"sig={token['sig']}" in token["tile_url"]
        assert f"exp={token['exp']}" in token["tile_url"]
        # ...and the placeholders survive the query string.
        assert "{z}" in token["tile_url"] and "{y}" in token["tile_url"]

    async def test_a_signed_template_renders_a_private_raster_without_a_header(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The whole point: no Authorization, no X-Api-Key, still authorized."""
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        token = (
            await client.get(f"/tiles/token/{dataset.id}/", headers=admin_auth_header)
        ).json()

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id), **self._signed_params(token)},
        )

        assert resp.status_code == 200
        assert asset.asset_uri in resp.headers["x-geolens-asset-openpath"]

    async def test_an_unsigned_request_for_a_private_raster_still_401s(
        self, client: AsyncClient, test_db_session
    ):
        """The signed branch is additive; it does not open the unsigned path."""
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/", params={"dataset_id": str(dataset.id)}
        )

        assert resp.status_code == 401

    async def test_a_tampered_signature_falls_through_to_normal_auth(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        token = (
            await client.get(f"/tiles/token/{dataset.id}/", headers=admin_auth_header)
        ).json()
        params = self._signed_params(token)
        params["sig"] = "0" * len(params["sig"])

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id), **params},
        )

        # fix(#688 codex r1): an unusable signature falls through to the normal
        # branches rather than refusing, so an unauthenticated caller lands on
        # the same 401 it would have got without presenting one at all.
        assert resp.status_code == 401

    async def test_a_signature_minted_for_another_dataset_does_not_authorize(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """The scope binds the token to one dataset, so it cannot be replayed.

        This is the check that makes the id-based scope meaningful: without it a
        token for any raster the caller can read would open every other one.
        """
        admin_id = await _get_admin_id(test_db_session)
        _r1, mine, _a1 = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        _r2, other, _a2 = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        token = (
            await client.get(f"/tiles/token/{mine.id}/", headers=admin_auth_header)
        ).json()

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(other.id), **self._signed_params(token)},
        )

        assert resp.status_code == 401

    async def test_an_expired_signature_does_not_authorize(
        self, client: AsyncClient, test_db_session
    ):
        from app.core.tenancy import tenant_bound_scope
        from app.processing.tiles.signing import generate_tile_signature

        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        scope = tenant_bound_scope(str(dataset.id))
        expired = int(time.time()) - 60

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={
                "dataset_id": str(dataset.id),
                "sig": generate_tile_signature(scope, expired),
                "exp": expired,
                "scope": scope,
            },
        )

        assert resp.status_code == 401

    async def test_a_non_numeric_exp_does_not_500(
        self, client: AsyncClient, test_db_session
    ):
        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={
                "dataset_id": str(dataset.id),
                "sig": "abc",
                "exp": "not-a-number",
                "scope": "whatever",
            },
        )

        assert resp.status_code == 401

    async def test_a_signed_template_renders_an_unpublished_public_draft(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """fix(#688 codex r1): the draft-preview case.

        A public-but-unpublished raster is an owner/admin preview, and the mint
        endpoint issues a template for it. Gating the signature branch on
        ``visibility != "public"`` sent that template to the unpublished branch,
        which 404s a headerless caller — so the advertised self-sufficient
        template could not render a case it was minted for.
        """
        admin_id = await _get_admin_id(test_db_session)
        record, dataset, _asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        record.record_status = "draft"
        await test_db_session.commit()
        token = (
            await client.get(f"/tiles/token/{dataset.id}/", headers=admin_auth_header)
        ).json()

        # Without the signature this same caller is anonymous, so it 404s.
        bare = await client.get(
            "/tiles/raster-auth-check/", params={"dataset_id": str(dataset.id)}
        )
        assert bare.status_code == 404

        signed = await client.get(
            "/tiles/raster-auth-check/",
            params={"dataset_id": str(dataset.id), **self._signed_params(token)},
        )
        assert signed.status_code == 200

    async def test_an_expired_signature_does_not_break_a_signed_in_session(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """fix(#688 codex r1): the signature is additive, never a restriction.

        MapLibre keeps requesting the URL it was handed, so a preemptive refusal
        403'd an in-app map holding a valid session the moment its 15-minute
        template aged out. An unusable signature must fall through to the
        credentials the caller actually has.
        """
        from app.core.tenancy import tenant_bound_scope
        from app.processing.tiles.signing import generate_tile_signature

        admin_id = await _get_admin_id(test_db_session)
        _record, dataset, asset = await _create_raster_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        scope = tenant_bound_scope(str(dataset.id))
        expired = int(time.time()) - 60

        resp = await client.get(
            "/tiles/raster-auth-check/",
            params={
                "dataset_id": str(dataset.id),
                "sig": generate_tile_signature(scope, expired),
                "exp": expired,
                "scope": scope,
            },
            headers=admin_auth_header,
        )

        assert resp.status_code == 200
        assert asset.asset_uri in resp.headers["x-geolens-asset-openpath"]
