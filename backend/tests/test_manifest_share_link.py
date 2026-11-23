"""A version 2 publish that leaves a map public hands out its share link once.

Requirements: the docker database must be running with migrations applied.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
import structlog
from sqlalchemy import func, select, update
from starlette.requests import Request

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.catalog.maps import manifest_apply
from app.modules.catalog.maps.manifest_share import mint_share_link
from app.modules.catalog.maps.models import Map, MapEditHistoryEvent, MapShareToken
from app.modules.catalog.maps.service import revoke_share_token_by_map
from app.processing.ingest import manifest_links, manifest_share_links
from app.processing.ingest.manifest_share_links import (
    embed_snippet,
    minted_share_links,
)
from app.processing.ingest.manifest_schemas import (
    ManifestApplyRequest,
    ManifestMapResult,
)
from app.processing.ingest.manifest_service import apply_manifest
from tests.test_manifest_maps_apply import (
    _apply,
    _count,
    _as_publish_key,
    _dataset,
    _layer,
    _map,
)
from tests.test_manifest_maps_dry_run import _admin, _body
from tests.test_manifest_response_links import _frontend_routes

pytestmark = pytest.mark.anyio

APP_ROOT = "https://geolens.test"


@pytest.fixture(autouse=True)
def _public_urls(monkeypatch):
    monkeypatch.setattr(settings, "public_app_url", APP_ROOT)


def _token(share_url: str) -> str:
    parts = urlsplit(share_url)
    assert f"{parts.scheme}://{parts.netloc}" == APP_ROOT
    assert parts.path.startswith("/m/") and not parts.query
    return parts.path.removeprefix("/m/")


async def _share_rows(session, map_id) -> list[MapShareToken]:
    rows = await session.execute(
        select(MapShareToken)
        .where(MapShareToken.map_id == map_id)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _public_map(session, user, key="qgis-map-share", **fields):
    dataset_id = await _dataset(session, user.id)
    entry = _map(key, _layer(dataset_id=str(dataset_id)), **fields)
    [result] = (await _apply(session, user, entry)).maps
    return entry, result


async def _opens(client, session, token: str, map_id) -> bool:
    """Whether the share route serves the map ``map_id`` under ``token``."""
    response = await client.get(f"/maps/shared/{token}")
    name = await session.scalar(select(Map.name).where(Map.id == map_id))
    return response.status_code == 200 and response.json()["name"] == name


def test_the_embed_snippet_matches_the_share_panels():
    # The web app's share panel pins the same string, with an embed token.
    assert embed_snippet("https://geolens.example.com/m/abc123", "Harbor map") == (
        '<iframe src="https://geolens.example.com/m/abc123?embed=true"'
        ' title="Harbor map" width="100%" height="600"'
        ' sandbox="allow-scripts allow-same-origin"'
        ' style="border:none;"></iframe>'
    )


def test_the_embed_snippet_escapes_the_title():
    snippet = embed_snippet(
        "https://geolens.example.com/m/abc123", 'Bob\'s "Q&A" <map>'
    )

    assert 'title="Bob\'s &quot;Q&amp;A&quot; &lt;map&gt;"' in snippet


async def test_the_publish_that_creates_the_link_returns_it_and_the_embed_code(
    client, test_db_session, clean_tables
):
    admin = await _admin(test_db_session)

    _, created = await _public_map(
        test_db_session, admin, visibility="public", name='Parks & "Trails"'
    )

    assert (created.action, created.visibility) == ("create", "public")
    assert created.messages == []
    links = created.links
    assert links is not None and links.share is not None
    token = _token(links.share)
    [row] = await _share_rows(test_db_session, created.map_id)
    # The token is the one the share service stored, not one made elsewhere.
    assert hashlib.sha256(token.encode()).hexdigest() == row.token_hash
    assert (row.is_active, row.expires_at) == (True, None)
    assert await _opens(client, test_db_session, token, created.map_id)
    assert 'path="/m/:token"' in _frontend_routes()
    assert links.embed == (
        f'<iframe src="{APP_ROOT}/m/{token}?embed=true"'
        ' title="Parks &amp; &quot;Trails&quot;" width="100%" height="600"'
        ' sandbox="allow-scripts allow-same-origin"'
        ' style="border:none;"></iframe>'
    )


async def test_a_republish_returns_no_link_and_keeps_the_one_it_has(
    client, test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    entry, created = await _public_map(test_db_session, admin, visibility="public")
    token = _token(created.links.share)

    response = await _apply(test_db_session, admin, entry)

    [republished] = response.maps
    assert (republished.action, republished.visibility) == ("update", "public")
    assert republished.links is not None
    assert (republished.links.share, republished.links.embed) == (None, None)
    assert token not in response.model_dump_json()
    [row] = await _share_rows(test_db_session, created.map_id)
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert await _opens(client, test_db_session, token, created.map_id)


@pytest.mark.parametrize("visibility", [None, "internal"])
async def test_a_map_that_is_not_public_gets_no_link(
    test_db_session, clean_tables, visibility
):
    admin = await _admin(test_db_session)
    fields = {} if visibility is None else {"visibility": visibility}

    _, created = await _public_map(test_db_session, admin, **fields)

    assert created.visibility != "public"
    assert (created.links.share, created.links.embed) == (None, None)
    assert await _share_rows(test_db_session, created.map_id) == []


async def test_a_dry_run_creates_no_link(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    entry, created = await _public_map(test_db_session, admin)
    made_public = await client.put(
        f"/maps/{created.map_id}",
        json={"visibility": "public"},
        headers=admin_auth_header,
    )
    assert made_public.status_code == 200, made_public.text

    [existing] = (await _apply(test_db_session, admin, entry, dry_run=True)).maps
    [new] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-new",
                _layer(dataset_id=str(entry["layers"][0]["dataset_id"])),
                visibility="public",
            ),
            dry_run=True,
        )
    ).maps

    assert existing.visibility == "public"
    assert (existing.links.share, existing.links.embed) == (None, None)
    assert new.links is None
    assert (
        await test_db_session.scalar(select(func.count()).select_from(MapShareToken))
        == 0
    )


async def test_a_map_in_error_gets_no_link(test_db_session, clean_tables):
    admin = await _admin(test_db_session)

    [failed] = (
        await _apply(
            test_db_session,
            admin,
            _map(
                "qgis-map-share",
                _layer(dataset_id="00000000-0000-0000-0000-00000000beef"),
                visibility="public",
            ),
        )
    ).maps

    assert (failed.action, failed.links) == ("error", None)
    assert (
        await test_db_session.scalar(select(func.count()).select_from(MapShareToken))
        == 0
    )


async def test_a_publish_reactivating_a_revoked_link_returns_the_new_one(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    entry, created = await _public_map(test_db_session, admin, visibility="public")
    old = _token(created.links.share)
    revoked = await client.delete(
        f"/maps/{created.map_id}/share", headers=admin_auth_header
    )
    assert revoked.status_code == 204, revoked.text

    [republished] = (await _apply(test_db_session, admin, entry)).maps

    new = _token(republished.links.share)
    assert new != old
    [row] = await _share_rows(test_db_session, created.map_id)
    assert row.token_hash == hashlib.sha256(new.encode()).hexdigest()
    assert await _opens(client, test_db_session, new, created.map_id)
    # Reactivating replaces the stored hash, so the old token names nothing.
    assert (await client.get(f"/maps/shared/{old}")).status_code == 404


async def test_a_publish_that_narrows_the_map_retires_its_link(
    client, test_db_session, clean_tables
):
    admin = await _admin(test_db_session)
    entry, created = await _public_map(test_db_session, admin, visibility="public")
    token = _token(created.links.share)

    [narrowed] = (
        await _apply(test_db_session, admin, {**entry, "visibility": "private"})
    ).maps

    assert narrowed.visibility == "private"
    assert (narrowed.links.share, narrowed.links.embed) == (None, None)
    [row] = await _share_rows(test_db_session, created.map_id)
    assert row.is_active is False
    assert (await client.get(f"/maps/shared/{token}")).status_code == 410


async def test_a_publish_key_gives_a_public_map_its_link(
    client, test_db_session, admin_auth_header, clean_tables
):
    admin = await _admin(test_db_session)
    entry, created = await _public_map(test_db_session, admin)
    made_public = await client.put(
        f"/maps/{created.map_id}",
        json={"visibility": "public"},
        headers=admin_auth_header,
    )
    assert made_public.status_code == 200, made_public.text
    assert await _share_rows(test_db_session, created.map_id) == []
    _as_publish_key(test_db_session)

    [first] = (await _apply(test_db_session, admin, entry)).maps
    [again] = (await _apply(test_db_session, admin, entry)).maps

    assert (first.visibility, again.visibility) == ("public", "public")
    token = _token(first.links.share)
    assert await _opens(client, test_db_session, token, created.map_id)
    assert (again.links.share, again.links.embed) == (None, None)
    [row] = await _share_rows(test_db_session, created.map_id)
    assert row.expires_at is None
    [audit] = (
        await test_db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "map.share",
                AuditLog.resource_id == created.map_id,
            )
        )
    ).scalars()
    assert "api_key_id" in audit.details


@pytest.mark.parametrize("as_key", [False, True], ids=["person", "publish-key"])
async def test_a_publish_never_changes_a_live_links_expiry(
    client, test_db_session, admin_auth_header, clean_tables, as_key
):
    admin = await _admin(test_db_session)
    entry, created = await _public_map(test_db_session, admin, visibility="public")
    token = _token(created.links.share)
    expiring = await client.patch(
        f"/maps/{created.map_id}/share",
        json={"expires_in_days": 7},
        headers=admin_auth_header,
    )
    assert expiring.status_code == 200, expiring.text
    [row] = await _share_rows(test_db_session, created.map_id)
    expires_at = row.expires_at
    assert expires_at is not None
    assert expires_at > datetime.now(timezone.utc) + timedelta(days=6)
    if as_key:
        # A publish key may keep a map public but never ask for public.
        _as_publish_key(test_db_session)
        entry = {k: v for k, v in entry.items() if k != "visibility"}

    [republished] = (await _apply(test_db_session, admin, entry)).maps

    assert republished.visibility == "public"

    assert republished.links.share is None
    [row] = await _share_rows(test_db_session, created.map_id)
    assert (row.is_active, row.expires_at) == (True, expires_at)
    assert await _opens(client, test_db_session, token, created.map_id)


async def test_the_raw_token_reaches_only_the_response(test_db_session, clean_tables):
    admin = await _admin(test_db_session)

    with structlog.testing.capture_logs() as logs:
        _, created = await _public_map(test_db_session, admin, visibility="public")

    token = _token(created.links.share)
    assert token not in repr(logs)
    history = (
        await test_db_session.execute(
            select(MapEditHistoryEvent.details).where(
                MapEditHistoryEvent.map_id == created.map_id
            )
        )
    ).scalars()
    audits = (
        await test_db_session.execute(
            select(AuditLog.details).where(AuditLog.resource_id == created.map_id)
        )
    ).scalars()
    stored = [*history, *audits]
    assert stored and token not in repr(stored)
    assert {"token_hint": token[:8]} in stored


async def test_a_session_hands_out_a_minted_token_once(test_db_session, clean_tables):
    admin = await _admin(test_db_session)
    _, created = await _public_map(test_db_session, admin, visibility="public")
    await revoke_share_token_by_map(test_db_session, created.map_id)
    await test_db_session.commit()
    # Held, so the session hands the service this same instance each time.
    [row] = await _share_rows(test_db_session, created.map_id)

    minted = (await mint_share_link(test_db_session, created.map_id, admin, None)).token
    await test_db_session.commit()
    again = (await mint_share_link(test_db_session, created.map_id, admin, None)).token

    assert minted is not None
    assert again is None
    assert row.token_hash == hashlib.sha256(minted.encode()).hexdigest()


def test_minted_links_reach_the_response_only_as_its_links():
    result = ManifestMapResult(map_key="qgis-map-share", action="update")
    result._minted_links = minted_share_links(
        APP_ROOT, uuid.uuid4(), "secret-raw-token", "Parks"
    )

    assert "secret-raw-token" not in result.model_dump_json()
    assert "secret-raw-token" not in repr(result)


def test_the_embed_snippet_escapes_the_share_url():
    snippet = embed_snippet('https://a"b.example/m/abc123', "Parks")

    assert 'src="https://a&quot;b.example/m/abc123?embed=true"' in snippet


def _not_live(shape: str) -> dict:
    past = datetime.now(timezone.utc) - timedelta(days=1)
    return {"expires_at": past, "is_active": shape == "active-expired"}


_SHAPES = ["revoked-expired", "active-expired"]


@pytest.mark.parametrize("shape", _SHAPES)
async def test_a_publish_replaces_a_link_that_is_not_live(
    client, test_db_session, clean_tables, shape
):
    admin = await _admin(test_db_session)
    entry, created = await _public_map(test_db_session, admin, visibility="public")
    old = _token(created.links.share)
    await test_db_session.execute(
        update(MapShareToken)
        .where(MapShareToken.map_id == created.map_id)
        .values(**_not_live(shape))
    )
    await test_db_session.commit()

    [republished] = (await _apply(test_db_session, admin, entry)).maps

    new = _token(republished.links.share)
    assert new != old
    [row] = await _share_rows(test_db_session, created.map_id)
    assert (row.is_active, row.expires_at) == (True, None)
    assert await _opens(client, test_db_session, new, created.map_id)
    assert (await client.get(f"/maps/shared/{old}")).status_code == 404
    [again] = (await _apply(test_db_session, admin, entry)).maps
    assert again.links.share is None


@pytest.mark.parametrize("shape", _SHAPES)
async def test_sharing_replaces_a_link_that_is_not_live(
    client, test_db_session, admin_auth_header, clean_tables, shape
):
    admin = await _admin(test_db_session)
    _, created = await _public_map(test_db_session, admin, visibility="public")
    old = _token(created.links.share)
    await test_db_session.execute(
        update(MapShareToken)
        .where(MapShareToken.map_id == created.map_id)
        .values(**_not_live(shape))
    )
    await test_db_session.commit()

    response = await client.post(
        f"/maps/{created.map_id}/share", json={}, headers=admin_auth_header
    )

    assert response.status_code == 200, response.text
    body = response.json()
    new = body["token"]
    assert (new != old, body["is_active"], body["expires_at"]) == (True, True, None)
    assert body["share_url"] == f"/m/{new}"
    assert await _opens(client, test_db_session, new, created.map_id)


async def test_a_failure_building_other_links_keeps_a_minted_share(
    client, test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)

    async def broken(*_args, **_kwargs):
        raise RuntimeError("in-flight lookup failed")

    monkeypatch.setattr(manifest_links, "datasets_with_jobs_in_flight", broken)

    _, created = await _public_map(test_db_session, admin, visibility="public")

    assert created.links is not None
    assert created.links.viewer == f"{APP_ROOT}/maps/{created.map_id}"
    token = _token(created.links.share)
    assert created.links.embed is not None and token in created.links.embed
    assert await _opens(client, test_db_session, token, created.map_id)


async def test_a_failure_after_the_mint_writes_no_link(
    test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)

    async def broken(*_args, **_kwargs):
        raise RuntimeError("groups lookup failed")

    monkeypatch.setattr(manifest_apply, "map_groups", broken)

    _, failed = await _public_map(test_db_session, admin, visibility="public")

    assert (failed.action, failed.links) == ("error", None)
    assert await _count(test_db_session, MapShareToken, "qgis-map-share") == 0
    assert await _count(test_db_session, Map, "qgis-map-share") == 0


def _app_url_lookup_fails(monkeypatch) -> None:
    async def broken(*_args, **_kwargs):
        raise RuntimeError("settings lookup failed")

    monkeypatch.setattr(manifest_share_links, "get_configured_public_app_url", broken)


async def _published_without_a_link(session, result, key) -> None:
    """A public map published, with no share link minted and info A074."""
    assert (result.action, result.visibility) == ("create", "public")
    links = result.links
    assert links is None or (links.share, links.embed) == (None, None)
    assert [(m.code, m.severity) for m in result.messages] == [("A074", "info")]
    assert "PUBLIC_APP_URL" in result.messages[0].message
    assert await _count(session, Map, key) == 1
    assert await _count(session, MapShareToken, key) == 0


def _request(*, headers=(), state=None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/ingest/manifest/apply",
            "scheme": "http",
            "headers": [(k.encode(), v.encode()) for k, v in headers],
            "state": state or {},
        }
    )


async def _apply_with(session, user, http_request, *entries):
    body = ManifestApplyRequest.model_validate(_body(*entries, dry_run=False))
    return (await apply_manifest(session, body, user, http_request)).maps


async def _public_entry(session, user, key="qgis-map-share"):
    dataset_id = await _dataset(session, user.id)
    return _map(key, _layer(dataset_id=str(dataset_id)), visibility="public")


async def test_a_private_map_publishes_when_the_app_url_cannot_be_resolved(
    test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)
    _app_url_lookup_fails(monkeypatch)

    _, created = await _public_map(test_db_session, admin)

    assert (created.action, created.visibility) == ("create", "private")
    assert created.messages == []
    assert (created.links.share, created.links.embed) == (None, None)
    assert await _count(test_db_session, Map, "qgis-map-share") == 1


async def test_a_public_map_publishes_without_a_link_when_the_lookup_fails(
    test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)
    dataset_id = await _dataset(test_db_session, admin.id)
    layer = _layer(dataset_id=str(dataset_id))
    _app_url_lookup_fails(monkeypatch)

    response = await _apply(
        test_db_session,
        admin,
        _map("qgis-map-public", layer, visibility="public"),
        _map("qgis-map-private", layer),
    )

    public, private = response.maps
    await _published_without_a_link(test_db_session, public, "qgis-map-public")
    assert (private.action, private.visibility) == ("create", "private")
    assert await _count(test_db_session, Map, "qgis-map-private") == 1


@pytest.mark.parametrize(
    "headers",
    [
        # A desktop client calling the API directly: the API's host is never
        # where the web app serves /m/{token}.
        [("host", "geolens.example.com:8001")],
        [("host", "127.0.0.1:8001")],
        [("host", "localhost:8001")],
        [
            ("host", "api:8000"),
            ("origin", "https://geolens.example.com"),
            ("x-forwarded-proto", "https"),
            ("x-forwarded-host", "geolens.example.com"),
        ],
        [("host", "geolens.test"), ("x-forwarded-host", "geolens.test%2f@evil")],
    ],
    ids=["dns-host", "ip-host", "localhost", "forwarded-host", "malformed-forwarded"],
)
async def test_a_public_map_publishes_without_a_link_without_public_app_url(
    test_db_session, clean_tables, monkeypatch, headers
):
    admin = await _admin(test_db_session)
    monkeypatch.setattr(settings, "public_app_url", None)
    entry = await _public_entry(test_db_session, admin)

    [result] = await _apply_with(
        test_db_session, admin, _request(headers=headers), entry
    )

    await _published_without_a_link(test_db_session, result, "qgis-map-share")


async def test_a_public_map_with_a_live_link_publishes_without_the_app_url(
    client, test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)
    entry, created = await _public_map(test_db_session, admin, visibility="public")
    token = _token(created.links.share)
    _app_url_lookup_fails(monkeypatch)

    [republished] = (await _apply(test_db_session, admin, entry)).maps

    assert (republished.action, republished.visibility) == ("update", "public")
    assert republished.messages == []
    assert republished.links.share is None
    assert await _opens(client, test_db_session, token, created.map_id)


_TENANT_ID = "00000000-0000-0000-0000-0000000000a1"


def _tenant(origin: str | None) -> Request:
    return _request(state={"tenant_id": _TENANT_ID, "tenant_public_origin": origin})


async def test_a_tenant_request_without_its_origin_mints_no_link(
    test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)
    entry = await _public_entry(test_db_session, admin)
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")

    [result] = await _apply_with(test_db_session, admin, _tenant(None), entry)

    await _published_without_a_link(test_db_session, result, "qgis-map-share")


async def test_a_tenant_request_gets_links_on_its_origin(
    test_db_session, clean_tables, monkeypatch
):
    admin = await _admin(test_db_session)
    entry = await _public_entry(test_db_session, admin)
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    origin = "https://tenant-a.example.test"

    [created] = await _apply_with(test_db_session, admin, _tenant(origin), entry)

    assert (created.action, created.messages) == ("create", [])
    share = created.links.share
    assert share is not None and share.startswith(f"{origin}/m/")
    assert created.links.embed.startswith(f'<iframe src="{share}?embed=true"')
    assert created.links.viewer == f"{origin}/maps/{created.map_id}"
    [row] = await _share_rows(test_db_session, created.map_id)
    token = share.removeprefix(f"{origin}/m/")
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
