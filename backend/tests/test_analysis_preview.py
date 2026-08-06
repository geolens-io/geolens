"""Tests for the parameterized PostGIS analysis preview endpoint (M4).

Exercises /datasets/{id}/analysis/preview/ plus the pure SQL builder.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import math
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.api import router_analysis
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.datasets.domain.schemas import AnalysisPreviewRequest
from app.modules.catalog.datasets.domain.service import build_preview_sql
from app.platform.sandbox.schemas import SandboxError

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


async def _create_wkt_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    wkt: str,
    column_type: str,
    geometry_type: str,
):
    """Create a one-row dataset holding exactly ``wkt``.

    fix(#697): every other fixture in this suite sits at low latitude and low
    longitude, which is why antimeridian output went unnoticed. Callers pass the
    seam and high-latitude coordinates the analysis operations have to survive.
    ``column_type`` is the PostGIS typmod (``Point`` / ``MultiPoint`` / ...) and
    ``geometry_type`` the catalog's uppercase classification.
    """
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  name TEXT,"
            f"  geom geometry({column_type}, 4326),"
            f"  geom_4326 geometry({column_type}, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (name, geom, geom_4326) VALUES "  # noqa: S608
            f"('p', ST_SetSRID(ST_GeomFromText(:wkt), 4326),"
            f"      ST_SetSRID(ST_GeomFromText(:wkt), 4326))"
        ).bindparams(wkt=wkt)
    )
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type=geometry_type,
        feature_count=1,
    )


async def _create_point_dataset_at(
    session: AsyncSession, *, created_by: uuid.UUID, lon: float, lat: float
):
    """Create a one-row point dataset at an explicit longitude/latitude."""
    return await _create_wkt_dataset(
        session,
        created_by=created_by,
        wkt=f"POINT({lon} {lat})",
        column_type="Point",
        geometry_type="POINT",
    )


async def _create_empty_dataset(session: AsyncSession, *, created_by: uuid.UUID):
    """Create a real, correctly shaped data table holding zero rows.

    fix(#699): distinct from an empty *result* — the table and its catalog rows
    exist and the operation is legal, there is simply nothing to operate on.
    """
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
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POLYGON",
        feature_count=0,
    )


async def _create_raster_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    is_dem: bool = True,
    visibility: str = "public",
):
    """Create a real raster record: Record + Dataset + RasterAsset.

    fix(#699): the analysis suite rejected non-vector sources only through a
    synthetic ``geometry_type=None`` dataset, which is a shape no ingest path
    produces. This is the row shape ``tasks_raster._register_raster`` actually
    writes — ``record_type='raster_dataset'``, a ``raster_``-prefixed
    ``table_name`` backed by no physical table, ``source_format='geotiff'``,
    and a RasterAsset carrying ``is_dem``.
    """
    from app.processing.raster.models import RasterAsset

    record = Record(
        title=f"Raster {uuid.uuid4().hex[:6]}",
        record_type="raster_dataset",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        theme_category=["test"],
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"raster_{record.id.hex[:16]}",
        source_format="geotiff",
        source_filename="elevation.tif",
        srid=3857,
    )
    session.add(dataset)
    await session.flush()
    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/cog.tif",
            storage_backend="local",
            driver="GTiff",
            band_count=1,
            dtype="float32",
            is_dem=is_dem,
        )
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


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


class TestPreviewGlobalBound:
    """fix(#1014): previews are bounded globally, not only per user."""

    def test_bound_is_sized_from_the_configured_pool(self, monkeypatch):
        """fix(#1014 review): the bound must track DB_POOL_SIZE/DB_MAX_OVERFLOW.

        A hardcoded 4 against the supported small-pool configuration
        (DB_POOL_SIZE=2, DB_MAX_OVERFLOW=0) would admit twice as many previews
        as there are connections — the exact failure the bound exists to
        prevent, at a different scale.
        """
        from app.core.config import settings
        from app.modules.catalog.datasets.domain import service_analysis

        # Default pool: 10 + 3 = 13 slots, a quarter of which is 3. A quarter
        # rather than a third because the AI chat path cannot release its
        # request session, so those previews cost two slots each.
        monkeypatch.setattr(settings, "db_pool_size", 10)
        monkeypatch.setattr(settings, "db_max_overflow", 3)
        assert service_analysis._preview_bound() == 3

        monkeypatch.setattr(settings, "db_pool_size", 2)
        monkeypatch.setattr(settings, "db_max_overflow", 0)
        assert service_analysis._preview_bound() == 1

        # -1 means "unlimited overflow"; it must not shrink the budget.
        monkeypatch.setattr(settings, "db_pool_size", 8)
        monkeypatch.setattr(settings, "db_max_overflow", -1)
        assert service_analysis._preview_bound() == 2

        # Never zero — a semaphore of zero would refuse every preview.
        monkeypatch.setattr(settings, "db_pool_size", 1)
        monkeypatch.setattr(settings, "db_max_overflow", 0)
        assert service_analysis._preview_bound() == 1

        # With an external pooler the engine uses NullPool, so DB_POOL_SIZE and
        # DB_MAX_OVERFLOW are ignored and deriving from them would be
        # arithmetic on numbers that no longer mean anything.
        monkeypatch.setattr(settings, "db_use_external_pooler", True)
        assert service_analysis._preview_bound() == 3
        monkeypatch.setattr(settings, "db_pool_size", 400)
        monkeypatch.setattr(settings, "db_max_overflow", 400)
        assert service_analysis._preview_bound() == 3

    async def test_previews_never_exceed_the_global_bound(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """More concurrent previews than slots must fail cleanly, not pile onto
        the pool.

        Asserts the PEAK number of previews simultaneously inside execute_safe,
        not pool checkout counts: the test engine uses NullPool, so checkout
        numbers here say nothing about the production QueuePool (the same
        reason test_preview_releases_request_session_before_sandbox_query
        asserts on in_transaction()). The peak is the pool-independent form of
        the same invariant — it is exactly what determines how many pool slots
        previews can hold at once.

        execute_safe is replaced, so its per-user advisory lock never runs and
        one user can stand in for many. That is the point: the per-user lock is
        not what is under test.
        """
        import asyncio

        from app.modules.catalog.datasets.domain import service_analysis

        bound = service_analysis._MAX_CONCURRENT_PREVIEWS
        gate = asyncio.Event()
        inside = 0
        peak = 0
        real = service_analysis.execute_safe

        async def _parked_execute_safe(db, sql, **kwargs):
            nonlocal inside, peak
            inside += 1
            peak = max(peak, inside)
            try:
                await gate.wait()
                return await real(db, sql, **kwargs)
            finally:
                inside -= 1

        monkeypatch.setattr(service_analysis, "execute_safe", _parked_execute_safe)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)

        tasks = [
            asyncio.create_task(
                client.post(
                    _preview_url(ds.id),
                    json={"operation": "buffer", "distance_meters": 1000},
                    headers=admin_auth_header,
                )
            )
            for _ in range(bound * 2)
        ]
        # Wait until EVERY request has reached the bound, then open the gate.
        # A request that got a slot is parked (counted by `inside`); one that
        # was refused has already returned its 429 and its task is done. Any
        # weaker wait is flaky: each request first authenticates, loads the
        # dataset and checks quota, and those are DB round-trips of unbounded
        # duration, so a fixed number of event-loop turns released the gate
        # early and late arrivals were refused by the per-user lock instead of
        # by the bound. Nothing can drain a slot before the gate opens, so once
        # this holds the split is fixed.
        for _ in range(2000):
            settled = inside + sum(1 for t in tasks if t.done())
            if settled >= len(tasks):
                break
            await asyncio.sleep(0.01)
        assert inside + sum(1 for t in tasks if t.done()) == len(tasks), (
            f"only {inside} parked and "
            f"{sum(1 for t in tasks if t.done())} returned, of {len(tasks)}"
        )
        assert inside == bound, f"{inside} previews hold slots, expected {bound}"
        gate.set()
        responses = await asyncio.gather(*tasks)

        assert peak <= bound, (
            f"{peak} previews were inside the sandbox at once against a bound of "
            f"{bound} — previews can still exhaust the connection pool"
        )
        details = [r.json()["detail"] for r in responses if r.status_code == 429]
        # The refusals split by CAUSE, and the split is the point. Half never
        # got a slot and were refused by the global bound; the rest are the
        # per-user advisory lock inside the real execute_safe, which the gate
        # releases them into all at once — an artifact of one user standing in
        # for many, and proof the two refusals are distinguishable rather than
        # one message doing double duty. Telling a user "you already have one
        # running" when this is their first request would be a misleading
        # explanation, which is why the bound has its own message.
        at_capacity = [d for d in details if "maximum number of analysis previews" in d]
        assert len(at_capacity) == bound, (
            f"expected {bound} previews refused by the global bound, got "
            f"{len(at_capacity)} of {len(details)} refusals: {details}"
        )
        assert all("already running for this user" not in d for d in at_capacity)
        assert all(r.status_code in (200, 429) for r in responses), [
            r.status_code for r in responses
        ]

    async def test_the_exact_count_query_holds_a_slot_too(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """fix(#1097 review): the second sandbox query counts against the bound.

        Operations that report an exact total run TWO sandbox statements, each
        opening its own connection. The count used to run after the semaphore
        was released, so a preview could admit the next caller while still
        holding a connection — the bound would stop describing how many
        connections previews can hold, which is the only reason it exists.

        The count is the likelier of the two to still be running when the
        geometry query returns: it is uncapped and scans both inputs, while the
        geometry query stops at PREVIEW_FEATURE_CAP rows.

        Asserted through `.locked()` against a one-slot semaphore rather than
        by counting: locked() is unambiguous at a bound of one, and the bound
        is what is under test, not the arithmetic that sizes it.
        """
        import asyncio

        from app.modules.catalog.datasets.domain import service_analysis

        monkeypatch.setattr(service_analysis, "_preview_slots", asyncio.Semaphore(1))
        real = service_analysis.execute_safe
        held: list[bool] = []

        async def _recording_execute_safe(db, sql, **kwargs):
            held.append(service_analysis._preview_slots.locked())
            return await real(db, sql, **kwargs)

        monkeypatch.setattr(service_analysis, "execute_safe", _recording_execute_safe)

        admin_id = await get_user_id(test_db_session, "admin")
        src = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        mask = await _create_mask_dataset(
            test_db_session, created_by=admin_id, wkt=SQUARE
        )

        resp = await client.post(
            _preview_url(src.id),
            json={
                "operation": "select_by_location",
                "mask_dataset_id": str(mask.id),
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        # The exact total is what makes this a two-statement operation; without
        # it the test would pass on a single query and prove nothing.
        assert resp.json()["match_count"] == 1

        assert len(held) == 2, (
            f"expected a geometry query and a count query, saw {len(held)}"
        )
        assert held == [True, True], (
            "a sandbox query ran outside the preview semaphore: previews can "
            "hold more connections than the bound allows"
        )


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

    @pytest.mark.parametrize(
        ("category", "expected_status"),
        [
            # The routine one: the sandbox advisory lock is shared with AI chat,
            # so a preview fired while a chat query holds it must read as
            # "try again", not as a server fault.
            ("query_busy", 429),
            # fix(#789): #1014 added a second 429 category after this test
            # landed covering only four. Server-at-capacity is deliberately
            # distinct from query_busy so the message is not relabelled as the
            # per-user one — same status, different text, so the pair only
            # stays honest if both are exercised.
            ("query_at_capacity", 429),
            ("query_timeout", 422),
            ("query_data_error", 422),
            # Anything unmapped falls through the .get default. query_failed
            # also covers connection loss and role-binding failures, which are
            # server faults rather than bad requests.
            ("query_failed", 500),
        ],
    )
    async def test_sandbox_error_category_maps_to_status(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        category: str,
        expected_status: int,
    ):
        """fix(#789): _SANDBOX_STATUS is the only thing standing between a
        sandbox failure category and the status the caller sees, and it was
        untested — tests/test_sandbox.py asserts the category the sandbox
        raises, not what the route does with it.

        Patches the name `router_analysis` imported, not the definition in
        service_analysis, the way the suite already patches the queue hop.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        message = f"sandbox says: {category}"
        with patch.object(
            router_analysis,
            "run_analysis_preview",
            AsyncMock(side_effect=SandboxError(category, message)),
        ):
            resp = await client.post(
                _preview_url(ds.id),
                json={"operation": "centroid"},
                headers=admin_auth_header,
            )
        assert resp.status_code == expected_status, resp.text
        # user_message is the sandbox's already-sanitized text, so it is what
        # the caller reads on every branch including the 500 fallback.
        assert resp.json()["detail"] == message

    def test_every_sandbox_status_category_is_parametrized(self):
        """fix(#789): the parametrize above is a hand-kept list, so #1014's new
        category joined the mapping and simply went untested — four of five,
        still green. Pin the mapping's key set: adding a category now fails
        here until it is given a case above."""
        assert set(router_analysis._SANDBOX_STATUS) == {
            "query_busy",
            "query_at_capacity",
            "query_timeout",
            "query_data_error",
        }

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

    async def test_source_feature_count_none_for_clip_with_bbox(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Denominator case 3 (fix(#727)): clip stays null WITH a bbox too —
        a row-filtering operation's total is unknowable from the source count
        whether or not the preview is viewport-scoped."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "clip",
                "mask": CLIP_MASK,
                "bbox": [-10.0, -10.0, 10.0, 10.0],
            },
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


class TestBboxScopedPreview:
    """Live-DB behavior for a viewport-scoped preview (fix(#727)): the row
    filter actually restricts which rows the cap sees, the 1:1 denominator
    switches from the cached snapshot to a live bbox-scoped count, and the
    live count runs before the connection-releasing rollback."""

    async def test_bbox_filters_preview_to_the_viewport(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The concrete bug: an unscoped preview over a spread-out dataset
        returns the first PREVIEW_FEATURE_CAP rows in gid order, which here
        are ALL west of x=0. Scoping to a viewport east of x=0 must return
        points from THAT extent instead — proof the filter runs before the
        cap, not merely that it is syntactically present in the SQL."""
        admin_id = await get_user_id(test_db_session, "admin")
        # 900 points along the equator, x = (gid - 1) * 0.002 - 1.1: x(500) is
        # -0.102 (comfortably < 0) and x(900) is 0.698, so the full dataset
        # spans past x=0 while an unscoped 500-row cap in gid order does not.
        ds = await _create_point_dataset(test_db_session, created_by=admin_id, n=900)
        table_name = ds.table_name
        await test_db_session.execute(
            text(
                f"UPDATE data.{table_name} SET "
                "geom = ST_SetSRID(ST_MakePoint((gid - 1) * 0.002 - 1.1, 0), 4326),"
                "geom_4326 = ST_SetSRID(ST_MakePoint((gid - 1) * 0.002 - 1.1, 0), 4326)"
            )
        )
        await test_db_session.commit()

        unscoped = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert unscoped.status_code == 200, unscoped.text
        unscoped_xs = [
            f["geometry"]["coordinates"][0]
            for f in unscoped.json()["geojson"]["features"]
        ]
        assert unscoped_xs and max(unscoped_xs) < 0, (
            "fixture assumption broken: the unscoped cap was expected to stay "
            "entirely west of x=0 in gid order"
        )

        scoped = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid", "bbox": [0.0, -1.0, 0.5, 1.0]},
            headers=admin_auth_header,
        )
        assert scoped.status_code == 200, scoped.text
        scoped_features = scoped.json()["geojson"]["features"]
        assert scoped_features
        scoped_xs = [f["geometry"]["coordinates"][0] for f in scoped_features]
        # Small tolerance for float round-trip through PostGIS/GeoJSON, not a
        # loosening of the property under test: a point genuinely outside the
        # envelope misses by a whole 0.002 grid step, not float noise.
        assert all(-1e-6 <= x <= 0.5 + 1e-6 for x in scoped_xs), (
            "a bbox-scoped preview returned a feature outside the requested "
            f"envelope: {scoped_xs}"
        )

    async def test_source_feature_count_uses_cached_snapshot_without_bbox(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Denominator case 1: no bbox uses the CACHED dataset.feature_count,
        not a live count — proven by setting the cache to a value the live
        table cannot possibly have and asserting the response echoes the
        (wrong) cached number verbatim."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        ds.feature_count = 999_999
        await test_db_session.commit()
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer", "distance_meters": 10},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_feature_count"] == 999_999

    async def test_source_feature_count_is_live_and_bbox_scoped(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Denominator case 2: WITH a bbox, source_feature_count is a live
        count of rows intersecting the envelope, not the cached whole-table
        snapshot — even when the cache is set to a value that would make the
        cached number pass this assertion by coincidence, the live count
        (2 of 3 points fall in the queried envelope) is what comes back."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_point_dataset(test_db_session, created_by=admin_id, n=3)
        table_name = ds.table_name
        # Points at x = 0, 1, 2 (see _create_point_dataset: x = i * 0.001).
        # Rewrite to x = 0, 1, 2 exactly so a bbox can cleanly include two.
        await test_db_session.execute(
            text(
                f"UPDATE data.{table_name} SET "
                "geom = ST_SetSRID(ST_MakePoint(gid - 1, 0), 4326),"
                "geom_4326 = ST_SetSRID(ST_MakePoint(gid - 1, 0), 4326)"
            )
        )
        # Deliberately wrong cache — if this leaks through, the test would
        # only catch it by accident. It does not equal 2.
        ds.feature_count = 3
        await test_db_session.commit()

        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "buffer",
                "distance_meters": 1,
                "bbox": [-0.5, -0.5, 1.5, 0.5],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_feature_count"] == 2

    async def test_bbox_source_count_holds_a_preview_slot_too(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """fix(#727 codex P1 round 1): the bbox-scoped count runs through
        execute_safe now (not a bare db.execute before the semaphore), so it
        counts against the SAME global preview bound as the geometry query —
        otherwise N concurrent viewport-scoped previews could each hold a
        connection open for an unbounded, unmetered count query, exhausting
        the pool the semaphore exists to protect (the exact class fix(#716)/
        fix(#1014) already cover for the geometry query). Modeled on
        test_the_exact_count_query_holds_a_slot_too's `.locked()` probe
        against a one-slot semaphore."""
        import asyncio

        from app.modules.catalog.datasets.domain import service_analysis

        monkeypatch.setattr(service_analysis, "_preview_slots", asyncio.Semaphore(1))
        real = service_analysis.execute_safe
        held: list[bool] = []

        async def _recording_execute_safe(db, sql, **kwargs):
            held.append(service_analysis._preview_slots.locked())
            return await real(db, sql, **kwargs)

        monkeypatch.setattr(service_analysis, "execute_safe", _recording_execute_safe)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "buffer",
                "distance_meters": 10,
                "bbox": [-10.0, -10.0, 10.0, 10.0],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        # A bbox-scoped buffer preview is a two-statement operation now: the
        # bbox count and the geometry query. Without the count this would pass
        # trivially on a single query and prove nothing.
        assert len(held) == 2, (
            f"expected a bbox-count query and a geometry query, saw {len(held)}"
        )
        assert held == [True, True], (
            "a sandbox query ran outside the preview semaphore: previews can "
            "hold more connections than the bound allows"
        )

    async def test_bbox_source_count_degrades_to_none_on_sandbox_error(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """fix(#727 codex P2 round 1): a bbox-scoped denominator that could not
        be computed within the query budget must come back null, not a
        LIMIT-capped number dressed up as exact — the response's documented
        contract for both source_feature_count and match_count."""
        from app.modules.catalog.datasets.domain import service_analysis
        from app.platform.sandbox.schemas import SandboxError

        real = service_analysis.execute_safe
        calls = 0

        async def _fail_first_call(db, sql, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise SandboxError("query_timeout", "boom")
            return await real(db, sql, **kwargs)

        monkeypatch.setattr(service_analysis, "execute_safe", _fail_first_call)

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={
                "operation": "buffer",
                "distance_meters": 10,
                "bbox": [-10.0, -10.0, 10.0, 10.0],
            },
            headers=admin_auth_header,
        )
        # The bbox count fails; the geometry query (call 2) still succeeds —
        # a broken denominator must not take down the whole preview.
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_feature_count"] is None
        assert resp.json()["feature_count"] == 2


# ---------------------------------------------------------------------------
# Source-shape and parameter-bound edges (fix(#699))
# ---------------------------------------------------------------------------


class TestSourceShapeEdges:
    """Sources the analysis rails have to survive: a real raster record, a
    table with no rows, and a point source that keeps survivors through a
    layer mask."""

    async def test_real_raster_record_is_rejected_by_preview(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The suite's only non-vector rejection ran through a synthetic
        ``geometry_type=None`` dataset. This is the row shape raster ingest
        actually writes, DEM flag and all."""
        admin_id = await get_user_id(test_db_session, "admin")
        raster = await _create_raster_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(raster.id),
            json={"operation": "centroid"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text
        assert "vector" in resp.json()["detail"].lower()

    async def test_real_raster_record_is_rejected_as_a_clip_mask(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The mask loader runs the same vector gate before the polygon one,
        so a DEM chosen as a mask must never reach the geometry-type check
        against a table that does not exist."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        raster = await _create_raster_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "clip", "mask_dataset_id": str(raster.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text
        assert "vector" in resp.json()["detail"].lower()

    async def test_empty_source_previews_as_zero_features(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A 0-row source is not an error on the read path — the operation is
        legal and the answer is empty. Distinct from an empty *result*, which
        fails the materialize job."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_empty_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer", "distance_meters": 100},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 0
        assert data["truncated"] is False
        assert data["geojson"]["features"] == []
        # No rows means no extent to report; a [null, null, null, null] bbox
        # would render as a jump to the origin.
        assert data["bbox"] is None

    async def test_clip_by_layer_keeps_points_inside_the_mask(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The line equivalents assert survivors; the point one only ever
        asserted the zero-survivor degenerate-mask case. Points are the
        dimension where ST_CollectionExtract takes its narrowest branch
        (ST_Dimension = 0), so a survivor case has to exist."""
        admin_id = await get_user_id(test_db_session, "admin")
        # Points sit at 0.001..0.005 along the equator.
        points = await _create_point_dataset(test_db_session, created_by=admin_id, n=5)
        mask = await _create_mask_dataset(
            test_db_session,
            created_by=admin_id,
            # Covers the first three points only.
            wkt="POLYGON((0 -1, 0 1, 0.0035 1, 0.0035 -1, 0 -1))",
        )
        resp = await client.post(
            _preview_url(points.id),
            json={"operation": "clip", "mask_dataset_id": str(mask.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["feature_count"] == 3
        assert {f["geometry"]["type"] for f in data["geojson"]["features"]} == {"Point"}
        xs = sorted(
            f["geometry"]["coordinates"][0] for f in data["geojson"]["features"]
        )
        assert xs == pytest.approx([0.001, 0.002, 0.003])


class TestPreviewParameterBounds:
    """The distance bounds are pinned at the SQL-builder and chat layers; this
    is the HTTP contract, where a client actually sends them."""

    @pytest.mark.parametrize("distance", [-1, 0, -0.0001])
    async def test_non_positive_distance_rejected_over_http(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        distance: float,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "buffer", "distance_meters": distance},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text

    @pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
    async def test_non_finite_distance_rejected_over_http(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
        token: str,
    ):
        """Pydantic's `allow_inf_nan` defaults to True, so NaN and the
        infinities parse as perfectly good floats; what stops them is that
        every comparison against NaN is False, which fails `le` (not `gt`,
        the bound the finite cases fail). Sent as bare JSON tokens, which is
        what a JS client serializing a NaN emits.

        Pinning the message keeps this honest: if `allow_inf_nan` were ever
        set False the rejection would come from parsing instead, and the
        builder's own isfinite check would stop being the second line."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            content=f'{{"operation": "buffer", "distance_meters": {token}}}',
            headers={**admin_auth_header, "content-type": "application/json"},
        )
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "distance_meters" in detail
        assert ("less than or equal" in detail) or ("greater than" in detail)


class TestBboxRequestValidation:
    """AnalysisPreviewRequest.bbox: shape, finiteness, ordering, and — the
    acceptance criterion this class exists to pin — that it is NOT owned by
    any single operation, so _drop_params_for_other_operations never strips
    it (fix(#727))."""

    def test_bbox_absent_from_analysis_param_owners(self):
        from app.modules.catalog.datasets.domain.schemas import (
            _ANALYSIS_PARAM_OWNERS,
        )

        assert "bbox" not in _ANALYSIS_PARAM_OWNERS

    def test_bbox_survives_on_a_non_buffer_operation(self):
        """The concrete regression _ANALYSIS_PARAM_OWNERS guards against:
        every OTHER per-operation field gets dropped when the operation
        doesn't own it. bbox must be the one field that never does."""
        req = AnalysisPreviewRequest(operation="centroid", bbox=[0.0, 0.0, 1.0, 1.0])
        assert req.bbox == [0.0, 0.0, 1.0, 1.0]
        # distance_meters IS operation-scoped (buffer only) — sent alongside
        # centroid it must vanish, which is the contrast that makes the bbox
        # assertion above meaningful rather than a no-op.
        req2 = AnalysisPreviewRequest.model_validate(
            {
                "operation": "centroid",
                "distance_meters": 10,
                "bbox": [0.0, 0.0, 1.0, 1.0],
            }
        )
        assert req2.distance_meters is None
        assert req2.bbox == [0.0, 0.0, 1.0, 1.0]

    def test_bbox_none_by_default(self):
        assert AnalysisPreviewRequest(operation="centroid").bbox is None

    @pytest.mark.parametrize(
        "bbox",
        [
            [0.0, 0.0, 1.0],  # too few
            [0.0, 0.0, 1.0, 1.0, 1.0],  # too many
        ],
    )
    def test_bbox_wrong_length_rejected(self, bbox):
        with pytest.raises(ValueError, match="exactly 4 coordinates"):
            AnalysisPreviewRequest(operation="centroid", bbox=bbox)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_bbox_non_finite_rejected(self, bad):
        with pytest.raises(ValueError, match="finite"):
            AnalysisPreviewRequest(operation="centroid", bbox=[bad, 0.0, 1.0, 1.0])

    def test_bbox_minx_greater_than_maxx_rejected(self):
        with pytest.raises(ValueError, match="minx is greater than maxx"):
            AnalysisPreviewRequest(operation="centroid", bbox=[2.0, 0.0, 1.0, 1.0])

    def test_bbox_miny_greater_than_maxy_rejected(self):
        with pytest.raises(ValueError, match="miny is greater than maxy"):
            AnalysisPreviewRequest(operation="centroid", bbox=[0.0, 2.0, 1.0, 1.0])

    async def test_bbox_rejected_over_http(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_polygon_dataset(test_db_session, created_by=admin_id)
        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "centroid", "bbox": [1.0, 0.0, 0.0, 1.0]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Pure SQL-builder tests (no DB)
# ---------------------------------------------------------------------------


class TestBuildPreviewSql:
    def test_buffer_sql(self):
        req = AnalysisPreviewRequest(operation="buffer", distance_meters=500)
        sql = build_preview_sql('"data"."t1"', req)
        # fix(#891): the validated source is hoisted behind an OFFSET 0 fence so
        # the projection guard can read it, so the buffer takes `_pb.g` rather
        # than the column expression.
        assert "SELECT ST_MakeValid(geom_4326) AS g OFFSET 0) AS _pb" in sql
        assert "ST_Buffer(_pb.g::geography, 500.0)::geometry" in sql
        assert 'FROM "data"."t1"' in sql
        assert "ORDER BY gid" in sql

    def test_buffer_sql_is_dateline_safe(self):
        """fix(#697): buffer output must go through the ±180 split, and only
        buffer — clip and dissolve cannot introduce a wrap the source lacked,
        and adding the guard there would be dead cost on every row."""
        from app.platform.analysis_sql import render_geometry_expr

        buffer_expr, _ = render_geometry_expr("buffer", distance_meters=500)
        # fix(#883 review): the split decision is per polygon component, not on
        # the envelope of the whole buffer — one feature can hold components at
        # both seams, which want opposite treatment.
        assert "ST_Dump" in buffer_expr
        assert "ST_CollectionHomogenize(ST_Collect(_dl_p.p))" in buffer_expr
        # The per-component guard needs BOTH conditions: a wide planar span
        # alone also describes a pole-encircling component, which must be left
        # alone.
        assert "ST_XMax(_dl_c.c) - ST_XMin(_dl_c.c) > 180" in buffer_expr
        assert (
            "ST_XMax(_dl_c.s) - ST_XMin(_dl_c.s) < ST_XMax(_dl_c.c) - ST_XMin(_dl_c.c)"
            in buffer_expr
        )
        assert "ST_WrapX(ST_MakeValid(_dl_c.s), 180, -360)" in buffer_expr
        # The envelope span still gates ENTRY to the per-component pass. It is a
        # necessary condition (the envelope contains every component), so the
        # ordinary buffer never pays for the dump/re-collect.
        assert "ST_XMax(_dl.g) - ST_XMin(_dl.g) > 180 THEN" in buffer_expr
        assert "ELSE _dl.g END" in buffer_expr
        # ST_ShiftLongitude must run BEFORE ST_MakeValid: validating the
        # wrapped ring first nodes the seam into slivers.
        assert "ST_MakeValid(ST_ShiftLongitude" not in buffer_expr
        # The buffer and each component's shifted copy stay behind an OFFSET 0
        # fence, so neither is re-evaluated per CASE reference (fix(#700
        # review)). fix(#891) adds a second projection strategy, so both the
        # buffer and the seam pass now have two rendered call sites — one per
        # branch of the projection CASE, never both on the same row. EXPLAIN
        # ANALYZE over a 2 000-row mix (285 wide multipart rows, 1 715
        # single-part) put the per-component SubPlan at loops=285 and the
        # whole-input SubPlan at loops=1715.
        assert buffer_expr.count("ST_Buffer(") == 2
        # fix(#902 codex r1-r3): beyond the two dateline-safe passes, the
        # sliced branch shifts per component (1) and per segment on the
        # jump-carrying fallback (3: the CASE tests the shifted copy twice
        # and emits it once).
        assert buffer_expr.count("ST_ShiftLongitude(") == 6
        # fix(#902): the sliced branch adds a fence for the per-component
        # unwrap of the segmentized copy.
        assert buffer_expr.count("OFFSET 0") == 6

        for op, kwargs in (
            ("centroid", {}),
            ("clip", {"mask": CLIP_MASK}),
        ):
            other_expr, _ = render_geometry_expr(op, **kwargs)
            assert "ST_ShiftLongitude" not in other_expr

    def test_buffer_sql_slices_wide_inputs_into_local_projections(self):
        """fix(#891)/fix(#902): ``ST_Buffer(...::geography, d)`` picks ONE
        planar SRID for the whole input, so anything spanning more than one UTM
        zone — a spread multipart OR a single wide component — is buffered in
        a projection local to at most part of it. The wide branch slices the
        geography-segmentized input into sub-zone longitude bands.
        """
        from app.platform.analysis_sql import (
            BUFFER_LOCAL_SRID_SPAN_DEG,
            BUFFER_SLICE_SEGMENTIZE_M,
            render_geometry_expr,
        )

        buffer_expr, _ = render_geometry_expr("buffer", distance_meters=500)
        # The guard is on the SOURCE, and on the VALIDATED source specifically
        # (ST_MakeValid can widen the effective footprint of a
        # self-intersecting POLYGON); that is what the OFFSET 0 fence pays for.
        assert "(SELECT ST_MakeValid(geom_4326) AS g OFFSET 0) AS _pb" in buffer_expr
        assert (
            f"ST_XMax(_pb.g) - ST_XMin(_pb.g) >= {BUFFER_LOCAL_SRID_SPAN_DEG}"
            in buffer_expr
        )
        # fix(#902): the ST_NumGeometries(...) > 1 half of the old gate is
        # deliberately gone — a single 90°-wide component fell to world
        # Mercator exactly like a spread multipart did.
        assert "ST_NumGeometries" not in buffer_expr
        # Edges are densified BEFORE the planar band cut: lineal components
        # along great circles (geography buffers geodesic edges — cutting the
        # bare planar chord buffered a different line, 141.7e9 m² vs the
        # 134.1e9 truth on the 90° fixture), polygonal components PLANAR-ly
        # (fix(#902 codex r4): geography-segmentizing a ring moved the region
        # itself).
        from app.platform.analysis_sql import BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG

        assert (
            f"ST_Segmentize(_pb_d0.c0::geography, {BUFFER_SLICE_SEGMENTIZE_M})"
            "::geometry" in buffer_expr
        )
        assert (
            f"ST_Segmentize(_pb_d0.c0, {BUFFER_SLICE_SEGMENTIZE_PLANAR_DEG})"
            in buffer_expr
        )
        assert "ST_Dimension(_pb_d0.c0) >= 2" in buffer_expr
        # fix(#902 codex r5): the shifted domain must win by the shared
        # longitude epsilon in BOTH the per-component and per-segment
        # unwraps, or ±360 float noise on a tied span tears a
        # Greenwich-crossing ring via the per-vertex shift.
        from app.core.geo import LON_EPSILON_DEGREES

        assert buffer_expr.count(f"- ST_XMin(_pb_u.c) - {LON_EPSILON_DEGREES}") == 1
        assert buffer_expr.count(f"- ST_XMin(_pb_e2.geom) - {LON_EPSILON_DEGREES}") == 1
        # Bands are anchored at the input's own XMin and cut a hair under the
        # zone width: at exactly 6.0° _ST_BestSRID leaves the local UTM zone.
        assert f"({BUFFER_LOCAL_SRID_SPAN_DEG} - 0.001)" in buffer_expr
        assert "generate_series" in buffer_expr
        assert "ST_Intersection(_pb_g.uc," in buffer_expr
        # fix(#902 codex r3): a component still carrying a >180-degree planar
        # segment (it crosses BOTH meridians, so no whole-component unwrap
        # exists) bypasses band slicing and buffers per segment instead.
        assert "ST_DumpSegments(_pb_g.uc)" in buffer_expr
        # Each band piece is dumped to simple parts and buffered on its own,
        # and each piece's buffer is dumped so ST_Collect never mixes POLYGON
        # with MULTIPOLYGON into a GEOMETRYCOLLECTION.
        assert "ST_Dump(ST_Buffer(_pb_c.c::geography, 500.0)::geometry)" in buffer_expr
        assert "ST_CollectionHomogenize(ST_Collect(_pb_p.p))" in buffer_expr
        # Pass order: seam split (_pb_m) INSIDE the union, never the reverse —
        # unioning a still-wrapping component raises a GEOS side-location
        # conflict and aborts the statement.
        union_at = buffer_expr.index("ST_UnaryUnion(")
        split_at = buffer_expr.index("ST_WrapX(ST_MakeValid(_pb_m_c.s)")
        assert union_at < split_at
        # The common path is a bare ELSE: the whole-input buffer, wrapped in the
        # fix(#883) seam pass and nothing else — no slicing, no re-collect, no
        # dissolve.
        else_at = buffer_expr.index("ELSE (SELECT CASE WHEN ST_XMax(_dl.g)")
        assert buffer_expr.count("ST_UnaryUnion(") == 1
        assert union_at < else_at
        assert "ST_Buffer(_pb.g::geography, 500.0)::geometry" in buffer_expr[else_at:]

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
        # fix(#891): buffer renders TWO ST_Buffer call sites — one per branch of
        # the projection CASE — and exactly one of them is reachable on any given
        # row, which EXPLAIN ANALYZE confirms (a 2 000-row mix put the
        # per-component SubPlan at loops=285 and the whole-input SubPlan at
        # loops=1715, summing to 2 000, not 4 000).
        cases = {
            "ST_Intersection": (
                AnalysisPreviewRequest(operation="clip", mask=CLIP_MASK),
                1,
            ),
            "ST_Buffer": (
                AnalysisPreviewRequest(operation="buffer", distance_meters=10),
                2,
            ),
            "ST_Centroid": (AnalysisPreviewRequest(operation="centroid"), 1),
        }
        for fn, (req, call_sites) in cases.items():
            sql = build_preview_sql('"data"."t1"', req)
            assert "CROSS JOIN LATERAL (SELECT" in sql
            assert "OFFSET 0" in sql
            assert sql.count(fn) == call_sites
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

    # -----------------------------------------------------------------------
    # bbox viewport scoping (#727)
    # -----------------------------------------------------------------------

    def test_no_bbox_reproduces_pre_727_sql_byte_for_byte(self):
        """Acceptance criterion: omitting bbox reproduces today's behaviour."""
        req_without = AnalysisPreviewRequest(operation="centroid")
        req_with_none = AnalysisPreviewRequest(operation="centroid", bbox=None)
        sql = build_preview_sql('"data"."t1"', req_without)
        assert sql == build_preview_sql('"data"."t1"', req_with_none)
        assert "ST_MakeEnvelope" not in sql
        assert sql.endswith("ORDER BY gid")

    def test_bbox_adds_indexed_prefilter_and_preserves_order_by_gid(self):
        """Acceptance criterion: only features intersecting the envelope are
        returned, and ORDER BY gid is still in the emitted SQL — the row cap's
        early-stop property is invisible to a result-only assertion, so this
        pins the SQL SHAPE directly. Centroid, not buffer: buffer's own
        dateline-safety expression nests several WHERE clauses of its own
        (see test_buffer_sql_slices_wide_inputs_into_local_projections), which
        would contaminate a bare `sql.count("WHERE")` unrelated to this test's
        claim about the OUTER predicate assembly."""
        req = AnalysisPreviewRequest(operation="centroid", bbox=[-1.0, -2.0, 3.0, 4.0])
        sql = build_preview_sql('"data"."t1"', req)
        assert "_src.geom_4326 && ST_MakeEnvelope(-1.0, -2.0, 3.0, 4.0, 4326)" in sql
        assert sql.endswith("ORDER BY gid")
        # The prefilter must land in the SAME WHERE as NOT_EMPTY_PREDICATE,
        # not a wrapping subquery — that is what keeps ORDER BY gid able to
        # ride the pkey index (fix(#700 review)).
        assert sql.count("WHERE") == 1

    def test_bbox_applies_to_clip_by_layer_and_select_by_location(self):
        """The shared WHERE composition covers every operation that flows
        through build_preview_sql's final assembly — both mask_table_ref
        branches included, not just the identity/expression branch."""
        bbox = [0.0, 0.0, 1.0, 1.0]
        for req in (
            AnalysisPreviewRequest(
                operation="clip", mask_dataset_id=uuid.uuid4(), bbox=bbox
            ),
            AnalysisPreviewRequest(
                operation="select_by_location", mask_dataset_id=uuid.uuid4(), bbox=bbox
            ),
        ):
            sql = build_preview_sql('"data"."t1"', req, '"data"."m1"')
            assert "_src.geom_4326 && ST_MakeEnvelope(0.0, 0.0, 1.0, 1.0, 4326)" in sql
            assert sql.endswith("ORDER BY gid")

    def test_bbox_threaded_into_intersect(self):
        """fix(#727 codex round 2): intersect renders through a separate
        JOIN+GROUP BY pipeline (render_intersect_preview/render_intersect_pairs)
        that does not share build_preview_sql's WHERE composition, so it needs
        its own explicit bbox plumbing — this pins that it actually receives
        one rather than silently discarding it (the frontend sends bbox for
        every operation uniformly, so a discarded bbox here would keep
        clustering intersect previews in gid order, the exact bug #727 exists
        to fix, for one operation only)."""
        req = AnalysisPreviewRequest(
            operation="intersect",
            mask_dataset_id=uuid.uuid4(),
            bbox=[0.0, 0.0, 1.0, 1.0],
        )
        sql = build_preview_sql('"data"."t1"', req, '"data"."m1"')
        assert "_src.geom_4326 && ST_MakeEnvelope(0.0, 0.0, 1.0, 1.0, 4326)" in sql
        # The filter must land on the SOURCE (_src), inside the inner subquery
        # that feeds the pair-generating join — not on the mask/overlay layer,
        # and not as an outer wrapper around the whole aggregate (which would
        # filter OUTPUT pieces instead of scoping which source rows are
        # considered, changing the shape of the row cap's early-stop rather
        # than just its size).
        assert sql.index("_src.geom_4326 && ST_MakeEnvelope") < sql.index("GROUP BY")

    def test_bbox_not_threaded_into_intersect_materialize(self):
        """fix(#727 codex round 2): render_intersect_pairs's bbox param is
        PREVIEW-ONLY. A saved dataset must be the WHOLE overlay, not whatever
        was on screen when Create dataset was clicked — the materialize
        worker's call site (processing/analysis/tasks.py) must keep omitting
        it, so this pins the DEFAULT stays unscoped rather than assuming a
        caller always passes bbox explicitly."""
        from app.platform.analysis_sql import render_intersect_pairs

        sql = render_intersect_pairs('"data"."t1"', '"data"."m1"')
        assert "ST_MakeEnvelope" not in sql

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
