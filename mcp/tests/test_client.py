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

# A valid UUID (with hex letters, so .upper() exercises canonicalization) —
# the detail routes (dataset/map/collection) take uuid.UUID.
DS = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


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


def test_search_datasets_drops_collection_features():
    # /search/datasets augments page 0 with up to 5 `collection` records whose
    # ids 404 in the dataset tools; the wrapper must strip them.
    payload = {
        "type": "FeatureCollection",
        "numberReturned": 3,
        "numberMatched": 3,
        "features": [
            {
                "id": "d1",
                "properties": {"record_type": "vector_dataset", "type": "dataset"},
            },
            {
                "id": "c1",
                "properties": {"record_type": "collection", "type": "collection"},
            },
            {
                "id": "r1",
                "properties": {"record_type": "raster_dataset", "type": "dataset"},
            },
        ],
    }
    api, _ = _api(_ok(payload))
    out = api.search_datasets("parks")
    ids = [f["id"] for f in out["features"]]
    assert ids == ["d1", "r1"]  # collection c1 removed; raster kept
    assert out["numberReturned"] == 2  # count kept consistent


@pytest.mark.parametrize(
    ("source_format", "record_type", "expected_origin"),
    [
        ("gpkg", "vector_dataset", "upload"),
        (None, "vector_dataset", "postgis"),
        ("wfs", "vector_dataset", "service"),
        ("stac", "raster_dataset", "stac"),
        ("created", "vector_dataset", "created"),
        ("geotiff", "vrt_dataset", None),
    ],
)
def test_search_datasets_adds_stable_source_state_summary(
    source_format, record_type, expected_origin
):
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "d1",
                "properties": {
                    "record_type": record_type,
                    "source_format": source_format,
                    "source_freshness": "overdue",
                },
            }
        ],
    }
    api, seen = _api(_ok(payload))

    properties = api.search_datasets("roads")["features"][0]["properties"]

    assert len(seen) == 1  # never fan out into one detail request per result
    assert properties["source_origin"] == expected_origin
    assert properties["source_freshness"] == "overdue"
    assert properties["source_health"] is None
    assert properties["source_health_detail"] is None
    assert properties["last_checked_at"] is None
    assert properties["last_refreshed_at"] is None


def test_search_datasets_prefers_future_summary_state_and_drops_raw_pointers():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "d1",
                "properties": {
                    "origin": "service",
                    "source_format": "wfs",
                    "source_health": "inaccessible",
                    "source_health_detail": "unauthorized",
                    "last_checked_at": "2026-08-08T12:00:00Z",
                    "last_refreshed_at": "2026-08-01T12:00:00Z",
                    "origin_uri": "https://provider.example/private-layer",
                    "origin_ref": {
                        "kind": "service",
                        "url": "https://provider.example/wfs?token=secret",
                    },
                    "source_url": "https://provider.example/?token=secret",
                },
            }
        ],
    }
    api, _ = _api(_ok(payload))

    properties = api.search_datasets("roads")["features"][0]["properties"]

    assert properties["source_origin"] == "service"
    assert properties["source_health"] == "inaccessible"
    assert properties["source_health_detail"] == "unauthorized"
    assert properties["last_checked_at"] == "2026-08-08T12:00:00Z"
    assert properties["last_refreshed_at"] == "2026-08-01T12:00:00Z"
    assert not {"origin_uri", "origin_ref", "source_url"} & properties.keys()


def test_get_dataset_schema_has_no_trailing_slash():
    api, seen = _api(_ok({"id": DS, "column_info": []}))
    api.get_dataset_schema(DS)
    assert seen[-1].url.path == f"/api/datasets/{DS}"  # detail route: NO trailing slash


def test_get_dataset_schema_surfaces_real_source_state_without_provider_pointers():
    payload = {
        "id": DS,
        "source_format": "wfs",
        "origin": "service",
        "origin_uri": "https://provider.example/private-layer",
        "origin_ref": {
            "kind": "service",
            "url": "https://provider.example/wfs?token=secret",
        },
        "source_url": "https://provider.example/?token=secret",
        "source_freshness": "overdue",
        "source_health": "inaccessible",
        "source_health_detail": "unauthorized",
        "last_checked_at": "2026-08-08T12:00:00Z",
        "last_refreshed_at": "2026-08-01T12:00:00Z",
    }
    api, _ = _api(_ok(payload))

    detail = api.get_dataset_schema(DS)

    assert detail["source_origin"] == "service"
    assert detail["source_freshness"] == "overdue"
    assert detail["source_health"] == "inaccessible"
    assert detail["source_health_detail"] == "unauthorized"
    assert detail["last_checked_at"] == "2026-08-08T12:00:00Z"
    assert detail["last_refreshed_at"] == "2026-08-01T12:00:00Z"
    assert not {"origin_uri", "origin_ref", "source_url"} & detail.keys()


