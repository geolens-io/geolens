"""Migration 0041's backfill of raster_assets.crs_wkt (#1376).

The two writers of the column now ask rasterio for ``WKT2_2019``
(``processing/raster/cog.py`` for local uploads, ``catalog/sources/
cog_info.py`` for the remote probe; each is pinned in its own test file).
This file covers the OTHER half of the single-dialect claim: the rows that
were already stored when those writers still emitted WKT1_GDAL.

The round trip is real — ``alembic downgrade -1`` (0041's downgrade is a
documented no-op) followed by ``alembic upgrade head`` re-runs the backfill
over rows this test committed first, through the same alembic.ini/env.py
stack CI uses. Testing the conversion helper in isolation would prove PROJ
converts WKT, which was never in doubt; what needs proving is that the
migration's predicate SELECTS the right rows and its loop survives one it
cannot convert.

Run with: cd backend && set -a && source ../.env.test && set +a &&
          uv run pytest tests/test_crs_wkt2_backfill_1376.py -x -q
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from tests.alembic_helpers import run_alembic as _run_alembic
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio


def _enterprise_migrations_present() -> bool:
    """Mirror the sibling migration files' overlay skip: a multi-head alembic
    cannot disambiguate ``head`` / ``-1``, so the round trip runs in the
    no-overlay job."""
    import pathlib
    from importlib.metadata import entry_points

    for ep in entry_points(group="geolens.migrations"):
        try:
            fn = ep.load()
            if callable(fn) and any(pathlib.Path(p).is_dir() for p in fn()):
                return True
        except Exception:
            pass
    return False


_SKIP_UNDER_OVERLAY = pytest.mark.skipif(
    _enterprise_migrations_present(),
    reason=(
        "OSS migration round trip; multi-head under the enterprise overlay — "
        "runs in the no-overlay Pytest Parallel Isolation job instead."
    ),
)

# A real WKT1_GDAL string of the shape every pre-#1376 ingest wrote.
_WKT1_UTM_21N = (
    'PROJCS["WGS 84 / UTM zone 21N",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG","7030"]],'
    'AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]],PROJECTION["Transverse_Mercator"],'
    'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",-57],'
    'PARAMETER["scale_factor",0.9996],PARAMETER["false_easting",500000],'
    'PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AXIS["Easting",EAST],AXIS["Northing",NORTH],AUTHORITY["EPSG","32621"]]'
)

# WKT1-SHAPED but not parseable as a CRS: it matches the migration's
# predicate and must still be left exactly as stored. Truncated rather than
# invented, because PROJ is far more tolerant than it looks — a made-up
# ``LOCAL_CS["...",NONSENSE[1,2,3]]`` parses fine and converts to ``ENGCRS``,
# so only a structurally broken string reaches the skip branch. Same shape
# ``test_wkt_is_geographic.py`` uses for its unparseable case.
_WKT1_SHAPED_GARBAGE = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84"'


async def _fresh_query(query: str, params: dict | None = None):
    """Read committed state on an autocommit connection.

    The alembic subprocess commits outside the test session's transaction, so
    the session's snapshot cannot see what the migration wrote (same reason
    ``test_email_verification_migration.py`` carries this helper).
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import settings

    engine = create_async_engine(
        settings.test_database_url, isolation_level="AUTOCOMMIT"
    )
    try:
        async with engine.connect() as conn:
            result = await conn.execute(sa.text(query), params or {})
            return result.fetchall() if result.returns_rows else []
    finally:
        await engine.dispose()


async def _seed_raster_asset(session, admin_id: uuid.UUID, crs_wkt: str) -> uuid.UUID:
    """Commit one dataset + raster_asset pair holding ``crs_wkt``.

    One dataset per asset: ``uq_raster_assets_dataset`` allows a dataset only
    one raster asset.
    """
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        name=f"wkt2 backfill {uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="scene.tif",
    )
    asset_id = uuid.uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO catalog.raster_assets (id, dataset_id, asset_uri, crs_wkt) "
            "VALUES (:id, :dataset_id, :asset_uri, :crs_wkt)"
        ),
        {
            "id": asset_id,
            "dataset_id": dataset.id,
            "asset_uri": f"rasters/{asset_id}/source.cog.tif",
            "crs_wkt": crs_wkt,
        },
    )
    await session.commit()
    return asset_id


def _wkt1_root_re() -> str:
    """The migration's predicate, loaded from the migration itself.

    Copying the pattern here would let the two drift, and a predicate that
    silently stopped matching would show up as a migration that converts
    nothing — which looks exactly like a database that had nothing to
    convert.
    """
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0041_raster_assets_crs_wkt2.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0041", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._WKT1_ROOT_RE


