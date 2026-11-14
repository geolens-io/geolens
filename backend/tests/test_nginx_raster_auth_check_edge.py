"""The public edge refuses the raster authorization check, which only the tile proxy calls."""

import pytest

from tests.test_nginx_raster_proxy_ratelimit_1778 import _select, _tree


@pytest.mark.parametrize(
    "path",
    [
        "/api/tiles/raster-auth-check/",
        "/api/tiles/raster-auth-check",
        "/api/api/tiles/raster-auth-check/",
    ],
)
def test_the_edge_refuses_the_raster_auth_check(path):
    selected = _select(_tree(), path)

    assert selected is not None
    assert "return 404;" in selected.own
    assert "proxy_pass" not in selected.own


def test_the_raster_proxy_it_backs_still_reaches_the_api():
    selected = _select(
        _tree(),
        "/api/tiles/raster-proxy/00000000-0000-0000-0000-000000000000/1/2/3.png",
    )

    assert selected is not None
    assert "proxy_pass" in selected.own
