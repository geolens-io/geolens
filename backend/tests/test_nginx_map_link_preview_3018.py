"""nginx sends link-preview crawlers on a map or story page to the api's tags.

Browsers must keep getting the SPA shell from ``location /`` with its headers,
and the embed shell under ``/m/`` must not move.
"""

import re

import pytest

from tests.test_nginx_raster_proxy_ratelimit_1778 import (
    NGINX_CONF,
    _select,
    _tree,
    _without_comments,
)

MAP_PAGE = "/maps/0b6f1c2e-6a4f-4e43-9d0e-3b2f8f0c9a11"
STORY_PAGE = "/stories/5d1e7f3a-2c4b-4a8e-9f60-1b7c3d9e8a22"
PAGES = (MAP_PAGE, STORY_PAGE)

CRAWLERS = (
    "Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)",
    "Twitterbot/1.0",
    "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)",
    "LinkedInBot/1.0 (compatible; Mozilla/5.0; Apache-HttpClient +http://www.linkedin.com)",
    "TelegramBot (like TwitterBot)",
    "WhatsApp/2.23.20.0 A",
    "Mozilla/5.0 (Windows NT 6.1; WOW64) SkypeUriPreview Preview/0.5",
)

BROWSERS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:143.0) Gecko/20100101 Firefox/143.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1",
    "",
)


def _page_uri_for(user_agent: str, uri: str = MAP_PAGE) -> str:
    """Evaluate the ``$geolens_preview_page_uri`` map the way nginx does."""
    text = _without_comments(NGINX_CONF.read_text())
    body = re.search(
        r"map \$http_user_agent \$geolens_preview_page_uri \{(.*?)\n\}", text, re.S
    )
    assert body is not None, "the $geolens_preview_page_uri map is gone"
    default = None
    for line in body.group(1).strip().splitlines():
        key, value = line.strip().rstrip(";").rsplit(None, 1)
        value = value.replace("$uri", uri)
        if key == "default":
            default = value
            continue
        pattern = key.strip('"')
        assert pattern.startswith("~*"), key
        if re.search(pattern[2:], user_agent, re.I):
            return value
    assert default is not None
    return default


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("user_agent", CRAWLERS)
def test_crawlers_are_sent_to_the_preview(user_agent: str, page: str) -> None:
    assert _page_uri_for(user_agent, page) == f"/_link_preview{page}"


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("user_agent", BROWSERS)
def test_browsers_get_the_spa_shell(user_agent: str, page: str) -> None:
    assert _page_uri_for(user_agent, page) == "/index.html"


@pytest.mark.parametrize("page", PAGES)
def test_page_only_rewrites_and_leaves_headers_to_location_root(page: str) -> None:
    """An add_header here would replace the SPA's CSP, frame and cache headers."""
    for path in (page, page + "/", page.upper()):
        selected = _select(_tree(), path)
        assert selected is not None, path
        directives = [
            line.strip() for line in selected.own.splitlines() if line.strip()
        ]
        assert directives == ["rewrite ^ $geolens_preview_page_uri last;"], path

    shell = _select(_tree(), "/index.html")
    assert shell is not None and shell.pattern == "/"
    assert "frame-ancestors 'self'" in shell.own
    assert 'add_header Cache-Control "no-cache" always;' in shell.own


@pytest.mark.parametrize(
    "path",
    [
        "/maps",
        "/maps/",
        "/maps/new",
        "/m/sharetoken",
        "/stories",
        "/stories/",
        f"{STORY_PAGE}/edit",
    ],
)
def test_other_routes_keep_their_locations(path: str) -> None:
    selected = _select(_tree(), path)
    assert selected is not None
    assert "geolens_preview_page_uri" not in selected.own


def test_embed_shell_is_still_served_by_its_own_location() -> None:
    selected = _select(_tree(), "/m/sharetoken")
    assert selected is not None and selected.pattern == "^/m/"
    assert "auth_request /_embed_frame_policy;" in selected.own


@pytest.mark.parametrize("page", PAGES)
def test_preview_location_is_internal_and_anonymous(page: str) -> None:
    selected = _select(_tree(), f"/_link_preview{page}")
    assert selected is not None
    assert selected.modifier == "^~"
    own = selected.own
    assert "internal;" in own
    assert "proxy_pass $upstream_api;" in own
    for header in ("Authorization", "Cookie", "X-Api-Key"):
        assert f'proxy_set_header {header} "";' in own
    assert "add_header" not in own


def _rewrite_preview(uri: str) -> str | None:
    """Apply the preview location's rewrites to ``uri`` the way nginx would:
    the first that matches ends rewriting."""
    own = _select(_tree(), f"/_link_preview{MAP_PAGE}").own
    rewrites = re.findall(r'rewrite "([^"]+)" (\S+)\? break;', own)
    assert rewrites, "the preview rewrites are gone"
    for pattern, target in rewrites:
        match = re.search(pattern, uri)
        if match is not None:
            return target.replace("$1", match.group(1))
    return None


@pytest.mark.parametrize(
    "page",
    [
        spelling
        for page in PAGES
        for spelling in (page, page + "/", page.upper(), page.upper() + "/")
    ],
)
def test_every_spelling_a_page_accepts_reaches_its_preview_route(page: str) -> None:
    """The page location and the SPA router match paths case-insensitively."""
    assert _select(_tree(), page) is not None
    internal = _page_uri_for(CRAWLERS[0], uri=page)
    kind, page_id = page.strip("/").split("/")
    assert _rewrite_preview(internal) == f"/{kind.lower()}/{page_id}/link-preview"


def test_preview_failures_fall_back_to_the_spa_shell() -> None:
    """A 404 for a private map or story must look exactly like a missing one's."""
    own = _select(_tree(), f"/_link_preview{MAP_PAGE}").own
    assert "proxy_intercept_errors on;" in own
    error_page = re.search(r"error_page ([\d ]+) = /index\.html;", own)
    assert error_page is not None
    codes = set(error_page.group(1).split())
    # 429 comes from the api's global rate limiter, 401/403 from auth middleware.
    assert {"401", "403", "404", "422", "429", "500", "502", "503", "504"} <= codes
