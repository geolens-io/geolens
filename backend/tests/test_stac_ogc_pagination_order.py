"""Deterministic pagination coverage for OFFSET/LIMIT endpoints that had no
row-order tiebreaker.

fix(#1778): codebase audit 2026-08-30 (8dc529f17) found three STAC/OGC
OFFSET/LIMIT endpoints with NO ``order_by`` at all (STAC collection items,
STAC search, OGC ``/collections``) and two siblings whose ``order_by`` sorted
on non-unique server-default columns (collection membership ``sort_order``,
record contact ``sort_order``). PostgreSQL gives no row-order guarantee for
an unordered/tied-order query, so a plan change between page fetches can
duplicate some rows and drop others.

Two kinds of coverage per endpoint:

- A structural check that captures the actual SQL sent to Postgres (via a
  before_cursor_execute listener on the test engine, the same event-capture
  technique test_export_request_budget.py uses for pool checkouts) and
  asserts the paginated query has an ORDER BY at all, or -- for the two
  siblings that already had one on a non-unique column -- that the unique
  tiebreaker column is in it. This is what actually fails on main: main
  emits no ORDER BY (or one without the tiebreaker) full stop, so this is
  deterministic regardless of physical row order or plan choice.
- A behavioral no-dupes/no-drops walk across tied rows, mirroring
  test_search_pagination.py (#315), kept as end-to-end confirmation the fix
  doesn't change the response shape. On a small, static, single-connection
  test table Postgres tends to return heap order deterministically even
  without an ORDER BY, so this half alone does not fail on main -- the
  structural check above is the counterfactual that does.
"""

import uuid
from contextlib import contextmanager
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import event, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordContact,
)

from tests.factories import get_user_id

FIXED_TS = date(2024, 3, 14)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _capture_sql():
    """Capture raw SQL text sent to the test database's engine.

    Same before_cursor_execute event-listener technique the pool-checkout
    test in test_export_request_budget.py uses for "checkout"/"checkin" --
    listens on db_module.engine.sync_engine, which the `client` fixture has
    already pointed at the test database.
    """
    import app.core.db as db_module

    captured: list[str] = []

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        captured.append(statement)

    sync_engine = db_module.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _on_execute)
    try:
        yield captured
    finally:
        event.remove(sync_engine, "before_cursor_execute", _on_execute)


async def _create_tied_raster(
    session: AsyncSession, *, created_by: uuid.UUID, name: str
) -> Dataset:
    """Public+published raster Record+Dataset with created_at pinned to a
    shared fixed timestamp, so every seeded row ties on created_at."""
    record = Record(
        title=name,
        summary=f"Pagination order test: {name}",
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
        update(Record).where(Record.id == record.id).values(created_at=FIXED_TS)
    )
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _walk_pages(
    client: AsyncClient, path: str, base_params: dict, *, page_size: int
) -> list[str]:
    """Walk a StacItemCollectionResponse-shaped endpoint page by page,
    collecting feature ids in order, using numberMatched to know when to
    stop."""
    all_ids: list[str] = []
    offset = 0
    while True:
        params = {**base_params, "limit": page_size, "offset": offset}
        resp = await client.get(path, params=params)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        all_ids.extend(f["id"] for f in data["features"])
        offset += page_size
        if offset >= data["numberMatched"]:
            break
        if offset > data["numberMatched"] + page_size * 5:
            pytest.fail("pagination did not terminate")
    return all_ids


# ---------------------------------------------------------------------------
# STAC /stac/collections/{id}/items -- get_collection_items
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_collection_items_pagination_no_dupes_no_drops(
    client: AsyncClient, test_db_session: AsyncSession
):
    admin_id = await get_user_id(test_db_session, "admin")
    prefix = f"stac-items-order-{uuid.uuid4().hex[:8]}"
    datasets = [
        await _create_tied_raster(
            test_db_session, created_by=admin_id, name=f"{prefix}-{i}"
        )
        for i in range(7)
    ]
    expected = {str(ds.id) for ds in datasets}

    # Datasets not added to any Collection surface under the unassigned
    # pseudo-collection.
    with _capture_sql() as captured:
        paged = await _walk_pages(
            client, "/stac/collections/geolens-unassigned/items", {}, page_size=2
        )
    seen = [pid for pid in paged if pid in expected]

    assert len(seen) == len(set(seen)), "duplicate ids paging STAC collection items"
    assert set(seen) == expected, "missing/extra ids paging STAC collection items"

    # fix(#1778): the counterfactual -- on main the paginated dataset query
    # carries no ORDER BY at all, so this fails there regardless of the
    # (Postgres-plan-dependent, not reliably reproducible in a small static
    # test table) dupe/drop symptom above.
    paginated_sql = [
        s for s in captured if "OFFSET" in s.upper() and "catalog.datasets" in s
    ]
    assert paginated_sql, "expected at least one paginated dataset query"
    assert all("ORDER BY" in s.upper() for s in paginated_sql), (
        "paginated STAC collection-items query has no ORDER BY"
    )


