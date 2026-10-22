"""Publish-scoped API keys: what a desktop or browser publishing client may do.

A ``publish`` key may read, upload, apply manifests, write dataset metadata and
create maps, because each of those adds something or can be undone. It may
not update a map, delete anything, write features, make anything public, or
reach admin and key routes, since none of those can be undone.
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
from app.platform.request_credential import _SESSION_KEY, DATASET_WRITE_KEY_ROUTES
from app.processing.ingest.manifest_schemas import ManifestApplyResponse
from tests import test_api_key_dataset_scope as _dataset_scope
from tests.factories import create_map_via_api, create_raster_dataset
from tests.test_api_key_scope_875 import _mounted_route_pairs
from tests.test_manifest_apply_api import valid_manifest_payload
from tests.test_maps import _valid_png_data_uri

PUBLISH_REFUSAL = {
    "code": "api_key_scope",
    "message": (
        "This API key has the publish scope, which can't delete datasets or "
        "maps, update a map, write features or reach admin and key routes"
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
    **dict.fromkeys(
        [
            ("POST", "/maps/import/arcgis-webmap"),
            ("POST", "/maps/import/arcgis-webmap/"),
        ],
        "migration import, not a desktop publish",
    ),
    ("PATCH", "/maps/{map_id}"): "transfers map ownership",
    ("PUT", "/maps/{map_id}"): (
        "replaces a map's layers and settings in place, with no earlier "
        "version to restore; a republish creates a new map"
    ),
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
    (
        "POST",
        "/datasets/{dataset_id}/previous-versions/{version_number}/restore",
    ): "restores an older kept version; a publish key restores only the newest",
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
    """GET templates gated by an instance-mode permission or an admin capability."""
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
                if {"manage_settings", "manage_users", "manage_tenants"} & set(needed):
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
            refreshed, "A publish key can't refresh a raster or remote-origin dataset"
        ), refreshed.text
        full_refresh = await client.post(f"/datasets/{raster.id}/refresh", headers=full)
        assert not _scope_refused(full_refresh), full_refresh.text
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_a_publish_key_cannot_transfer_dataset_ownership(
    client: AsyncClient, admin_auth_header, owner, datasets
):
    """Refused for the scope, before the admin check a transfer also needs."""
    headers, _ = owner
    publish = await _mint(client, headers, "publish")
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
            url, json={"name": "Renamed", "layers": None}, headers=headers
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
    client: AsyncClient, owner, test_db_session
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

        # An expired link serves nothing, so a publish key may renew it.
        await test_db_session.execute(
            text(
                "UPDATE catalog.map_share_tokens SET expires_at = now() - interval '1 day' "
                "WHERE map_id = :id"
            ),
            {"id": map_id},
        )
        await test_db_session.commit()
        renewed = await client.post(
            share_url, json={"expires_in_days": 7}, headers=publish
        )
        assert renewed.status_code == 200, renewed.text
        assert renewed.json()["expires_at"] is not None
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


@pytest.mark.anyio
async def test_a_publish_key_cancels_and_retries_only_its_owners_jobs(
    client: AsyncClient, admin_auth_header, owner, datasets, test_db_session
):
    """An admin's publish key can't stop or rerun another user's job; the admin could."""
    from app.platform.jobs.models import IngestJob

    _, owner_id = owner
    publish = await _mint(client, admin_auth_header, "publish")
    dataset = datasets[0]
    job = IngestJob(
        status="pending",
        created_by=owner_id,
        dataset_id=dataset.id,
        attempt_id=uuid.uuid4(),
        source_filename="someone-elses.geojson",
    )
    test_db_session.add(job)
    await test_db_session.commit()
    try:
        resp = await client.post(f"/jobs/{job.id}/cancel", headers=publish)
        assert _refused_with(resp, "A publish key can cancel only its owner's jobs"), (
            resp.text
        )
        read = await client.get(f"/jobs/{job.id}", headers=publish)
        assert _refused_with(read, "A publish key can read only its owner's jobs"), (
            read.text
        )
        # The admin's publish key doesn't see the editor's private dataset at all.
        by_dataset = await client.get(f"/jobs/by-dataset/{dataset.id}", headers=publish)
        assert by_dataset.status_code == 404, by_dataset.text
        batch = await client.post(
            "/jobs/status/", json={"job_ids": [str(job.id)]}, headers=publish
        )
        assert batch.status_code == 200, batch.text
        assert batch.json()["jobs"][0]["status"] == "not_found"
        full = await _mint(client, admin_auth_header, "full")
        seen = await client.post(
            "/jobs/status/", json={"job_ids": [str(job.id)]}, headers=full
        )
        assert seen.json()["jobs"][0]["status"] == "pending", seen.text
        retry = await client.post(f"/jobs/{job.id}/retry", headers=publish)
        assert _refused_with(retry, "A publish key can retry only its owner's jobs"), (
            retry.text
        )
        for url, body in (
            (f"/ingest/preview/{job.id}", None),
            (f"/ingest/commit/{job.id}", {"title": "Not mine"}),
        ):
            used = await client.post(url, json=body, headers=publish)
            assert _refused_with(used, "A publish key can use only its owner's jobs"), (
                url,
                used.text,
            )
        await test_db_session.refresh(job)
        assert job.status == "pending"
    finally:
        await test_db_session.delete(job)
        await test_db_session.commit()


