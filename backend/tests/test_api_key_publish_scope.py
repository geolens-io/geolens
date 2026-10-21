"""Publish-scoped API keys: what a desktop or browser publishing client may do.

A ``publish`` key may read, upload, apply manifests and write metadata and
maps, because each of those adds something or can be undone. It may not
delete anything, write features, or reach admin and key routes, since none of
those can be undone.
"""

from __future__ import annotations

import re
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.modules.auth.dependencies import (
    _PUBLISH_KEY_ROUTES,
    _READ_ONLY_KEY_EXEMPT_ROUTES,
    _publish_key_may_call,
)
from app.platform.request_credential import DATASET_WRITE_KEY_ROUTES
from app.processing.ingest.manifest_schemas import ManifestApplyResponse
from tests import test_api_key_dataset_scope as _dataset_scope
from tests.test_api_key_scope_875 import _mounted_route_pairs
from tests.test_manifest_apply_api import valid_manifest_payload

PUBLISH_REFUSAL = {
    "code": "api_key_scope",
    "message": (
        "This API key has the publish scope, which can't delete data, write "
        "features or reach admin and key routes"
    ),
}

# Whole families a publish key never reaches, by path prefix.
_REFUSED_PREFIXES: dict[str, str] = {
    "/admin/": "admin routes",
    "/auth/": "sign-in, session and key routes",
    "/settings": "admin settings",
    "/config-ops/": "admin configuration import",
    "/ai/": "AI authoring, not publishing",
    "/services/": "server-side fetches of remote services",
    "/layers": "column DDL, which can't be undone",
}

