"""Story embed and video blocks: the approved-host setting, save and publish
refusals, and the frame-src nginx copies into the page CSP."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient

from app.core import public_urls
from app.core.config import settings
from app.platform.story_frames import (
    StoryFrameHost,
    frame_src_directive,
    frame_url_host,
    normalize_frame_host,
    parse_frame_hosts,
)
from tests.factories import create_user
from tests.test_story_embed_frame_policy import _public_story

MEDIA = "media.example.org"
VIDEO = "video.example.net"
OWN_HOST = "maps.example.org"


# ---------------------------------------------------------------------------
# Host and address shapes
# ---------------------------------------------------------------------------


def test_hosts_are_lower_cased_and_deduplicated():
    assert parse_frame_hosts(
        [
            {"host": " Media.Example.ORG "},
            {"host": "media.example.org", "allow_same_origin": True},
            {"host": VIDEO, "allow_same_origin": True},
        ]
    ) == [
        {"host": MEDIA, "allow_same_origin": False},
        {"host": VIDEO, "allow_same_origin": True},
    ]


@pytest.mark.parametrize(
    "host",
    [
        "*.example.org",
        "https://media.example.org",
        "media.example.org:8443",
        "media.example.org/path",
        "localhost",
        "10.0.0.1",
        "0x7f.0x0.0x0.0x1",
        "0x7f.1",
        "media\n.example.org",
        "[::1]",
        "exa%6dple.org",
        "-bad.example.org",
        "",
    ],
)
def test_a_host_that_is_not_an_exact_name_is_refused(host: str):
    with pytest.raises(ValueError):
        normalize_frame_host(host)


def test_the_list_holds_at_most_fifty_hosts():
    parse_frame_hosts([{"host": f"h{i}.example.org"} for i in range(50)])
    with pytest.raises(ValueError):
        parse_frame_hosts([{"host": f"h{i}.example.org"} for i in range(51)])
    with pytest.raises(ValueError):
        parse_frame_hosts("media.example.org")
    with pytest.raises(ValueError):
        parse_frame_hosts([{"host": MEDIA, "extra": 1}])


def test_the_sites_own_host_is_refused():
    with pytest.raises(ValueError, match="own host"):
        parse_frame_hosts([{"host": "Maps.Example.org"}], own_host=OWN_HOST)
    assert parse_frame_hosts([{"host": "www.youtube.com"}], own_host=OWN_HOST) == [
        {"host": "www.youtube.com", "allow_same_origin": False}
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://media.example.org/v/1",
        "https://user@media.example.org/v/1",
        "https://user:pw@media.example.org/v/1",
        "https://media.example.org:8443/v/1",
        "https://10.0.0.1/v/1",
        "https://0x7f.0x0.0x0.0x1/v/1",
        "https://[::1]/v/1",
        "https://media.example.org\\@evil.example.com/",
        "https://media.example.org/v 1",
        "javascript:alert(1)",
        "//media.example.org/v/1",
    ],
)
def test_a_frame_address_must_be_https_on_a_plain_host(url: str):
    with pytest.raises(ValueError):
        frame_url_host(url)


def test_a_frame_address_keeps_its_path_and_query():
    assert frame_url_host("https://Media.Example.org:443/v/1?t=30#x") == MEDIA


def test_the_directive_names_exactly_the_hosts():
    hosts = [StoryFrameHost(host=MEDIA), StoryFrameHost(host=VIDEO)]
    assert frame_src_directive([]) == "frame-src 'self' blob:"
    assert (
        frame_src_directive(hosts)
        == f"frame-src 'self' blob: https://{MEDIA} https://{VIDEO}"
    )


# ---------------------------------------------------------------------------
# Through the API
# ---------------------------------------------------------------------------


def _detail(resp) -> dict:
    detail = resp.json()["detail"]
    return json.loads(detail) if isinstance(detail, str) else detail


async def _set_hosts(client: AsyncClient, admin: dict, hosts: list) -> None:
    resp = await client.put(
        "/settings/", json={"settings": {"story_frame_hosts": hosts}}, headers=admin
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture
async def owner(client: AsyncClient, admin_auth_header: dict):
    headers, _ = await create_user(client, admin_auth_header, "editor")
    yield headers
    await _set_hosts(client, admin_auth_header, [])


def _frame(kind: str, url: str, title: str = "A chart") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": kind,
        "v": 1,
        "config": {"url": url, "title": title},
    }


def _chapter(*blocks: dict) -> dict:
    return {"id": str(uuid.uuid4()), "title": "One", "blocks": list(blocks)}


async def _story(client: AsyncClient, headers: dict) -> dict:
    resp = await client.post("/stories/", json={"title": "Framed"}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _save(client, headers, story: dict, chapters: list[dict]):
    return await client.put(
        f"/stories/{story['id']}/draft",
        json={
            "revision": story["revision"],
            "document": {"version": 1, "chapters": chapters},
        },
        headers=headers,
    )


async def _policy(client: AsyncClient) -> str:
    resp = await client.get("/stories/frame-src-policy")
    assert resp.status_code == 200
    assert resp.content == b""
    return resp.headers["x-story-frame-src"]


@pytest.mark.anyio
async def test_only_an_admin_sets_the_hosts(
    client: AsyncClient, admin_auth_header: dict, owner: dict
):
    resp = await client.put(
        "/settings/",
        json={"settings": {"story_frame_hosts": [{"host": MEDIA}]}},
        headers=owner,
    )
    assert resp.status_code == 403
    resp = await client.put(
        "/settings/",
        json={"settings": {"story_frame_hosts": [{"host": "*.example.org"}]}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
    await _set_hosts(
        client, admin_auth_header, [{"host": "Media.Example.org"}, {"host": MEDIA}]
    )
    resp = await client.get("/stories/frame-hosts/")
    assert resp.status_code == 200
    assert resp.json() == [{"host": MEDIA, "allow_same_origin": False}]


def _serve_from_own_host(monkeypatch) -> None:
    async def _no_persisted_overrides(db):
        return {}

    monkeypatch.setattr(
        public_urls, "_load_public_url_overrides", _no_persisted_overrides
    )
    monkeypatch.setattr(settings, "public_app_url", f"https://{OWN_HOST}")
    public_urls.invalidate_public_url_cache()


@pytest.fixture(autouse=True)
def _fresh_public_url_cache():
    yield
    public_urls.invalidate_public_url_cache()


@pytest.mark.anyio
async def test_the_sites_own_host_cannot_be_approved(
    client: AsyncClient, admin_auth_header: dict, owner: dict, monkeypatch
):
    _serve_from_own_host(monkeypatch)
    resp = await client.put(
        "/settings/",
        json={"settings": {"story_frame_hosts": [{"host": OWN_HOST}]}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text
    await _set_hosts(client, admin_auth_header, [{"host": "www.youtube.com"}])
    resp = await client.get("/stories/frame-hosts/")
    assert resp.json() == [{"host": "www.youtube.com", "allow_same_origin": False}]


@pytest.mark.anyio
async def test_a_stored_own_host_is_dropped_and_the_rest_kept(
    client: AsyncClient, admin_auth_header: dict, owner: dict, monkeypatch
):
    await _set_hosts(
        client, admin_auth_header, [{"host": OWN_HOST}, {"host": "www.youtube.com"}]
    )
    _serve_from_own_host(monkeypatch)
    assert (await client.get("/stories/frame-hosts/")).json() == [
        {"host": "www.youtube.com", "allow_same_origin": False}
    ]
    assert await _policy(client) == "frame-src 'self' blob: https://www.youtube.com"


@pytest.mark.anyio
async def test_a_public_app_url_set_in_the_same_request_is_checked(
    client: AsyncClient, admin_auth_header: dict, owner: dict, monkeypatch
):
    async def _no_persisted_overrides(db):
        return {}

    monkeypatch.setattr(
        public_urls, "_load_public_url_overrides", _no_persisted_overrides
    )
    monkeypatch.setattr(settings, "public_app_url", None)
    public_urls.invalidate_public_url_cache()
    resp = await client.put(
        "/settings/",
        json={
            "settings": {
                "public_app_url": f"https://{OWN_HOST}",
                "story_frame_hosts": [{"host": OWN_HOST}],
            }
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.anyio
async def test_the_policy_follows_the_list(
    client: AsyncClient, admin_auth_header: dict, owner: dict
):
    assert await _policy(client) == "frame-src 'self' blob:"
    await _set_hosts(
        client,
        admin_auth_header,
        [{"host": MEDIA}, {"host": VIDEO, "allow_same_origin": True}],
    )
    assert (
        await _policy(client)
        == f"frame-src 'self' blob: https://{MEDIA} https://{VIDEO}"
    )
    await _set_hosts(client, admin_auth_header, [{"host": VIDEO}])
    assert await _policy(client) == f"frame-src 'self' blob: https://{VIDEO}"


@pytest.mark.anyio
async def test_an_empty_list_refuses_every_frame_block(client: AsyncClient, owner):
    story = await _story(client, owner)
    for kind in ("embed", "video"):
        block = _frame(kind, f"https://{MEDIA}/a")
        resp = await _save(client, owner, story, [_chapter(block)])
        assert resp.status_code == 422, resp.text
        detail = _detail(resp)
        assert detail["code"] == "story_frame_host_not_allowed"
        assert detail["blocks"] == [
            {"chapter": 1, "block_id": block["id"], "type": kind, "host": MEDIA}
        ]


@pytest.mark.anyio
async def test_a_listed_host_saves_and_another_is_named(
    client: AsyncClient, admin_auth_header: dict, owner: dict
):
    await _set_hosts(client, admin_auth_header, [{"host": MEDIA}])
    story = await _story(client, owner)
    listed = _frame("video", f"https://{MEDIA}/v/1?t=3", " Talk ")
    resp = await _save(client, owner, story, [_chapter(listed)])
    assert resp.status_code == 200, resp.text
    saved = resp.json()["document"]["chapters"][0]["blocks"][0]
    assert saved["config"] == {"url": f"https://{MEDIA}/v/1?t=3", "title": "Talk"}

    other = _frame("embed", "https://elsewhere.example.com/form")
    resp = await _save(
        client,
        owner,
        resp.json(),
        [_chapter(listed), _chapter(listed | {"id": str(uuid.uuid4())}, other)],
    )
    assert resp.status_code == 422, resp.text
    assert _detail(resp)["blocks"] == [
        {
            "chapter": 2,
            "block_id": other["id"],
            "type": "embed",
            "host": "elsewhere.example.com",
        }
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "config",
    [
        {"url": f"http://{MEDIA}/a", "title": "A"},
        {"url": f"https://{MEDIA}:8443/a", "title": "A"},
        {"url": f"https://{MEDIA}/a", "title": "  "},
        {"url": f"https://{MEDIA}/a"},
        {"url": f"https://{MEDIA}/a", "title": "A", "html": "<iframe>"},
    ],
)
async def test_a_frame_block_needs_an_https_address_and_a_title(
    client: AsyncClient, admin_auth_header: dict, owner: dict, config: dict
):
    await _set_hosts(client, admin_auth_header, [{"host": MEDIA}])
    story = await _story(client, owner)
    block = {"id": str(uuid.uuid4()), "type": "embed", "v": 1, "config": config}
    resp = await _save(client, owner, story, [_chapter(block)])
    assert resp.status_code == 422, resp.text


@pytest.mark.anyio
async def test_publish_names_a_block_whose_host_was_removed(
    client: AsyncClient, admin_auth_header: dict, owner: dict
):
    await _set_hosts(client, admin_auth_header, [{"host": MEDIA}, {"host": VIDEO}])
    story = await _story(client, owner)
    kept = _frame("embed", f"https://{VIDEO}/chart")
    dropped = _frame("video", f"https://{MEDIA}/v/2")
    resp = await _save(client, owner, story, [_chapter(kept, dropped)])
    assert resp.status_code == 200, resp.text
    revision = resp.json()["revision"]

    await _set_hosts(client, admin_auth_header, [{"host": VIDEO}])
    resp = await client.post(
        f"/stories/{story['id']}/publish", json={"revision": revision}, headers=owner
    )
    assert resp.status_code == 422, resp.text
    assert _detail(resp)["blocks"] == [
        {"chapter": 1, "block_id": dropped["id"], "type": "video", "host": MEDIA}
    ]
    read = await client.get(f"/stories/{story['id']}", headers=owner)
    assert read.json()["published_at"] is None

    await _set_hosts(client, admin_auth_header, [{"host": VIDEO}, {"host": MEDIA}])
    resp = await client.post(
        f"/stories/{story['id']}/publish", json={"revision": revision}, headers=owner
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
async def test_the_embed_page_policy_carries_the_same_frame_src(
    client: AsyncClient, admin_auth_header: dict, owner: dict
):
    story_id = await _public_story(client, admin_auth_header)
    missing = str(uuid.uuid4())
    for target in (story_id, missing, "not-a-story"):
        resp = await client.get(f"/stories/{target}/frame-policy")
        assert resp.headers["x-story-frame-src"] == "frame-src 'self' blob:"
    await _set_hosts(client, admin_auth_header, [{"host": MEDIA}, {"host": VIDEO}])
    for target in (story_id, missing, "not-a-story"):
        resp = await client.get(f"/stories/{target}/frame-policy")
        assert resp.status_code == 200
        assert resp.headers["x-story-frame-src"] == await _policy(client)
        assert resp.headers["x-story-frame-src"].endswith(
            f"https://{MEDIA} https://{VIDEO}"
        )