@pytest.mark.anyio
async def test_an_admin_capability_refuses_a_publish_key_wherever_mounted(
    client: AsyncClient, admin_auth_header, monkeypatch
):
    """The capability check backs up the route list, so a new admin read is covered."""
    publish = await _mint(client, admin_auth_header, "publish")
    detail = dependencies._SCOPE_RULES["publish"][1]
    monkeypatch.setitem(
        dependencies._SCOPE_RULES, "publish", (lambda *_a, **_k: True, detail)
    )

    resp = await client.get("/admin/users/", headers=publish)
    assert (resp.status_code, resp.json()["detail"]) == (403, PUBLISH_REFUSAL)


@pytest.mark.anyio
async def test_a_publish_key_cannot_refresh_a_stac_dataset(
    client: AsyncClient, owner, test_db_session, monkeypatch
):
    from tests.factories import create_dataset

    headers, owner_id = owner
    stac = await create_dataset(
        test_db_session, created_by=owner_id, source_format="stac", visibility="private"
    )
    record_id = stac.record_id
    try:
        publish = await _mint(client, headers, "publish")
        resp = await client.post(f"/datasets/{stac.id}/refresh", headers=publish)
        assert _refused_with(
            resp, "A publish key can't refresh a raster or remote-origin dataset"
        ), resp.text
        # A restore couldn't bring the STAC binding back after a replacement.
        refusal = "A publish key can't replace a dataset bound to a remote origin"
        upload = await client.post(
            f"/datasets/{stac.id}/reupload",
            files={"file": ("new.geojson", b'{"type":"FeatureCollection"}')},
            headers=publish,
        )
        assert _refused_with(upload, refusal), upload.text
        commit = await client.post(
            f"/datasets/{stac.id}/reupload/{uuid.uuid4()}/commit",
            json={},
            headers=publish,
        )
        assert _refused_with(commit, refusal), commit.text
        from app.core.config import settings

        monkeypatch.setattr(settings, "storage_provider", "s3")
        presigned = await client.post(
            f"/datasets/{stac.id}/reupload/presigned",
            json={
                "filename": "new.geojson",
                "file_size": 10,
                "content_type": "application/geo+json",
            },
            headers=publish,
        )
        assert _refused_with(presigned, refusal), presigned.text
        completed = await client.post(
            f"/datasets/{stac.id}/reupload/presigned/{uuid.uuid4()}/complete",
            json={},
            headers=publish,
        )
        assert _refused_with(completed, refusal), completed.text
        restored = await client.post(
            f"/datasets/{stac.id}/previous-version/restore",
            json={"expected_version_number": 1},
            headers=publish,
        )
        assert _refused_with(
            restored,
            "A publish key can't restore over a dataset bound to a remote origin",
        ), restored.text
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
        await test_db_session.commit()


@pytest.mark.parametrize(
    "scope,source_format,refused",
    [
        ("publish", "stac", True),
        ("publish", "wfs", True),
        ("publish", None, True),
        ("publish", "geojson", False),
        ("publish", "created", False),
        ("full", "stac", False),
    ],
)
def test_a_manifest_update_refuses_a_publish_key_on_a_remote_origin(
    scope, source_format, refused
):
    """The manifest update replaces the binding, as a reupload does."""
    from types import SimpleNamespace

    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.platform.request_credential import ApiKeyCredential, record_api_key
    from app.processing.ingest.manifest_service import (
        _refuse_publish_key_remote_origin,
    )

    session = AsyncSession()
    record_api_key(
        session, ApiKeyCredential(id=uuid.uuid4(), scope=scope, dataset_id=None)
    )
    dataset = SimpleNamespace(
        source_format=source_format,
        record=SimpleNamespace(record_type="vector_dataset"),
    )
    if refused:
        with pytest.raises(HTTPException) as exc:
            _refuse_publish_key_remote_origin(session, dataset)
        assert exc.value.detail["code"] == "api_key_scope"
    else:
        _refuse_publish_key_remote_origin(session, dataset)


