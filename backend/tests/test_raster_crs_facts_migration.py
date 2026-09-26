"""Migration 0073 fills raster_assets' CRS facts through the probe child."""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
import rasterio.crs
import sqlalchemy as sa

from app.core.geo import wkt_crs_facts
from app.processing.raster.probe import RasterProbeError

from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query,
    run_alembic,
)
from tests.factories import create_dataset, get_user_id

pytestmark = pytest.mark.anyio

_SKIP_UNDER_OVERLAY = pytest.mark.skipif(
    enterprise_migrations_present(),
    reason=(
        "OSS migration round trip; multi-head under the enterprise overlay — "
        "runs in the no-overlay Pytest Parallel Isolation job instead."
    ),
)

_FACTS = ("crs_is_geographic", "crs_has_degree_unit", "crs_metres_per_unit")

_TEXTS = [
    rasterio.crs.CRS.from_epsg(4326).to_wkt(version="WKT2_2019"),
    rasterio.crs.CRS.from_epsg(2263).to_wkt(version="WKT2_2019"),
    rasterio.crs.CRS.from_epsg(4807).to_wkt(),
    # Truncated, so PROJ refuses it and the keyword sniff answers.
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84"',
]


def _migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0073_raster_crs_facts.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0073", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _seed(session, crs_wkt: str | None) -> uuid.UUID:
    dataset = await create_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name=f"crs facts backfill {uuid.uuid4().hex[:8]}",
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


async def _facts(ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple]:
    rows = await fresh_query(
        f"SELECT id, {', '.join(_FACTS)} FROM catalog.raster_assets "
        "WHERE id = ANY(:ids)",
        {"ids": ids},
    )
    return {row.id: tuple(getattr(row, name) for name in _FACTS) for row in rows}


def _expected(crs_wkt: str) -> tuple:
    facts = wkt_crs_facts(crs_wkt)
    return tuple(facts[name] for name in _FACTS)


async def _delete(ids: list[uuid.UUID]) -> None:
    await fresh_query(
        "DELETE FROM catalog.raster_assets WHERE id = ANY(:ids)", {"ids": ids}
    )


@_SKIP_UNDER_OVERLAY
class TestBackfillRoundTrip:
    async def test_upgrade_fills_every_row_from_the_child(self, test_db_session):
        by_text = {wkt: await _seed(test_db_session, wkt) for wkt in _TEXTS}
        twin = await _seed(test_db_session, _TEXTS[1])
        no_crs = await _seed(test_db_session, None)
        ids = [*by_text.values(), twin, no_crs]
        try:
            down = run_alembic("downgrade", _migration().down_revision)
            assert down.returncode == 0, down.stderr
            up = run_alembic("upgrade", "head")
            assert up.returncode == 0, up.stderr

            stored = await _facts(ids)
            for wkt, asset_id in by_text.items():
                assert stored[asset_id] == _expected(wkt), wkt
            assert stored[twin] == _expected(_TEXTS[1])
            assert stored[no_crs] == (None, None, None)
        finally:
            restore = run_alembic("upgrade", "head")
            await _delete(ids)
            assert restore.returncode == 0, restore.stderr


class TestBackfillLoop:
    async def test_a_text_the_child_cannot_answer_for_stays_unknown(
        self, test_db_session
    ):
        answered = await _seed(test_db_session, _TEXTS[1])
        stalled = await _seed(test_db_session, _TEXTS[0])

        def _facts_of(wkt: str) -> dict:
            if wkt == _TEXTS[0]:
                raise RasterProbeError("timeout", timeout=30)
            return wkt_crs_facts(wkt)

        try:
            await test_db_session.run_sync(
                lambda s: _migration().backfill(s.connection(), facts_of=_facts_of)
            )
            await test_db_session.commit()

            stored = await _facts([answered, stalled])
            assert stored[answered] == _expected(_TEXTS[1])
            assert stored[stalled] == (None, None, None)
        finally:
            await _delete([answered, stalled])

    async def test_a_child_that_cannot_describe_wgs84_stops_the_backfill(
        self, test_db_session
    ):
        seeded = await _seed(test_db_session, _TEXTS[1])

        def _broken(wkt: str) -> dict:
            raise RasterProbeError("internal", timeout=30)

        try:
            with pytest.raises(RuntimeError, match="could not describe WGS 84"):
                await test_db_session.run_sync(
                    lambda s: _migration().backfill(s.connection(), facts_of=_broken)
                )
            await test_db_session.rollback()

            assert (await _facts([seeded]))[seeded] == (None, None, None)
        finally:
            await _delete([seeded])
