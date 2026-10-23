# SPDX-License-Identifier: Apache-2.0
"""The MCP server reads maps with their restricted visibility."""

import pytest

from geolens_mcp.client import build_httpx_client


@pytest.mark.parametrize(
    "credential", [{}, {"GEOLENS_API_KEY": "key"}, {"GEOLENS_TOKEN": "tok"}]
)
def test_every_client_sends_the_map_visibility_opt_in(monkeypatch, credential):
    monkeypatch.setenv("GEOLENS_INSTANCE", "https://geolens.example.com")
    monkeypatch.delenv("GEOLENS_API_KEY", raising=False)
    monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
    for name, value in credential.items():
        monkeypatch.setenv(name, value)

    http = build_httpx_client()

    assert http.headers["X-GeoLens-Map-Visibility"] == "restricted"