# Every other unsafe route a publish key is refused, with the reason. Exact in
# both directions below, so a new route has to be classified here or in
# _PUBLISH_KEY_ROUTES rather than silently refused.
_REFUSED_ROUTES: dict[tuple[str, str], str] = {
    **dict.fromkeys(
        [
            ("POST", "/catalog/collections"),
            ("POST", "/catalog/collections/"),
            ("PATCH", "/catalog/collections/{collection_id}"),
        ],
        "collection management, not publishing",
    ),
    **dict.fromkeys(
        [
            ("PATCH", "/datasets/{dataset_id}/status"),
            ("PATCH", "/datasets/{dataset_id}/status/"),
            ("PATCH", "/datasets/{dataset_id}/target-status"),
            ("PATCH", "/datasets/{dataset_id}/target-status/"),
        ],
        "workflow transitions stay with full keys",
    ),
    ("PATCH", "/maps/{map_id}"): "transfers map ownership",
    **dict.fromkeys(
        [
            ("POST", "/maps/{map_id}/embed-tokens"),
            ("POST", "/maps/{map_id}/embed-tokens/"),
            ("PATCH", "/maps/{map_id}/embed-tokens/{token_id}"),
            ("PATCH", "/maps/{map_id}/embed-tokens/{token_id}/"),
            ("POST", "/datasets/{dataset_id}/api-keys"),
        ],
        "mints or changes a credential",
    ),
    **dict.fromkeys(
        [
            ("POST", "/maps/{map_id}/layers"),
            ("POST", "/maps/{map_id}/layers/"),
            ("PATCH", "/maps/{map_id}/layers"),
            ("PATCH", "/maps/{map_id}/layers/"),
            ("POST", "/maps/{map_id}/layers/bulk-delete"),
        ],
        "layer edits in place; publishing writes the whole map",
    ),
    ("PATCH", "/maps/{map_id}/share"): "changes or revokes a share link",
    ("PATCH", "/maps/{map_id}/share/"): "changes or revokes a share link",
    **dict.fromkeys(
        [
            ("POST", "/records/{record_id}/contacts"),
            ("POST", "/records/{record_id}/contacts/"),
            ("PATCH", "/records/{record_id}/contacts/{contact_id}"),
            ("PATCH", "/records/{record_id}/contacts/{contact_id}/"),
            ("POST", "/records/{record_id}/distributions"),
            ("POST", "/records/{record_id}/distributions/"),
            ("PATCH", "/records/{record_id}/distributions/{distribution_id}"),
            ("PATCH", "/records/{record_id}/distributions/{distribution_id}/"),
            ("PUT", "/records/{record_id}/translations/{language}"),
            ("PUT", "/records/{record_id}/translations/{language}/"),
            ("POST", "/datasets/{dataset_id}/relationships"),
            ("POST", "/datasets/{dataset_id}/relationships/"),
            ("POST", "/datasets/{dataset_id}/analysis/materialize"),
            ("POST", "/datasets/{dataset_id}/analysis/materialize/"),
            ("POST", "/datasets/{dataset_id}/analysis/preview"),
            ("POST", "/datasets/{dataset_id}/analysis/preview/"),
            ("POST", "/datasets/{dataset_id}/reupload/presigned"),
            ("POST", "/datasets/{dataset_id}/reupload/presigned/{job_id}/complete"),
            ("POST", "/maps/icons"),
            ("POST", "/maps/{map_id}/duplicate"),
            ("POST", "/maps/{map_id}/duplicate/"),
            ("POST", "/search/saved"),
            ("POST", "/search/saved/"),
        ],
        "not needed to publish",
    ),
    ("POST", "/datasets/bulk-delete"): "deletes datasets",
    ("POST", "/datasets/bulk-delete/"): "deletes datasets",
    ("POST", "/datasets/create"): "creates an empty dataset to edit features in",
    ("POST", "/datasets/create/"): "creates an empty dataset to edit features in",
    **dict.fromkeys(
        [
            ("POST", "/datasets/{dataset_id}/attributes/{attribute_id}/reset"),
            ("POST", "/datasets/{dataset_id}/attributes/{attribute_id}/reset/"),
        ],
        "discards edited attribute metadata",
    ),
    **dict.fromkeys(
        [
            ("POST", "/datasets/{dataset_id}/reupload/service/preview"),
            ("POST", "/datasets/{dataset_id}/source-health"),
            ("POST", "/datasets/{dataset_id}/source-health/"),
            ("POST", "/ingest/upload/url"),
        ],
        "server-side fetch of a remote URL",
    ),
    **dict.fromkeys(
        [
            ("POST", "/datasets/{dataset_id}/vrt/regenerate"),
            ("POST", "/datasets/{dataset_id}/vrt/regenerate/"),
            ("POST", "/ingest/vrt/create"),
            ("POST", "/ingest/vrt/{dataset_id}/sources"),
            ("POST", "/ingest/vrt/{dataset_id}/sources/"),
        ],
        "VRT authoring",
    ),
    **dict.fromkeys(
        [
            ("POST", "/ingest/preview/{job_id}"),
            ("POST", "/ingest/commit/{job_id}"),
            ("POST", "/ingest/commit-fan-out/{job_id}"),
        ],
        "the interactive import wizard; clients publish through the manifest",
    ),
    **dict.fromkeys(
        [
            ("POST", "/ingest/register"),
            ("POST", "/ingest/register/"),
            ("POST", "/ingest/register/bulk"),
            ("POST", "/ingest/register/bulk/"),
        ],
        "registers database tables",
    ),
    ("POST", "/jobs/cleanup/stale"): "admin maintenance",
    ("POST", "/jobs/cleanup/stale/"): "admin maintenance",
    ("PUT", "/datasets/{dataset_id}/retention"): "schedules data for deletion",
    ("PUT", "/datasets/{dataset_id}/retention/"): "schedules data for deletion",
}

# Shared with the dataset-key tests: an editor owning two private point
# datasets, and removal of every key a test mints.
owner = _dataset_scope.owner
datasets = _dataset_scope.datasets
_remove_keys_minted_by_the_test = _dataset_scope._remove_keys_minted_by_the_test

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _refused_by_rule(method: str, path: str) -> bool:
    return (
        method == "DELETE"
        or "/features" in path
        or any(path.startswith(prefix) for prefix in _REFUSED_PREFIXES)
    )


def _unsafe_mounted_pairs() -> set[tuple[str, str]]:
    return {pair for pair in _mounted_route_pairs() if pair[0] not in _SAFE_METHODS}


# ---------------------------------------------------------------------------
# The allowlist, walked against the live route table
# ---------------------------------------------------------------------------


def test_every_unsafe_route_is_classified_for_publish():
    allowed = _PUBLISH_KEY_ROUTES | _READ_ONLY_KEY_EXEMPT_ROUTES
    unclassified = sorted(
        pair
        for pair in _unsafe_mounted_pairs()
        if pair not in allowed
        and pair not in _REFUSED_ROUTES
        and not _refused_by_rule(*pair)
    )
    assert not unclassified, (
        "decide whether a publish key may call these, in _PUBLISH_KEY_ROUTES or "
        f"in this test's _REFUSED_ROUTES: {unclassified}"
    )


