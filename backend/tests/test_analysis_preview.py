"""Tests for the parameterized PostGIS analysis preview endpoint (M4).

Exercises /datasets/{id}/analysis/preview/ plus the pure SQL builder.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import math
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.schemas import AnalysisPreviewRequest
from app.modules.catalog.datasets.domain.service import build_preview_sql

from tests.factories import create_dataset, get_user_id

SQUARE = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"
FAR_SQUARE = "POLYGON((10 10, 10 11, 11 11, 11 10, 10 10))"

# Mask overlapping only SQUARE's lower-left quarter.
CLIP_MASK = {
    "type": "Polygon",
    "coordinates": [[[-0.5, -0.5], [-0.5, 0.5], [0.5, 0.5], [0.5, -0.5], [-0.5, -0.5]]],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_polygon_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
):
    """Create a real data table with two polygons + its catalog rows."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  geom geometry(Polygon, 4326),"
            f"  geom_4326 geometry(Polygon, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, geom, geom_4326) VALUES "
            f"('a', ST_GeomFromText('{SQUARE}', 4326),"
            f" ST_GeomFromText('{SQUARE}', 4326)),"
            f"('b', ST_GeomFromText('{FAR_SQUARE}', 4326),"
            f" ST_GeomFromText('{FAR_SQUARE}', 4326))"
        )
    )
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POLYGON",
        feature_count=2,
        visibility=visibility,
    )


async def _create_point_dataset(
    session: AsyncSession, *, created_by: uuid.UUID, n: int
):
    """Create a data table with ``n`` points along the equator."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  geom geometry(Point, 4326),"
            f"  geom_4326 geometry(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326) "
            f"SELECT ST_SetSRID(ST_MakePoint(i * 0.001, 0), 4326),"
            f"       ST_SetSRID(ST_MakePoint(i * 0.001, 0), 4326) "
            f"FROM generate_series(1, {n}) AS i"
        )
    )
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POINT",
        feature_count=n,
    )


async def _create_point_dataset_at(
    session: AsyncSession, *, created_by: uuid.UUID, lon: float, lat: float
):
    """Create a one-row point dataset at an explicit longitude/latitude.

    fix(#697): every other fixture in this suite sits at low latitude and low
    longitude, which is why antimeridian output went unnoticed. Callers pass the
    seam and high-latitude coordinates the analysis operations have to survive.
    """
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  geom geometry(Point, 4326),"
            f"  geom_4326 geometry(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, geom, geom_4326) VALUES "  # noqa: S608
            f"('p', ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),"
            f"      ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))"
        ).bindparams(lon=lon, lat=lat)
    )
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POINT",
        feature_count=1,
    )


async def _create_mask_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    wkt: str,
    visibility: str = "public",
    extra_wkts: tuple[str, ...] = (),
):
    """Create a small polygon dataset usable as a clip-by-layer mask."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  geom geometry(Polygon, 4326),"
            f"  geom_4326 geometry(Polygon, 4326)"
            f")"
        )
    )
    for row_wkt in (wkt, *extra_wkts):
        await session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "
                f"(ST_GeomFromText('{row_wkt}', 4326),"
                f" ST_GeomFromText('{row_wkt}', 4326))"
            )
        )
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POLYGON",
        feature_count=1 + len(extra_wkts),
        visibility=visibility,
    )


def _preview_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/preview/"


# ---------------------------------------------------------------------------
# Endpoint tests
# ---------------------------------------------------------------------------


