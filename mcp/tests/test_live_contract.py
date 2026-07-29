# SPDX-License-Identifier: Apache-2.0
"""Live-contract tier for the MCP server (test #827, live tier).

Runs every MCP tool in server.py against a REAL GeoLens API and asserts the
read contract's shape — key presence and types, not exact data — so a backend
change that breaks what the tools return fails here instead of shipping
invisibly. The mock tier (test_client.py / test_server.py) pins paths, params,
and registration; only this tier sees the actual response bodies.

Skipped unless ``RUN_MCP_LIVE=1`` (mirrors the ``RUN_AI_EVALS`` gate for the
backend's live evals); once explicitly enabled, an unreachable target FAILS
the tier rather than skipping it back to green. Environment:

    GEOLENS_INSTANCE          target instance (default http://localhost:8080,
                              the dev stack)
    GEOLENS_ADMIN_USERNAME /  credentials used to log in, seed the fixtures,
    GEOLENS_ADMIN_PASSWORD    and authenticate the tools (default admin/admin,
                              the dev stack admin)

Local run (dev stack up):  ``make mcp-live-test``
CI: the mcp-test job boots db+api via compose and runs this tier against it.

The tier seeds its own fixtures over the API — one empty "created" dataset
(plus a probe feature when the dataset-editing admin flag is on) and one map —
and deletes them in teardown, so it is safe against a long-lived dev instance.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import httpx
import pytest

from geolens_mcp import server
from geolens_mcp.client import DEFAULT_TIMEOUT, normalize_instance_url

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MCP_LIVE") != "1",
    reason="live MCP contract tier; set RUN_MCP_LIVE=1 with a running instance",
)

DEFAULT_INSTANCE = "http://localhost:8080"


@dataclass
class SeededInstance:
    dataset_id: str
    dataset_title: str
    map_id: str
    map_name: str
    marker: str
    feature_inserted: bool


@pytest.fixture(scope="session")
def live():
    """Log in, seed one dataset + one map, point server.py's client at them."""
    base = normalize_instance_url(
        os.environ.get("GEOLENS_INSTANCE") or DEFAULT_INSTANCE
    )
    username = os.environ.get("GEOLENS_ADMIN_USERNAME", "admin")
    password = os.environ.get("GEOLENS_ADMIN_PASSWORD", "admin")

    http = httpx.Client(base_url=base, timeout=DEFAULT_TIMEOUT)
    try:
        # Form-encoded login (OAuth2PasswordRequestForm) — JSON bodies 422.
        resp = http.post(
            "/auth/login", data={"username": username, "password": password}
        )
    except httpx.HTTPError as exc:
        # The tier was EXPLICITLY enabled (RUN_MCP_LIVE=1) — an unreachable
        # target must fail loudly, never skip-to-green (#866 review). The only
        # skip path is the env-var-absent pytestmark above.
        pytest.fail(f"RUN_MCP_LIVE=1 but no reachable GeoLens API at {base}: {exc}")
    assert resp.status_code == 200, f"admin login failed: HTTP {resp.status_code}"
    token = resp.json()["access_token"]
    http.headers["Authorization"] = f"Bearer {token}"

    # Unique per run: dodges the catalog/search caches and makes the seeded
    # records findable by free text without depending on instance content.
    marker = f"mcplive{uuid.uuid4().hex[:10]}"
    dataset_title = f"MCP live contract {marker}"
    map_name = f"MCP live contract map {marker}"

    created = http.post(
        "/datasets/create/",
        json={"title": dataset_title, "columns": [{"name": "name", "type": "text"}]},
    )
    assert created.status_code == 201, f"dataset seed failed: {created.text[:200]}"
    dataset_id = str(created.json()["id"])

    # Probe feature so get_features has a real row to shape-check. The write
    # path is gated by the enable_dataset_editing admin flag — a 403 means the
    # flag is off, and the tier falls back to the empty-collection contract.
    feature = http.post(
        f"/datasets/{dataset_id}/features/",
        json={
            "geometry": {"type": "Point", "coordinates": [-73.97, 40.78]},
            "properties": {"name": marker},
        },
    )
    assert feature.status_code in (201, 403), (
        f"feature seed failed unexpectedly: HTTP {feature.status_code} "
        f"{feature.text[:200]}"
    )

    mapped = http.post("/maps/", json={"name": map_name})
    assert mapped.status_code == 201, f"map seed failed: {mapped.text[:200]}"
    map_id = str(mapped.json()["id"])

    # Route the server module's lazily-built client at the same instance with
    # the admin JWT (the seeds are private, so anonymous would 404 them).
    saved_env = {
        key: os.environ.get(key)
        for key in ("GEOLENS_INSTANCE", "GEOLENS_TOKEN", "GEOLENS_API_KEY")
    }
    os.environ["GEOLENS_INSTANCE"] = base
    os.environ["GEOLENS_TOKEN"] = token
    os.environ.pop("GEOLENS_API_KEY", None)
    server._api = None

    try:
        yield SeededInstance(
            dataset_id=dataset_id,
            dataset_title=dataset_title,
            map_id=map_id,
            map_name=map_name,
            marker=marker,
            feature_inserted=feature.status_code == 201,
        )
    finally:
        server._api = None
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        try:
            # Dataset delete requires title confirmation in the body.
            http.request(
                "DELETE",
                f"/datasets/{dataset_id}",
                json={"confirm_title": dataset_title},
            )
            http.delete(f"/maps/{map_id}")
        except httpx.HTTPError:
            pass  # best-effort cleanup; the run's verdict is already decided
        http.close()


