"""nginx gives every SPA shell the frame-src the api builds from the approved
story frame hosts, and falls back to this origin and blob: for anything else."""

import re

import pytest

from tests.test_nginx_raster_proxy_ratelimit_1778 import (
    NGINX_CONF,
    _select,
    _tree,
    _without_comments,
)

STORY = "/stories/5d1e7f3a-2c4b-4a8e-9f60-1b7c3d9e8a22"
BASE = "frame-src 'self' blob:"


def _story_frame_src(answer: str) -> str:
    """Evaluate the ``$geolens_story_frame_src`` map the way nginx does."""
    text = _without_comments(NGINX_CONF.read_text())
    body = re.search(
        r"map \$story_frame_src \$geolens_story_frame_src \{(.*?)\n\}", text, re.S
    )
    assert body is not None, "the $geolens_story_frame_src map is gone"
    default = None
    for line in body.group(1).strip().splitlines():
        key, value = re.fullmatch(r'\s*("[^"]*"|\S+)\s+("[^"]*"|\S+);', line).groups()
        value = value.strip('"')
        if key == "default":
            default = value
            continue
        pattern = key.strip('"')
        assert pattern.startswith("~"), key
        if re.search(pattern[1:], answer):
            return answer if value == "$story_frame_src" else value
    assert default is not None
    return default


@pytest.mark.parametrize(
    "answer",
    [
        BASE,
        f"{BASE} https://media.example.org",
        f"{BASE} https://media.example.org https://www.youtube-nocookie.com",
    ],
)
def test_the_api_answer_is_copied_when_it_names_only_https_hosts(answer: str):
    assert _story_frame_src(answer) == answer


@pytest.mark.parametrize(
    "answer",
    [
        "",
        f"{BASE} https://media.example.org; script-src *",
        f"{BASE} http://media.example.org",
        f"{BASE} https://*.example.org",
        f"{BASE} *",
        f"{BASE} https://media.example.org:8443",
        f"{BASE} 'unsafe-inline'",
        "frame-src *",
        f"{BASE} https://media.example.org\nscript-src *",
    ],
)
def test_any_other_answer_falls_back_to_this_origin(answer: str):
    assert _story_frame_src(answer) == BASE


@pytest.mark.parametrize("path", ["/index.html", STORY, f"{STORY}/edit", "/stories"])
def test_every_shell_asks_for_the_frame_src(path: str):
    selected = _select(_tree(), path)
    if selected is not None and "rewrite ^ $geolens_preview_page_uri last;" in (
        selected.own
    ):
        selected = _select(_tree(), "/index.html")
    assert selected is not None and selected.pattern == "/"
    own = selected.own
    assert "auth_request /_story_frame_src_policy;" in own
    assert "auth_request_set $story_frame_src $upstream_http_x_story_frame_src;" in own
    csp = re.search(r'add_header Content-Security-Policy "([^"]+)" always;', own)
    assert csp is not None
    directives = [d.strip() for d in csp.group(1).split(";")]
    assert "$geolens_story_frame_src" in directives
    assert "script-src 'self' 'wasm-unsafe-eval'${CSP_SCRIPT_SRC_EXTRA}" in directives
    assert "child-src 'self' blob:" in directives


@pytest.mark.parametrize(
    ("location", "upstream"),
    [
        ("/_story_frame_src_policy", "/stories/frame-src-policy"),
        ("/_story_embed_frame_policy", "/stories/$story_embed_policy_id/frame-policy"),
    ],
)
def test_the_policy_request_is_internal_anonymous_and_cannot_fail_the_shell(
    location: str, upstream: str
):
    selected = _select(_tree(), location)
    assert selected is not None and selected.modifier == "="
    own = selected.own
    assert "internal;" in own
    assert f"proxy_pass $upstream_api{upstream};" in own
    for header in ("Authorization", "Cookie", "X-Api-Key"):
        assert f'proxy_set_header {header} "";' in own
    assert "add_header" not in own
    for directive in (
        "resolver_timeout 2s;",
        "proxy_buffer_size 32k;",
        "proxy_buffers 4 32k;",
        "proxy_busy_buffers_size 64k;",
        "proxy_connect_timeout 2s;",
        "proxy_send_timeout 2s;",
        "proxy_read_timeout 2s;",
    ):
        assert directive in own, directive
    error_page = re.search(r"error_page ([0-9 ]+) = (@\w+);", own)
    assert error_page is not None
    # An older api reads the policy path as a story id and answers 422.
    answers = {"400", "401", "403", "404", "405", "409", "422", "429", "500", "502"}
    assert answers | {"503", "504"} <= set(error_page.group(1).split())
    fallback = next(loc for loc in _tree() if loc.pattern == error_page.group(2))
    status = re.search(r"return (\d{3});", fallback.own)
    assert status is not None and status.group(1).startswith("2")


def test_the_story_embed_page_takes_the_frame_src_from_its_one_policy_request():
    selected = _select(_tree(), f"{STORY}/embed")
    assert selected is not None and "embed" in selected.pattern
    own = selected.own
    assert own.count("auth_request ") == 1
    assert "auth_request /_story_embed_frame_policy;" in own
    assert "auth_request_set $story_frame_src $upstream_http_x_story_frame_src;" in own
    csp = re.search(r'add_header Content-Security-Policy "([^"]+)" always;', own)
    assert csp is not None
    assert "$geolens_story_frame_src" in [d.strip() for d in csp.group(1).split(";")]


def test_the_map_embed_shell_keeps_its_own_policy():
    selected = _select(_tree(), "/m/sharetoken")
    assert selected is not None and selected.pattern == "^/m/"
    assert "story_frame_src" not in selected.own