def test_the_manifest_update_path_runs_the_remote_origin_refusal():
    """Wired where the update is validated, before staging or a dry-run answer."""
    import inspect

    from app.processing.ingest import manifest_service

    source = inspect.getsource(manifest_service)
    validated = source.index(
        "_validate_existing_dataset_update(existing_dataset, prepared)"
    )
    refused = source.index("_refuse_publish_key_remote_origin(db, existing_dataset)")
    dry_run = source.index("if request.dry_run:", validated)
    assert validated < refused < dry_run


def test_manifest_admission_rechecks_the_origin_under_the_lock():
    """The binding can change while the source stages; admission checks it again."""
    import inspect

    from app.processing.ingest.manifest_service import _admit_refresh_run

    source = inspect.getsource(_admit_refresh_run)
    locked = source.index("lock_dataset_rows_for_write(db, dataset)")
    reread = source.index('db.refresh(dataset, attribute_names=["source_format"])')
    refused = source.index("_refuse_publish_key_remote_origin(db, dataset)")
    assert locked < reread < refused


# The publish-allowlisted routes on a dataset that replace or repoint its data,
# and the ones that don't. Exact, so a new dataset route has to be sorted here.
_DATA_REPLACING_ROUTES = {
    ("POST", "/datasets/{dataset_id}/refresh"),
    ("POST", "/datasets/{dataset_id}/previous-version/restore"),
    ("POST", "/datasets/{dataset_id}/reupload"),
    ("POST", "/datasets/{dataset_id}/reupload/presigned"),
    ("POST", "/datasets/{dataset_id}/reupload/presigned/{job_id}/complete"),
    ("POST", "/datasets/{dataset_id}/reupload/{job_id}/commit"),
}
_DATA_KEEPING_ROUTES = {
    ("PATCH", "/datasets/{dataset_id}"),
    ("PATCH", "/datasets/{dataset_id}/attributes/{attribute_id}"),
    ("PATCH", "/datasets/{dataset_id}/attributes/{attribute_id}/"),
    ("POST", "/datasets/{dataset_id}/reupload/{job_id}/preview"),
}