def test_the_classification_names_only_mounted_routes():
    mounted = _unsafe_mounted_pairs()
    assert not sorted(_PUBLISH_KEY_ROUTES - mounted)
    assert not sorted(set(_REFUSED_ROUTES) - mounted)
    for prefix in _REFUSED_PREFIXES:
        assert any(path.startswith(prefix) for _, path in mounted), prefix


def test_the_allowlist_holds_nothing_that_cannot_be_undone():
    assert not sorted(p for p in _PUBLISH_KEY_ROUTES if _refused_by_rule(*p))
    assert not sorted(_PUBLISH_KEY_ROUTES & set(_REFUSED_ROUTES))
    assert not sorted(_PUBLISH_KEY_ROUTES & DATASET_WRITE_KEY_ROUTES)
    assert not sorted(p for p in _PUBLISH_KEY_ROUTES if "api-keys" in p[1])
    assert all(method not in _SAFE_METHODS for method, _ in _PUBLISH_KEY_ROUTES)


def test_a_publish_key_inherits_the_read_only_rules():
    for pair in _READ_ONLY_KEY_EXEMPT_ROUTES:
        assert _publish_key_may_call(*pair)
    assert _publish_key_may_call("GET", "/datasets/")
    assert not _publish_key_may_call(
        "GET", "/datasets/{dataset_id}/validate/", {"refresh": "true"}
    )


def test_an_allowed_path_does_not_carry_other_methods():
    assert _publish_key_may_call("PATCH", "/datasets/{dataset_id}")
    assert not _publish_key_may_call("DELETE", "/datasets/{dataset_id}")
    assert not _publish_key_may_call("PUT", "/datasets/{dataset_id}")
    assert not _publish_key_may_call("DELETE", "/maps/{map_id}")
    assert not _publish_key_may_call("POST", "<unmatched-route>")


# ---------------------------------------------------------------------------
# Live requests
# ---------------------------------------------------------------------------


