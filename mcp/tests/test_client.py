# SPDX-License-Identifier: Apache-2.0
"""Self-checks for the read-only GeoLens API client.

Uses httpx.MockTransport so no live instance is needed — asserts each tool hits
the right resolved path (incl. the load-bearing `/api` prefix and trailing-slash
rules) with the right query params, and that HTTP errors surface cleanly.
"""

from __future__ import annotations

import httpx
import pytest

from geolens_mcp.client import (
    ConfigError,
    GeoLensReadOnlyAPI,
    normalize_instance_url,
)


# --- normalize_instance_url (the /api footgun-guard) ---


def test_normalize_appends_api():
    assert (
        normalize_instance_url("https://x.example.com") == "https://x.example.com/api"
    )


def test_normalize_is_idempotent_and_strips_trailing_slash():
    assert (
        normalize_instance_url("https://x.example.com/api/")
        == "https://x.example.com/api"
    )


def test_normalize_rejects_non_http():
    with pytest.raises(ConfigError):
        normalize_instance_url("ftp://x.example.com")
    with pytest.raises(ConfigError):
        normalize_instance_url("   ")


# --- API methods against a mock transport ---


def _api(handler) -> tuple[GeoLensReadOnlyAPI, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.Client(
        base_url="http://test/api", transport=httpx.MockTransport(_record)
    )
    return GeoLensReadOnlyAPI(http), seen


def _ok(payload):
    return lambda request: httpx.Response(200, json=payload)


def test_search_datasets_path_and_params():
    api, seen = _api(_ok({"type": "FeatureCollection", "features": []}))
    out = api.search_datasets("roads", limit=5, offset=10)
    assert out == {"type": "FeatureCollection", "features": []}
    req = seen[-1]
    assert req.url.path == "/api/search/datasets"  # /api preserved, no trailing slash
    assert req.url.params["q"] == "roads"
    assert req.url.params["limit"] == "5"
    assert req.url.params["offset"] == "10"


def test_get_dataset_schema_has_no_trailing_slash():
    api, seen = _api(_ok({"id": "abc", "column_info": []}))
    api.get_dataset_schema("abc")
    assert seen[-1].url.path == "/api/datasets/abc"  # detail route: NO trailing slash


def test_get_features_uses_ogc_items_and_bbox():
    api, seen = _api(_ok({"type": "FeatureCollection"}))
    api.get_features("d1", limit=3, bbox="-1,-1,1,1")
    req = seen[-1]
    assert req.url.path == "/api/collections/d1/items"
    assert req.url.params["limit"] == "3"
    assert req.url.params["bbox"] == "-1,-1,1,1"


def test_list_maps_pages_with_skip_not_offset():
    api, seen = _api(_ok({"maps": [], "total": 0}))
    api.list_maps(search="city", limit=25, offset=50)
    req = seen[-1]
    assert req.url.path == "/api/maps"
    assert req.url.params["search"] == "city"
    assert req.url.params["skip"] == "50"  # this endpoint uses `skip`
    assert "offset" not in req.url.params


def test_get_map_has_no_trailing_slash():
    api, seen = _api(_ok({"id": "m1", "layers": []}))
    api.get_map("m1")
    assert seen[-1].url.path == "/api/maps/m1"


def test_none_params_are_dropped():
    api, seen = _api(_ok({"maps": []}))
    api.list_maps()  # search=None must not appear
    assert "search" not in seen[-1].url.params


def test_ids_are_path_escaped_against_traversal():
    # Model-controlled ids must not be able to traverse out of the resource
    # path. Without escaping, httpx collapses `..` and this would hit
    # GET /api/admin/users with the caller's credentials.
    for call in (
        lambda a: a.get_dataset_schema("../admin/users"),
        lambda a: a.get_map("../admin/users"),
        lambda a: a.get_features("../../admin/users"),
    ):
        api, seen = _api(_ok({}))
        call(api)
        raw = seen[-1].url.raw_path.decode()
        assert "/api/admin/users" not in raw
        assert (
            raw.startswith("/api/datasets/")
            or raw.startswith("/api/collections/")
            or raw.startswith("/api/maps/")
        )


def test_http_error_surfaces_detail():
    def handler(request):
        return httpx.Response(404, json={"detail": "Dataset not found"})

    api, _ = _api(handler)
    with pytest.raises(RuntimeError) as exc:
        api.get_dataset_schema("missing")
    assert "404" in str(exc.value)
    assert "Dataset not found" in str(exc.value)
