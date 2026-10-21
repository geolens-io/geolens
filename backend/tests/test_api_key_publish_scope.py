"""Publish-scoped API keys: what a desktop or browser publishing client may do.

A ``publish`` key may read, upload, apply manifests and write metadata and
maps, because each of those adds something or can be undone. It may not
delete anything, write features, or reach admin and key routes, since none of
those can be undone.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.auth import dependencies
from app.modules.auth.dependencies import (
    _PUBLISH_KEY_ROUTES,
    _READ_ONLY_KEY_EXEMPT_ROUTES,
    _READ_ONLY_SAFE_METHODS,
    _publish_key_may_call,
)
from app.modules.embed_tokens.models import EmbedToken
from app.platform.request_credential import DATASET_WRITE_KEY_ROUTES
from app.processing.ingest.manifest_schemas import ManifestApplyResponse
from tests import test_api_key_dataset_scope as _dataset_scope
from tests.factories import create_map_via_api, create_raster_dataset
from tests.test_api_key_scope_875 import _mounted_route_pairs
from tests.test_manifest_apply_api import valid_manifest_payload

PUBLISH_REFUSAL = {
    "code": "api_key_scope",
    "message": (
        "This API key has the publish scope, which can't delete datasets or "
        "maps, write features or reach admin and key routes"
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
        "not needed to publish; PATCH /datasets/{id} and the manifest set status",
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
    (
        "PATCH",
        "/maps/{map_id}/share",
    ): "changes a share link's expiry, which can end it",
    (
        "PATCH",
        "/maps/{map_id}/share/",
    ): "changes a share link's expiry, which can end it",
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
        "resets attribute metadata to harvested values; not needed to publish",
    ),
    **dict.fromkeys(
        [
            ("POST", "/datasets/{dataset_id}/reupload/service/preview"),
            ("POST", "/ingest/upload/url"),
        ],
        "imports from a service or URL; publishing clients upload files",
    ),
    **dict.fromkeys(
        [
            ("POST", "/datasets/{dataset_id}/source-health"),
            ("POST", "/datasets/{dataset_id}/source-health/"),
        ],
        "probes the dataset's stored origin; not needed to publish",
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


def _refused_by_rule(method: str, path: str) -> bool:
    return (
        method == "DELETE"
        or "/features" in path
        or any(path.startswith(prefix) for prefix in _REFUSED_PREFIXES)
    )


def _unsafe_mounted_pairs() -> set[tuple[str, str]]:
    return {
        pair
        for pair in _mounted_route_pairs()
        if pair[0] not in _READ_ONLY_SAFE_METHODS
    }


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
    assert all(
        method not in _READ_ONLY_SAFE_METHODS for method, _ in _PUBLISH_KEY_ROUTES
    )


def test_a_publish_key_inherits_the_read_only_rules():
    for pair in _READ_ONLY_KEY_EXEMPT_ROUTES:
        assert _publish_key_may_call(*pair)
    assert _publish_key_may_call("GET", "/datasets/")
    assert not _publish_key_may_call(
        "GET", "/datasets/{dataset_id}/validate/", {"refresh": "true"}
    )


def _admin_only_reads() -> set[str]:
    """GET templates gated by an instance-mode permission or a manage_* capability."""
    import inspect

    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app

    def gates(dependant):
        for sub in dependant.dependencies:
            yield sub.call
            yield from gates(sub)

    found = set()
    for ctx in iter_route_contexts(app.routes):
        if not isinstance(ctx.route, APIRoute) or "GET" not in ctx.route.methods:
            continue
        for call in gates(ctx.route.dependant):
            name = getattr(call, "__qualname__", "")
            if "_mode_permission_checker" in name:
                found.add(ctx.path)
            elif "_permission_checker" in name:
                needed = inspect.getclosurevars(call).nonlocals.get("capabilities", ())
                if {"manage_settings", "manage_users"} & set(needed):
                    found.add(ctx.path)
    return found


def test_every_admin_only_read_is_refused():
    reads = _admin_only_reads()
    assert "/settings/all" in reads and "/admin/users" in reads
    allowed = sorted(t for t in reads if _publish_key_may_call("GET", t))
    assert not allowed, allowed


def test_admin_and_key_reads_are_refused():
    for template in (
        "/admin/users",
        "/auth/api-keys/",
        "/datasets/{dataset_id}/api-keys",
    ):
        assert not _publish_key_may_call("GET", template), template
    assert _publish_key_may_call("GET", "/auth/me/")


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
    if detail == "This API key is read-only":
        return True
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


def _refused_with(resp, message: str) -> bool:
    return resp.status_code == 403 and resp.json()["detail"] == {
        "code": "api_key_scope",
        "message": message,
    }


@pytest.mark.anyio
async def test_a_publish_key_cannot_replace_a_raster(
    client: AsyncClient, owner, test_db_session
):
    """A raster replace or refresh keeps no previous version to restore."""
    headers, owner_id = owner
    raster = await create_raster_dataset(
        test_db_session, created_by=owner_id, visibility="private"
    )
    record_id = raster.record_id
    try:
        publish = await _mint(client, headers, "publish")
        full = await _mint(client, headers, "full")
        refusal = "A publish key can't replace a raster dataset"

        upload = await client.post(
            f"/datasets/{raster.id}/reupload",
            files={"file": ("new.tif", b"II*\x00", "image/tiff")},
            headers=publish,
        )
        assert _refused_with(upload, refusal), upload.text
        commit_url = f"/datasets/{raster.id}/reupload/{uuid.uuid4()}/commit"
        commit = await client.post(commit_url, json={}, headers=publish)
        assert _refused_with(commit, refusal), commit.text
        # A full key gets past the refusal to the job lookup.
        assert (await client.post(commit_url, json={}, headers=full)).status_code == 404

        refreshed = await client.post(f"/datasets/{raster.id}/refresh", headers=publish)
        assert _refused_with(
            refreshed, "A publish key can't refresh a raster or STAC dataset"
        ), refreshed.text
        full_refresh = await client.post(f"/datasets/{raster.id}/refresh", headers=full)
        assert not _scope_refused(full_refresh), full_refresh.text
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_a_publish_key_cannot_revoke_map_links(
    client: AsyncClient, owner, datasets, test_db_session
):
    headers, owner_id = owner
    kept, other = (str(dataset.id) for dataset in datasets)
    publish = await _mint(client, headers, "publish")
    map_id = (await create_map_via_api(client, headers))["id"]
    url = f"/maps/{map_id}"
    try:
        setup = await client.put(
            url,
            json={"visibility": "internal", "layers": [{"dataset_id": kept}]},
            headers=headers,
        )
        assert setup.status_code == 200, setup.text
        token = EmbedToken(
            map_id=uuid.UUID(map_id),
            token_hash=uuid.uuid4().hex,
            token_hint="smoke",
            scoped_dataset_ids=[kept],
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            created_by=owner_id,
        )
        test_db_session.add(token)
        await test_db_session.commit()

        dropped = await client.put(
            url, json={"layers": [{"dataset_id": other}]}, headers=publish
        )
        assert _refused_with(
            dropped, "A publish key can't drop a dataset an active embed token covers"
        ), dropped.text
        lowered = await client.put(url, json={"visibility": "private"}, headers=publish)
        assert _refused_with(lowered, "A publish key can't lower a map's visibility"), (
            lowered.text
        )

        added = await client.put(
            url,
            json={
                "name": "Parks, updated",
                "layers": [
                    {"dataset_id": kept, "sort_order": 0},
                    {"dataset_id": other, "sort_order": 1},
                ],
            },
            headers=publish,
        )
        assert added.status_code == 200, added.text
        await test_db_session.refresh(token)
        assert token.is_active
    finally:
        await client.delete(url, headers=headers)


@pytest.mark.anyio
async def test_a_publish_key_cannot_transfer_dataset_ownership(
    client: AsyncClient, admin_auth_header, datasets
):
    """Refused for the scope even when the key's owner is an admin who could."""
    publish = await _mint(client, admin_auth_header, "publish")
    admin_id = (await client.get("/auth/me/", headers=admin_auth_header)).json()["id"]

    resp = await client.patch(
        f"/datasets/{datasets[0].id}", json={"owner_id": admin_id}, headers=publish
    )
    assert _refused_with(resp, "A publish key can't transfer dataset ownership"), (
        resp.text
    )