def test_get_features_uses_ogc_items_and_bbox():
    api, seen = _api(_ok({"type": "FeatureCollection"}))
    api.get_features(DS, limit=3, bbox="-1,-1,1,1")
    req = seen[-1]
    assert req.url.path == f"/api/collections/{DS}/items"
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
    api, seen = _api(_ok({"id": DS, "layers": []}))
    api.get_map(DS)
    assert seen[-1].url.path == f"/api/maps/{DS}"


def test_none_params_are_dropped():
    api, seen = _api(_ok({"maps": []}))
    api.list_maps()  # search=None must not appear
    assert "search" not in seen[-1].url.params


def test_ids_must_be_uuids_no_path_redirection():
    # Model-controlled ids are validated as UUIDs before touching the path, so
    # traversal ("../admin/users"), bare dot-segments (".", "..") that httpx
    # would normalize into a different endpoint, and any non-UUID garbage are
    # all rejected before a request is made.
    for bad in ("../admin/users", ".", "..", "abc", "", "1 or 1=1"):
        for call in (
            lambda a, x=bad: a.get_dataset_schema(x),
            lambda a, x=bad: a.get_map(x),
            lambda a, x=bad: a.get_features(x),
        ):
            api, seen = _api(_ok({}))
            with pytest.raises(ValueError, match="UUID"):
                call(api)
            assert seen == []  # no request left the client


def test_valid_uuid_is_canonicalized():
    api, seen = _api(_ok({"id": DS}))
    api.get_dataset_schema(DS.upper())  # accepts any UUID spelling
    assert seen[-1].url.path == f"/api/datasets/{DS}"  # canonical (lowercased)


def test_http_error_surfaces_detail():
    def handler(request):
        return httpx.Response(404, json={"detail": "Dataset not found"})

    api, _ = _api(handler)
    with pytest.raises(RuntimeError) as exc:
        api.get_dataset_schema(DS)
    assert "404" in str(exc.value)
    assert "Dataset not found" in str(exc.value)


# --- query (#565: the one POST — read-only semantically) ---


def test_query_posts_json_to_the_slashed_route():
    api, seen = _api(
        _ok({"columns": ["n"], "rows": [[1]], "row_count": 1, "truncated": False})
    )
    out = api.query(
        "SELECT count(*) AS n FROM data.roads",
        restrict_tables=["roads"],
        row_limit=5,
    )
    assert out["rows"] == [[1]]
    req = seen[-1]
    assert req.method == "POST"
    # Trailing slash is load-bearing: it is the canonical registration AND the
    # exact template of the read_only-key carve-out pair (#875/#565).
    assert req.url.path == "/api/query/"
    import json as _json

    body = _json.loads(req.content.decode())
    assert body == {
        "sql": "SELECT count(*) AS n FROM data.roads",
        "restrict_tables": ["roads"],
        "row_limit": 5,
    }


def test_query_defaults_row_limit():
    api, seen = _api(_ok({"columns": [], "rows": [], "row_count": 0, "truncated": False}))
    api.query("SELECT gid FROM data.roads", restrict_tables=["roads"])
    import json as _json

    assert _json.loads(seen[-1].content.decode())["row_limit"] == 100


def test_query_error_surfaces_sanitized_detail():
    def handler(request):
        return httpx.Response(
            422, json={"detail": "Query references the same table too many times"}
        )

    api, _ = _api(handler)
    with pytest.raises(RuntimeError) as exc:
        api.query("SELECT 1", restrict_tables=["roads"])
    assert "422" in str(exc.value)
    assert "same table too many times" in str(exc.value)


def test_query_stringifies_structured_validation_detail():
    # FastAPI 422 body-validation errors carry a LIST detail; the client must
    # surface something readable rather than crash on .get of a list element.
    def handler(request):
        return httpx.Response(
            422,
            json={
                "detail": [
                    {
                        "loc": ["body", "restrict_tables"],
                        "msg": "Field required",
                        "type": "missing",
                    }
                ]
            },
        )

    api, _ = _api(handler)
    with pytest.raises(RuntimeError) as exc:
        api.query("SELECT 1", restrict_tables=[])
    assert "422" in str(exc.value)
    assert "Field required" in str(exc.value)
