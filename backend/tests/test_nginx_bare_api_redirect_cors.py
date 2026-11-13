"""nginx answers the bare ``/api`` with a relative 301 to ``/api/`` that a cross-origin page can follow."""

import re

from tests.repo_paths import repo_root
from tests.test_nginx_assets_cors_1515 import _location_block, _without_comments

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

BARE_API_LOCATION = r"location\s+=\s+/api\s*\{"


def _bare_api_block() -> str:
    return _location_block(_without_comments(NGINX_CONF.read_text()), BARE_API_LOCATION)


def test_the_bare_api_redirect_is_readable_cross_origin() -> None:
    block = _bare_api_block()

    assert re.search(
        r'add_header\s+Access-Control-Allow-Origin\s+"\*"\s+always\s*;', block
    ), "a browser following /api -> /api/ from another origin needs the wildcard"
    assert re.search(r"return\s+301\s+/api/\$is_args\$args\s*;", block), (
        "the bare /api must redirect to the relative /api/ with its query string"
    )


def test_the_bare_api_redirect_keeps_the_security_headers() -> None:
    block = _bare_api_block()

    for header, value in (
        ("X-Frame-Options", "SAMEORIGIN"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ):
        assert re.search(
            rf'add_header\s+{re.escape(header)}\s+"{re.escape(value)}"\s+always\s*;',
            block,
        ), f"location = /api must re-declare {header}; add_header disables inheritance"