@pytest.mark.anyio
async def test_a_restricted_scope_without_a_rule_is_refused_everything(
    client: AsyncClient, owner, monkeypatch
):
    headers, _ = owner
    publish = await _mint(client, headers, "publish")
    monkeypatch.delitem(dependencies._SCOPE_RULES, "publish")

    resp = await client.get("/auth/me/", headers=publish)
    assert _refused_with(resp, "This API key's scope is not recognized"), resp.text


@pytest.mark.anyio
async def test_a_null_layer_list_revokes_no_embed_token(
    client: AsyncClient, owner, datasets, test_db_session
):
    """``"layers": null`` replaces nothing, so it must not run the revocation either."""
    headers, owner_id = owner
    on_map, off_map = (str(dataset.id) for dataset in datasets)
    publish = await _mint(client, headers, "publish")
    map_id = (await create_map_via_api(client, headers))["id"]
    url = f"/maps/{map_id}"
    try:
        setup = await client.put(
            url, json={"layers": [{"dataset_id": on_map}]}, headers=headers
        )
        assert setup.status_code == 200, setup.text
        # Scoped wider than the layers, as a token minted before a layer
        # removal is; any layer replacement would revoke it.
        token = EmbedToken(
            map_id=uuid.UUID(map_id),
            token_hash=uuid.uuid4().hex,
            token_hint="smoke",
            scoped_dataset_ids=[on_map, off_map],
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            created_by=owner_id,
        )
        test_db_session.add(token)
        await test_db_session.commit()

        renamed = await client.put(
            url, json={"name": "Renamed", "layers": None}, headers=publish
        )
        assert renamed.status_code == 200, renamed.text
        await test_db_session.refresh(token)
        assert token.is_active
    finally:
        await client.delete(url, headers=headers)


