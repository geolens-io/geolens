"""OGC items pages carry a weak ETag and answer If-None-Match with 304."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient

from tests.factories import get_user_id
from tests.test_ogc_features import _cleanup_table, _create_test_table_and_dataset

pytestmark = pytest.mark.anyio

_BBOX = "-73.985,40.705,-73.895,40.805"


@pytest.fixture
async def points(test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session, created_by=admin_id, with_features=12
    )
    yield dataset
    await _cleanup_table(test_db_session, dataset.table_name)


async def _etag(client: AsyncClient, url: str, **kwargs) -> str:
    resp = await client.get(url, **kwargs)
    assert resp.status_code == 200, resp.text
    return resp.headers["etag"]


async def test_a_200_carries_a_weak_etag_and_revalidation_cache_control(
    client: AsyncClient, points
) -> None:
    resp = await client.get(f"/collections/{points.id}/items")

    assert resp.status_code == 200
    assert resp.headers["etag"].startswith('W/"')
    assert resp.headers["cache-control"] == "no-cache"
    assert "authorization" in resp.headers["vary"].lower()


async def test_a_credentialed_request_gets_private_cache_control(
    client: AsyncClient, points, admin_auth_header
) -> None:
    resp = await client.get(
        f"/collections/{points.id}/items", headers=admin_auth_header
    )

    assert resp.headers["cache-control"] == "private, no-cache"


async def test_a_matching_tag_answers_304_without_a_body_or_the_feature_query(
    client: AsyncClient, points
) -> None:
    url = f"/collections/{points.id}/items"
    tag = await _etag(client, url)

    with patch(
        "app.standards.ogc.router.get_features", side_effect=AssertionError("queried")
    ):
        resp = await client.get(url, headers={"If-None-Match": tag})

    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == tag


async def test_if_none_match_accepts_a_list_a_strong_spelling_and_a_star(
    client: AsyncClient, points
) -> None:
    url = f"/collections/{points.id}/items"
    tag = await _etag(client, url)
    opaque = tag.removeprefix("W/")

    for header in (f'"nope", {tag}', opaque, "*"):
        resp = await client.get(url, headers={"If-None-Match": header})
        assert resp.status_code == 304, header
    stale = await client.get(url, headers={"If-None-Match": '"nope"'})
    assert stale.status_code == 200


@pytest.mark.parametrize(
    "variant",
    [
        {"limit": 5},
        {"offset": 2},
        {"startindex": 2},
        {"bbox": _BBOX},
        {"filter": "name = 'Feature 1'"},
        {"f": "json"},
        {"status": "active"},
        {"include_geometry": "false"},
        {"after_gid": 3},
    ],
)
async def test_the_tag_changes_with_the_query(
    client: AsyncClient, points, variant: dict
) -> None:
    url = f"/collections/{points.id}/items"
    base = await _etag(client, url)

    assert await _etag(client, url, params=variant) != base


async def test_startindex_and_offset_share_a_tag(client: AsyncClient, points) -> None:
    url = f"/collections/{points.id}/items"

    assert await _etag(client, url, params={"offset": 2}) == await _etag(
        client, url, params={"startindex": 2}
    )


async def test_the_tag_changes_with_the_base_url_of_the_links(
    client: AsyncClient, points
) -> None:
    url = f"/collections/{points.id}/items"
    base = await _etag(client, url)

    with patch(
        "app.standards.ogc.router.get_public_api_url",
        return_value="https://example.test/other",
    ):
        other = await _etag(client, url)

    assert other != base


async def test_a_feature_edit_changes_the_tag(
    client: AsyncClient, points, admin_auth_header
) -> None:
    url = f"/collections/{points.id}/items"
    tag = await _etag(client, url)

    edit = await client.patch(
        f"/datasets/{points.id}/features/1",
        json={"properties": {"name": "Renamed"}},
        headers=admin_auth_header,
    )
    assert edit.status_code == 200, edit.text

    resp = await client.get(url, headers={"If-None-Match": tag})
    assert resp.status_code == 200
    assert resp.headers["etag"] != tag


async def test_a_recounted_feature_total_changes_the_tag(
    client: AsyncClient, points, test_db_session
) -> None:
    url = f"/collections/{points.id}/items"
    tag = await _etag(client, url)

    points.feature_count = (points.feature_count or 0) + 5
    await test_db_session.commit()

    assert await _etag(client, url) != tag


async def test_a_private_collection_refuses_an_anonymous_caller_with_a_guessed_tag(
    client: AsyncClient, test_db_session, admin_auth_header
) -> None:
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_test_table_and_dataset(
        test_db_session, created_by=admin_id, visibility="private", with_features=3
    )
    try:
        url = f"/collections/{dataset.id}/items"
        tag = await _etag(client, url, headers=admin_auth_header)

        for header in (tag, "*"):
            resp = await client.get(url, headers={"If-None-Match": header})
            assert resp.status_code == 404, header
    finally:
        await _cleanup_table(test_db_session, dataset.table_name)


@pytest.mark.parametrize("header", ["*", None])
async def test_an_invalid_filter_answers_400_whatever_if_none_match_says(
    client: AsyncClient, points, header
) -> None:
    url = f"/collections/{points.id}/items"
    tag = await _etag(client, url)
    headers = {"If-None-Match": header or tag}

    bare = await client.get(url, params={"filter": "nope ??"})
    resp = await client.get(url, params={"filter": "nope ??"}, headers=headers)

    assert bare.status_code == 400
    assert resp.status_code == 400


async def test_a_registered_table_gets_no_validator_and_ignores_if_none_match(
    client: AsyncClient, points, test_db_session
) -> None:
    points.source_format = None
    points.origin_ref = None
    await test_db_session.commit()
    url = f"/collections/{points.id}/items"

    resp = await client.get(url, headers={"If-None-Match": "*"})

    assert resp.status_code == 200
    assert "etag" not in resp.headers
    assert "cache-control" not in resp.headers
