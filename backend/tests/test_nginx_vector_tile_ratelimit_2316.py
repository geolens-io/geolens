"""Edge vector admission requires a recovered identity and preserves proxy headers."""

import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.test_nginx_raster_proxy_ratelimit_1778 import (
    NGINX_CONF,
    _select,
    _tree,
)


@pytest.mark.parametrize("prefix", ["", "clusters/"])
def test_vector_locations_limit_and_preserve_proxy_inheritance(prefix):
    selected = _select(_tree(), f"/api/tiles/{prefix}data.roads/0/0/0.pbf")
    assert selected is not None
    for directive in (
        "limit_req zone=vector_anon burst=720 delay=120;",
        "limit_req_status 429;",
        "error_page 429 = @tile_rate_limited;",
        "set $upstream_api",
        "rewrite ^/api/(.*)",
        "proxy_pass",
    ):
        assert directive in selected.own
    for inherited in ("add_header", "proxy_hide_header", "proxy_cache"):
        assert inherited not in selected.own
    assert (
        "limit_req_zone $geolens_vector_limit_key zone=vector_anon:10m rate=5400r/m;"
        in NGINX_CONF.read_text()
    )


def test_other_tile_routes_do_not_use_the_vector_budget():
    selected = _select(_tree(), "/api/tiles/token/dataset/")
    assert selected is not None
    assert "limit_req" not in selected.own


def test_edge_rejection_is_retryable_and_cors_visible():
    conf = NGINX_CONF.read_text()
    block = conf.split("location @tile_rate_limited {", 1)[1].split("}", 1)[0]
    for header, value in {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Retry-After",
        "Retry-After": "2",
        "Cache-Control": "no-store",
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }.items():
        assert f'add_header {header} "{value}" always;' in block
    assert "return 429;" in block


def _render_proxy_config(cidrs):
    entrypoint = (
        Path(__file__).resolve().parents[2] / "frontend/docker-entrypoint.sh"
    ).read_text()
    section = entrypoint.split("TRUSTED_PROXY_CONFIG=", 1)[1].split(
        "\nexport API_UPSTREAM", 1
    )[0]
    return subprocess.run(
        [
            "sh",
            "-c",
            "set -e\nTRUSTED_PROXY_CONFIG="
            + section
            + '\nprintf "%s" "$TRUSTED_PROXY_CONFIG"',
        ],
        env={**os.environ, "TRUSTED_PROXY_CIDRS": cidrs},
        capture_output=True,
        text=True,
    )


def test_unconfigured_proxy_keeps_vector_limit_disabled():
    result = _render_proxy_config("")
    assert result.returncode == 0
    assert 'map $remote_addr $geolens_vector_limit_key { default ""; }' in result.stdout
    assert "set_real_ip_from" not in result.stdout


def test_explicit_trust_requires_a_recovered_address_for_the_limit():
    result = _render_proxy_config("192.0.2.10/32,2001:db8::1/128")
    assert result.returncode == 0
    assert "set_real_ip_from 192.0.2.10/32;" in result.stdout
    assert "set_real_ip_from 2001:db8::1/128;" in result.stdout
    assert "real_ip_header X-Forwarded-For;" in result.stdout
    assert "real_ip_recursive on;" in result.stdout
    assert (
        'map "$remote_addr,$realip_remote_addr" $geolens_vector_limit_key'
        in result.stdout
    )
    equality = re.search(r'"(~[^"\n]+)" "";', result.stdout)
    assert equality is not None
    pattern = equality[1][1:]
    assert re.search(pattern, "192.0.2.10,192.0.2.10")
    assert re.search(pattern, "2001:db8::1,2001:db8::1")
    assert not re.search(pattern, "198.51.100.1,192.0.2.10")
    assert "default $binary_remote_addr;" in result.stdout


def test_proxy_configuration_rejects_directive_injection():
    assert _render_proxy_config("192.0.2.10;include /tmp/evil").returncode != 0
