"""Framing for a story's embed page: any site for a published public story,
no site for anything else, and the rest of the app unchanged."""

import re
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from tests.test_nginx_raster_proxy_ratelimit_1778 import (
    NGINX_CONF,
    _select,
    _tree,
    _without_comments,
)
from tests.test_stories import _chapter, _publish, _saved, _store, _story

pytestmark = pytest.mark.anyio

OPEN = "frame-ancestors *"
CLOSED = "frame-ancestors 'none'"
STORY_ID = "5d1e7f3a-2c4b-4a8e-9f60-1b7c3d9e8a22"
EMBED_PAGE = f"/stories/{STORY_ID}/embed"
POLICY_LOCATION = "/_story_embed_frame_policy"


async def _public_story(client: AsyncClient, headers: dict) -> str:
    story = await _story(client, headers, title="Embedded story")
    story = await _saved(client, headers, story, [_chapter()])
    made_public = await client.patch(
        f"/stories/{story['id']}", json={"visibility": "public"}, headers=headers
    )
    assert made_public.status_code == 200, made_public.text
    published = await _publish(client, headers, story["id"])
    assert published.status_code == 200, published.text
    return story["id"]


async def _policy(client: AsyncClient, story_id: str, headers: dict | None = None):
    resp = await client.get(f"/stories/{story_id}/frame-policy", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.content == b""
    return resp


async def test_a_published_public_story_may_be_framed_by_any_site(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    story_id = await _public_story(client, admin_auth_header)

    for spelling in (story_id, story_id.upper()):
        resp = await _policy(client, spelling)
        assert resp.headers["x-embed-frame-ancestors"] == OPEN
        assert resp.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "change",
    [
        {"visibility": "private"},
        {"visibility": "internal"},
        {"visibility": "restricted"},
        {"published_at": None},
    ],
    ids=["private", "internal", "restricted", "unpublished"],
)
async def test_any_story_an_anonymous_reader_cannot_open_is_never_framed(
    client: AsyncClient, admin_auth_header: dict, test_db_session, change: dict
) -> None:
    story_id = await _public_story(client, admin_auth_header)
    assert (await _policy(client, story_id)).headers["x-embed-frame-ancestors"] == OPEN

    await _store(test_db_session, story_id, **change)

    # Signing in changes nothing: the embed reads the story as anyone would.
    for headers in (None, admin_auth_header):
        resp = await _policy(client, story_id, headers)
        assert resp.headers["x-embed-frame-ancestors"] == CLOSED


async def test_a_hidden_story_answers_exactly_like_a_missing_one(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    story_id = await _public_story(client, admin_auth_header)
    await _store(test_db_session, story_id, visibility="private")

    def shape(resp) -> tuple:
        skip = {"date", "x-request-id", "x-process-time", "server-timing"}
        return (
            resp.status_code,
            resp.content,
            sorted((k, v) for k, v in resp.headers.items() if k not in skip),
        )

    hidden = await _policy(client, story_id)
    missing = await _policy(client, str(uuid.uuid4()))
    malformed = await _policy(client, "not-a-story")
    assert shape(hidden) == shape(missing) == shape(malformed)
    assert hidden.headers["x-embed-frame-ancestors"] == CLOSED


async def test_republishing_as_public_opens_framing_again(
    client: AsyncClient, admin_auth_header: dict, test_db_session
) -> None:
    story_id = await _public_story(client, admin_auth_header)
    await _store(test_db_session, story_id, visibility="private")
    assert (await _policy(client, story_id)).headers[
        "x-embed-frame-ancestors"
    ] == CLOSED

    await _store(
        test_db_session,
        story_id,
        visibility="public",
        published_at=datetime.now(timezone.utc),
    )
    assert (await _policy(client, story_id)).headers["x-embed-frame-ancestors"] == OPEN


def _directives(location) -> list[str]:
    return [line.strip() for line in location.own.splitlines() if line.strip()]


def _csp(location) -> str:
    match = re.search(
        r'add_header Content-Security-Policy "([^"]+)" always;', location.own
    )
    assert match is not None, location.header
    return match.group(1)


@pytest.mark.parametrize(
    "path", [EMBED_PAGE, EMBED_PAGE + "/", EMBED_PAGE.upper(), EMBED_PAGE.upper() + "/"]
)
def test_the_embed_page_takes_its_framing_from_the_api(path: str) -> None:
    page = _select(_tree(), path)
    assert page is not None and "story_embed" in page.pattern
    own = page.own
    assert f"auth_request {POLICY_LOCATION};" in own
    assert (
        "auth_request_set $story_embed_frame_ancestors "
        "$upstream_http_x_embed_frame_ancestors;"
    ) in own
    assert "X-Frame-Options" not in own
    assert _csp(page).endswith("; $geolens_story_embed_frame_ancestors")
    # Served in place: an internal redirect would land in `location /` and
    # send that block's same-origin headers instead.
    assert "rewrite ^ /index.html break;" in _directives(page)
    assert "try_files" not in own


def test_the_embed_page_keeps_the_app_csp_apart_from_framing() -> None:
    page = _select(_tree(), EMBED_PAGE)
    shell = _select(_tree(), "/index.html")
    assert shell is not None and shell.pattern == "/"
    app_csp = _csp(shell)
    assert app_csp.endswith("; frame-ancestors 'self'")
    assert _csp(page).removesuffix("$geolens_story_embed_frame_ancestors") == (
        app_csp.removesuffix("frame-ancestors 'self'")
    )


def _framing_for(api_answer: str, request_uri: str) -> str:
    """Evaluate the story embed framing map the way nginx does."""
    text = _without_comments(NGINX_CONF.read_text())
    body = re.search(
        r'map "\$story_embed_frame_ancestors \$request_uri" '
        r"\$geolens_story_embed_frame_ancestors \{(.*?)\n\}",
        text,
        re.S,
    )
    assert body is not None, "the story embed framing map is gone"
    default = None
    key = f"{api_answer} {request_uri}"
    for line in body.group(1).strip().splitlines():
        source, value = re.fullmatch(
            r'\s*(default|"[^"]*")\s+"([^"]*)";', line
        ).groups()
        if source == "default":
            default = value
            continue
        pattern = source.strip('"')
        assert pattern.startswith("~*"), source
        if re.search(pattern[2:], key, re.I):
            return value
    assert default is not None
    return default


@pytest.mark.parametrize(
    "request_uri",
    [EMBED_PAGE, EMBED_PAGE + "/", EMBED_PAGE.upper(), EMBED_PAGE + "?utm=x"],
)
def test_framing_opens_only_on_the_api_word(request_uri: str) -> None:
    assert _framing_for(OPEN, request_uri) == OPEN
    for answer in (CLOSED, "", "frame-ancestors * https://a.example", "*"):
        assert _framing_for(answer, request_uri) == CLOSED, answer


@pytest.mark.parametrize(
    "request_uri",
    [
        f"/stories/{STORY_ID}/%65mbed",
        f"/stories/{STORY_ID}/embe%64/",
        f"/stories/%35{STORY_ID[1:]}/embed",
        f"//stories/{STORY_ID}/embed",
        f"/stories//{STORY_ID}/embed",
        f"/stories/{STORY_ID}//embed",
        f"/stories/x/../{STORY_ID}/embed",
    ],
)
def test_framing_stays_closed_for_a_spelling_the_router_reads_differently(
    request_uri: str,
) -> None:
    """nginx picks the embed location on the decoded, merged path, so these
    reach it; the router either matches another page or nothing."""
    assert _framing_for(OPEN, request_uri) == CLOSED


def test_the_policy_request_is_internal_and_anonymous() -> None:
    policy = _select(_tree(), POLICY_LOCATION)
    assert policy is not None and policy.modifier == "="
    own = policy.own
    assert "internal;" in own
    assert (
        "proxy_pass $upstream_api/stories/$story_embed_policy_id/frame-policy;" in own
    )
    for header in ("Authorization", "Cookie", "X-Api-Key"):
        assert f'proxy_set_header {header} "";' in own
    page = _select(_tree(), EMBED_PAGE)
    assert "set $story_embed_policy_id $story_embed_id;" in page.own


@pytest.mark.parametrize(
    "path",
    [
        f"/stories/{STORY_ID}",
        f"/stories/{STORY_ID}/",
        f"/stories/{STORY_ID}/edit",
        f"/stories/{STORY_ID}/embedded",
        f"/stories/{STORY_ID}/embed/more",
        f"/maps/{STORY_ID}/embed",
        "/stories/embed",
        "/index.html",
    ],
)
def test_every_other_page_keeps_same_origin_framing(path: str) -> None:
    selected = _select(_tree(), path)
    assert selected is not None
    assert "story_embed" not in selected.pattern
    # The story and map pages only rewrite into the SPA shell's own block.
    served = _select(_tree(), "/index.html") if "rewrite" in selected.own else selected
    assert served.pattern == "/"
    assert 'add_header X-Frame-Options "SAMEORIGIN" always;' in served.own
    assert _csp(served).endswith("; frame-ancestors 'self'")
