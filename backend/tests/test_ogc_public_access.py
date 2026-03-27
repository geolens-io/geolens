"""Tests for anonymous (public) access to OGC collection endpoints and OGC media types.

Verifies:
  - Collections endpoints are accessible without authentication
  - Anonymous users see only public datasets
  - Authenticated users see public + their private datasets
  - Feature responses use application/geo+json content type
  - /search/datasets still requires authentication
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record

from .conftest import _create_test_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    visibility: str = "public",
    record_status: str = "published",
) -> Dataset:
    """Insert a Record + Dataset pair for public access tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test dataset: {name}",
        theme_category=["test"],
        visibility=visibility,
        record_status=record_status,
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Anonymous access tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collections_list_no_auth_returns_200(client: AsyncClient):
    """GET /collections with no Authorization header returns 200."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    ids = [c["id"] for c in data["collections"]]
    assert "datasets" in ids


@pytest.mark.anyio
async def test_collection_metadata_no_auth_returns_200(client: AsyncClient):
    """GET /collections/datasets with no Authorization header returns 200."""
    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert "title" in data
    assert "links" in data


@pytest.mark.anyio
async def test_collection_items_no_auth_returns_public_only(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous GET /collections/datasets/items returns only public datasets."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    pub1 = await _create_dataset(
        session, created_by=admin_id, name="Public Alpha", visibility="public"
    )
    pub2 = await _create_dataset(
        session, created_by=admin_id, name="Public Beta", visibility="public"
    )
    priv = await _create_dataset(
        session, created_by=admin_id, name="Private Gamma", visibility="private"
    )

    resp = await client.get("/collections/datasets/items", params={"limit": 100})
    assert resp.status_code == 200
    data = resp.json()
    feature_ids = [f["id"] for f in data["features"]]

    assert str(pub1.id) in feature_ids
    assert str(pub2.id) in feature_ids
    assert str(priv.id) not in feature_ids


@pytest.mark.anyio
async def test_collection_single_item_no_auth_public_visible(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous GET /collections/datasets/items/{id} returns a public dataset."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    pub = await _create_dataset(
        session, created_by=admin_id, name="Public Visible", visibility="public"
    )

    resp = await client.get(f"/collections/datasets/items/{pub.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Feature"
    assert data["id"] == str(pub.id)


@pytest.mark.anyio
async def test_collection_single_item_no_auth_private_returns_404(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous GET /collections/datasets/items/{id} returns 404 for private dataset."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    priv = await _create_dataset(
        session, created_by=admin_id, name="Private Hidden", visibility="private"
    )

    resp = await client.get(f"/collections/datasets/items/{priv.id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_collection_items_authenticated_user_sees_more(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Authenticated user sees public datasets and their own private datasets."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    # Create a viewer user who owns a private dataset
    viewer_headers, viewer_id_str = await _create_test_user(
        client, admin_auth_header, "viewer"
    )
    viewer_id = uuid.UUID(viewer_id_str)

    pub = await _create_dataset(
        session, created_by=admin_id, name="Public Shared", visibility="public"
    )
    owned_priv = await _create_dataset(
        session,
        created_by=viewer_id,
        name="Viewer Private",
        visibility="private",
    )

    # Anonymous sees only public
    anon_resp = await client.get("/collections/datasets/items", params={"limit": 100})
    anon_ids = [f["id"] for f in anon_resp.json()["features"]]
    assert str(pub.id) in anon_ids
    assert str(owned_priv.id) not in anon_ids

    # Authenticated viewer sees public + their own private
    auth_resp = await client.get(
        "/collections/datasets/items",
        params={"limit": 100},
        headers=viewer_headers,
    )
    assert auth_resp.status_code == 200
    auth_ids = [f["id"] for f in auth_resp.json()["features"]]
    assert str(pub.id) in auth_ids
    assert str(owned_priv.id) in auth_ids


# ---------------------------------------------------------------------------
# Media type tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_items_content_type_is_geo_json(client: AsyncClient):
    """GET /collections/datasets/items returns application/geo+json content type."""
    resp = await client.get("/collections/datasets/items")
    assert resp.status_code == 200
    assert "application/geo+json" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_collection_single_item_content_type_is_geo_json(
    client: AsyncClient,
    test_db_session,
):
    """GET /collections/datasets/items/{id} returns application/geo+json content type."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    pub = await _create_dataset(
        session, created_by=admin_id, name="GeoJSON Type Test", visibility="public"
    )

    resp = await client.get(f"/collections/datasets/items/{pub.id}")
    assert resp.status_code == 200
    assert "application/geo+json" in resp.headers["content-type"]


