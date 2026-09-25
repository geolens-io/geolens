"""Migration 0069's backfill of the dataset_assets rows of older rasters.

The factory rasters here have a raster asset and no ``dataset_assets`` rows,
the shape of a raster uploaded before v1.3.0. Each test commits them, then
downgrades to 0069's predecessor and upgrades to head through the alembic
stack CI uses, so the backfill runs over them.

Run with: cd backend && set -a && source ../.env.test && set +a &&
          uv run pytest tests/test_raster_dataset_assets_backfill.py -x -q
"""

from __future__ import annotations

import uuid

import pytest

from app.processing.ingest.tasks_raster import _build_dataset_asset_rows
from tests.alembic_helpers import (
    enterprise_migrations_present,
    fresh_query,
    run_alembic,
)
from tests.factories import create_raster_dataset

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        enterprise_migrations_present(),
        reason=(
            "OSS migration round trip; multi-head under the enterprise overlay — "
            "runs in the no-overlay Pytest Parallel Isolation job instead."
        ),
    ),
]

_COLUMNS = ("href", "media_type", "title", "description", "roles", "size_bytes")


def _down_revision() -> str:
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0069_backfill_raster_dataset_assets.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0069", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.down_revision


async def _run_backfill(session) -> None:
    # Reaching 0069's predecessor runs every later migration's downgrade first,
    # and their DDL waits on the locks this session's open read still holds.
    await session.commit()
    for args in (("downgrade", _down_revision()), ("upgrade", "head")):
        result = run_alembic(*args)
        assert result.returncode == 0, (
            f"alembic {' '.join(args)} failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


def _keys() -> dict[str, str]:
    base = f"rasters/{uuid.uuid4()}/{uuid.uuid4().hex}"
    return {
        "asset_uri": f"{base}/source.cog.tif",
        "quicklook_256_uri": f"{base}/quicklook_256.png",
        "quicklook_512_uri": f"{base}/quicklook_512.png",
    }


async def _make_owner(session) -> uuid.UUID:
    from app.modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"backfill_owner_{suffix}",
        email=f"backfill_owner_{suffix}@example.invalid",
        password_hash="x",
    )
    session.add(user)
    await session.commit()
    return user.id


async def _raster(session, owner_id, **kwargs):
    return await create_raster_dataset(
        session,
        created_by=owner_id,
        name=f"backfill raster {uuid.uuid4().hex[:8]}",
        create_raster_asset=True,
        **kwargs,
    )


async def _rows(dataset_id) -> dict[str, tuple]:
    rows = await fresh_query(
        f"SELECT key, {', '.join(_COLUMNS)} FROM catalog.dataset_assets "
        "WHERE dataset_id = :d",
        {"d": dataset_id},
    )
    return {row.key: tuple(getattr(row, c) for c in _COLUMNS) for row in rows}


async def _purge(datasets, owner_id) -> None:
    for dataset in datasets:
        await fresh_query(
            "DELETE FROM catalog.datasets WHERE id = :d", {"d": dataset.id}
        )
        await fresh_query(
            "DELETE FROM catalog.records WHERE id = :r", {"r": dataset.record_id}
        )
    await fresh_query("DELETE FROM catalog.users WHERE id = :u", {"u": owner_id})


@pytest.mark.parametrize("record_status", ["published", "draft"])
async def test_a_raster_without_rows_gets_the_rows_ingest_writes(
    test_db_session, record_status
) -> None:
    import app.core.db as db_module
    from app.modules.quota.service import get_user_quota_usage

    owner_id = await _make_owner(test_db_session)
    keys = _keys()
    raster = await _raster(
        test_db_session,
        owner_id,
        record_status=record_status,
        raster_asset_kwargs={**keys, "size_bytes": 7_340_032},
    )
    try:
        await _run_backfill(test_db_session)

        expected = {
            row["key"]: tuple(row.get(c) for c in _COLUMNS)
            for row in _build_dataset_asset_rows(
                dataset_id=raster.id,
                cog_key=keys["asset_uri"],
                ql256_key=keys["quicklook_256_uri"],
                ql512_key=keys["quicklook_512_uri"],
                cog_size=7_340_032,
                is_manifest_vrt=False,
            )
        }
        assert await _rows(raster.id) == expected

        async with db_module.async_session() as session:
            usage = await get_user_quota_usage(session, owner_id)
        assert usage.bytes_used == 7_340_032
    finally:
        await _purge([raster], owner_id)


async def test_vrts_by_reference_rasters_and_unmanaged_keys_get_no_rows(
    test_db_session,
) -> None:
    owner_id = await _make_owner(test_db_session)
    vrt_keys = _keys()
    vrt = await _raster(
        test_db_session,
        owner_id,
        record_type="vrt_dataset",
        source_format=None,
        raster_asset_kwargs={
            **vrt_keys,
            "asset_uri": vrt_keys["asset_uri"].replace("source.cog.tif", "source.vrt"),
            "driver": "VRT",
            "vrt_type": "mosaic",
        },
    )
    by_reference = await _raster(
        test_db_session,
        owner_id,
        source_format="stac",
        raster_asset_kwargs={
            "asset_uri": "https://example.org/scenes/scene.tif",
            "storage_backend": "remote",
        },
    )
    partial_keys = _keys()
    partial = await _raster(
        test_db_session,
        owner_id,
        raster_asset_kwargs={
            "asset_uri": partial_keys["asset_uri"],
            "quicklook_256_uri": None,
            "quicklook_512_uri": "/var/lib/geolens/quicklook_512.png",
        },
    )
    try:
        await _run_backfill(test_db_session)

        assert await _rows(vrt.id) == {}
        assert await _rows(by_reference.id) == {}
        assert set(await _rows(partial.id)) == {"data"}
    finally:
        await _purge([vrt, by_reference, partial], owner_id)


async def test_an_existing_row_is_kept_on_every_run(test_db_session) -> None:
    owner_id = await _make_owner(test_db_session)
    keys = _keys()
    raster = await _raster(
        test_db_session,
        owner_id,
        raster_asset_kwargs={**keys, "size_bytes": 7_340_032},
    )
    await fresh_query(
        "INSERT INTO catalog.dataset_assets (dataset_id, key, href, size_bytes) "
        "VALUES (:d, 'data', 'rasters/kept/source.cog.tif', 1)",
        {"d": raster.id},
    )
    try:
        await _run_backfill(test_db_session)
        first = await _rows(raster.id)
        await _run_backfill(test_db_session)

        assert await _rows(raster.id) == first
        assert first["data"] == (
            "rasters/kept/source.cog.tif",
            None,
            None,
            None,
            None,
            1,
        )
        assert set(first) == {"data", "thumbnail", "overview"}
    finally:
        await _purge([raster], owner_id)