class TestWkt1Predicate:
    """Which rows the backfill claims, evaluated by postgres rather than by
    a Python re-implementation of its regex dialect.

    The round trip above proves the loop; this proves its WHERE clause, on
    the CRS kinds too rare to seed a row for. The pairs that matter are the
    WKT1/WKT2 near-twins — ``GEOGCS`` against ``GEOGCRS``, ``PROJCS``
    against ``PROJCRS`` — where only the ``\\[`` anchor separates a match
    from a prefix match, and getting that wrong would rewrite already-WKT2
    rows on every run.
    """

    @pytest.mark.parametrize(
        ("value", "matches"),
        [
            ('PROJCS["x"]', True),
            ('GEOGCS["x"]', True),
            ('GEOCCS["x"]', True),
            ('LOCAL_CS["x"]', True),
            ('COMPD_CS["x"]', True),
            ('VERT_CS["x"]', True),
            ('FITTED_CS["x"]', True),
            ('  \n GEOGCS["leading whitespace"]', True),
            ('geogcs["lowercase — WKT keywords are case-insensitive"]', True),
            ('GEOGCS ["space before the bracket"]', True),
            ('PROJCRS["x"]', False),
            ('GEOGCRS["x"]', False),
            ('GEODCRS["x"]', False),
            ('ENGCRS["x"]', False),
            ('COMPOUNDCRS["x"]', False),
            ('VERTCRS["x"]', False),
            # Already WKT2 at the root, with a WKT1-spelled CRS nested
            # inside it. The predicate reads the ROOT keyword, so this is
            # correctly left alone — converting it would be a no-op at best.
            ('BOUNDCRS[SOURCECRS[GEOGCS["nested"]]]', False),
        ],
    )
    async def test_the_predicate_matches_wkt1_roots_only(self, value, matches):
        rows = await _fresh_query(
            "SELECT :value ~* :pattern AS matched",
            {"value": value, "pattern": _wkt1_root_re()},
        )
        assert rows[0].matched is matches


@_SKIP_UNDER_OVERLAY
class TestCrsWkt2Backfill:
    async def test_backfill_converts_wkt1_and_leaves_the_rest_alone(
        self, test_db_session
    ):
        """One round trip, three row shapes.

        They share a migration run on purpose: the interesting question is
        not how each row fares alone but whether the row PROJ cannot convert
        stops the loop before it reaches the others.
        """
        admin_id = await get_user_id(test_db_session, "admin")

        wkt1_id = await _seed_raster_asset(test_db_session, admin_id, _WKT1_UTM_21N)
        garbage_id = await _seed_raster_asset(
            test_db_session, admin_id, _WKT1_SHAPED_GARBAGE
        )
        # Already WKT2 — the state a post-#1376 ingest writes, and the state
        # every converted row is in on a second run. It must come out byte
        # identical, which is what makes the migration re-runnable.
        from rasterio.crs import CRS

        already_wkt2 = CRS.from_wkt(_WKT1_UTM_21N).to_wkt(version="WKT2_2019")
        wkt2_id = await _seed_raster_asset(test_db_session, admin_id, already_wkt2)

        try:
            down = _run_alembic("downgrade", "-1")
            assert down.returncode == 0, (
                f"alembic downgrade -1 failed (rc={down.returncode}):\n"
                f"stdout: {down.stdout}\nstderr: {down.stderr}"
            )
            up = _run_alembic("upgrade", "head")
            assert up.returncode == 0, (
                f"alembic upgrade head failed (rc={up.returncode}):\n"
                f"stdout: {up.stdout}\nstderr: {up.stderr}"
            )

            rows = await _fresh_query(
                "SELECT id, crs_wkt FROM catalog.raster_assets "
                "WHERE id IN (:a, :b, :c)",
                {"a": wkt1_id, "b": garbage_id, "c": wkt2_id},
            )
            stored = {row.id: row.crs_wkt for row in rows}

            assert stored[wkt1_id].startswith("PROJCRS["), (
                "the WKT1 row is what the backfill exists for"
            )
            assert "32621" in stored[wkt1_id], (
                "converting the dialect must not lose the CRS identity"
            )
            assert stored[garbage_id] == _WKT1_SHAPED_GARBAGE, (
                "a row PROJ cannot parse is left as stored, not blanked"
            )
            assert stored[wkt2_id] == already_wkt2, (
                "an already-WKT2 row is outside the predicate and untouched"
            )
        finally:
            restore = _run_alembic("upgrade", "head")
            # The unconvertible row is deliberately hostile input; leaving it
            # in a per-worker database that later tests share would hand them
            # a WKT no reader can parse. Their datasets stay — an ordinary
            # committed dataset is fixture noise every test here leaves.
            await _fresh_query(
                "DELETE FROM catalog.raster_assets WHERE id IN (:a, :b, :c)",
                {"a": wkt1_id, "b": garbage_id, "c": wkt2_id},
            )
            assert restore.returncode == 0, (
                f"alembic upgrade head (restore) failed (rc={restore.returncode}):\n"
                f"stdout: {restore.stdout}\nstderr: {restore.stderr}"
            )