# ---------------------------------------------------------------------------
# STAC /stac/search -- _execute_search
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_search_pagination_no_dupes_no_drops(
    client: AsyncClient, test_db_session: AsyncSession
):
    admin_id = await get_user_id(test_db_session, "admin")
    prefix = f"stac-search-order-{uuid.uuid4().hex[:8]}"
    datasets = [
        await _create_tied_raster(
            test_db_session, created_by=admin_id, name=f"{prefix}-{i}"
        )
        for i in range(7)
    ]
    expected = {str(ds.id) for ds in datasets}
    ids_param = ",".join(sorted(expected))

    with _capture_sql() as captured:
        paged = await _walk_pages(
            client, "/stac/search", {"ids": ids_param}, page_size=2
        )
    seen = [pid for pid in paged if pid in expected]

    assert len(seen) == len(set(seen)), "duplicate ids paging STAC search"
    assert set(seen) == expected, "missing/extra ids paging STAC search"

    # fix(#1778): the counterfactual -- fails on main, no ORDER BY at all.
    paginated_sql = [
        s for s in captured if "OFFSET" in s.upper() and "catalog.datasets" in s
    ]
    assert paginated_sql, "expected at least one paginated dataset query"
    assert all("ORDER BY" in s.upper() for s in paginated_sql), (
        "paginated STAC search query has no ORDER BY"
    )


# ---------------------------------------------------------------------------
# OGC /collections -- list_collections (per-dataset feature collections)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ogc_collections_list_pagination_no_dupes_no_drops(
    client: AsyncClient, test_db_session: AsyncSession, admin_auth_header: dict
):
    # No filter param exists on this endpoint, so truncate first for a known
    # total -- otherwise there is no numberMatched/count to page against.
    await test_db_session.execute(text("TRUNCATE TABLE catalog.datasets CASCADE"))
    await test_db_session.commit()

    admin_id = await get_user_id(test_db_session, "admin")
    prefix = f"ogc-coll-order-{uuid.uuid4().hex[:8]}"
    datasets = [
        await _create_tied_raster(
            test_db_session, created_by=admin_id, name=f"{prefix}-{i}"
        )
        for i in range(7)
    ]
    expected = {str(ds.id) for ds in datasets}

    from urllib.parse import urlparse

    all_ids: list[str] = []
    path_and_query = "/collections?limit=2"
    seen_pages = 0
    with _capture_sql() as captured:
        while path_and_query and seen_pages <= len(expected) + 2:
            resp = await client.get(path_and_query, headers=admin_auth_header)
            assert resp.status_code == 200, resp.text
            data = resp.json()
            all_ids.extend(c["id"] for c in data["collections"] if c["id"] in expected)
            next_link = next(
                (link for link in data["links"] if link["rel"] == "next"), None
            )
            if next_link is None:
                break
            parsed = urlparse(next_link["href"])
            path_and_query = parsed.path + (f"?{parsed.query}" if parsed.query else "")
            seen_pages += 1

    assert len(all_ids) == len(set(all_ids)), "duplicate ids paging OGC /collections"
    assert set(all_ids) == expected, "missing/extra ids paging OGC /collections"

    # fix(#1778): the counterfactual -- fails on main, no ORDER BY at all.
    paginated_sql = [
        s for s in captured if "OFFSET" in s.upper() and "catalog.datasets" in s
    ]
    assert paginated_sql, "expected at least one paginated dataset query"
    assert all("ORDER BY" in s.upper() for s in paginated_sql), (
        "paginated OGC /collections query has no ORDER BY"
    )


