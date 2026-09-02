"""fix(#1778): /stac/collections held up to 5 concurrent DB-pool connections
per in-flight request.

Codebase audit 2026-08-30 (8dc529f17): ``get_collections`` (stac/router.py)
executes ``select(Collection)`` on its own request-scoped ``db`` (which
``get_db`` never commits on the read path, so that connection stays checked
out for the whole request), then ``asyncio.gather``s four more aggregate
queries, each opening its own ``async_session()``. That is 5 checkouts for
one anonymous, uncached request; 3 concurrent requests exhaust the default
13-connection pool (``db_pool_size=10`` + ``db_max_overflow=3``).

Same event-listener technique test_export_request_budget.py uses for its
pool-checkout test: listen on ``checkout``/``checkin`` on the app's own
engine and track live/peak concurrently-held connections, with the request's
own connection as a positive control so the counter can't pass vacuously.
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id


async def _create_raster(
    session: AsyncSession, *, created_by: uuid.UUID, name: str
) -> Dataset:
    """Public+published raster Record+Dataset so the four aggregate queries
    in get_collections have at least one row to group over."""
    record = Record(
        title=name,
        summary=f"Pool checkout test: {name}",
        visibility="public",
        record_status="published",
        record_type="raster_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"ds_{uuid.uuid4().hex[:12]}",
        srid=4326,
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.flush()
    await session.execute(
        update(Record)
        .where(Record.id == record.id)
        .values(created_at=date(2024, 3, 14))
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.mark.anyio
async def test_stac_collections_does_not_hold_more_than_one_pool_connection(
    client: AsyncClient, test_db_session: AsyncSession
):
    admin_id = await get_user_id(test_db_session, "admin")
    await _create_raster(
        test_db_session, created_by=admin_id, name=f"pool-{uuid.uuid4().hex[:8]}"
    )

    import app.core.db as db_module

    live = {"n": 0}
    peak = {"n": 0}

    def _on_checkout(dbapi_connection, connection_record, connection_proxy):
        live["n"] += 1
        peak["n"] = max(peak["n"], live["n"])

    def _on_checkin(dbapi_connection, connection_record):
        live["n"] -= 1

    sync_engine = db_module.engine.sync_engine
    event.listen(sync_engine, "checkout", _on_checkout)
    event.listen(sync_engine, "checkin", _on_checkin)

    try:
        baseline = live["n"]
        resp = await client.get("/stac/collections")
    finally:
        event.remove(sync_engine, "checkout", _on_checkout)
        event.remove(sync_engine, "checkin", _on_checkin)

    assert resp.status_code == 200, resp.text
    # Positive control: the counter observed at least the request's own
    # connection, so it is capable of seeing a held connection at all.
    assert peak["n"] >= baseline + 1

    # fix(#1778): the finding. On main this hits baseline + 5 (the request's
    # own connection plus four nested async_session() checkouts running
    # concurrently under asyncio.gather); the fix runs the four aggregates
    # sequentially on the caller's own session, so only the request's own
    # connection is ever held.
    assert peak["n"] <= baseline + 1, (
        f"peak concurrent pool checkouts {peak['n']} exceeded baseline "
        f"{baseline} + 1 -- /stac/collections held more than its own "
        "connection at once"
    )