@pytest.mark.anyio
async def test_every_data_replacing_route_refuses_a_remote_origin_dataset(
    client: AsyncClient, owner, test_db_session, monkeypatch
):
    from app.core.config import settings
    from tests.factories import create_dataset

    dataset_routes = {p for p in _PUBLISH_KEY_ROUTES if "{dataset_id}" in p[1]}
    assert dataset_routes == _DATA_REPLACING_ROUTES | _DATA_KEEPING_ROUTES

    headers, owner_id = owner
    service = await create_dataset(
        test_db_session, created_by=owner_id, source_format="wfs", visibility="private"
    )
    record_id = service.record_id
    monkeypatch.setattr(settings, "storage_provider", "s3")
    try:
        publish = await _mint(client, headers, "publish")
        for method, template in sorted(_DATA_REPLACING_ROUTES):
            url = template.replace("{dataset_id}", str(service.id)).replace(
                "{job_id}", str(uuid.uuid4())
            )
            if template.endswith("/reupload"):
                kwargs = {
                    "files": {"file": ("a.geojson", b'{"type":"FeatureCollection"}')}
                }
            elif template.endswith("/presigned"):
                kwargs = {"json": {"filename": "a.geojson", "file_size": 10}}
            elif template.endswith("/restore"):
                kwargs = {"json": {"expected_version_number": 1}}
            else:
                kwargs = {"json": {}}
            resp = await client.request(method, url, headers=publish, **kwargs)
            assert _scope_refused(resp), (template, resp.text)
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_a_publish_key_cannot_restore_or_delete_a_kept_version_by_number(
    client: AsyncClient, owner, test_db_session
):
    """A publish key restores only the newest kept version, through the older route."""
    from tests.factories import create_dataset

    headers, owner_id = owner
    dataset = await create_dataset(
        test_db_session, created_by=owner_id, source_format="geojson"
    )
    record_id = dataset.record_id
    try:
        publish = await _mint(client, headers, "publish")
        base = f"/datasets/{dataset.id}/previous-versions/1"
        for method, url in (("POST", f"{base}/restore"), ("DELETE", base)):
            resp = await client.request(method, url, headers=publish)
            assert _scope_refused(resp), (url, resp.text)
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_run_admission_refuses_a_publish_key_on_a_remote_origin(
    test_db_session, owner
):
    """The chokepoint behind every data-replacing door, refresh acceptance included."""
    from fastapi import HTTPException

    from app.platform.refresh.service import create_pending_run
    from app.platform.request_credential import ApiKeyCredential, record_api_key
    from tests.factories import create_dataset

    _, owner_id = owner
    service = await create_dataset(
        test_db_session, created_by=owner_id, source_format="wfs", visibility="private"
    )
    record_id = service.record_id
    try:
        record_api_key(
            test_db_session,
            ApiKeyCredential(id=uuid.uuid4(), scope="publish", dataset_id=None),
        )
        with pytest.raises(HTTPException) as exc:
            await create_pending_run(
                test_db_session,
                dataset_id=service.id,
                origin_kind="upload",
                trigger="api",
                triggered_by=owner_id,
                ingest_job_id=None,
                feature_count_before=0,
            )
        assert exc.value.detail["code"] == "api_key_scope"
    finally:
        test_db_session.info.pop(_SESSION_KEY, None)
        await test_db_session.rollback()
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_run_admission_rechecks_the_origin_after_the_insert(
    test_db_session, owner, monkeypatch
):
    """A rebinding that commits while the insert waits on the active run is seen."""
    from fastapi import HTTPException

    from app.platform.refresh.service import create_pending_run
    from app.platform.request_credential import ApiKeyCredential, record_api_key
    from tests.factories import create_dataset

    _, owner_id = owner
    upload = await create_dataset(
        test_db_session, created_by=owner_id, source_format="gpkg", visibility="private"
    )
    record_id = upload.record_id
    real_flush = test_db_session.flush

    async def flush_then_rebind(*args, **kwargs):
        await real_flush(*args, **kwargs)
        await test_db_session.execute(
            text("UPDATE catalog.datasets SET source_format = 'wfs' WHERE id = :id"),
            {"id": upload.id},
        )

    try:
        record_api_key(
            test_db_session,
            ApiKeyCredential(id=uuid.uuid4(), scope="publish", dataset_id=None),
        )
        monkeypatch.setattr(test_db_session, "flush", flush_then_rebind)
        with pytest.raises(HTTPException) as exc:
            await create_pending_run(
                test_db_session,
                dataset_id=upload.id,
                origin_kind="upload",
                trigger="api",
                triggered_by=owner_id,
                ingest_job_id=None,
                feature_count_before=0,
            )
        assert exc.value.detail["code"] == "api_key_scope"
    finally:
        monkeypatch.undo()
        test_db_session.info.pop(_SESSION_KEY, None)
        await test_db_session.rollback()
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_an_admins_publish_key_acts_only_on_its_owners_objects(
    client: AsyncClient, admin_auth_header, owner, datasets
):
    """Each object type an editor owns, against the admin's publish key and full key."""
    headers, _ = owner
    publish = await _mint(client, admin_auth_header, "publish")
    full = await _mint(client, admin_auth_header, "full")
    dataset = datasets[0]
    map_id = (await create_map_via_api(client, headers))["id"]
    collection = await client.post(
        "/catalog/collections/", json={"name": "Editor collection"}, headers=headers
    )
    assert collection.status_code == 201, collection.text
    collection_id = collection.json()["id"]
    try:
        attempts = [
            ("PATCH", f"/datasets/{dataset.id}", {"title": "Taken"}),
            ("POST", f"/maps/{map_id}/share/", None),
            (
                "POST",
                f"/catalog/collections/{collection_id}/datasets/",
                {"dataset_ids": [str(dataset.id)]},
            ),
            ("POST", f"/records/{dataset.record_id}/keywords/", {"keyword": "taken"}),
        ]
        for method, url, body in attempts:
            refused = await client.request(method, url, json=body, headers=publish)
            assert refused.status_code in (403, 404), (url, refused.text)
        allowed = await client.patch(
            f"/datasets/{dataset.id}", json={"title": "Admin edit"}, headers=full
        )
        assert allowed.status_code == 200, allowed.text
    finally:
        await client.delete(f"/maps/{map_id}", headers=headers)
        await client.delete(f"/catalog/collections/{collection_id}", headers=headers)


