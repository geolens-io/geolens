"""Hashed assets send one Cache-Control header, and unknown raster tile paths 404."""

import re

from tests.repo_paths import repo_root
from tests.test_nginx_raster_tile_404_1516 import _location_block, _without_comments

CONF = _without_comments((repo_root(__file__) / "frontend" / "nginx.conf").read_text())


def test_assets_send_a_single_cache_control_header():
    block = _location_block(CONF, r"location\s+/assets/")

    # `expires` adds its own Cache-Control, so combining it with add_header
    # sends two.
    assert not re.search(r"\bexpires\b", block)
    headers = re.findall(r'add_header\s+Cache-Control\s+"([^"]+)"', block)
    assert headers == ["public, max-age=31536000, immutable"]
    for security in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"):
        assert f"add_header {security}" in block


def test_no_location_combines_expires_with_cache_control():
    for match in re.finditer(r"location\s+[^{]+\{", CONF):
        block = _location_block(CONF, re.escape(match.group(0).split("{")[0]))
        assert not (
            re.search(r"\bexpires\b", block) and "add_header Cache-Control" in block
        ), match.group(0)


def test_unknown_raster_tiles_path_answers_404_not_the_shell():
    block = _location_block(CONF, r"location\s+/raster-tiles/\s")

    assert re.search(r"return\s+404\s*;", block)
