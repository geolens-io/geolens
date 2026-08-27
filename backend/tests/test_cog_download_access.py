"""Regression tests for the anonymous-access asymmetry between
``/datasets/{id}/export`` (vector) and ``/datasets/{id}/download/cog``
(raster).

Before this fix, ``download_cog``'s own visibility gate
(``check_dataset_access_or_anonymous`` + a public-visibility
defense-in-depth check) was correct and already matched
``/export``'s — but a plain anonymous GET (no Authorization header, no
minted ``?token=``) never reached it: the ``_resolve_download_user``
dependency unconditionally raised 401 first. That meant a public+published
raster's tiles rendered anonymously while its COG could only be downloaded
after a separate authenticated or token-minting round trip, breaking the
"download this and open it in QGIS" flow for exactly the showcase rasters.

Mirrors ``test_export_access.py``'s EXP-01/EXP-02 matrix for the COG route:
  - anon + public+published -> 200
  - anon + public-unpublished (record_status="internal") -> {401,403,404}
  - anon + private -> {401,403,404} (404 specifically: existence hiding)
  - anon + restricted -> {401,403,404}
  - non-owner authenticated (viewer, not the admin owner) + private ->
    {401,403,404}

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
  - Run with: set -a && source ../.env.test && set +a
               uv run pytest tests/test_cog_download_access.py -v
"""

from httpx import AsyncClient

from app.platform.storage import get_storage

from tests.factories import create_raster_dataset, get_user_id

_COG_BYTES = b"GEOLENS-TEST-COG-BYTES" * 64


async def _raster_dataset_with_bytes(session, *, visibility, record_status, created_by):
    """A raster Dataset + RasterAsset with real bytes in local storage.

    Mirrors ``test_cog_head_ranges_1528.py``'s ``_raster_dataset`` fixture:
    the conftest points the storage singleton at a ``LocalStorageProvider``
    rooted in the per-test staging dir, so ``get_storage().put`` writes real
    bytes a 200 response actually streams back.
    """
    dataset = await create_raster_dataset(
        session,
        created_by=created_by,
        name=f"CogDownloadAccess {visibility}/{record_status}",
        visibility=visibility,
        record_status=record_status,
        create_raster_asset=True,
    )
    # create_raster_dataset doesn't return the RasterAsset row directly, so
    # look up the asset_uri it stamped and write real bytes for it.
    from sqlalchemy import select

    from app.processing.raster.models import RasterAsset

    result = await session.execute(
        select(RasterAsset).where(RasterAsset.dataset_id == dataset.id)
    )
    raster_asset = result.scalar_one()
    await get_storage().put(raster_asset.asset_uri, _COG_BYTES)
    return dataset


# ---------------------------------------------------------------------------
# Positive guard
# ---------------------------------------------------------------------------


async def test_anon_cog_download_public_published_allowed(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous GET (no header, no ?token=) of a public+published raster's
    COG must return 200 and stream the stored bytes back — the exact case
    the reported asymmetry broke.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _raster_dataset_with_bytes(
        test_db_session,
        visibility="public",
        record_status="published",
        created_by=admin_id,
    )

    resp = await client.get(f"/datasets/{ds.id}/download/cog")

    assert resp.status_code == 200, (
        f"Expected 200 for anon download of public+published raster COG, "
        f"got {resp.status_code}: {resp.text}"
    )
    assert resp.content == _COG_BYTES
    assert resp.headers.get("content-type") == "image/tiff"


# ---------------------------------------------------------------------------
# Deny matrix
# ---------------------------------------------------------------------------


async def test_anon_cog_download_public_unpublished_denied(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous download of a public but unpublished (internal) raster must
    be denied — status in {401, 403, 404}.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="CogDownloadPublicUnpublishedDenied",
        visibility="public",
        record_status="internal",  # unpublished
        create_raster_asset=True,
    )

    resp = await client.get(f"/datasets/{ds.id}/download/cog")

    assert resp.status_code in {401, 403, 404}, (
        f"Expected denial (401/403/404) for anon download of public+unpublished "
        f"raster, got {resp.status_code}: {resp.text}"
    )


async def test_anon_cog_download_private_denied(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous download of a private+published raster must be denied with
    404 specifically — check_dataset_access_or_anonymous hides existence for
    anon callers on non-public datasets, so this must not leak a 401/403 that
    confirms the dataset exists.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="CogDownloadPrivateDenied",
        visibility="private",
        record_status="published",
        create_raster_asset=True,
    )

    resp = await client.get(f"/datasets/{ds.id}/download/cog")

    assert resp.status_code == 404, (
        f"Expected 404 (existence-hiding) for anon download of private raster, "
        f"got {resp.status_code}: {resp.text}"
    )


async def test_anon_cog_download_restricted_denied(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous download of a restricted+published raster must be denied —
    status in {401, 403, 404}.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="CogDownloadRestrictedDenied",
        visibility="restricted",
        record_status="published",
        create_raster_asset=True,
    )

    resp = await client.get(f"/datasets/{ds.id}/download/cog")

    assert resp.status_code in {401, 403, 404}, (
        f"Expected denial (401/403/404) for anon download of restricted raster, "
        f"got {resp.status_code}: {resp.text}"
    )


async def test_non_owner_cog_download_private_denied(
    client: AsyncClient,
    test_db_session,
    viewer_auth_header: dict,
):
    """Authenticated non-owner (viewer) download of a private raster must be
    denied — status in {401, 403, 404}, per the existing authenticated-branch
    policy (check_dataset_access raises 404 for non-owner denials).

    The dataset is owned by admin; the viewer is a distinct user who is
    neither the owner nor an admin.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="CogDownloadNonOwnerPrivateDenied",
        visibility="private",
        record_status="published",
        create_raster_asset=True,
    )

    resp = await client.get(
        f"/datasets/{ds.id}/download/cog",
        headers=viewer_auth_header,
    )

    assert resp.status_code in {401, 403, 404}, (
        f"Expected denial (401/403/404) for non-owner (viewer) download of "
        f"private raster, got {resp.status_code}: {resp.text}"
    )