class TestAnalysisPreviewEndpoint:
    async def test_preview_releases_request_session_before_sandbox_query(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """fix(#716): a preview must cost ONE pool connection, not two.

        `execute_safe` opens its own connection (it needs READ ONLY + SET LOCAL
        ROLE, which it cannot get on the caller's session). If the handler still
        holds the request session's connection when that happens, each in-flight
        preview pins two of the pool's 13 slots, and ~7 concurrent previews
        stall every endpoint on the worker for the 30s pool_timeout.

        Asserts on `in_transaction()` rather than `pool.checkedout()`: the test
        engine uses NullPool, so checkout counts here say nothing about the
        production QueuePool. An open transaction is what pins the connection,
        so it is the pool-independent form of the same invariant.
        """
        from app.modules.catalog.datasets.domain import service_analysis

        seen: list[bool] = []
        real = service_analysis.execute_safe

        async def _recording_execute_safe(db, sql, **kwargs):
            seen.append(db.in_transaction())
            return await real(db, sql, **kwargs)

        monkeypatch.setattr(service_analysis, "execute_safe", _recording_execute_safe)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer", "distance_meters": 1000},
            headers=admin_auth_header,
        )

        assert resp.status_code == 200, resp.text
        assert seen, "execute_safe was never called"
        assert seen[0] is False, (
            "the request session was still in a transaction when the sandbox "
            "query started, so it was holding a second pooled connection; "
            "release it before calling execute_safe"
        )
        # The release expires the ORM objects, so the response must still carry
        # source_feature_count — it has to be read off the Dataset beforehand.
        assert resp.json()["source_feature_count"] == 2

    async def test_preview_does_not_release_the_session_by_default(
        self,
        test_db_session: AsyncSession,
    ):
        """fix(#716 review): the release must stay OPT-IN.

        The rollback that returns the connection expires EVERY ORM instance on
        the session, not just `dataset` — including the authenticated User.
        A caller that reads `user.id` afterwards (both AI-chat paths do) would
        get a sync refresh on an expired instance and raise MissingGreenlet.
        So the default must leave the session alone, and callers opt in only
        when they own it and need nothing from it after.
        """
        from app.modules.catalog.datasets.domain.schemas import AnalysisPreviewRequest
        from app.modules.catalog.datasets.domain.service import run_analysis_preview
        from app.modules.auth.models import User

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        user = await test_db_session.get(User, admin_id)
        assert user is not None

        await run_analysis_preview(
            test_db_session,
            ds,
            AnalysisPreviewRequest(operation="centroid"),
            admin_id,
        )

        # Would raise MissingGreenlet if the session had been rolled back.
        assert user.id == admin_id
        assert user.username is not None

    async def test_buffer_preview(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer", "distance_meters": 1000},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 2
        assert data["truncated"] is False
        fc = data["geojson"]
        assert fc["type"] == "FeatureCollection"
        assert len(fc["features"]) == 2
        for feature in fc["features"]:
            assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
            assert "gid" in feature["properties"]
        # A 1km buffer extends past the unit square's origin corner.
        assert data["bbox"][0] < 0

    async def test_centroid_preview(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 2
        types = {f["geometry"]["type"] for f in data["geojson"]["features"]}
        assert types == {"Point"}
        # Centroid of the unit square is (0.5, 0.5).
        first = data["geojson"]["features"][0]["geometry"]["coordinates"]
        assert first == pytest.approx([0.5, 0.5])

    async def test_clip_preview(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask": CLIP_MASK},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # Only the near square intersects the mask.
        assert data["feature_count"] == 1
        bbox = data["bbox"]
        assert bbox == pytest.approx([0.0, 0.0, 0.5, 0.5])

    async def test_buffer_requires_distance(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_buffer_distance_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer", "distance_meters": 200_000},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_clip_rejects_non_polygon_mask(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "clip",
                "mask": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_clip_rejects_malformed_mask(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "clip",
                "mask": {"type": "Polygon", "coordinates": "'; DROP TABLE x; --"},
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_requires_auth(
        self,
        client: AsyncClient,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
        )
        assert resp.status_code == 401

    async def test_private_dataset_hidden_from_other_user(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """IDOR guard: a private dataset 404s for a non-owner."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(
            test_db_session, created_by=admin_id, visibility="private"
        )
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 404

    async def test_non_vector_dataset_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type=None,
        )
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_truncation_at_feature_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_point_dataset(test_db_session, created_by=admin_id, n=501)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 500
        assert data["truncated"] is True
        # 1:1 op — the source total rides along so clients can say "500 of N".
        assert data["source_feature_count"] == 501

    async def test_nan_mask_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """NaN parses as JSON and as shapely coords — must 422, not 500."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            content=(
                '{"operation": "clip", "mask": {"type": "Polygon", "coordinates":'
                " [[[0, 0], [10, 0], [NaN, 10], [0, 10], [0, 0]]]}}"
            ),
            headers={**admin_auth_header, "Content-Type": "application/json"},
        )
        assert resp.status_code == 422, resp.text

    async def test_empty_mask_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """An empty ring used to be a silent no-op reading as 'matched nothing'."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask": {"type": "Polygon", "coordinates": []}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422

    async def test_self_intersecting_mask_repaired(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A bowtie mask goes through shapely.make_valid rather than erroring."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        bowtie = {
            "type": "Polygon",
            "coordinates": [[[-1, -1], [2, 2], [2, -1], [-1, 2], [-1, -1]]],
        }
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask": bowtie},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["feature_count"] >= 1

    async def test_grazing_clip_yields_no_features(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A mask sharing only an edge intersects at a lower dimension — the
        output must be empty, not a LineString smuggled into a polygon result."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        grazing = {
            "type": "Polygon",
            "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]],
        }
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask": grazing},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 0
        assert data["geojson"]["features"] == []

    async def test_centroid_ignores_stray_distance(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """distance_meters is documented as buffer-only; out-of-range values on
        other operations must not 422 (SDK/CLI callers send placeholders)."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        for stray in (0, -5, 999_999):
            resp = await client.post(
                _preview_url(ds.id),
                json={"operation": "centroid", "distance_meters": stray},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, (stray, resp.text)

    async def test_buffer_ignores_stray_mask_sources(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#682): mask/mask_dataset_id are clip-only; a stray (even
        nonexistent) mask dataset riding along on a buffer request must not
        be loaded, let alone 404 the whole call."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "buffer",
                "distance_meters": 100,
                "mask": CLIP_MASK,
                "mask_dataset_id": str(uuid.uuid4()),
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["feature_count"] == 2

    async def test_grazing_rows_do_not_consume_preview_cap(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#680 review): 550 low-gid rows only graze the mask boundary
        (they pass ST_Intersects but extract to EMPTY). The empties must be
        filtered inside the SQL row cap, or they exhaust the 500-row preview
        budget and hide the one real intersection at gid 551."""
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(Polygon, 4326),"
                f"  geom_4326 geometry(Polygon, 4326)"
                f")"
            )
        )
        # Grazers share the mask's right edge (x = 0.5) from outside.
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) "
                f"SELECT ST_MakeEnvelope(0.5, -0.4, 1.5, 0.4, 4326),"
                f"       ST_MakeEnvelope(0.5, -0.4, 1.5, 0.4, 4326) "
                f"FROM generate_series(1, 550)"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "
                f"(ST_MakeEnvelope(0, 0, 0.3, 0.3, 4326),"
                f" ST_MakeEnvelope(0, 0, 0.3, 0.3, 4326))"
            )
        )
        await test_db_session.commit()
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="POLYGON",
            feature_count=551,
        )
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask": CLIP_MASK},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 1
        assert data["truncated"] is False

    async def test_invalid_source_geometry_repaired(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """One self-intersecting source row used to abort every clip as a 500."""
        admin_id = await get_user_id(test_db_session, "admin")
        table_name = f"ds_{uuid.uuid4().hex[:12]}"
        bowtie = "POLYGON((0 0, 1 1, 1 0, 0 1, 0 0))"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table_name} ("
                f"  gid SERIAL PRIMARY KEY,"
                f"  geom geometry(Polygon, 4326),"
                f"  geom_4326 geometry(Polygon, 4326)"
                f")"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "
                f"(ST_GeomFromText('{bowtie}', 4326),"
                f" ST_GeomFromText('{bowtie}', 4326))"
            )
        )
        await test_db_session.commit()
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            table_name=table_name,
            geometry_type="POLYGON",
            feature_count=1,
        )
        covering = {
            "type": "Polygon",
            "coordinates": [[[-1, -1], [2, -1], [2, 2], [-1, 2], [-1, -1]]],
        }
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask": covering},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["feature_count"] == 1

    async def test_source_feature_count_none_for_clip(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """clip filters rows, so the source total would be a lie — omit it."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask": CLIP_MASK},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_feature_count"] is None

    async def test_clip_by_layer_preview(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Clip against another dataset's unioned geometries via mask_dataset_id."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        # Mask layer overlapping only SQUARE's lower-left quarter (same
        # geometry as CLIP_MASK, but sourced from a table).
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
        )
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask_dataset_id": str(mask_ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 1
        assert data["bbox"] == pytest.approx([0.0, 0.0, 0.5, 0.5])

    async def test_clip_by_layer_overlapping_mask_rows(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#693): the preview semi-joins the mask per row instead of
        unioning the layer per request; two OVERLAPPING mask rows must still
        yield one merged feature per source row (intersection distributes
        over union), not duplicates or double-counted slivers."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        # Together the two rows cover SQUARE's lower-left quarter, same as
        # CLIP_MASK — but split into overlapping halves (both cover
        # x in [0.1, 0.25]).
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-0.5 -0.5, -0.5 0.5, 0.25 0.5, 0.25 -0.5, -0.5 -0.5))",
            extra_wkts=("POLYGON((0.1 -0.5, 0.1 0.5, 0.5 0.5, 0.5 -0.5, 0.1 -0.5))",),
        )
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask_dataset_id": str(mask_ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 1
        assert data["bbox"] == pytest.approx([0.0, 0.0, 0.5, 0.5])
        # The overlapping pieces union into one clean polygon.
        geometry = data["geojson"]["features"][0]["geometry"]
        assert geometry["type"] == "Polygon"

    async def test_oversized_mask_layer_rejected(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#693): the materialize path unions the mask layer whole and
        the preview subdivides every mask row per request — gate on the
        cached feature_count when the mask dataset loads."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        mask_ds = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))",
        )
        mask_ds.feature_count = 1_001
        await test_db_session.commit()

        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask_dataset_id": str(mask_ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "mask layer has too many features" in resp.json()["detail"].lower()

        # At the cap it still runs.
        mask_ds.feature_count = 1_000
        await test_db_session.commit()
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask_dataset_id": str(mask_ds.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text

    async def test_clip_by_layer_mask_access_checked(
        self,
        client: AsyncClient,
        viewer_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Rule 1 applies to the MASK dataset too: a private mask layer of
        another user 404s even when the source dataset is readable."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        private_mask = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((-1 -1, -1 1, 1 1, 1 -1, -1 -1))",
            visibility="private",
        )
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask_dataset_id": str(private_mask.id)},
            headers=viewer_auth_header,
        )
        assert resp.status_code == 404

    async def test_clip_by_layer_requires_polygonal_mask(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        points = await _create_point_dataset(test_db_session, created_by=admin_id, n=3)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask_dataset_id": str(points.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422
        assert "polygon dataset" in resp.json()["detail"]

    async def test_degenerate_mask_row_stays_polygonal(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#682): ST_MakeValid collapses a zero-area mask polygon to
        LINESTRING(0 0, 0.002 0); without polygon extraction in the mask
        union, the point source at (0.001, 0) sits on that line and would
        survive the clip despite being outside every real polygon."""
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_point_dataset(test_db_session, created_by=admin_id, n=1)
        degenerate = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            wkt="POLYGON((0 0, 0.002 0, 0.002 0, 0 0))",
        )
        resp = await client.post(
            _preview_url(points.id),
            json={"operation": "clip", "mask_dataset_id": str(degenerate.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["feature_count"] == 0

    async def test_clip_rejects_both_mask_sources(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "clip",
                "mask": CLIP_MASK,
                "mask_dataset_id": str(uuid.uuid4()),
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Pure SQL-builder tests (no DB)
# ---------------------------------------------------------------------------


class TestBuildPreviewSql:
    def test_buffer_sql(self):
        req = AnalysisPreviewRequest(operation="buffer", distance_meters=500)
        sql = build_preview_sql('"data"."t1"', req)
        assert "ST_Buffer(ST_MakeValid(geom_4326)::geography, 500.0)::geometry" in sql
        assert 'FROM "data"."t1"' in sql
        assert "ORDER BY gid" in sql

    def test_buffer_sql_is_dateline_safe(self):
        """fix(#697): buffer output must go through the ±180 split, and only
        buffer — clip and dissolve cannot introduce a wrap the source lacked,
        and adding the guard there would be dead cost on every row."""
        from app.platform.analysis_sql import render_geometry_expr

        buffer_expr, _ = render_geometry_expr("buffer", distance_meters=500)
        # The guard needs BOTH conditions: a wide planar span alone also
        # describes a pole-encircling geometry, which must be left alone.
        assert "ST_XMax(_dl.g) - ST_XMin(_dl.g) > 180" in buffer_expr
        assert (
            "ST_XMax(_dl.s) - ST_XMin(_dl.s) < ST_XMax(_dl.g) - ST_XMin(_dl.g)"
            in buffer_expr
        )
        assert "ST_WrapX(ST_MakeValid(_dl.s), 180, -360)" in buffer_expr
        # ST_ShiftLongitude must run BEFORE ST_MakeValid: validating the
        # wrapped ring first nodes the seam into slivers.
        assert "ST_MakeValid(ST_ShiftLongitude" not in buffer_expr
        # Both the buffer and the shifted copy stay behind an OFFSET 0 fence,
        # so neither is re-evaluated per CASE reference (fix(#700 review)).
        assert buffer_expr.count("ST_Buffer(") == 1
        assert buffer_expr.count("ST_ShiftLongitude(") == 1
        assert buffer_expr.count("OFFSET 0") == 2

        for op, kwargs in (
            ("centroid", {}),
            ("clip", {"mask": CLIP_MASK}),
        ):
            other_expr, _ = render_geometry_expr(op, **kwargs)
            assert "ST_ShiftLongitude" not in other_expr

    def test_centroid_sql(self):
        req = AnalysisPreviewRequest(operation="centroid")
        sql = build_preview_sql('"data"."t1"', req)
        assert "ST_Centroid(ST_MakeValid(geom_4326))" in sql

    def test_buffer_distance_revalidated_at_sql_layer(self):
        """The renderer enforces MAX_BUFFER_METERS itself — worker payloads
        must not depend solely on the API schema's bounds."""
        from app.platform.analysis_sql import render_geometry_expr

        for bad in (0, -1, 200_000, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                render_geometry_expr("buffer", distance_meters=bad)
        # The documented cap itself is inclusive.
        expr, _ = render_geometry_expr("buffer", distance_meters=100_000)
        assert "100000" in expr

    def test_clip_mask_is_reserialized(self):
        req = AnalysisPreviewRequest(operation="clip", mask=CLIP_MASK)
        sql = build_preview_sql('"data"."t1"', req)
        assert "ST_GeomFromGeoJSON" in sql
        assert "ST_Intersects" in sql
        # The mask appears three times (expression + bbox && term + WHERE
        # ST_Intersects); each embed contributes exactly its two wrapping
        # quotes — shapely re-serialization guarantees no quote characters
        # inside the JSON itself.
        assert sql.count("'") == 6

    def test_preview_sql_evaluates_expression_once_per_row(self):
        """fix(#700 review): the geometry expression lives in a LATERAL
        subquery (OFFSET 0 blocks pull-up), so the three geom_out references
        don't triple-evaluate it — while the base table stays a plain FROM
        item whose pkey index can satisfy ORDER BY and early-terminate at
        the sandbox row cap."""
        cases = {
            "ST_Intersection": AnalysisPreviewRequest(operation="clip", mask=CLIP_MASK),
            "ST_Buffer": AnalysisPreviewRequest(operation="buffer", distance_meters=10),
            "ST_Centroid": AnalysisPreviewRequest(operation="centroid"),
        }
        for fn, req in cases.items():
            sql = build_preview_sql('"data"."t1"', req)
            assert "CROSS JOIN LATERAL (SELECT" in sql
            assert "OFFSET 0" in sql
            assert sql.count(fn) == 1
            assert sql.endswith("ORDER BY gid")

    def test_clip_by_layer_sql_subdivides_instead_of_unioning(self):
        """fix(#693): a layer-sourced clip preview must not union the whole
        mask layer per request — that shape made realistic masks time out
        inside the 10s sandbox budget. The preview subdivides the mask into
        bounded pieces once per statement, joins the pieces per source row,
        and row-filters via an EXISTS probe of the raw (GIST-indexed) mask
        table; the whole-layer union remains materialize-only."""
        req = AnalysisPreviewRequest(operation="clip", mask_dataset_id=uuid.uuid4())
        sql = build_preview_sql('"data"."t1"', req, '"data"."m1"')
        assert "ST_Subdivide" in sql
        assert "AS MATERIALIZED" in sql
        # The layer union shape must be gone...
        assert "ST_Union(ST_CollectionExtract(ST_MakeValid" not in sql
        # ...replaced by one per-row aggregate over the intersected pieces:
        # one output row per gid however many mask rows intersect it.
        assert sql.count("ST_Union") == 1
        assert sql.count("ST_Intersection") == 1
        # Mask table referenced twice: the pieces CTE and the EXISTS probe.
        assert sql.count('"data"."m1"') == 2
        assert "EXISTS" in sql
        assert "CROSS JOIN LATERAL" in sql
        assert sql.endswith("ORDER BY gid")

    def test_clip_mask_injection_rejected(self):
        req = AnalysisPreviewRequest(
            operation="clip",
            mask={"type": "Polygon", "coordinates": "'; DROP TABLE x; --"},
        )
        with pytest.raises(ValueError):
            build_preview_sql('"data"."t1"', req)

    def test_clip_mask_vertex_cap(self):
        ring = [
            [
                math.cos(i * 2 * math.pi / 6000) * 0.01,
                math.sin(i * 2 * math.pi / 6000) * 0.01,
            ]
            for i in range(6000)
        ]
        ring.append(ring[0])
        req = AnalysisPreviewRequest(
            operation="clip", mask={"type": "Polygon", "coordinates": [ring]}
        )
        with pytest.raises(ValueError, match="vertices"):
            build_preview_sql('"data"."t1"', req)

    def test_materialize_request_drops_other_operations_params(self):
        """fix(#682): the defer builds worker kwargs from the parsed model, so
        stray clip/dissolve params on a buffer request must parse to None or
        the worker would resolve a mask dataset the operation never uses."""
        from app.modules.catalog.datasets.domain.schemas import (
            AnalysisMaterializeRequest,
        )

        req = AnalysisMaterializeRequest.model_validate(
            {
                "operation": "buffer",
                "title": "t",
                "distance_meters": 100,
                "mask": CLIP_MASK,
                "mask_dataset_id": str(uuid.uuid4()),
                "by_field": "name",
            }
        )
        assert req.mask is None
        assert req.mask_dataset_id is None
        assert req.by_field is None
        assert req.distance_meters == 100