@pytest.mark.anyio
async def test_a_publish_key_cannot_replace_an_uploaded_preview_image(
    client: AsyncClient, owner, test_db_session
):
    headers, _ = owner
    publish = await _mint(client, headers, "publish")
    map_id = (await create_map_via_api(client, headers))["id"]
    url = f"/maps/{map_id}/og-image/"
    try:
        first = await client.put(
            url, json={"data_uri": "data:image/png;base64,AAAAAAAA"}, headers=publish
        )
        assert not _scope_refused(first), first.text
        await test_db_session.execute(
            text(
                "UPDATE catalog.maps SET og_image_uri = 'maps/og/x.png' WHERE id = :id"
            ),
            {"id": map_id},
        )
        await test_db_session.commit()
        second = await client.put(
            url, json={"data_uri": "data:image/png;base64,AAAAAAAA"}, headers=publish
        )
        assert _refused_with(
            second, "A publish key can't replace a map's preview image"
        ), second.text
    finally:
        await client.delete(f"/maps/{map_id}", headers=headers)


def test_the_preview_image_refusal_is_rechecked_under_the_asset_lock():
    """A preview uploaded while the request waited is still not replaced."""
    import inspect

    from app.modules.catalog.maps.router import upload_og_image

    source = inspect.getsource(upload_og_image)
    locked = source.index("locked = await lock_map_for_asset_write(db, map_id)")
    refused = source.index("refuse_publish_key(", locked)
    written = source.index("_record_image_capture(", locked)
    assert locked < refused < written


# ---------------------------------------------------------------------------
# Map updates and visibility
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_a_publish_key_cannot_update_a_map(client: AsyncClient, owner, datasets):
    """Nothing restores a map's earlier layers, so a republish creates a new map."""
    headers, _ = owner
    publish = await _mint(client, headers, "publish")
    map_id = (await create_map_via_api(client, headers))["id"]
    url = f"/maps/{map_id}"
    try:
        resp = await client.put(
            url,
            json={"name": "Taken", "layers": [{"dataset_id": str(datasets[0].id)}]},
            headers=publish,
        )
        assert (resp.status_code, resp.json()["detail"]) == (403, PUBLISH_REFUSAL)
        kept = (await client.get(url, headers=headers)).json()
        assert kept["name"] != "Taken" and kept["layers"] == []
        renamed = await client.put(url, json={"name": "Renamed"}, headers=headers)
        assert renamed.status_code == 200, renamed.text
    finally:
        await client.delete(url, headers=headers)


async def _set_record(session, record_id, **values) -> None:
    sets = ", ".join(f"{column} = :{column}" for column in values)
    await session.execute(
        text(f"UPDATE catalog.records SET {sets} WHERE id = :id"),
        {"id": record_id, **values},
    )
    await session.commit()


async def _record_values(session, record_id) -> tuple[str, str]:
    row = (
        await session.execute(
            text(
                "SELECT visibility, record_status FROM catalog.records WHERE id = :id"
            ),
            {"id": record_id},
        )
    ).one()
    return row.visibility, row.record_status


@pytest.mark.anyio
async def test_a_publish_key_cannot_set_public_visibility(
    client: AsyncClient, owner, datasets, test_db_session
):
    """Refused even for a dataset that is already public; the owner signed in may."""
    headers, _ = owner
    dataset = datasets[0]
    publish = await _mint(client, headers, "publish")
    url = f"/datasets/{dataset.id}"

    raised = await client.patch(url, json={"visibility": "public"}, headers=publish)
    assert _refused_with(raised, "A publish key can't make anything public"), (
        raised.text
    )
    await _set_record(test_db_session, dataset.record_id, visibility="public")
    kept = await client.patch(
        url, json={"visibility": "public", "title": "Same"}, headers=publish
    )
    assert _refused_with(kept, "A publish key can't make anything public"), kept.text

    await _set_record(test_db_session, dataset.record_id, visibility="private")
    signed_in = await client.patch(url, json={"visibility": "public"}, headers=headers)
    assert signed_in.status_code == 200, signed_in.text
    assert await _record_values(test_db_session, dataset.record_id) == (
        "public",
        "published",
    )


@pytest.mark.anyio
async def test_a_publish_key_keeps_or_narrows_a_datasets_visibility(
    client: AsyncClient, owner, datasets, test_db_session
):
    headers, _ = owner
    dataset = datasets[0]
    publish = await _mint(client, headers, "publish")
    url = f"/datasets/{dataset.id}"

    widened = await client.patch(url, json={"visibility": "internal"}, headers=publish)
    assert _refused_with(widened, "A publish key can't widen a dataset's visibility"), (
        widened.text
    )
    assert await _record_values(test_db_session, dataset.record_id) == (
        "private",
        "published",
    )

    await _set_record(test_db_session, dataset.record_id, visibility="internal")
    for visibility in ("internal", "restricted", "private"):
        narrowed = await client.patch(
            url, json={"visibility": visibility}, headers=publish
        )
        assert narrowed.status_code == 200, (visibility, narrowed.text)
    assert await _record_values(test_db_session, dataset.record_id) == (
        "private",
        "published",
    )

    signed_in = await client.patch(
        url, json={"visibility": "internal"}, headers=headers
    )
    assert signed_in.status_code == 200, signed_in.text


