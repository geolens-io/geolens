"""Story embed and video blocks: the approved-host setting, save and publish
refusals, and the frame-src nginx copies into the page CSP."""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient

from app.platform.story_frames import (
    StoryFrameHost,
    frame_src_directive,
    frame_url_host,
    normalize_frame_host,
    parse_frame_hosts,
)
from tests.factories import create_user

MEDIA = "media.example.org"
VIDEO = "video.example.net"


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


@pytest.mark.parametrize(
    "url",
    [
        "http://media.example.org/v/1",
        "https://user@media.example.org/v/1",
        "https://user:pw@media.example.org/v/1",
        "https://media.example.org:8443/v/1",
        "https://10.0.0.1/v/1",
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
