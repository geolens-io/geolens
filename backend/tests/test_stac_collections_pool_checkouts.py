"""A STAC read holds one pool connection: the request's own.

``get_db`` never commits on the read path, so the request's connection stays
checked out until the handler returns. A supplementary query that opens a
session of its own holds a second connection on top of it, so a few
concurrent requests exhaust the default 13-connection pool
(``db_pool_size=10`` + ``db_max_overflow=3``), and a pool of one cannot serve
a single request. Supplementary queries run on the caller's session instead.

Same event-listener technique test_export_request_budget.py uses: listen on
``checkout``/``checkin`` on the app's own engine and track the peak number of
connections held at once, with the request's own connection as a positive
control so the counter can't pass vacuously.
"""

import uuid
from contextlib import contextmanager
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.standards.stac.router import STAC_UNASSIGNED_COLLECTION_ID

from tests.factories import get_user_id


async def _create_raster(
    session: AsyncSession, *, created_by: uuid.UUID, name: str
) -> Dataset:
    """Public+published raster Record+Dataset, unassigned to any collection, so
    every STAC read has at least one row to build from."""
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


@contextmanager
def _pool_checkouts():
    """Yield ``(baseline, peak)``: connections held when it started, and the
    most held at once since. Read ``peak`` after the block."""
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
        yield live["n"], peak
    finally:
        event.remove(sync_engine, "checkout", _on_checkout)
        event.remove(sync_engine, "checkin", _on_checkin)


@pytest.mark.anyio
async def test_the_counter_sees_a_supplementary_session(
    client: AsyncClient, test_db_session: AsyncSession
):
    """Positive control: a second session held beside the first is counted."""
    from app.core.db import async_session

    with _pool_checkouts() as (baseline, peak):
        async with async_session() as first, async_session() as second:
            await first.execute(text("SELECT 1"))
            await second.execute(text("SELECT 1"))

    assert peak["n"] >= baseline + 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/stac/collections", None),
        ("GET", f"/stac/collections/{STAC_UNASSIGNED_COLLECTION_ID}", None),
        ("GET", f"/stac/collections/{STAC_UNASSIGNED_COLLECTION_ID}/items", None),
        (
            "GET",
            f"/stac/collections/{STAC_UNASSIGNED_COLLECTION_ID}/items/{{id}}",
            None,
        ),
        ("GET", "/stac/items/{id}", None),
        ("GET", "/stac/search", None),
        ("POST", "/stac/search", {"limit": 5}),
    ],
    ids=[
        "collections",
        "collection",
        "collection-items",
        "collection-item",
        "item",
        "search-get",
        "search-post",
    ],
)
async def test_a_stac_read_does_not_hold_more_than_one_pool_connection(
    client: AsyncClient, test_db_session: AsyncSession, method, path, body
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_raster(
        test_db_session, created_by=admin_id, name=f"pool-{uuid.uuid4().hex[:8]}"
    )

    with _pool_checkouts() as (baseline, peak):
        resp = await client.request(method, path.format(id=dataset.id), json=body)

    assert resp.status_code == 200, resp.text
    # The request's own connection is the least it can hold, so the counter
    # is capable of seeing a held connection at all.
    assert peak["n"] >= baseline + 1
    assert peak["n"] <= baseline + 1, (
        f"peak concurrent pool checkouts {peak['n']} exceeded baseline "
        f"{baseline} + 1 -- {method} {path} held more than its own connection at once"
    )