async def _mint(client: AsyncClient, headers: dict, scope: str) -> dict[str, str]:
    resp = await client.post(
        "/auth/api-keys/",
        json={"name": f"{scope} key", "scope": scope},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["scope"] == scope
    return {"X-Api-Key": resp.json()["key"]}


def _scope_refused(resp) -> bool:
    if resp.status_code != 403:
        return False
    detail = resp.json().get("detail")
    return isinstance(detail, dict) and detail.get("code") == "api_key_scope"


@pytest.mark.anyio
async def test_both_mint_surfaces_round_trip_the_publish_scope(
    client: AsyncClient, admin_auth_header
):
    await _mint(client, admin_auth_header, "publish")
    admin_id = (await client.get("/auth/me/", headers=admin_auth_header)).json()["id"]
    resp = await client.post(
        "/admin/api-keys/",
        json={"user_id": admin_id, "name": "Publisher", "scope": "publish"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    listing = await client.get("/admin/api-keys/", headers=admin_auth_header)
    listed = {item["id"]: item["scope"] for item in listing.json()["items"]}
    assert listed[resp.json()["id"]] == "publish"


@pytest.mark.anyio
async def test_every_allowlisted_route_passes_the_scope_gate(
    client: AsyncClient, owner
):
    """Each pair reaches its handler with a publish key and not with a read_only one.

    Path parameters are random ids, so the handlers answer 404 or 422; what
    matters is which key the scope gate refused.
    """
    headers, _ = owner
    publish = await _mint(client, headers, "publish")
    read_only = await _mint(client, headers, "read_only")
    with patch("app.processing.ingest.router.queue_ingest_job", new_callable=AsyncMock):
        for method, template in sorted(_PUBLISH_KEY_ROUTES):
            url = re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), template)
            published = await client.request(method, url, headers=publish)
            refused = await client.request(method, url, headers=read_only)
            assert not _scope_refused(published), (method, template, published.text)
            assert _scope_refused(refused), (method, template, refused.text)


@pytest.mark.anyio
async def test_a_publish_key_cannot_write_features(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    dataset = datasets[0]
    publish = await _mint(client, headers, "publish")
    full = await _mint(client, headers, "full")
    base = f"/datasets/{dataset.id}/features"
    feature = {"geometry": _dataset_scope.POINT, "properties": {"name": "made"}}

    created = await client.post(f"{base}/", json=feature, headers=full)
    assert created.status_code == 201, created.text
    gid = created.json()["id"]

    for method, url, body in (
        ("POST", f"{base}/", feature),
        ("POST", base, feature),
        ("POST", f"{base}/dry-run/", feature),
        ("PUT", f"{base}/{gid}", feature),
        ("PATCH", f"{base}/{gid}", {"properties": {"name": "changed"}}),
        ("DELETE", f"{base}/{gid}", None),
        ("POST", f"{base}/delete/", {"ids": [gid]}),
    ):
        resp = await client.request(method, url, json=body, headers=publish)
        assert (resp.status_code, resp.json()["detail"]) == (403, PUBLISH_REFUSAL), (
            method,
            url,
        )

    kept = await client.get(f"{base}/{gid}", headers=publish)
    assert kept.status_code == 200, kept.text
    assert kept.json()["properties"]["name"] == "made"
    assert (await client.delete(f"{base}/{gid}", headers=full)).status_code == 204


@pytest.mark.anyio
async def test_a_publish_key_cannot_delete_a_dataset(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    dataset = datasets[0]
    publish = await _mint(client, headers, "publish")

    resp = await client.delete(f"/datasets/{dataset.id}", headers=publish)
    assert (resp.status_code, resp.json()["detail"]) == (403, PUBLISH_REFUSAL)
    assert (
        await client.get(f"/datasets/{dataset.id}", headers=headers)
    ).status_code == 200


@pytest.mark.anyio
async def test_a_publish_key_cannot_reach_key_routes(client: AsyncClient, owner):
    headers, _ = owner
    publish = await _mint(client, headers, "publish")
    listing = (await client.get("/auth/api-keys/", headers=headers)).json()["items"]

    minted = await client.post(
        "/auth/api-keys/", json={"name": "Child"}, headers=publish
    )
    assert (minted.status_code, minted.json()["detail"]) == (403, PUBLISH_REFUSAL)
    revoked = await client.delete(f"/auth/api-keys/{listing[0]['id']}", headers=publish)
    assert (revoked.status_code, revoked.json()["detail"]) == (403, PUBLISH_REFUSAL)


@pytest.mark.anyio
async def test_a_publish_key_publishes(client: AsyncClient, owner, datasets, tmp_path):
    headers, _ = owner
    dataset = datasets[0]
    publish = await _mint(client, headers, "publish")

    async def _save_to_temp(file, job_id: str, **_):
        dest = tmp_path / f"{job_id}_{file.filename}"
        dest.write_bytes(await file.read())
        await file.seek(0)
        return dest

    with (
        patch("app.processing.ingest.router.save_upload_file", new=_save_to_temp),
        patch("app.processing.ingest.router.queue_ingest_job", new_callable=AsyncMock),
    ):
        uploaded = await client.post(
            "/ingest/upload",
            files={
                "file": (
                    "parks.geojson",
                    b'{"type":"FeatureCollection","features":[]}',
                    "application/geo+json",
                )
            },
            headers=publish,
        )
    assert uploaded.status_code == 201, uploaded.text

    with patch(
        "app.processing.ingest.manifest_service.apply_manifest",
        new_callable=AsyncMock,
        return_value=ManifestApplyResponse(accepted=True, dry_run=True, results=[]),
    ) as applied:
        resp = await client.post(
            "/ingest/manifest/apply",
            json={**valid_manifest_payload(), "dry_run": True},
            headers=publish,
        )
    assert resp.status_code == 200, resp.text
    applied.assert_awaited_once()

    renamed = await client.patch(
        f"/datasets/{dataset.id}", json={"title": "Published parks"}, headers=publish
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Published parks"

    made = await client.post("/maps/", json={"name": "Parks map"}, headers=publish)
    assert made.status_code == 201, made.text
    map_id = made.json()["id"]
    gone = await client.delete(f"/maps/{map_id}", headers=publish)
    assert (gone.status_code, gone.json()["detail"]) == (403, PUBLISH_REFUSAL)
    assert (await client.delete(f"/maps/{map_id}", headers=headers)).status_code == 204
