"""DB-backed regression tests for VRT source authorization (Phase 1172).

SEC-C (HIGH) — write-time hole: an editor (default ``upload`` permission) could
mosaic ANOTHER user's PRIVATE raster into a VRT they own, then read the victim's
pixels back through raster tile/quicklook/COG endpoints that authorize only the
attacker-owned VRT. VRT member pixels are compiled into ONE served asset and
cannot be filtered at read time, so the fix authorizes every source dataset at
write/link time (``create_vrt_job`` + ``add_vrt_source``).

SEC-E (MED) — read-time backstop: SEC-C only authorizes at link time and there
is no migration re-authorizing existing ``vrt_source_links``, so legacy / authz-
drift links still leak member title/CRS/resolution/extent/health via
``list_vrt_sources`` / ``get_vrt_status``. A per-member non-raising filter drops
those rows.

Attack + SEC-E tests fail on main ``407c0688`` (no per-source authz); the GUARD
tests (owned sources → 202) pass before and after the fix.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import RasterAsset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one().id


async def _make_editor(
    client: AsyncClient, admin_headers: dict
) -> tuple[dict[str, str], uuid.UUID]:
    """Create a non-admin editor user; return (auth_header, user_id).

    The editor role carries the ``upload`` permission (so it clears
    ``require_permission("upload")`` on the VRT endpoints) but is NOT admin —
    exactly the threat actor for SEC-C.
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
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "private",
    record_status: str = "published",
) -> uuid.UUID:
    """Create a raster_dataset Record + Dataset + RasterAsset.

    Metadata is mosaic-compatible (crs_wkt=None so ``_check_crs`` skips it,
    identical dtype, single band, matching resolution) so ``validate_sources``
    returns [] for a pair of these — letting the GUARD tests reach 202.
    """
    record = Record(
        title=f"VRT Authz Raster {uuid.uuid4().hex[:6]}",
        summary="raster source for VRT authz tests",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        record_type="raster_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"vrt_authz_src_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.flush()

    asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/abc123/source.cog.tif",
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
    session.add(asset)
    await session.flush()
    await session.commit()
    return dataset.id


async def _create_vrt_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "private",
    record_status: str = "published",
) -> uuid.UUID:
    """Create a ready vrt_dataset Record + Dataset + RasterAsset."""
    record = Record(
        title=f"VRT Authz VRT {uuid.uuid4().hex[:6]}",
        summary="VRT for authz tests",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        record_type="vrt_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"vrt_authz_vrt_{uuid.uuid4().hex[:8]}",
        # VRT datasets carry no source_format (avoids chk_datasets_source_format);
        # mirrors app/processing/ingest/tasks_vrt.py.
        source_format=None,
        source_filename=None,
    )
    session.add(dataset)
    await session.flush()

    asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/vrt/source.vrt",
        storage_backend="local",
        status="ready",
        vrt_type="mosaic",
        resolution_strategy="finest",
        epsg=4326,
        band_count=1,
    )
    session.add(asset)
    await session.flush()
    await session.commit()
    return dataset.id


async def _link_source(
    session, vrt_id: uuid.UUID, source_id: uuid.UUID, position: int
) -> None:
    """Raw-insert a vrt_source_links row (mirrors add_vrt_source's INSERT) to
    simulate a legacy / pre-authz link."""
    await session.execute(
        text(
            "INSERT INTO catalog.vrt_source_links"
            "(vrt_dataset_id, source_dataset_id, position) "
            "VALUES (:vrt, :src, :pos)"
        ),
        {"vrt": str(vrt_id), "src": str(source_id), "pos": position},
    )
    await session.commit()


def _patch_defer():
    """Patch both VRT defer tasks so the success path returns 202 without a
    live Procrastinate connection. Used by GUARD tests (and the attack tests so
    they cleanly return 202 on unfixed main rather than a 503 defer failure)."""
    create_task = MagicMock()
    create_task.defer_async = AsyncMock(return_value=None)
    regen_task = MagicMock()
    regen_task.defer_async = AsyncMock(return_value=None)
    return (
        patch("app.processing.ingest.tasks.ingest_vrt", create_task),
        patch("app.processing.ingest.router.regenerate_vrt", regen_task),
    )


# ---------------------------------------------------------------------------
# SEC-C — write-time authorization (create_vrt_job)
# ---------------------------------------------------------------------------


