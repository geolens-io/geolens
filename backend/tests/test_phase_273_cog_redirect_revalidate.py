"""SEC-06: download_cog re-validates SSRF on remote-backend redirect.

Pins the v13.13 closure of M-68. DNS records can change between import
time and download time — a hostname that was a public CDN may now resolve
to 169.254.169.254 or 10.x. Re-running validate_url_for_ssrf at download
time defeats the DNS-rebinding TOCTOU window.
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient
from sqlalchemy import select

from app.modules.auth.models import User
from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.sources.security import SSRFError
from app.processing.raster.models import RasterAsset


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one().id


async def _create_remote_raster_dataset(
    session,
    *,
    created_by: uuid.UUID,
    asset_uri: str = "https://example.com/data.tif",
) -> tuple[Record, Dataset, RasterAsset]:
    """Create a Record + Dataset + RasterAsset with storage_backend='remote'."""
    record = Record(
        title=f"Remote COG Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for SEC-06 cog redirect re-validation tests",
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
        table_name=f"remote_cog_test_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.flush()

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=asset_uri,
        storage_backend="remote",
    )
    session.add(raster_asset)
    await session.flush()

    await session.commit()
    await session.refresh(dataset)
    await session.refresh(raster_asset)
    return record, dataset, raster_asset


async def _create_local_raster_dataset(
    session,
    *,
    created_by: uuid.UUID,
) -> tuple[Record, Dataset, RasterAsset]:
    """Create a Record + Dataset + RasterAsset with storage_backend='local'."""
    record = Record(
        title=f"Local COG Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for SEC-06 local-backend regression tests",
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
        table_name=f"local_cog_test_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.flush()

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/abc123/source.cog.tif",
        storage_backend="local",
    )
    session.add(raster_asset)
    await session.flush()

    await session.commit()
    await session.refresh(dataset)
    await session.refresh(raster_asset)
    return record, dataset, raster_asset


# ---------------------------------------------------------------------------
# SEC-06 tests
# ---------------------------------------------------------------------------


async def test_remote_redirect_blocked_when_ssrf_fails(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A remote COG whose asset_uri now resolves to a private IP returns 403."""
    admin_id = await _get_admin_id(test_db_session)
    _, dataset, _ = await _create_remote_raster_dataset(
        test_db_session,
        created_by=admin_id,
        asset_uri="https://example.com/data.tif",
    )

    # Patch the validator at the SSRF source module — the new code does a
    # function-scope `from app.modules.catalog.sources.security import ...`
    # so we patch at the source.
    with patch(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        new=AsyncMock(
            side_effect=SSRFError(
                "URLs targeting private/internal networks are not allowed"
            )
        ),
    ):
        resp = await client.get(
            f"/datasets/{dataset.id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert "ssrf" in resp.json()["detail"].lower()


async def test_remote_redirect_allowed_when_ssrf_passes(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A remote COG whose asset_uri resolves to a public IP returns 302."""
    admin_id = await _get_admin_id(test_db_session)
    _, dataset, raster_asset = await _create_remote_raster_dataset(
        test_db_session,
        created_by=admin_id,
        asset_uri="https://example.com/data.tif",
    )

    with patch(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        new=AsyncMock(return_value=None),  # passes
    ):
        resp = await client.get(
            f"/datasets/{dataset.id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location == raster_asset.asset_uri


async def test_remote_redirect_blocked_for_disallowed_scheme(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A remote COG with file:// scheme (or any non-http(s)) returns 403."""
    admin_id = await _get_admin_id(test_db_session)
    _, dataset, _ = await _create_remote_raster_dataset(
        test_db_session,
        created_by=admin_id,
        asset_uri="https://example.com/data.tif",
    )

    with patch(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        new=AsyncMock(side_effect=SSRFError("Only http and https URLs are allowed")),
    ):
        resp = await client.get(
            f"/datasets/{dataset.id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )
    assert resp.status_code == 403


async def test_local_storage_unaffected_by_ssrf_revalidation(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """storage_backend='local' is unaffected — never calls validate_url_for_ssrf."""
    admin_id = await _get_admin_id(test_db_session)
    _, dataset, _ = await _create_local_raster_dataset(
        test_db_session, created_by=admin_id
    )

    mock_ssrf = AsyncMock()
    with patch(
        "app.modules.catalog.sources.security.validate_url_for_ssrf",
        new=mock_ssrf,
    ):
        resp = await client.get(
            f"/datasets/{dataset.id}/download/cog",
            headers=admin_auth_header,
            follow_redirects=False,
        )
    # Status: 200 (streamed) or 503 (storage error in test env) or 404 — not 403.
    # The local-storage code path will likely fail to find the file in the
    # test staging dir, but the SSRF re-validation MUST NOT have been invoked.
    assert resp.status_code != 403
    assert mock_ssrf.call_count == 0
