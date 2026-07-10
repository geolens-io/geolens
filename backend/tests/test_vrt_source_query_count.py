"""fix(#435): the VRT source endpoints must not issue one query per member row.

`list_vrt_sources` and `get_vrt_status` used to call `get_dataset()` once per source
link, so a 200-source VRT cost 200 round trips before it could return a page. The fix
batches the member load into a single query (`_load_source_datasets`). This pins the
query count so a future edit cannot silently reintroduce the N+1.

The per-row `can_access_dataset()` call is intentionally NOT batched: only `restricted`
targets reach the database from there, and a batch op on the permission seam would let
a wrapping overlay's policy be skipped (SLOT-02). An admin caller short-circuits that
check with no query, so the count below reflects the batched member load alone.
"""

import uuid

from sqlalchemy import event, select, text

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.datasets.api.router_vrt import list_vrt_sources
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import RasterAsset


async def _admin(session) -> User:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one()


async def _make_raster_source(session, *, created_by: uuid.UUID) -> uuid.UUID:
    record = Record(
        title=f"QC source {uuid.uuid4().hex[:6]}",
        summary="raster source",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        record_type="raster_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"qc_src_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="s.tif",
    )
    session.add(dataset)
    await session.flush()
    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=f"rasters/{dataset.id}/s.cog.tif",
            storage_backend="local",
            status="ready",
            epsg=4326,
            band_count=1,
            res_x=0.001,
            res_y=0.001,
        )
    )
    await session.flush()
    return dataset.id


async def _make_vrt_with_sources(
    session, *, created_by: uuid.UUID, n: int
) -> uuid.UUID:
    record = Record(
        title=f"QC VRT {uuid.uuid4().hex[:6]}",
        summary="vrt",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        record_type="vrt_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    vrt = Dataset(
        record_id=record.id,
        table_name=f"qc_vrt_{uuid.uuid4().hex[:8]}",
        source_format=None,
        source_filename=None,
    )
    session.add(vrt)
    await session.flush()
    session.add(
        RasterAsset(
            dataset_id=vrt.id,
            asset_uri=f"rasters/{vrt.id}/v.vrt",
            storage_backend="local",
            status="ready",
            vrt_type="mosaic",
            resolution_strategy="finest",
            epsg=4326,
            band_count=1,
        )
    )
    await session.flush()
    for pos in range(n):
        src = await _make_raster_source(session, created_by=created_by)
        await session.execute(
            text(
                "INSERT INTO catalog.vrt_source_links"
                "(vrt_dataset_id, source_dataset_id, position) "
                "VALUES (:vrt, :src, :pos)"
            ),
            {"vrt": str(vrt.id), "src": str(src), "pos": pos},
        )
    await session.commit()
    return vrt.id


async def _count_list_vrt_sources_queries(
    session, vrt_id: uuid.UUID, user
) -> tuple[int, int]:
    count = 0

    def _tick(*args, **kwargs):
        nonlocal count
        count += 1

    sync_engine = session.bind.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _tick)
    try:
        result = await list_vrt_sources(dataset_id=vrt_id, user=user, db=session)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _tick)
    return len(result.sources), count


async def test_list_vrt_sources_query_count_is_flat(test_db_session) -> None:
    """Query count must not grow with the number of VRT sources."""
    admin = await _admin(test_db_session)

    small = await _make_vrt_with_sources(test_db_session, created_by=admin.id, n=1)
    large = await _make_vrt_with_sources(test_db_session, created_by=admin.id, n=8)

    n_small, q_small = await _count_list_vrt_sources_queries(
        test_db_session, small, admin
    )
    n_large, q_large = await _count_list_vrt_sources_queries(
        test_db_session, large, admin
    )

    assert n_small == 1 and n_large == 8, "the endpoint must return every source"
    # Pre-fix: q_large - q_small would be ~7 (one get_dataset per extra source).
    # Batched: the delta is 0. Allow 1 for incidental variation, never O(n).
    assert q_large - q_small <= 1, (
        f"query count scales with source count: {q_small} for 1 source, "
        f"{q_large} for 8 — the per-row get_dataset N+1 is back"
    )