async def test_create_vrt_rejects_foreign_private_sources(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Editor POSTs create with two admin-owned PRIVATE rasters → 403/404.

    Fails on main (202): create_vrt_job authorizes no source.
    """
    admin_id = await _get_admin_id(test_db_session)
    src_a = await _create_raster_dataset(test_db_session, created_by=admin_id)
    src_b = await _create_raster_dataset(test_db_session, created_by=admin_id)

    editor_headers, _ = await _make_editor(client, admin_auth_header)

    p_create, p_regen = _patch_defer()
    with p_create, p_regen:
        resp = await client.post(
            "/ingest/vrt/create",
            json={
                "source_dataset_ids": [str(src_a), str(src_b)],
                "vrt_type": "mosaic",
                "resolution_strategy": "finest",
                "title": "Attack VRT",
            },
            headers=editor_headers,
        )

    assert resp.status_code in (403, 404), (
        f"expected 403/404 denying foreign private sources, got "
        f"{resp.status_code}: {resp.text}"
    )


async def test_add_vrt_source_rejects_foreign_private_source(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Editor owns a ready VRT, POSTs add-source with an admin-owned PRIVATE
    raster → 403/404.

    Fails on main: add_vrt_source authorizes no source.
    """
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)

    vrt_id = await _create_vrt_dataset(test_db_session, created_by=editor_id)
    foreign_src = await _create_raster_dataset(test_db_session, created_by=admin_id)

    p_create, p_regen = _patch_defer()
    with p_create, p_regen:
        resp = await client.post(
            f"/ingest/vrt/{vrt_id}/sources/",
            json={"source_dataset_id": str(foreign_src)},
            headers=editor_headers,
        )

    assert resp.status_code in (403, 404), (
        f"expected 403/404 denying a foreign private source, got "
        f"{resp.status_code}: {resp.text}"
    )


async def test_create_vrt_allows_owned_sources(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """GUARD: admin owns two private rasters, POSTs create → 202. Passes both
    on main and after the fix (admin is always authorized)."""
    admin_id = await _get_admin_id(test_db_session)
    src_a = await _create_raster_dataset(test_db_session, created_by=admin_id)
    src_b = await _create_raster_dataset(test_db_session, created_by=admin_id)

    p_create, p_regen = _patch_defer()
    with p_create, p_regen:
        resp = await client.post(
            "/ingest/vrt/create",
            json={
                "source_dataset_ids": [str(src_a), str(src_b)],
                "vrt_type": "mosaic",
                "resolution_strategy": "finest",
                "title": "Owned VRT (admin)",
            },
            headers=admin_auth_header,
        )

    assert resp.status_code == 202, (
        f"admin VRT creation from owned sources must succeed, got "
        f"{resp.status_code}: {resp.text}"
    )


async def test_create_vrt_allows_editor_owned_sources(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """GUARD: editor owns two private rasters → 202. Proves authorization is by
    ownership, not admin-ness (the fix must not over-block non-admin owners)."""
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    src_a = await _create_raster_dataset(test_db_session, created_by=editor_id)
    src_b = await _create_raster_dataset(test_db_session, created_by=editor_id)

    p_create, p_regen = _patch_defer()
    with p_create, p_regen:
        resp = await client.post(
            "/ingest/vrt/create",
            json={
                "source_dataset_ids": [str(src_a), str(src_b)],
                "vrt_type": "mosaic",
                "resolution_strategy": "finest",
                "title": "Owned VRT (editor)",
            },
            headers=editor_headers,
        )

    assert resp.status_code == 202, (
        f"editor VRT creation from its OWN sources must succeed, got "
        f"{resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# SEC-E — read-time per-member filter (legacy / authz-drift links)
# ---------------------------------------------------------------------------


async def test_list_vrt_sources_omits_unauthorized_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Editor-owned VRT with a legacy link to an admin-owned PRIVATE raster:
    GET /datasets/{vrt}/vrt-sources/ omits the unauthorized member.

    Fails on main: list_vrt_sources returns every linked member.
    """
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)

    vrt_id = await _create_vrt_dataset(test_db_session, created_by=editor_id)
    owned_src = await _create_raster_dataset(test_db_session, created_by=editor_id)
    foreign_src = await _create_raster_dataset(test_db_session, created_by=admin_id)
    await _link_source(test_db_session, vrt_id, owned_src, 0)
    await _link_source(test_db_session, vrt_id, foreign_src, 1)

    resp = await client.get(f"/datasets/{vrt_id}/vrt-sources/", headers=editor_headers)
    assert resp.status_code == 200, resp.text
    listed = {s["dataset_id"] for s in resp.json()["sources"]}

    assert str(foreign_src) not in listed, (
        "SEC-E: unauthorized private member must be omitted from vrt-sources"
    )
    assert str(owned_src) in listed, "authorized member must still be listed"


async def test_get_vrt_status_omits_unauthorized_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Same setup: GET /datasets/{vrt}/vrt/status/ omits the unauthorized
    member from source_health (source_count stays the raw total).

    Fails on main: get_vrt_status reports health for every linked member.
    """
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)

    vrt_id = await _create_vrt_dataset(test_db_session, created_by=editor_id)
    owned_src = await _create_raster_dataset(test_db_session, created_by=editor_id)
    foreign_src = await _create_raster_dataset(test_db_session, created_by=admin_id)
    await _link_source(test_db_session, vrt_id, owned_src, 0)
    await _link_source(test_db_session, vrt_id, foreign_src, 1)

    resp = await client.get(f"/datasets/{vrt_id}/vrt/status/", headers=editor_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    health_ids = {h["dataset_id"] for h in body["source_health"]}

    assert str(foreign_src) not in health_ids, (
        "SEC-E: unauthorized private member must be omitted from source_health"
    )
    assert str(owned_src) in health_ids, "authorized member must still be reported"
    # source_count intentionally reflects the raw total link count (documented
    # divergence) — both links are counted even though one is filtered out.
    assert body["source_count"] == 2
