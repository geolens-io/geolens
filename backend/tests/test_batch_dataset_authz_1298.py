"""Regression tests for #1298: batched dataset loading and authorization.

``create_vrt_job()`` (VRT creation) and the collection-linking route each used
to authorize their linked datasets one id at a time — ``get_dataset()`` then
``check_dataset_access()`` per id — so a single request could cost hundreds of
sequential round trips before the write even happened (500 for VRT creation,
100 for collection linking). The fix adds ``check_datasets_access_bulk()`` in
``app.modules.catalog.authorization`` and swaps it in at both call sites.

Covers:
  - Parity: the batch helper allows/denies exactly what the scalar
    ``check_dataset_access`` allows/denies, for the same mixed set.
  - Query-count regression at both call sites, mirroring
    ``test_vrt_source_query_count.py``'s read-side test.
  - Fail-closed positional coverage: a denied dataset in the MIDDLE of an
    otherwise-valid batch still denies the whole request.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import event, select

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.authorization import (
    check_dataset_access,
    check_datasets_access_bulk,
    get_user_roles,
)
from app.modules.catalog.collections.router import add_datasets_endpoint
from app.modules.catalog.collections.schemas import CollectionAddDatasetsRequest
from app.modules.catalog.collections.service import create_collection
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.datasets.domain.service import get_dataset
from app.processing.ingest.schemas import VrtCreateRequest
from app.processing.ingest.service import create_vrt_job
from app.processing.raster.models import RasterAsset
from tests.factories import create_dataset, create_raster_dataset, get_user_id


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _admin(session) -> User:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one()


async def _get_admin_id(session) -> uuid.UUID:
    return await get_user_id(session, "admin")


async def _make_editor(
    client: AsyncClient, admin_headers: dict
) -> tuple[dict[str, str], uuid.UUID]:
    """Create a non-admin editor user; return (auth_header, user_id).

    The editor role carries ``upload`` and ``manage_collections`` (mirrors
    the threat actor in test_vrt_source_authz_1172.py / test_collections.py).
    """
    unique = uuid.uuid4().hex[:8]
    username = f"editor_{unique}"
    password = "TestPass1234!"  # 12-char + 3-class policy
    resp = await client.post(
        "/admin/users/",
        json={"username": username, "password": password, "role": "editor"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, f"create editor failed: {resp.text}"
    user_id = uuid.UUID(resp.json()["id"])
    login = await client.post(
        "/auth/login", data={"username": username, "password": password}
    )
    assert login.status_code == 200, f"editor login failed: {login.text}"
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, user_id


async def _create_raster_dataset(
    session, *, created_by: uuid.UUID, visibility: str
) -> uuid.UUID:
    """A raster_dataset Record + Dataset + RasterAsset, mosaic-compatible.

    Same fields as test_vrt_source_authz_1172.py's helper so validate_sources
    accepts any combination of these as VRT sources.
    """
    dataset = await create_raster_dataset(
        session,
        created_by=created_by,
        name=f"Batch authz raster {uuid.uuid4().hex[:6]}",
        description="raster source",
        theme_category=["test"],
        visibility=visibility,
        table_name=f"batch_authz_src_{uuid.uuid4().hex[:8]}",
        source_filename="s.tif",
        create_raster_asset=True,
        raster_asset_kwargs=dict(
            status="ready",
            epsg=4326,
            crs_wkt=None,
            dtype="uint8",
            nodata=None,
            band_count=1,
            res_x=0.001,
            res_y=0.001,
            width=100,
            height=100,
            is_rotated=False,
        ),
    )
    return dataset.id


async def _make_raster_sources_bulk(
    session, *, created_by: uuid.UUID, n: int
) -> list[uuid.UUID]:
    """Create n mosaic-compatible raster sources in three batched flushes.

    Client-side UUIDs avoid needing a per-row round trip to learn the
    server-default id before inserting the dependent row, so setup for
    n=500 costs 3 flushes instead of 500 — this is setup, not the code under
    test, and is not what the query-count assertions below measure.
    """
    records: list[Record] = []
    datasets: list[Dataset] = []
    assets: list[RasterAsset] = []
    dataset_ids: list[uuid.UUID] = []

    for _ in range(n):
        record_id = uuid.uuid4()
        dataset_id = uuid.uuid4()
        records.append(
            Record(
                id=record_id,
                title=f"QC bulk source {uuid.uuid4().hex[:6]}",
                summary="raster source",
                theme_category=["test"],
                visibility="public",
                record_status="published",
                record_type="raster_dataset",
                created_by=created_by,
            )
        )
        datasets.append(
            Dataset(
                id=dataset_id,
                record_id=record_id,
                table_name=f"qc_bulk_src_{uuid.uuid4().hex[:8]}",
                source_format="geotiff",
                source_filename="s.tif",
            )
        )
        assets.append(
            RasterAsset(
                dataset_id=dataset_id,
                asset_uri=f"rasters/{dataset_id}/s.cog.tif",
                storage_backend="local",
                status="ready",
                epsg=4326,
                crs_wkt=None,
                dtype="uint8",
                nodata=None,
                band_count=1,
                res_x=0.001,
                res_y=0.001,
                width=100,
                height=100,
                is_rotated=False,
            )
        )
        dataset_ids.append(dataset_id)

    session.add_all(records)
    await session.flush()
    session.add_all(datasets)
    await session.flush()
    session.add_all(assets)
    await session.flush()
    await session.commit()
    return dataset_ids


async def _make_datasets_bulk(
    session, *, created_by: uuid.UUID, n: int
) -> list[uuid.UUID]:
    """Create n plain vector datasets in two batched flushes (see above)."""
    records: list[Record] = []
    datasets: list[Dataset] = []
    dataset_ids: list[uuid.UUID] = []

    for _ in range(n):
        record_id = uuid.uuid4()
        dataset_id = uuid.uuid4()
        records.append(
            Record(
                id=record_id,
                title=f"QC bulk dataset {uuid.uuid4().hex[:6]}",
                summary="link target",
                theme_category=["test"],
                visibility="public",
                record_status="published",
                created_by=created_by,
            )
        )
        datasets.append(
            Dataset(
                id=dataset_id,
                record_id=record_id,
                table_name=f"qc_bulk_ds_{uuid.uuid4().hex[:8]}",
                source_format="geojson",
                source_filename="s.geojson",
            )
        )
        dataset_ids.append(dataset_id)

    session.add_all(records)
    await session.flush()
    session.add_all(datasets)
    await session.flush()
    await session.commit()
    return dataset_ids


class _FakeRequest:
    """Minimal stand-in for FastAPI's ``Request``.

    ``add_datasets_endpoint`` only reads ``request.client.host`` for the
    audit log entry; calling the handler directly (bypassing FastAPI's DI,
    like the read-side query-count test does for ``list_vrt_sources``)
    needs nothing more than that.
    """

    client = None


def _query_counter(session):
    """Return (sync_engine, tick_callback, get_count) for a cursor-execute counter.

    Caller registers ``tick_callback`` as a ``before_cursor_execute`` listener
    on ``sync_engine``, runs the code under test, then reads ``get_count()``.
    """
    count = 0

    def _tick(*args, **kwargs):
        nonlocal count
        count += 1

    sync_engine = session.bind.sync_engine

    def _get() -> int:
        return count

    return sync_engine, _tick, _get


async def _count_create_vrt_job_queries(
    session, source_ids: list[uuid.UUID], user
) -> int:
    request = VrtCreateRequest(
        source_dataset_ids=source_ids,
        vrt_type="mosaic",
        resolution_strategy="finest",
        title=f"QC VRT {uuid.uuid4().hex[:6]}",
    )
    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)

    sync_engine, tick, get_count = _query_counter(session)
    event.listen(sync_engine, "before_cursor_execute", tick)
    try:
        with patch("app.processing.ingest.tasks.ingest_vrt", task):
            await create_vrt_job(session, request, user)
    finally:
        event.remove(sync_engine, "before_cursor_execute", tick)
    return get_count()


async def _count_add_datasets_endpoint_queries(
    session, collection_id: uuid.UUID, dataset_ids: list[uuid.UUID], user
) -> int:
    body = CollectionAddDatasetsRequest(dataset_ids=dataset_ids)

    sync_engine, tick, get_count = _query_counter(session)
    event.listen(sync_engine, "before_cursor_execute", tick)
    try:
        await add_datasets_endpoint(
            collection_id=collection_id,
            body=body,
            request=_FakeRequest(),
            user=user,
            db=session,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", tick)
    return get_count()


# ---------------------------------------------------------------------------
# Parity: check_datasets_access_bulk vs. the scalar check_dataset_access loop
# ---------------------------------------------------------------------------


async def test_check_datasets_access_bulk_parity(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """Batch allow/deny must match check_dataset_access exactly (#1298).

    Mixed set — public, requester-owned private, other-user private, and a
    nonexistent id — proves the batch helper allows exactly the ids the
    scalar check would allow, and fails closed (404, same message) in every
    case the scalar check (or the get_dataset()-is-None branch it replaces
    for a missing id) would.
    """
    _, owner_id = await _make_editor(client, admin_auth_header)
    _, requester_id = await _make_editor(client, admin_auth_header)

    result = await test_db_session.execute(select(User).where(User.id == requester_id))
    requester = result.scalar_one()

    public_ds = await create_dataset(
        test_db_session, created_by=owner_id, name="Parity public", visibility="public"
    )
    owned_private_ds = await create_dataset(
        test_db_session,
        created_by=requester_id,
        name="Parity owned-private",
        visibility="private",
    )
    other_private_ds = await create_dataset(
        test_db_session,
        created_by=owner_id,
        name="Parity other-private",
        visibility="private",
    )
    missing_id = uuid.uuid4()

    user_roles = await get_user_roles(test_db_session, requester)

    # Scalar baseline: what check_dataset_access allows/denies per id.
    for ds in (public_ds, owned_private_ds):
        await check_dataset_access(
            test_db_session, ds, ds.id, requester, user_roles=user_roles
        )  # must not raise

    try:
        await check_dataset_access(
            test_db_session,
            other_private_ds,
            other_private_ds.id,
            requester,
            user_roles=user_roles,
        )
        raise AssertionError(
            "expected check_dataset_access to deny a foreign private dataset"
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Dataset not found"

    assert await get_dataset(test_db_session, missing_id) is None

    # Batch: the fully-accessible subset succeeds and returns exactly those ids.
    allowed = await check_datasets_access_bulk(
        test_db_session, [public_ds.id, owned_private_ds.id], requester, user_roles
    )
    assert set(allowed) == {public_ds.id, owned_private_ds.id}
    assert allowed[public_ds.id].id == public_ds.id
    assert allowed[owned_private_ds.id].id == owned_private_ds.id

    # Batch: a denied id anywhere in the set raises the same 404/message,
    # regardless of its position — the batch must not be more permissive
    # than a loop that raises on the first denial it reaches.
    for mixed in (
        [other_private_ds.id, public_ds.id, owned_private_ds.id],
        [public_ds.id, owned_private_ds.id, other_private_ds.id],
    ):
        try:
            await check_datasets_access_bulk(
                test_db_session, mixed, requester, user_roles
            )
            raise AssertionError(
                "expected check_datasets_access_bulk to deny a foreign private dataset"
            )
        except HTTPException as exc:
            assert exc.status_code == 404
            assert exc.detail == "Dataset not found"

    # Batch: a missing id is denied the same way get_dataset()-is-None was
    # denied pre-fix.
    try:
        await check_datasets_access_bulk(
            test_db_session, [public_ds.id, missing_id], requester, user_roles
        )
        raise AssertionError(
            "expected check_datasets_access_bulk to deny a nonexistent id"
        )
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "Dataset not found"


# ---------------------------------------------------------------------------
# Query-count regression
# ---------------------------------------------------------------------------


async def test_create_vrt_job_query_count_is_flat(test_db_session) -> None:
    """#1298: authorizing VRT sources must not cost one query per source.

    Pre-fix, create_vrt_job looped get_dataset()+check_dataset_access() per
    source, so the delta between 5 and 500 (the schema's cap) sources tracked
    source count almost 1:1. Post-fix the delta is flat — mirrors
    test_vrt_source_query_count.py's read-side regression test.
    """
    admin = await _admin(test_db_session)

    small_ids = await _make_raster_sources_bulk(
        test_db_session, created_by=admin.id, n=5
    )
    large_ids = await _make_raster_sources_bulk(
        test_db_session, created_by=admin.id, n=500
    )

    q_small = await _count_create_vrt_job_queries(test_db_session, small_ids, admin)
    q_large = await _count_create_vrt_job_queries(test_db_session, large_ids, admin)

    # Pre-fix: q_large - q_small would be ~495-990 (get_dataset per extra
    # source, admin short-circuits can_access_dataset with no query).
    # Batched: the delta is 0. Allow 1 for incidental variation, never O(n).
    assert q_large - q_small <= 1, (
        f"query count scales with source count: {q_small} for 5 sources, "
        f"{q_large} for 500 — the per-source get_dataset/check_dataset_access "
        f"N+1 is back"
    )


async def test_add_datasets_endpoint_query_count_is_flat(test_db_session) -> None:
    """#1298: authorizing collection link targets must not cost one query per id.

    Mirrors test_create_vrt_job_query_count_is_flat for the collection-
    linking route (100-id cap).
    """
    admin = await _admin(test_db_session)

    small_ids = await _make_datasets_bulk(test_db_session, created_by=admin.id, n=5)
    large_ids = await _make_datasets_bulk(test_db_session, created_by=admin.id, n=100)

    small_coll = await create_collection(
        test_db_session, f"QC Coll small {uuid.uuid4().hex[:6]}", None, admin.id
    )
    large_coll = await create_collection(
        test_db_session, f"QC Coll large {uuid.uuid4().hex[:6]}", None, admin.id
    )
    await test_db_session.commit()

    q_small = await _count_add_datasets_endpoint_queries(
        test_db_session, small_coll.id, small_ids, admin
    )
    q_large = await _count_add_datasets_endpoint_queries(
        test_db_session, large_coll.id, large_ids, admin
    )

    assert q_large - q_small <= 1, (
        f"query count scales with dataset count: {q_small} for 5 ids, "
        f"{q_large} for 100 — the per-id get_dataset/check_dataset_access "
        f"N+1 is back"
    )


# ---------------------------------------------------------------------------
# Fail-closed, positional coverage — a denial in the MIDDLE of a batch
# ---------------------------------------------------------------------------


async def test_create_vrt_rejects_foreign_private_source_mid_batch(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A denied source in the MIDDLE of an otherwise-owned batch still 404s.

    test_vrt_source_authz_1172.py covers a single foreign source; this closes
    the "position in the batch doesn't matter" gap the batch rewrite opens up.
    """
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)

    owned_a = await _create_raster_dataset(
        test_db_session, created_by=editor_id, visibility="private"
    )
    owned_b = await _create_raster_dataset(
        test_db_session, created_by=editor_id, visibility="private"
    )
    foreign = await _create_raster_dataset(
        test_db_session, created_by=admin_id, visibility="private"
    )
    owned_c = await _create_raster_dataset(
        test_db_session, created_by=editor_id, visibility="private"
    )

    task = MagicMock()
    task.defer_async = AsyncMock(return_value=None)
    with patch("app.processing.ingest.tasks.ingest_vrt", task):
        resp = await client.post(
            "/ingest/vrt/create",
            json={
                "source_dataset_ids": [
                    str(owned_a),
                    str(owned_b),
                    str(foreign),
                    str(owned_c),
                ],
                "vrt_type": "mosaic",
                "resolution_strategy": "finest",
                "title": "Mid-batch attack VRT",
            },
            headers=editor_headers,
        )

    assert resp.status_code in (403, 404), (
        f"expected 403/404 denying a foreign private source in the middle of "
        f"the batch, got {resp.status_code}: {resp.text}"
    )


async def test_add_datasets_rejects_foreign_private_dataset_mid_batch(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    """A denied link target in the MIDDLE of a batch still 404s, and nothing
    from the batch is linked (all-or-nothing, matching the loop it replaces).
    """
    _, owner_id = await _make_editor(client, admin_auth_header)
    attacker_headers, attacker_id = await _make_editor(client, admin_auth_header)

    a = await create_dataset(
        test_db_session, created_by=attacker_id, visibility="public"
    )
    b = await create_dataset(
        test_db_session, created_by=attacker_id, visibility="public"
    )
    private = await create_dataset(
        test_db_session, created_by=owner_id, visibility="private"
    )
    c = await create_dataset(
        test_db_session, created_by=attacker_id, visibility="public"
    )

    resp = await client.post(
        "/catalog/collections/",
        json={"name": f"Mid-batch Attacker Coll {uuid.uuid4().hex[:6]}"},
        headers=attacker_headers,
    )
    assert resp.status_code == 201
    coll_id = resp.json()["id"]

    resp = await client.post(
        f"/catalog/collections/{coll_id}/datasets/",
        json={
            "dataset_ids": [str(a.id), str(b.id), str(private.id), str(c.id)],
        },
        headers=attacker_headers,
    )
    assert resp.status_code in (403, 404), (
        f"expected 403/404 denying a foreign private dataset in the middle "
        f"of the batch, got {resp.status_code}: {resp.text}"
    )

    list_resp = await client.get(
        f"/catalog/collections/{coll_id}/datasets/", headers=attacker_headers
    )
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] == 0, (
        "a denied batch must link nothing, not the accessible prefix"
    )
