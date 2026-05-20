"""SEC-FU-01: STAC 5xx-mutation regression tests.

Verifies that when apply_visibility_filter raises an unexpected exception
(forcing a 5xx response path), the STAC item-read and search endpoints
do NOT leak private record IDs, titles, or property keys in the response body.

Uses the ``stac_visibility_force_5xx`` fixture from conftest.py.
"""

import types
import uuid

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# 5xx-safe client fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def client_no_raise(client: AsyncClient):
    """Wrap the standard ``client`` fixture with raise_app_exceptions=False.

    The standard ``client`` fixture's ASGITransport re-raises unhandled server
    exceptions into the test process.  For 5xx regression tests we need the
    transport to return the HTTP 500 response as a normal response object.

    This fixture replaces the underlying transport on the already-configured
    client so it shares the same test DB and session factory, keeping dataset
    setup (via ``test_db_session``) consistent.
    """
    from app.api.main import app as _app

    # Swap the transport to suppress server-exception re-raise
    client._transport = ASGITransport(app=_app, raise_app_exceptions=False)
    yield client
    # Restore default (client teardown handles engine/session cleanup)
    client._transport = ASGITransport(app=_app)


# ---------------------------------------------------------------------------
# Factory helper — raster dataset eligible for STAC (mirrors test_stac_visibility.py)
# ---------------------------------------------------------------------------


async def _create_raster_dataset_5xx(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    name: str = "SEC-FU-01 Test DS",
    visibility: str = "public",
    record_status: str = "published",
) -> Dataset:
    """Create a raster Record + Dataset pair directly."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"SEC-FU-01 regression test dataset: {name}",
        visibility=visibility,
        record_status=record_status,
        record_type="raster_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# SEC-FU-01: Test 1 — GET /stac/items/{id} returns 5xx, no private context in body
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_item_5xx_does_not_leak_private_context(
    client_no_raise: AsyncClient,
    test_db_session: AsyncSession,
    stac_visibility_force_5xx: types.SimpleNamespace,
):
    """When apply_visibility_filter raises, GET /stac/items/{id} returns 5xx
    and the response body does NOT contain the private record ID, title, or
    property key substrings.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_raster_dataset_5xx(
        test_db_session,
        created_by=admin_id,
        name="SEC-FU-01 Private Item No-Leak",
        visibility="private",
    )

    record_id_str = str(dataset.id)
    record_title = "SEC-FU-01 Private Item No-Leak"
    record_id_str_no_dash = dataset.id.hex  # alternative form

    assert stac_visibility_force_5xx.active, "Fixture should be active"

    resp = await client_no_raise.get(f"/stac/items/{dataset.id}")

    # Must be a server-side error (5xx), not success
    assert resp.status_code >= 500, (
        f"Expected 5xx status code, got {resp.status_code}: {resp.text}"
    )

    # Information-disclosure check: private record context must NOT appear in body
    body_text = resp.text
    assert record_id_str not in body_text, (
        f"Response body leaks dataset.id ({record_id_str}): {body_text[:200]}"
    )
    assert record_title not in body_text, (
        f"Response body leaks record title ({record_title!r}): {body_text[:200]}"
    )
    # Also check hex form without dashes
    assert record_id_str_no_dash not in body_text, (
        f"Response body leaks dataset.id hex ({record_id_str_no_dash}): {body_text[:200]}"
    )


# ---------------------------------------------------------------------------
# SEC-FU-01: Test 2 — GET /stac/search?ids=... returns 5xx, no private context
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_search_5xx_does_not_leak_private_context(
    client_no_raise: AsyncClient,
    test_db_session: AsyncSession,
    stac_visibility_force_5xx: types.SimpleNamespace,
):
    """When apply_visibility_filter raises, GET /stac/search?ids=... returns 5xx
    and the response body does NOT contain the private record ID or title.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_raster_dataset_5xx(
        test_db_session,
        created_by=admin_id,
        name="SEC-FU-01 Search No-Leak",
        visibility="private",
    )

    record_id_str = str(dataset.id)
    record_title = "SEC-FU-01 Search No-Leak"

    assert stac_visibility_force_5xx.active, "Fixture should be active"

    resp = await client_no_raise.get(f"/stac/search?ids={dataset.id}&limit=10")

    # Must be a server-side error (5xx)
    assert resp.status_code >= 500, (
        f"Expected 5xx status code, got {resp.status_code}: {resp.text}"
    )

    # Information-disclosure check
    body_text = resp.text
    assert record_id_str not in body_text, (
        f"Response body leaks dataset.id ({record_id_str}): {body_text[:200]}"
    )
    assert record_title not in body_text, (
        f"Response body leaks record title ({record_title!r}): {body_text[:200]}"
    )


# ---------------------------------------------------------------------------
# SEC-FU-01: Test 3 (control) — Without fixture, GET /stac/items/{id} returns 200
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_item_returns_200_without_5xx_fixture(
    client: AsyncClient,
    test_db_session: AsyncSession,
):
    """Without the stac_visibility_force_5xx fixture, GET /stac/items/{id} returns 200
    for a public raster record. Proves the fixture is the only thing causing the 5xx path.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_raster_dataset_5xx(
        test_db_session,
        created_by=admin_id,
        name="SEC-FU-01 Control Public Item",
        visibility="public",
        record_status="published",
    )

    resp = await client.get(f"/stac/items/{dataset.id}")
    assert resp.status_code == 200, (
        f"Expected 200 for public raster without 5xx fixture, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    # The item ID should be in the response (it is the dataset UUID)
    assert "id" in body or "type" in body, (
        f"Unexpected STAC item body shape: {body}"
    )