@pytest.mark.anyio
async def test_a_publish_key_cannot_publish_a_public_dataset(
    client: AsyncClient, owner, datasets, test_db_session
):
    """An unpublished public dataset is a preview; publishing opens it to anyone."""
    headers, _ = owner
    dataset = datasets[0]
    publish = await _mint(client, headers, "publish")
    url = f"/datasets/{dataset.id}"
    await _set_record(
        test_db_session, dataset.record_id, visibility="public", record_status="draft"
    )

    resp = await client.patch(url, json={"record_status": "published"}, headers=publish)
    assert _refused_with(resp, "A publish key can't publish a public dataset"), (
        resp.text
    )
    assert await _record_values(test_db_session, dataset.record_id) == (
        "public",
        "draft",
    )

    await _set_record(test_db_session, dataset.record_id, visibility="internal")
    internal = await client.patch(
        url, json={"record_status": "published"}, headers=publish
    )
    assert internal.status_code == 200, internal.text


@pytest.mark.anyio
async def test_a_publish_key_creates_anything_but_public(
    client: AsyncClient, owner, test_db_session
):
    """An import commit and a manifest entry may ask for any visibility but public."""
    from app.platform.jobs.models import IngestJob

    headers, owner_id = owner
    publish = await _mint(client, headers, "publish")
    job = IngestJob(
        status="pending",
        created_by=owner_id,
        attempt_id=uuid.uuid4(),
        source_filename="parks.geojson",
    )
    test_db_session.add(job)
    await test_db_session.commit()
    try:
        with patch(
            "app.processing.ingest.router.queue_ingest_job", new_callable=AsyncMock
        ):
            public = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parks", "visibility": "public"},
                headers=publish,
            )
            assert _refused_with(public, "A publish key can't make anything public"), (
                public.text
            )
            internal = await client.post(
                f"/ingest/commit/{job.id}",
                json={"title": "Parks", "visibility": "internal"},
                headers=publish,
            )
            assert not _scope_refused(internal), internal.text

        manifest = valid_manifest_payload()
        manifest["datasets"][0]["publication"] = {"intent": "published"}
        applied = await client.post(
            "/ingest/manifest/apply",
            json={**manifest, "dry_run": True},
            headers=publish,
        )
        assert applied.status_code == 200, applied.text
        [entry] = applied.json()["results"]
        assert entry["action"] == "error", entry
        assert "A publish key can't make anything public" in entry["message"]
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": job.id}
        )
        await test_db_session.commit()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "metadata,refused",
    [
        ({"visibility": "public"}, True),
        ({"reupload": True, "visibility": "internal"}, True),
        ({"visibility": "internal"}, False),
        ({"reupload": True}, False),
        (
            {
                "dataset_id": "6f1c2a8e-0000-4000-8000-000000000001",
                "visibility": "private",
            },
            True,
        ),
        ({"dataset_id": "6f1c2a8e-0000-4000-8000-000000000001"}, False),
    ],
)
async def test_a_publish_key_retries_no_job_that_sets_visibility(
    client: AsyncClient, owner, test_db_session, metadata, refused
):
    """Such a job came from another credential; a publish key's own never does."""
    from app.platform.jobs.models import IngestJob

    headers, owner_id = owner
    publish = await _mint(client, headers, "publish")
    job = IngestJob(
        status="failed",
        created_by=owner_id,
        attempt_id=uuid.uuid4(),
        source_filename="parks.geojson",
        user_metadata=metadata,
    )
    test_db_session.add(job)
    await test_db_session.commit()
    try:
        resp = await client.post(f"/jobs/{job.id}/retry", headers=publish)
        if refused:
            assert _refused_with(
                resp, "A publish key can't retry a job that sets visibility"
            ), resp.text
        else:
            assert not _scope_refused(resp), resp.text
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": job.id}
        )
        await test_db_session.commit()


