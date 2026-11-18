"""The API serves under /api whether or not a proxy strips the prefix."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.main import app


async def _get(path: str):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.get(path)


@pytest.mark.anyio
async def test_collections_links_carry_the_root_path(client):
    response = await client.get("/collections")

    assert response.status_code == 200
    hrefs = [link["href"] for link in response.json()["links"]]
    assert hrefs
    assert all("/api/" in href for href in hrefs), hrefs


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/collections", "/api/collections"])
async def test_prefixed_and_unprefixed_requests_both_route(client, path):
    response = await client.get(path)

    assert response.status_code == 200


@pytest.mark.anyio
async def test_docs_reference_the_prefixed_openapi_url():
    response = await _get("/docs")

    assert response.status_code == 200
    assert "/api/openapi.json" in response.text
