"""STAC item search: filter forwarding and next-page handling."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import AsyncClient

from app.modules.catalog.sources.adapters.stac import search_stac_items
from app.platform.security import SSRFError

CATALOG = "https://stac.example.com/v1"


def _capturing_client(payload: dict, sent: list[httpx.Request]) -> httpx.AsyncClient:
    raw = json.dumps(payload).encode()

    async def _chunks():
        yield raw

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=_chunks())

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def _search(payload: dict, **kwargs) -> tuple[dict, list[httpx.Request]]:
    sent: list[httpx.Request] = []
    with patch(
        "app.modules.catalog.sources.adapters.stac._make_client",
        return_value=_capturing_client(payload, sent),
    ):
        result = await search_stac_items(CATALOG, **kwargs)
    return result, sent


class TestSearchRequestBuilding:
    async def test_bbox_and_datetime_are_forwarded(self):
        _, sent = await _search(
            {"features": []},
            collections=["c1"],
            bbox=[-74.3, 40.5, -73.7, 40.9],
            datetime_range="2024-01-01T00:00:00Z/..",
        )
        body = json.loads(sent[0].content)
        assert sent[0].method == "POST"
        assert body["bbox"] == [-74.3, 40.5, -73.7, 40.9]
        assert body["datetime"] == "2024-01-01T00:00:00Z/.."
        assert body["collections"] == ["c1"]


class TestNextPageDerivation:
    async def test_post_next_link_is_returned(self):
        result, _ = await _search(
            {
                "features": [],
                "links": [
                    {
                        "rel": "next",
                        "method": "POST",
                        "href": f"{CATALOG}/search",
                        "body": {"next": "abc"},
                        "merge": True,
                    }
                ],
            }
        )
        assert result["next_page"] == {
            "method": "POST",
            "href": f"{CATALOG}/search",
            "body": {"next": "abc"},
            "merge": True,
        }

    async def test_get_next_link_defaults_and_resolves_relative_href(self):
        result, _ = await _search(
            {"features": [], "links": [{"rel": "next", "href": "search?token=t1"}]}
        )
        assert result["next_page"]["method"] == "GET"
        assert result["next_page"]["href"] == f"{CATALOG}/search?token=t1"
        assert result["next_page"]["body"] is None

    async def test_last_page_has_no_next_page(self):
        result, _ = await _search({"features": [], "links": []})
        assert result["next_page"] is None

    async def test_off_origin_next_link_is_dropped(self):
        result, _ = await _search(
            {
                "features": [],
                "links": [{"rel": "next", "href": "https://evil.example.net/search"}],
            }
        )
        assert result["next_page"] is None

    async def test_merged_post_follow_up_keeps_the_original_filters(self):
        next_page = {
            "method": "POST",
            "href": f"{CATALOG}/search",
            "body": {"next": "abc"},
            "merge": True,
        }
        _, sent = await _search(
            {"features": []},
            collections=["c1"],
            bbox=[1, 2, 3, 4],
            next_page=next_page,
        )
        body = json.loads(sent[0].content)
        assert body["next"] == "abc"
        assert body["collections"] == ["c1"]
        assert body["bbox"] == [1, 2, 3, 4]

    async def test_unmerged_post_follow_up_sends_only_the_link_body(self):
        next_page = {
            "method": "POST",
            "href": f"{CATALOG}/search",
            "body": {"next": "abc", "limit": 5},
            "merge": False,
        }
        _, sent = await _search(
            {"features": []}, collections=["c1"], next_page=next_page
        )
        assert json.loads(sent[0].content) == {"next": "abc", "limit": 5}

    async def test_get_follow_up_is_a_bodyless_get_of_the_link(self):
        next_page = {
            "method": "GET",
            "href": f"{CATALOG}/search?token=t1",
            "body": None,
            "merge": False,
        }
        _, sent = await _search({"features": []}, next_page=next_page)
        assert sent[0].method == "GET"
        assert str(sent[0].url) == f"{CATALOG}/search?token=t1"
        assert sent[0].content == b""


@pytest.fixture
def mock_search():
    with (
        patch(
            "app.modules.catalog.sources.stac_router.validate_url_for_ssrf",
            new_callable=AsyncMock,
        ) as ssrf,
        patch(
            "app.modules.catalog.sources.stac_router.search_stac_items",
            new_callable=AsyncMock,
        ) as search,
    ):
        search.return_value = {
            "items": [],
            "matched": 0,
            "returned": 0,
            "next_page": None,
        }
        yield search, ssrf


class TestNextPageRoute:
    async def _post(self, client, headers, next_page):
        return await client.post(
            "/services/stac/search",
            json={"url": CATALOG, "next_page": next_page},
            headers=headers,
        )

    async def test_next_link_on_another_host_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, mock_search
    ):
        search, _ = mock_search
        resp = await self._post(
            client,
            admin_auth_header,
            {"method": "GET", "href": "https://evil.example.net/search?t=1"},
        )
        assert resp.status_code == 400
        search.assert_not_called()

    async def test_next_link_on_another_port_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, mock_search
    ):
        search, _ = mock_search
        resp = await self._post(
            client,
            admin_auth_header,
            {"method": "GET", "href": "https://stac.example.com:8443/v1/search"},
        )
        assert resp.status_code == 400
        search.assert_not_called()

    async def test_next_link_that_fails_ssrf_validation_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, mock_search
    ):
        search, ssrf = mock_search
        ssrf.side_effect = [None, SSRFError("blocked")]
        resp = await self._post(
            client,
            admin_auth_header,
            {"method": "GET", "href": f"{CATALOG}/search?t=1"},
        )
        assert resp.status_code == 400
        search.assert_not_called()

    async def test_same_origin_next_link_is_followed_and_returned(
        self, client: AsyncClient, admin_auth_header: dict, mock_search
    ):
        search, _ = mock_search
        following = {
            "method": "POST",
            "href": f"{CATALOG}/search",
            "body": {"next": "xyz"},
            "merge": True,
        }
        search.return_value["next_page"] = following
        resp = await self._post(
            client,
            admin_auth_header,
            {"method": "POST", "href": f"{CATALOG}/search", "body": {"next": "abc"}},
        )
        assert resp.status_code == 200
        assert resp.json()["next_page"] == following
        sent = search.call_args.kwargs["next_page"]
        assert sent["href"] == f"{CATALOG}/search"
        assert sent["body"] == {"next": "abc"}