@pytest.mark.anyio
async def test_collections_list_content_type_is_json(client: AsyncClient):
    """GET /collections returns application/json content type (NOT geo+json)."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    content_type = resp.headers["content-type"]
    assert "application/json" in content_type
    assert "geo+json" not in content_type


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_datasets_still_requires_auth(client: AsyncClient):
    """GET /search/datasets with no auth returns 401."""
    resp = await client.get("/search/datasets/")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Record status visibility tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_anonymous_cannot_see_draft_in_listings(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous GET /collections/datasets/items does not include draft datasets."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    draft = await _create_dataset(
        session,
        created_by=admin_id,
        name="Draft Dataset Anon Listing",
        visibility="public",
        record_status="draft",
    )

    resp = await client.get("/collections/datasets/items", params={"limit": 100})
    assert resp.status_code == 200
    feature_ids = [f["id"] for f in resp.json()["features"]]
    assert str(draft.id) not in feature_ids


@pytest.mark.anyio
async def test_anonymous_gets_404_on_direct_draft_access(
    client: AsyncClient,
    test_db_session,
):
    """Anonymous GET /collections/datasets/items/{id} returns 404 for draft dataset."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    draft = await _create_dataset(
        session,
        created_by=admin_id,
        name="Draft Dataset Anon Direct",
        visibility="public",
        record_status="draft",
    )

    resp = await client.get(f"/collections/datasets/items/{draft.id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_non_owner_cannot_see_others_draft(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Authenticated non-owner cannot see another user's draft in listings."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    viewer_headers, _ = await _create_test_user(client, admin_auth_header, "viewer")

    draft = await _create_dataset(
        session,
        created_by=admin_id,
        name="Admin Draft Non-Owner Test",
        visibility="public",
        record_status="draft",
    )

    resp = await client.get(
        "/collections/datasets/items",
        params={"limit": 100},
        headers=viewer_headers,
    )
    assert resp.status_code == 200
    feature_ids = [f["id"] for f in resp.json()["features"]]
    assert str(draft.id) not in feature_ids


@pytest.mark.anyio
async def test_owner_can_see_own_draft(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Owner can see their own draft dataset in listings and via direct access."""
    session = test_db_session

    viewer_headers, viewer_id_str = await _create_test_user(
        client, admin_auth_header, "viewer"
    )
    viewer_id = uuid.UUID(viewer_id_str)

    draft = await _create_dataset(
        session,
        created_by=viewer_id,
        name="Viewer Owned Draft",
        visibility="public",
        record_status="draft",
    )

    # Direct access — authoritative check
    direct_resp = await client.get(
        f"/collections/datasets/items/{draft.id}",
        headers=viewer_headers,
    )
    assert direct_resp.status_code == 200

    # Listings — draft should appear, but may be beyond limit if many
    # datasets exist from other tests in the session
    list_resp = await client.get(
        "/collections/datasets/items",
        params={"limit": 100},
        headers=viewer_headers,
    )
    assert list_resp.status_code == 200
    feature_ids = [f["id"] for f in list_resp.json()["features"]]
    if list_resp.json().get("numberMatched", len(feature_ids)) <= 100:
        assert str(draft.id) in feature_ids


@pytest.mark.anyio
async def test_admin_sees_all_drafts(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Admin can see any draft dataset via direct access."""
    session = test_db_session

    viewer_headers, viewer_id_str = await _create_test_user(
        client, admin_auth_header, "viewer"
    )
    viewer_id = uuid.UUID(viewer_id_str)

    draft = await _create_dataset(
        session,
        created_by=viewer_id,
        name="Viewer Draft Admin Sees",
        visibility="public",
        record_status="draft",
    )

    # Direct access — authoritative check
    direct_resp = await client.get(
        f"/collections/datasets/items/{draft.id}",
        headers=admin_auth_header,
    )
    assert direct_resp.status_code == 200

    # Listings
    list_resp = await client.get(
        "/collections/datasets/items",
        params={"limit": 100},
        headers=admin_auth_header,
    )
    assert list_resp.status_code == 200
    feature_ids = [f["id"] for f in list_resp.json()["features"]]
    if list_resp.json().get("numberMatched", len(feature_ids)) <= 100:
        assert str(draft.id) in feature_ids