def _assert_feature_collection(fc):
    assert fc["type"] == "FeatureCollection"
    assert isinstance(fc["features"], list)
    assert isinstance(fc["numberReturned"], int)
    assert isinstance(fc["numberMatched"], int)


def test_search_datasets_contract(live):
    fc = server.search_datasets(live.marker, limit=50)
    _assert_feature_collection(fc)
    by_id = {}
    for feature in fc["features"]:
        assert feature.get("id"), "every search feature must carry a usable id"
        props = feature.get("properties")
        assert isinstance(props, dict)
        # The wrapper strips catalog collections (their ids 404 in the other
        # tools) — none may leak through.
        assert props.get("record_type") != "collection"
        by_id[str(feature["id"])] = props
    assert live.dataset_id in by_id, "seeded dataset is findable by its marker"
    assert by_id[live.dataset_id].get("title") == live.dataset_title


def test_get_dataset_schema_contract(live):
    schema = server.get_dataset_schema(live.dataset_id)
    assert str(schema["id"]) == live.dataset_id
    assert schema["title"] == live.dataset_title
    # The keys the tool description promises the agent: columns, geometry
    # type, CRS/SRID, feature count, and spatial extent.
    for key in ("column_info", "geometry_type", "srid", "feature_count", "extent_bbox"):
        assert key in schema, key
    columns = {c["name"]: c for c in schema["column_info"] or []}
    assert "name" in columns, "seeded user column is reported"
    assert columns["name"].get("type"), "columns carry a type"
    assert isinstance(schema["feature_count"], int)


def test_get_features_contract(live):
    fc = server.get_features(live.dataset_id, limit=5)
    _assert_feature_collection(fc)
    if live.feature_inserted:
        assert fc["numberReturned"] >= 1
        feature = fc["features"][0]
        assert feature["type"] == "Feature"
        assert feature.get("id") is not None
        assert (feature.get("geometry") or {}).get("type") == "Point"
        assert (feature.get("properties") or {}).get("name") == live.marker
    else:
        assert fc["features"] == []  # empty dataset still returns the contract


def test_get_features_bbox_filter_contract(live):
    # A bbox that cannot contain the probe point must still return the
    # FeatureCollection contract with zero rows (exercises the bbox param).
    fc = server.get_features(live.dataset_id, limit=5, bbox="10,10,11,11")
    _assert_feature_collection(fc)
    assert fc["features"] == []


def test_list_maps_contract(live):
    out = server.list_maps(search=live.map_name, limit=50)
    assert isinstance(out["maps"], list)
    assert isinstance(out["total"], int)
    match = next((m for m in out["maps"] if str(m["id"]) == live.map_id), None)
    assert match is not None, "seeded map is findable via the search filter"
    # The read-only metadata the tool description promises.
    for key in ("name", "visibility", "layer_count"):
        assert key in match, key
    assert match["name"] == live.map_name


def test_get_map_contract(live):
    result = server.get_map(live.map_id)
    assert str(result["id"]) == live.map_id
    assert result["name"] == live.map_name
    # Layers, view state, basemap, and terrain config per the tool description.
    for key in (
        "layers",
        "layer_count",
        "visibility",
        "basemap_style",
        "terrain_config",
        "center_lng",
        "center_lat",
        "zoom",
        "bearing",
        "pitch",
    ):
        assert key in result, key
    assert isinstance(result["layers"], list)