@pytest.mark.anyio
async def test_a_publish_key_reads_no_key_or_admin_route(
    client: AsyncClient, admin_auth_header, datasets
):
    """Even an admin's publish key, whose owner may read both."""
    publish = await _mint(client, admin_auth_header, "publish")
    for url in (
        "/auth/api-keys/",
        "/admin/api-keys/",
        "/admin/users/",
        f"/datasets/{datasets[0].id}/api-keys",
    ):
        resp = await client.get(url, headers=publish)
        assert (resp.status_code, resp.json()["detail"]) == (403, PUBLISH_REFUSAL), url
    assert (await client.get("/auth/me/", headers=publish)).status_code == 200


@pytest.mark.anyio
async def test_a_publish_key_cannot_change_a_live_share_links_expiry(
    client: AsyncClient, owner
):
    headers, _ = owner
    publish = await _mint(client, headers, "publish")
    map_id = (await create_map_via_api(client, headers))["id"]
    try:
        made_public = await client.put(
            f"/maps/{map_id}", json={"visibility": "public"}, headers=headers
        )
        assert made_public.status_code == 200, made_public.text
        share_url = f"/maps/{map_id}/share/"
        first = await client.post(share_url, headers=publish)
        assert first.status_code == 200, first.text

        shortened = await client.post(
            share_url, json={"expires_in_days": 1}, headers=publish
        )
        assert _refused_with(
            shortened, "A publish key can't change a share link's expiry"
        ), shortened.text
        reused = await client.post(share_url, headers=publish)
        assert reused.status_code == 200, reused.text
        assert reused.json()["expires_at"] is None
    finally:
        await client.delete(f"/maps/{map_id}", headers=headers)


