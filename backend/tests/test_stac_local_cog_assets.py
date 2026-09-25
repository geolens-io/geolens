"""STAC items of local-storage rasters advertise the routes serving their files.

A local storage key has no URL of its own, so the ``data`` asset points at the
COG download route and the quicklooks at the quicklook route. ``data`` is only
advertised to a caller that route would serve: anonymous callers get public
datasets, authenticated ones also need the export capability.

Requirements: the test database (``set -a && source ../.env.test && set +a``).
"""

import copy

import pytest
from httpx import AsyncClient

from app.modules.auth.permissions import DEFAULT_ROLE_PERMISSIONS
from app.processing.raster.models import DatasetAsset

from tests.factories import create_raster_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _published_raster_with_assets(session) -> str:
    admin_id = await get_user_id(session, "admin")
    dataset = await create_raster_dataset(
        session,
        created_by=admin_id,
        name="STAC local COG assets",
        visibility="public",
        record_status="published",
        create_raster_asset=True,
    )
    base = f"rasters/{dataset.id}/abc"
    for key, href, media_type in (
        ("data", f"{base}/source.cog.tif", "image/tiff; application=geotiff"),
        ("thumbnail", f"{base}/quicklook_256.png", "image/png"),
        ("overview", f"{base}/quicklook_512.png", "image/png"),
    ):
        session.add(
            DatasetAsset(
                dataset_id=dataset.id,
                key=key,
                href=href,
                media_type=media_type,
                roles=[key],
            )
        )
    await session.commit()
    return str(dataset.id)


async def test_anonymous_item_points_at_the_serving_routes(
    client: AsyncClient, test_db_session
):
    dataset_id = await _published_raster_with_assets(test_db_session)

    resp = await client.get(f"/stac/items/{dataset_id}")

    assert resp.status_code == 200, resp.text
    assets = resp.json()["assets"]
    assert assets["data"]["href"].endswith(f"/datasets/{dataset_id}/download/cog")
    for key, size in (("thumbnail", 256), ("overview", 512)):
        href = assets[key]["href"]
        assert f"/datasets/{dataset_id}/quicklook?size={size}&" in href
        # Versioned like the tile template, so a replaced raster's images
        # are not served from the public cache.
        assert "pv=" in href
    assert not [a for a in assets.values() if "/assets/" in a["href"]]


async def test_reader_without_export_gets_no_data_asset(
    client: AsyncClient,
    test_db_session,
    admin_auth_header: dict,
    viewer_auth_header: dict,
):
    dataset_id = await _published_raster_with_assets(test_db_session)
    matrix = copy.deepcopy(DEFAULT_ROLE_PERMISSIONS)
    matrix["viewer"]["export"] = False
    resp = await client.put(
        "/settings/",
        json={"settings": {"role_permissions": matrix}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    try:
        resp = await client.get(f"/stac/items/{dataset_id}", headers=viewer_auth_header)
        assert resp.status_code == 200, resp.text
        assets = resp.json()["assets"]
        assert "data" not in assets
        assert "thumbnail" in assets
        assert "overview" in assets

        cog = await client.get(
            f"/datasets/{dataset_id}/download/cog", headers=viewer_auth_header
        )
        assert cog.status_code == 403
    finally:
        resp = await client.post(
            "/settings/reset/",
            json={"keys": ["role_permissions"]},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
