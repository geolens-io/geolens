"""/metrics answers a direct scrape and nothing the public edge relays."""

import pytest
from httpx import ASGITransport, AsyncClient

from tests.test_nginx_raster_proxy_ratelimit_1778 import _select, _tree

_FORWARDING = [
    {"X-Forwarded-For": "203.0.113.7"},
    {"X-Real-IP": "203.0.113.7"},
    {"Forwarded": "for=203.0.113.7"},
]


async def _get(path: str, headers: dict[str, str] | None = None):
    from app.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.get(path, headers=headers)


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/metrics", "/api/metrics"])
async def test_a_direct_scrape_is_answered(path):
    resp = await _get(path)

    assert resp.status_code == 200
    assert "http_requests_total" in resp.text


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/metrics", "/api/metrics"])
@pytest.mark.parametrize("headers", _FORWARDING)
async def test_a_relayed_scrape_is_refused(path, headers):
    resp = await _get(path, headers)

    assert resp.status_code == 404
    assert "http_requests_total" not in resp.text


@pytest.mark.parametrize(
    "route",
    [
        "/metrics",
        "/internal/raster-relay/token/raster.tif",
        "/tiles/raster-proxy/00000000-0000-0000-0000-000000000000/1/2/3.png",
        "/tiles/data.roads/0/0/0.pbf",
        "/health",
    ],
)
def test_the_edge_refuses_the_root_path_spelling_of_every_route(route):
    """The api routes ``/api/<route>`` as well as ``/<route>``, so ``/api/api/``
    would reach any route past the edge's per-path blocks and tile limits."""
    selected = _select(_tree(), "/api/api" + route)

    assert selected is not None
    assert "return 404;" in selected.own
    assert "proxy_pass" not in selected.own