@pytest.mark.anyio
async def test_a_null_layer_list_keeps_the_public_map_check(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    map_id = (await create_map_via_api(client, headers))["id"]
    url = f"/maps/{map_id}"
    try:
        added = await client.put(
            url, json={"layers": [{"dataset_id": str(datasets[0].id)}]}, headers=headers
        )
        assert added.status_code == 200, added.text
        resp = await client.put(
            url, json={"visibility": "public", "layers": None}, headers=headers
        )
        assert resp.status_code == 400, resp.text
    finally:
        await client.delete(url, headers=headers)


@pytest.mark.anyio
async def test_an_expired_embed_token_does_not_pin_layers(
    client: AsyncClient, owner, datasets, test_db_session
):
    headers, owner_id = owner
    kept, other = (str(dataset.id) for dataset in datasets)
    publish = await _mint(client, headers, "publish")
    map_id = (await create_map_via_api(client, headers))["id"]
    url = f"/maps/{map_id}"
    try:
        setup = await client.put(
            url, json={"layers": [{"dataset_id": kept}]}, headers=headers
        )
        assert setup.status_code == 200, setup.text
        test_db_session.add(
            EmbedToken(
                map_id=uuid.UUID(map_id),
                token_hash=uuid.uuid4().hex,
                token_hint="expired",
                scoped_dataset_ids=[kept],
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                created_by=owner_id,
            )
        )
        await test_db_session.commit()

        swapped = await client.put(
            url, json={"layers": [{"dataset_id": other}]}, headers=publish
        )
        assert swapped.status_code == 200, swapped.text
    finally:
        await client.delete(url, headers=headers)


@pytest.mark.anyio
async def test_the_visibility_check_reads_the_map_under_its_lock(
    client: AsyncClient, owner, monkeypatch
):
    """A publish that commits before the lock is granted is what gets compared."""
    from sqlalchemy import update

    from app.modules.catalog.maps import _router_helpers
    from app.modules.catalog.maps.models import Map

    headers, _ = owner
    publish = await _mint(client, headers, "publish")
    map_id = (await create_map_via_api(client, headers))["id"]
    lock = _router_helpers.lock_map_layers

    async def published_while_waiting(session, locked_map_id):
        # Not synchronized into the session, as another transaction's write isn't.
        await session.execute(
            update(Map)
            .where(Map.id == locked_map_id)
            .values(visibility="public")
            .execution_options(synchronize_session=False)
        )
        await lock(session, locked_map_id)

    monkeypatch.setattr(_router_helpers, "lock_map_layers", published_while_waiting)
    try:
        resp = await client.put(
            f"/maps/{map_id}", json={"visibility": "internal"}, headers=publish
        )
        assert _refused_with(resp, "A publish key can't lower a map's visibility"), (
            resp.text
        )
    finally:
        monkeypatch.undo()
        await client.delete(f"/maps/{map_id}", headers=headers)


@pytest.mark.anyio
async def test_lowering_visibility_revokes_links_by_the_locked_read(
    client: AsyncClient, owner, monkeypatch
):
    """A map published while the update waited for the lock still loses its links."""
    from sqlalchemy import update

    from app.modules.catalog.maps import router as maps_router
    from app.modules.catalog.maps.models import Map

    headers, _ = owner
    map_id = (await create_map_via_api(client, headers))["id"]
    lock = maps_router.lock_map_layers
    revoked: list[uuid.UUID] = []

    async def published_while_waiting(session, locked_map_id):
        await session.execute(
            update(Map)
            .where(Map.id == locked_map_id)
            .values(visibility="public")
            .execution_options(synchronize_session=False)
        )
        await lock(session, locked_map_id)

    async def record_revoke(session, revoked_map_id):
        revoked.append(revoked_map_id)

    monkeypatch.setattr(maps_router, "lock_map_layers", published_while_waiting)
    monkeypatch.setattr(maps_router, "revoke_share_token_by_map", record_revoke)
    try:
        resp = await client.put(
            f"/maps/{map_id}", json={"visibility": "private"}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        assert revoked == [uuid.UUID(map_id)]
    finally:
        monkeypatch.undo()
        await client.delete(f"/maps/{map_id}", headers=headers)
