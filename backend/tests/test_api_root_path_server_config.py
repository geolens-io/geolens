"""The /api root path comes from the server, not from the FastAPI constructor."""

import re
from pathlib import Path

import pytest

from app.api.main import app

_DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"


def test_the_app_leaves_the_root_path_to_the_server():
    assert app.root_path == ""
    assert app.servers == [{"url": "/api"}]


def test_the_api_image_starts_uvicorn_under_api():
    """uvicorn reads UVICORN_ROOT_PATH, so a Compose or chart command that omits
    --root-path still serves under /api."""
    stages = re.split(r"^FROM ", _DOCKERFILE.read_text(), flags=re.M)
    api_stage = next(s for s in stages if s.startswith("backend-base AS api\n"))
    assert re.search(r"^ENV UVICORN_ROOT_PATH=/api$", api_stage, flags=re.M)


@pytest.mark.anyio
async def test_collections_links_carry_the_root_path(client):
    response = await client.get("/collections")

    assert response.status_code == 200
    hrefs = [link["href"] for link in response.json()["links"]]
    assert hrefs
    assert all("/api/" in href for href in hrefs), hrefs
