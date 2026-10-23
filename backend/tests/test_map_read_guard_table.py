"""Who reads a map, path by path: visibility × caller over every map read path.

Each test builds one map per visibility, owned by an editor, and records what
every caller gets back. The expected tables derive from ``READERS`` (the
signed-in map read rule) and ``SHARE_LINK_VISIBILITIES`` (a share or embed
token admits only the anonymous audience), so a path that drifts from either
fails here.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass
from io import BytesIO

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select, update

from app.core import public_urls
from app.core.config import settings
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.maps import service_public
from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.service import (
    create_share_token,
    find_maps_broken_by_dataset_visibility,
)
from app.modules.embed_tokens.service import create_embed_token
from app.processing.ai import router as ai_router

from tests.factories import create_dataset, create_user, get_user_id

pytestmark = pytest.mark.anyio

VISIBILITIES = ("private", "internal", "public")
CALLERS = ("anonymous", "owner", "admin", "other")

READERS = {
    "private": {"owner", "admin"},
    "internal": {"owner", "admin", "other"},
    "public": {"anonymous", "owner", "admin", "other"},
}
SHARE_LINK_VISIBILITIES = {"public"}


def _reads(visibility: str, caller: str) -> bool:
    return caller in READERS[visibility]


def _audience(caller: str) -> set[str]:
    return {v for v in VISIBILITIES if _reads(v, caller)}


def _table(fn) -> dict[tuple[str, str], object]:
    return {(v, c): fn(v, c) for v in VISIBILITIES for c in CALLERS}


@dataclass
class World:
    headers: dict[str, dict[str, str]]
    user_ids: dict[str, uuid.UUID]
    maps: dict[str, str]
    names: dict[str, str]
    dataset_id: str | None


def _png_data_uri() -> str:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(0, 0, 0)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


async def _world(
    client: AsyncClient,
    admin_headers: dict[str, str],
    session,
    *,
    with_layer: bool = False,
    with_images: bool = False,
) -> World:
    """One editor-owned map per visibility, plus an unrelated signed-in editor."""
    owner_headers, owner_id = await create_user(client, admin_headers, "editor")
    other_headers, other_id = await create_user(client, admin_headers, "editor")
    admin_id = await get_user_id(session, settings.geolens_admin_username)
    dataset_id = None
    if with_layer:
        dataset = await create_dataset(
            session, created_by=uuid.UUID(owner_id), visibility="public"
        )
        await session.commit()
        dataset_id = str(dataset.id)

    tag = uuid.uuid4().hex[:10]
    maps: dict[str, str] = {}
    names: dict[str, str] = {}
    for visibility in VISIBILITIES:
        name = f"guard-table-{tag}-{visibility}"
        resp = await client.post("/maps/", json={"name": name}, headers=owner_headers)
        assert resp.status_code == 201, resp.text
        map_id = resp.json()["id"]
        if dataset_id is not None:
            resp = await client.post(
                f"/maps/{map_id}/layers",
                json={"dataset_id": dataset_id},
                headers=owner_headers,
            )
            assert resp.status_code == 201, resp.text
        if with_images:
            for path in ("thumbnail", "og-image"):
                resp = await client.put(
                    f"/maps/{map_id}/{path}/",
                    json={"data_uri": _png_data_uri()},
                    headers=owner_headers,
                )
                assert resp.status_code == 204, resp.text
        if visibility != "private":
            resp = await client.put(
                f"/maps/{map_id}",
                json={"visibility": visibility},
                headers=owner_headers,
            )
            assert resp.status_code == 200, resp.text
        maps[visibility] = map_id
        names[visibility] = name

    return World(
        headers={
            "anonymous": {},
            "owner": owner_headers,
            "admin": admin_headers,
            "other": other_headers,
        },
        user_ids={
            "owner": uuid.UUID(owner_id),
            "admin": admin_id,
            "other": uuid.UUID(other_id),
        },
        maps=maps,
        names=names,
        dataset_id=dataset_id,
    )


async def _observe(world: World, request) -> dict[tuple[str, str], object]:
    return {
        (v, c): await request(world.maps[v], world.headers[c])
        for v in VISIBILITIES
        for c in CALLERS
    }


async def _set_visibility_directly(session, map_id: str, visibility: str) -> None:
    """Change visibility without the PUT side effects that revoke links."""
    await session.execute(
        update(Map).where(Map.id == uuid.UUID(map_id)).values(visibility=visibility)
    )
    await session.commit()


async def test_map_detail_and_access(client, admin_auth_header, test_db_session):
    world = await _world(client, admin_auth_header, test_db_session)
    expected = _table(lambda v, c: 200 if _reads(v, c) else 404)

    for path in ("", "/access/", "/style.json"):

        async def read(map_id, headers, path=path):
            resp = await client.get(f"/maps/{map_id}{path}", headers=headers)
            return resp.status_code

        assert await _observe(world, read) == expected, path


async def test_stored_images(client, admin_auth_header, test_db_session):
    world = await _world(client, admin_auth_header, test_db_session, with_images=True)

    def expected(v, c):
        if not _reads(v, c):
            return 404, None
        anonymous_reads = _reads(v, "anonymous")
        return 200, "public, no-cache" if anonymous_reads else "private, no-cache"

    for path in ("thumbnail", "og-image"):

        async def image(map_id, headers, path=path):
            resp = await client.get(f"/maps/{map_id}/{path}/", headers=headers)
            return resp.status_code, resp.headers.get("cache-control")

        assert await _observe(world, image) == _table(expected), path


async def test_map_list(client, admin_auth_header, test_db_session):
    world = await _world(client, admin_auth_header, test_db_session)
    tag = world.names["public"].rsplit("-", 1)[0]
    by_id = {map_id: v for v, map_id in world.maps.items()}

    observed = {}
    for caller in CALLERS:
        resp = await client.get(
            "/maps/", params={"search": tag}, headers=world.headers[caller]
        )
        assert resp.status_code == 200, resp.text
        observed[caller] = {by_id[m["id"]] for m in resp.json()["maps"]}

    assert observed == {c: _audience(c) for c in CALLERS}


async def test_dataset_map_list(client, admin_auth_header, test_db_session):
    world = await _world(client, admin_auth_header, test_db_session, with_layer=True)
    by_id = {map_id: v for v, map_id in world.maps.items()}

    observed = {}
    for caller in CALLERS:
        resp = await client.get(
            f"/datasets/{world.dataset_id}/maps/",
            params={"limit": 200},
            headers=world.headers[caller],
        )
        assert resp.status_code == 200, resp.text
        observed[caller] = {
            by_id[m["id"]] for m in resp.json()["maps"] if m["id"] in by_id
        }

    assert observed == {c: _audience(c) for c in CALLERS}


async def test_duplicate(client, admin_auth_header, test_db_session):
    world = await _world(client, admin_auth_header, test_db_session)

    async def duplicate(map_id, headers):
        resp = await client.post(f"/maps/{map_id}/duplicate/", headers=headers)
        return resp.status_code

    expected = _table(
        lambda v, c: 401 if c == "anonymous" else (201 if _reads(v, c) else 404)
    )
    assert await _observe(world, duplicate) == expected


async def test_visibility_check(client, admin_auth_header, test_db_session):
    world = await _world(client, admin_auth_header, test_db_session)

    async def check(map_id, headers):
        resp = await client.get(f"/maps/{map_id}/visibility-check/", headers=headers)
        return resp.status_code

    def expected(v, c):
        if c == "anonymous":
            return 401
        if not _reads(v, c):
            return 404
        return 200 if c in ("owner", "admin") else 403

    assert await _observe(world, check) == _table(expected)


async def test_link_preview_reads_as_anonymous(
    client, admin_auth_header, test_db_session, monkeypatch
):
    async def _no_persisted_overrides(db):
        return {}

    monkeypatch.setattr(
        public_urls, "_load_public_url_overrides", _no_persisted_overrides
    )
    monkeypatch.setattr(settings, "public_app_url", "https://maps.example.org")
    monkeypatch.setattr(settings, "public_api_url", None)
    monkeypatch.setattr(settings, "public_base_url", None)
    public_urls.invalidate_public_url_cache()
    try:
        world = await _world(client, admin_auth_header, test_db_session)

        async def preview(map_id, headers):
            resp = await client.get(f"/maps/{map_id}/link-preview", headers=headers)
            return resp.status_code

        expected = _table(lambda v, c: 200 if _reads(v, "anonymous") else 404)
        assert await _observe(world, preview) == expected
    finally:
        public_urls.invalidate_public_url_cache()


async def test_ai_chat_map_gate(client, admin_auth_header, test_db_session):
    world = await _world(client, admin_auth_header, test_db_session)
    users = {
        c: await test_db_session.get(User, world.user_ids[c])
        for c in ("owner", "admin", "other")
    }

    observed = {}
    for v in VISIBILITIES:
        for c, user in users.items():
            try:
                await ai_router._validate_chat_layers(
                    test_db_session, user, world.maps[v], [], port=None
                )
                observed[v, c] = 200
            except Exception as exc:  # broad: records the HTTP status raised
                observed[v, c] = getattr(exc, "status_code", repr(exc))

    assert observed == {
        (v, c): 200 if _reads(v, c) else 404 for v in VISIBILITIES for c in users
    }


async def test_share_link_creation(client, admin_auth_header, test_db_session):
    world = await _world(client, admin_auth_header, test_db_session)

    async def share(map_id, headers):
        resp = await client.post(f"/maps/{map_id}/share/", headers=headers)
        return resp.status_code

    def expected(v, c):
        if c == "anonymous":
            return 401
        if c == "other":
            return 403
        return 200 if v in SHARE_LINK_VISIBILITIES else 400

    assert await _observe(world, share) == _table(expected)

    observed = {}
    for v in VISIBILITIES:
        try:
            await create_share_token(
                test_db_session, uuid.UUID(world.maps[v]), world.user_ids["owner"]
            )
            observed[v] = "created"
        except ValueError as exc:
            observed[v] = str(exc)
        await test_db_session.rollback()
    assert observed == {
        v: "created"
        if v in SHARE_LINK_VISIBILITIES
        else "Map must be public before sharing"
        for v in VISIBILITIES
    }


@pytest.mark.parametrize("with_layer", [False, True])
async def test_shared_views(client, admin_auth_header, test_db_session, with_layer):
    """A link minted on a public map, observed after visibility changed under it.

    Without a layer the shared view answers from the map row; with one it
    answers from the layer query, so both reads of visibility are covered.
    An embed token needs a layer to scope, so only the layered maps carry one.
    """
    world = await _world(
        client, admin_auth_header, test_db_session, with_layer=with_layer
    )
    links: dict[str, tuple[str, str | None]] = {}
    for v in VISIBILITIES:
        map_id = world.maps[v]
        await _set_visibility_directly(test_db_session, map_id, "public")
        resp = await client.post(
            f"/maps/{map_id}/share/", headers=world.headers["owner"]
        )
        assert resp.status_code == 200, resp.text
        embed = None
        if with_layer:
            _, embed = await create_embed_token(
                test_db_session, uuid.UUID(map_id), world.user_ids["owner"]
            )
            await test_db_session.commit()
        links[v] = (resp.json()["token"], embed)
        await _set_visibility_directly(test_db_session, map_id, v)

    callers = (*CALLERS, "embed") if with_layer else CALLERS
    observed = {}
    for v in VISIBILITIES:
        share, embed = links[v]
        for c in callers:
            headers = {"X-Embed-Token": embed} if c == "embed" else world.headers[c]
            view = await client.get(f"/maps/shared/{share}", headers=headers)
            card = await client.get(f"/maps/shared/{share}/card", headers=headers)
            has_tags = re.search(r'property="og:title"', card.text) is not None
            observed[v, c] = (view.status_code, card.status_code, has_tags)

    assert observed == {
        (v, c): (200, 200, True) if v in SHARE_LINK_VISIBILITIES else (404, 200, False)
        for v in VISIBILITIES
        for c in callers
    }


async def test_admin_published_maps(client, admin_auth_header, test_db_session):
    world = await _world(client, admin_auth_header, test_db_session)
    tag = world.names["public"].rsplit("-", 1)[0]
    resp = await client.get(
        "/admin/share-tokens/", params={"search": tag}, headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    by_id = {map_id: v for v, map_id in world.maps.items()}
    listed = {by_id[t["map_id"]] for t in resp.json()["tokens"]}
    assert listed == SHARE_LINK_VISIBILITIES


async def test_stranded_shared_maps(
    client, admin_auth_header, test_db_session, monkeypatch
):
    """Which of the owner's maps a dataset narrowing would strand."""
    world = await _world(client, admin_auth_header, test_db_session, with_layer=True)
    dataset_id = uuid.UUID(world.dataset_id)
    record_id = (
        await test_db_session.execute(
            select(Dataset.record_id).where(Dataset.id == dataset_id)
        )
    ).scalar_one()
    by_name = {name: v for v, name in world.names.items()}

    async def stranded(old: str, new: str) -> set[str]:
        names = await find_maps_broken_by_dataset_visibility(
            test_db_session,
            dataset_id,
            old_visibility=old,
            new_visibility=new,
            record_status="published",
            record_id=record_id,
            owner_id=world.user_ids["owner"],
        )
        return {by_name[n] for n in names}

    signed_in_audience = _audience("other")
    anonymous_audience = _audience("anonymous")
    assert await stranded("public", "private") == signed_in_audience
    assert await stranded("public", "internal") == anonymous_audience
    assert await stranded("internal", "private") == signed_in_audience

    monkeypatch.setattr(
        service_public, "answers_audience_questions", lambda permission: False
    )
    assert await stranded("public", "internal") == signed_in_audience
