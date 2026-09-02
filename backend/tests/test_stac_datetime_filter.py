"""STAC datetime filter — null-temporal records use the created_at fallback.

fix(#430 BA-13 / #430 codex): records with no temporal_start/temporal_end advertise
``properties.datetime = created_at`` (see test_stac_record_output.py), so the
search filter must compare that same fallback instant — NOT admit every
null-temporal record unconditionally (pre-fix, ``datetime=1900-01-01/...``
matched a record created in 2026).
"""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id


async def _create_null_temporal_raster(
    session: AsyncSession, *, created_by: uuid.UUID, name: str
) -> Dataset:
    """Public+published raster Record with NO temporal bounds (created_at = now)."""
    record = Record(
        title=name,
        summary=f"Null-temporal STAC datetime test: {name}",
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
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_open_ended_raster(
    session: AsyncSession, *, created_by: uuid.UUID, name: str, temporal_start: date
) -> Dataset:
    """Public+published raster Record with temporal_start SET and
    temporal_end NULL -- an open-ended/ongoing temporal extent."""
    record = Record(
        title=name,
        summary=f"Open-ended STAC datetime test: {name}",
        visibility="public",
        record_status="published",
        record_type="raster_dataset",
        created_by=created_by,
        temporal_start=temporal_start,
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
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _search_ids(
    client: AsyncClient, datetime_str: str, ids: str | None = None
) -> set[str]:
    # fix(#439): scope the search to a specific item id when given. Under
    # `pytest -n`, sibling tests on the same per-worker DB seed records with
    # today's created_at that crowd the bounded result window and push the
    # target out — filtering to the record under test keeps the datetime
    # assertion hermetic while still exercising the created_at fallback filter.
    params = {"datetime": datetime_str}
    if ids is not None:
        params["ids"] = ids
    resp = await client.get("/stac/search", params=params)
    assert resp.status_code == 200, resp.text
    return {f["id"] for f in resp.json()["features"]}


@pytest.mark.anyio
async def test_past_interval_excludes_null_temporal_record(
    client: AsyncClient, test_db_session: AsyncSession
):
    """A 1900 interval must not match a record created now (created_at fallback)."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_null_temporal_raster(
        test_db_session, created_by=admin_id, name="Null Temporal Past"
    )
    ids = await _search_ids(
        client, "1900-01-01T00:00:00Z/1900-12-31T23:59:59Z", ids=str(ds.id)
    )
    assert str(ds.id) not in ids


@pytest.mark.anyio
async def test_interval_spanning_created_at_includes_null_temporal_record(
    client: AsyncClient, test_db_session: AsyncSession
):
    """BA-13 intent preserved: an interval containing created_at still matches."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_null_temporal_raster(
        test_db_session, created_by=admin_id, name="Null Temporal Spanning"
    )
    ids = await _search_ids(
        client, "2000-01-01T00:00:00Z/2100-01-01T00:00:00Z", ids=str(ds.id)
    )
    assert str(ds.id) in ids


@pytest.mark.anyio
async def test_past_instant_excludes_null_temporal_record(
    client: AsyncClient, test_db_session: AsyncSession
):
    """A single past instant must not match a null-temporal record created now."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_null_temporal_raster(
        test_db_session, created_by=admin_id, name="Null Temporal Instant"
    )
    ids = await _search_ids(client, "1900-06-01T00:00:00Z", ids=str(ds.id))
    assert str(ds.id) not in ids


@pytest.mark.anyio
async def test_advertised_fallback_instant_matches_null_temporal_record(
    client: AsyncClient, test_db_session: AsyncSession
):
    """fix(#430 codex r2): searching by the record's OWN advertised datetime
    (created_at) must match. parse_ogc_datetime is day-granular, so any
    created_at within the requested day counts — not just exact midnight."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_null_temporal_raster(
        test_db_session, created_by=admin_id, name="Null Temporal Own Day"
    )
    record = await test_db_session.get(Record, ds.record_id)
    own_day = record.created_at.date().isoformat()
    ids = await _search_ids(client, f"{own_day}T00:00:00Z", ids=str(ds.id))
    assert str(ds.id) in ids


# ---------------------------------------------------------------------------
# fix(#1778): an interval must not drop an open-ended record that the single
# instant inside that same interval matches. The interval branch's start
# clause read a NULL temporal_end as "open" only via the null_temporal (both
# NULL) arm -- a record with temporal_start SET and temporal_end NULL (an
# ongoing/open-ended extent) fell through every arm, so `datetime=<instant>`
# matched it but `datetime=<instant>/<instant+1day>` (a strictly WIDER window
# containing that instant) did not.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_interval_matches_open_ended_record_the_instant_alone_matches(
    client: AsyncClient, test_db_session: AsyncSession
):
    """Narrowing an interval to the instant it contains must not gain a match
    the interval itself lacked."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_open_ended_raster(
        test_db_session,
        created_by=admin_id,
        name="Open Ended Interval Parity",
        temporal_start=date(2015, 6, 1),
    )
    instant_ids = await _search_ids(client, "2021-06-15T00:00:00Z", ids=str(ds.id))
    interval_ids = await _search_ids(
        client, "2021-06-15T00:00:00Z/2021-06-16T00:00:00Z", ids=str(ds.id)
    )
    assert str(ds.id) in instant_ids
    assert str(ds.id) in interval_ids


@pytest.mark.anyio
async def test_interval_excludes_open_ended_record_starting_after_the_interval(
    client: AsyncClient, test_db_session: AsyncSession
):
    """Counterexample guard: the open-end fix must not over-match -- a
    record whose temporal_start is entirely after the interval's end still
    has no overlap and must stay excluded."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_open_ended_raster(
        test_db_session,
        created_by=admin_id,
        name="Open Ended Future Start",
        temporal_start=date(2030, 1, 1),
    )
    ids = await _search_ids(
        client, "2021-06-15T00:00:00Z/2021-06-16T00:00:00Z", ids=str(ds.id)
    )
    assert str(ds.id) not in ids
