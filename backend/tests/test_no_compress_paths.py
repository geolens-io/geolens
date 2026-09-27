"""Gzip is dropped from Accept-Encoding on the export and 3D Tiles paths, and only there."""

import pytest

from app.api.no_compress_paths import NoCompressionByPathMiddleware


async def _accept_encoding_seen(path: str) -> bytes | None:
    seen: dict[str, bytes | None] = {}

    async def downstream(scope, receive, send) -> None:
        seen["value"] = dict(scope["headers"]).get(b"accept-encoding")

    scope = {
        "type": "http",
        "path": path,
        "headers": [(b"accept-encoding", b"gzip, br")],
    }
    await NoCompressionByPathMiddleware(downstream)(scope, None, None)
    return seen["value"]


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/datasets/7/export", id="export"),
        pytest.param("/api/datasets/7/export/", id="api-export"),
        pytest.param("/datasets/7/tiles3d/tileset.json", id="tiles3d"),
        pytest.param("/api/datasets/7/tiles3d/tiles/0.glb", id="api-tiles3d"),
    ],
)
async def test_gzip_is_dropped_on_the_uncompressed_routes(path: str) -> None:
    assert await _accept_encoding_seen(path) == b"br"


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/datasets/7/dcat", id="dcat"),
        pytest.param("/datasets/7/features", id="features"),
        pytest.param("/datasets/7/tiles3d", id="tiles3d-bare"),
        pytest.param("/datasets/7/tiles3dx/tileset.json", id="tiles3d-lookalike"),
        pytest.param("/datasets/7/export/extra", id="export-suffix"),
        pytest.param("/v2/datasets/7/tiles3d/tileset.json", id="other-prefix"),
    ],
)
async def test_gzip_is_kept_everywhere_else(path: str) -> None:
    assert await _accept_encoding_seen(path) == b"gzip, br"