@pytest.mark.anyio
@pytest.mark.parametrize("scope,kept", [("publish", False), ("full", True)])
async def test_a_publish_keys_manifest_update_keeps_the_datasets_visibility(
    owner, datasets, test_db_session, scope, kept
):
    """The worker applies the entry's visibility later, over whatever is current then."""
    from pathlib import Path
    from shutil import copyfile

    from app.core.config import settings
    from app.modules.auth.models import User
    from app.platform.request_credential import ApiKeyCredential, record_api_key
    from app.processing.ingest import manifest_service
    from app.processing.ingest.manifest_schemas import ManifestApplyRequest
    from app.processing.ingest.manifest_sources import classify_manifest_source

    fixture = "tests/fixtures/ingest/basic_attrs.geojson"
    staged = Path(settings.upload_staging_dir) / fixture
    staged.parent.mkdir(parents=True, exist_ok=True)
    copyfile(Path(__file__).parent / "fixtures/ingest/basic_attrs.geojson", staged)
    entry = ManifestApplyRequest.model_validate(
        {
            "manifest_version": "1",
            "catalog": {"title": "Manifest catalog"},
            "datasets": [
                {
                    "key": f"publish-{uuid.uuid4().hex[:8]}",
                    "title": "Roads",
                    "sources": [
                        {"type": "vector", "uri": fixture, "format": "geojson"}
                    ],
                    "publication": {"intent": "internal"},
                }
            ],
        }
    ).datasets[0]
    prepared = await classify_manifest_source(entry.sources[0])
    _, owner_id = owner
    user = await test_db_session.get(User, owner_id)
    record_api_key(
        test_db_session,
        ApiKeyCredential(id=uuid.uuid4(), scope=scope, dataset_id=None),
    )
    reserved = None
    try:
        reserved = await manifest_service._reserve_entry(
            test_db_session,
            entry,
            prepared,
            "fingerprint",
            user,
            dataset_id=datasets[0].id,
            quota=manifest_service._ManifestQuotaReservation(),
        )
        metadata = reserved.job.user_metadata
        assert ("visibility" in metadata) is kept, metadata
        assert metadata["record_status"] == "internal"
    finally:
        test_db_session.info.pop(_SESSION_KEY, None)
        if reserved is not None:
            await test_db_session.execute(
                text("DELETE FROM catalog.ingest_jobs WHERE id = :id"),
                {"id": reserved.job.id},
            )
            await test_db_session.commit()


def test_a_publish_keys_acceptance_keeps_the_datasets_publication():
    """A held manifest entry may be another credential's."""
    import inspect
    from types import SimpleNamespace

    from app.modules.catalog.datasets.api.refresh_acceptance import (
        _accepted_upload_metadata,
        dispatch_upload_acceptance,
    )

    held = SimpleNamespace(
        id=uuid.uuid4(),
        user_metadata={
            "manifest_key": "roads",
            "title": "Roads",
            "visibility": "public",
            "record_status": "published",
        },
    )

    def accepted(publish_key: bool) -> dict:
        return _accepted_upload_metadata(
            held,
            dataset_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            fingerprint="fingerprint",
            held_version=None,
            publish_key=publish_key,
        )

    withheld = accepted(True)
    assert withheld["title"] == "Roads"
    assert "visibility" not in withheld and "record_status" not in withheld
    assert accepted(False)["visibility"] == "public"
    assert "publish_key=is_publish_key(db)" in inspect.getsource(
        dispatch_upload_acceptance
    )


@pytest.mark.anyio
async def test_a_publish_key_cannot_replace_a_maps_thumbnail(
    client: AsyncClient, owner, test_db_session
):
    """A first thumbnail is allowed; replacing one deletes the old image."""
    headers, _ = owner
    publish = await _mint(client, headers, "publish")
    map_id = (await create_map_via_api(client, headers))["id"]
    url = f"/maps/{map_id}/thumbnail/"
    image = {"data_uri": _valid_png_data_uri()}
    try:
        first = await client.put(url, json=image, headers=publish)
        assert not _scope_refused(first), first.text
        await test_db_session.execute(
            text(
                "UPDATE catalog.maps SET thumbnail_uri = 'maps/thumbnails/x.png' "
                "WHERE id = :id"
            ),
            {"id": map_id},
        )
        await test_db_session.commit()
        second = await client.put(url, json=image, headers=publish)
        assert _refused_with(second, "A publish key can't replace a map's thumbnail"), (
            second.text
        )
        kept = await test_db_session.scalar(
            text("SELECT thumbnail_uri FROM catalog.maps WHERE id = :id"),
            {"id": map_id},
        )
        assert kept == "maps/thumbnails/x.png"
        signed_in = await client.put(url, json=image, headers=headers)
        assert signed_in.status_code == 204, signed_in.text
    finally:
        await client.delete(f"/maps/{map_id}", headers=headers)


def test_the_thumbnail_refusal_is_rechecked_under_the_asset_lock():
    """A thumbnail uploaded while the request waited is still not replaced."""
    import inspect

    from app.modules.catalog.maps.router import upload_thumbnail

    source = inspect.getsource(upload_thumbnail)
    locked = source.index("locked = await lock_map_for_asset_write(db, map_id)")
    refused = source.index("refuse_publish_key(", locked)
    written = source.index("_record_image_capture(", locked)
    assert locked < refused < written


