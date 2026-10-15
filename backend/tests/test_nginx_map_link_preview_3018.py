"""nginx sends link-preview crawlers on a map page to the api's per-map tags.

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


def _map_page_uri_for(user_agent: str, uri: str = MAP_PAGE) -> str:
    """Evaluate the ``$geolens_map_page_uri`` map the way nginx does."""
    text = _without_comments(NGINX_CONF.read_text())
    body = re.search(
        r"map \$http_user_agent \$geolens_map_page_uri \{(.*?)\n\}", text, re.S
    )
    assert body is not None, "the $geolens_map_page_uri map is gone"
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


@pytest.mark.parametrize("user_agent", CRAWLERS)
def test_crawlers_are_sent_to_the_preview(user_agent: str) -> None:
    assert _map_page_uri_for(user_agent) == f"/_map_link_preview{MAP_PAGE}"


@pytest.mark.parametrize("user_agent", BROWSERS)
def test_browsers_get_the_spa_shell(user_agent: str) -> None:
    assert _map_page_uri_for(user_agent) == "/index.html"


def test_map_page_only_rewrites_and_leaves_headers_to_location_root() -> None:
    """An add_header here would replace the SPA's CSP, frame and cache headers."""
    for path in (MAP_PAGE, MAP_PAGE + "/", MAP_PAGE.upper()):
        selected = _select(_tree(), path)
        assert selected is not None, path
        directives = [
            line.strip() for line in selected.own.splitlines() if line.strip()
        ]
        assert directives == ["rewrite ^ $geolens_map_page_uri last;"], path

    shell = _select(_tree(), "/index.html")
    assert shell is not None and shell.pattern == "/"
    assert "frame-ancestors 'self'" in shell.own
    assert 'add_header Cache-Control "no-cache" always;' in shell.own


@pytest.mark.parametrize("path", ["/maps", "/maps/", "/maps/new", "/m/sharetoken"])
def test_other_routes_keep_their_locations(path: str) -> None:
    selected = _select(_tree(), path)
    assert selected is not None
    assert "geolens_map_page_uri" not in selected.own


def test_embed_shell_is_still_served_by_its_own_location() -> None:
    selected = _select(_tree(), "/m/sharetoken")
    assert selected is not None and selected.pattern == "^/m/"
    assert "auth_request /_embed_frame_policy;" in selected.own


def test_preview_location_is_internal_and_anonymous() -> None:
    selected = _select(_tree(), f"/_map_link_preview{MAP_PAGE}")
    assert selected is not None
    assert selected.modifier == "^~"
    own = selected.own
    assert "internal;" in own
    assert "proxy_pass $upstream_api;" in own
    for header in ("Authorization", "Cookie", "X-Api-Key"):
        assert f'proxy_set_header {header} "";' in own
    assert "add_header" not in own


def _rewrite_preview(uri: str) -> str | None:
    """Apply the preview location's rewrite to ``uri`` the way PCRE would."""
    own = _select(_tree(), f"/_map_link_preview{MAP_PAGE}").own
    rewrite = re.search(r'rewrite "([^"]+)" (\S+)\? break;', own)
    assert rewrite is not None, "the preview rewrite is gone"
    match = re.search(rewrite.group(1), uri)
    if match is None:
        return None
    return rewrite.group(2).replace("$1", match.group(1))


@pytest.mark.parametrize(
    "page", [MAP_PAGE, MAP_PAGE + "/", MAP_PAGE.upper(), MAP_PAGE.upper() + "/"]
)
def test_every_spelling_the_map_page_accepts_reaches_the_preview_route(
    page: str,
) -> None:
    """The map-page location and the SPA router match paths case-insensitively."""
    assert _select(_tree(), page) is not None
    internal = _map_page_uri_for(CRAWLERS[0], uri=page)
    map_id = page.split("/")[2]
    assert _rewrite_preview(internal) == f"/maps/{map_id}/link-preview"


def test_preview_failures_fall_back_to_the_spa_shell() -> None:
    """A 404 for a private map must look exactly like a missing map's."""
    own = _select(_tree(), f"/_map_link_preview{MAP_PAGE}").own
    assert "proxy_intercept_errors on;" in own
    error_page = re.search(r"error_page ([\d ]+) = /index\.html;", own)
    assert error_page is not None
    codes = set(error_page.group(1).split())
    assert {"404", "422", "500", "502", "503", "504"} <= codes