# ---------------------------------------------------------------------------
# /catalog/collections/{id}/datasets/ -- get_collection_datasets
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_datasets_pagination_no_dupes_no_drops(
    client: AsyncClient, test_db_session: AsyncSession, admin_auth_header: dict
):
    admin_id = await get_user_id(test_db_session, "admin")
    prefix = f"coll-ds-order-{uuid.uuid4().hex[:8]}"
    datasets = [
        await _create_tied_raster(
            test_db_session, created_by=admin_id, name=f"{prefix}-{i}"
        )
        for i in range(7)
    ]
    expected = {str(ds.id) for ds in datasets}

    resp = await client.post(
        "/catalog/collections/",
        json={"name": f"Pagination Order {uuid.uuid4().hex[:8]}"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    coll_id = resp.json()["id"]

    # A single POST inserts every CollectionDataset row inside one
    # transaction, so added_at (server default now()) and sort_order
    # (server default 0) tie across all seven rows -- exactly the hazard
    # #1778 flagged.
    resp = await client.post(
        f"/catalog/collections/{coll_id}/datasets/",
        json={"dataset_ids": sorted(expected)},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["added"] == 7

    all_ids: list[str] = []
    skip = 0
    with _capture_sql() as captured:
        while skip <= len(expected) + 2:
            resp = await client.get(
                f"/catalog/collections/{coll_id}/datasets/",
                params={"skip": skip, "limit": 2},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            page_ids = [d["id"] for d in data["datasets"]]
            if not page_ids:
                break
            all_ids.extend(page_ids)
            skip += 2

    assert len(all_ids) == len(set(all_ids)), "duplicate ids paging collection datasets"
    assert set(all_ids) == expected, "missing/extra ids paging collection datasets"

    # fix(#1778): the counterfactual -- on main, ORDER BY exists but only on
    # sort_order/added_at (both tied for every row here), no dataset_id
    # tiebreaker, so this fails there even though an ORDER BY is present.
    # dataset_id also appears in the JOIN condition, so isolate the ORDER BY
    # clause itself rather than searching the whole statement text.
    paginated_sql = [
        s for s in captured if "OFFSET" in s.upper() and "collection_datasets" in s
    ]
    assert paginated_sql, "expected at least one paginated collection-datasets query"
    for s in paginated_sql:
        order_clause = s.upper().split("ORDER BY", 1)[-1].split("LIMIT", 1)[0]
        assert "DATASET_ID" in order_clause, (
            "paginated collection-datasets query has no dataset_id tiebreaker "
            f"in ORDER BY: {order_clause!r}"
        )


# ---------------------------------------------------------------------------
# /records/{id}/contacts/ -- list_contacts
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_contacts_pagination_no_dupes_no_drops(
    client: AsyncClient, test_db_session: AsyncSession, admin_auth_header: dict
):
    admin_id = await get_user_id(test_db_session, "admin")
    record = Record(
        title="Contact Pagination Order",
        summary="Record for #1778 contact pagination coverage",
        visibility="public",
        record_status="published",
        created_by=admin_id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"ds_{uuid.uuid4().hex[:12]}",
        srid=4326,
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="test.geojson",
    )
    test_db_session.add(dataset)
    await test_db_session.flush()

    expected_ids = set()
    for i in range(7):
        contact = RecordContact(
            record_id=record.id,
            # sort_order defaults to 0 for every row -- the tie #1778 flags.
            role="pointOfContact",
            name=f"Contact {i}",
        )
        test_db_session.add(contact)
        await test_db_session.flush()
        expected_ids.add(str(contact.id))
    await test_db_session.commit()

    all_ids: list[str] = []
    skip = 0
    with _capture_sql() as captured:
        while skip <= len(expected_ids) + 2:
            resp = await client.get(
                f"/records/{record.id}/contacts/",
                params={"skip": skip, "limit": 2},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            page_ids = [c["id"] for c in data["contacts"]]
            if not page_ids:
                break
            all_ids.extend(page_ids)
            skip += 2

    assert len(all_ids) == len(set(all_ids)), "duplicate ids paging record contacts"
    assert set(all_ids) == expected_ids, "missing/extra ids paging record contacts"

    # fix(#1778): the counterfactual -- on main, ORDER BY exists but only on
    # sort_order (tied at 0 for every row here), no id tiebreaker.
    paginated_sql = [
        s for s in captured if "OFFSET" in s.upper() and "record_contacts" in s
    ]
    assert paginated_sql, "expected at least one paginated record-contacts query"
    for s in paginated_sql:
        order_clause = s.upper().split("ORDER BY", 1)[-1].split("LIMIT", 1)[0]
        assert "RECORD_CONTACTS.ID" in order_clause, (
            "paginated record-contacts query has no id tiebreaker in ORDER BY: "
            f"{order_clause!r}"
        )