@pytest.mark.anyio
async def test_a_publish_key_cannot_fan_out_a_public_import(
    client: AsyncClient, owner, test_db_session
):
    from app.platform.jobs.models import IngestJob

    headers, owner_id = owner
    publish = await _mint(client, headers, "publish")
    job = IngestJob(
        status="pending",
        created_by=owner_id,
        attempt_id=uuid.uuid4(),
        source_filename="parks.gpkg",
        user_metadata={"visibility": "public", "all_layers": ["parks", "trails"]},
    )
    test_db_session.add(job)
    await test_db_session.commit()
    try:
        resp = await client.post(
            f"/ingest/commit-fan-out/{job.id}",
            json={"layers": [{"layer_name": "parks"}]},
            headers=publish,
        )
        assert _refused_with(resp, "A publish key can't make anything public"), (
            resp.text
        )
        await test_db_session.refresh(job)
        assert job.status == "pending"
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.ingest_jobs WHERE id = :id"), {"id": job.id}
        )
        await test_db_session.commit()


def test_only_a_public_intent_publishes_a_manifest_record():
    """A publish key's manifest update keeps its record_status, which is safe
    only while the one intent that publishes also asks for public, which the
    visibility gate refuses."""
    from app.processing.ingest.manifest_sources import (
        _COMMUNITY_INTENT_VISIBILITY,
        _UNMAPPED_INTENT_VISIBILITY,
    )

    assert _COMMUNITY_INTENT_VISIBILITY["published"] == "public"
    assert _UNMAPPED_INTENT_VISIBILITY != "public"


@pytest.mark.anyio
async def test_a_publish_key_narrows_and_publishes_in_one_update(
    client: AsyncClient, owner, datasets, test_db_session
):
    """Publishing is judged on the visibility the same update asks for."""
    headers, _ = owner
    dataset = datasets[0]
    publish = await _mint(client, headers, "publish")
    await _set_record(
        test_db_session, dataset.record_id, visibility="public", record_status="draft"
    )
    resp = await client.patch(
        f"/datasets/{dataset.id}",
        json={"visibility": "internal", "record_status": "published"},
        headers=publish,
    )
    assert resp.status_code == 200, resp.text
    assert await _record_values(test_db_session, dataset.record_id) == (
        "internal",
        "published",
    )


@pytest.mark.anyio
async def test_the_locked_recheck_judges_an_admins_publish_key_without_admin(
    client: AsyncClient, admin_auth_header, owner, test_db_session, monkeypatch
):
    """A transfer committed while the write waited for its lock is honoured."""
    from app.modules.catalog import authorization
    from tests.factories import create_dataset, get_user_id

    _, editor_id = owner
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session, created_by=admin_id, visibility="internal"
    )
    record_id = dataset.record_id
    lock = authorization.lock_catalog_rows

    async def transferred_while_waiting(session, **kwargs):
        await session.execute(
            text("UPDATE catalog.records SET created_by = :owner WHERE id = :id"),
            {"owner": editor_id, "id": record_id},
        )
        await lock(session, **kwargs)

    try:
        publish = await _mint(client, admin_auth_header, "publish")
        full = await _mint(client, admin_auth_header, "full")
        monkeypatch.setattr(
            authorization, "lock_catalog_rows", transferred_while_waiting
        )
        refused = await client.patch(
            f"/datasets/{dataset.id}", json={"title": "Taken"}, headers=publish
        )
        assert refused.status_code in (403, 404), refused.text
        allowed = await client.patch(
            f"/datasets/{dataset.id}", json={"title": "Admin edit"}, headers=full
        )
        assert allowed.status_code == 200, allowed.text
    finally:
        monkeypatch.undo()
        await test_db_session.execute(
            text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
        )
        await test_db_session.commit()


@pytest.mark.anyio
async def test_a_publish_key_cannot_import_an_arcgis_web_map(
    client: AsyncClient, owner, test_db_session
):
    headers, owner_id = owner
    publish = await _mint(client, headers, "publish")
    try:
        resp = await client.post(
            "/maps/import/arcgis-webmap/", json={"webmap": {}}, headers=publish
        )
        assert _scope_refused(resp), resp.text
    finally:
        await test_db_session.execute(
            text(
                "DELETE FROM catalog.api_keys WHERE user_id = :u AND scope = 'publish'"
            ),
            {"u": owner_id},
        )
        await test_db_session.commit()
