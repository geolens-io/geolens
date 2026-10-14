"""Regression coverage for capability-safe nginx access logging."""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"


def _log_format(text: str) -> str:
    match = re.search(r"log_format\s+\w+\s+(.*?);", text, re.DOTALL)
    assert match, "expected a custom access-log format"
    return match.group(1)


def test_nginx_logs_no_query_strings_or_referrers():
    text = NGINX_CONF.read_text()
    log_format = _log_format(text)
    variables = set(re.findall(r"\$[A-Za-z0-9_]+", log_format))

    for unsafe_variable in (
        "$request",
        "$request_uri",
        "$args",
        "$query_string",
        "$http_referer",
    ):
        assert unsafe_variable not in variables

    assert "$request_method" in log_format
    assert "$request_id" in log_format
    assert "$status" in log_format
    assert "$geolens_safe_log_path" in log_format
    assert "$request_time" in log_format
    assert "$upstream_response_time" in log_format


def test_nginx_redacts_capability_path_segments():
    text = NGINX_CONF.read_text()

    assert re.search(
        r"map\s+\$request_uri\s+\$geolens_log_path_without_args\s*\{", text
    )
    assert '"~^(?<geolens_original_path>[^?]*)"' in text
    assert re.search(
        r"map\s+\$geolens_log_path_without_args\s+\$geolens_safe_log_path\s*\{",
        text,
    )
    assert re.search(r"\^/m/\[\^/\]\+.*?/m/\[REDACTED\]", text)
    assert re.search(
        r"\^/api/maps/shared/\[\^/\]\+.*?/api/maps/shared/\[REDACTED\]",
        text,
    )


def test_nginx_wires_safe_log_format_to_access_log():
    text = NGINX_CONF.read_text()
    m = re.search(r"log_format\s+(\w+)\s", text)
    assert m, "expected a custom capability-safe log_format"
    fmt_name = m.group(1)
    assert re.search(rf"access_log\s+\S+\s+{re.escape(fmt_name)}\s*;", text), (
        f"the capability-safe log_format '{fmt_name}' must be wired to access_log"
    )


def test_robots_txt_is_a_real_file_that_allows_crawling():
    robots = repo_root(__file__) / "frontend" / "public" / "robots.txt"
    lines = [ln.strip() for ln in robots.read_text().splitlines() if ln.strip()]

    assert "User-agent: *" in lines
    assert "Allow: /" in lines
    # Social crawlers fetch map preview images from /api/.
    assert not any(ln.lower().startswith("disallow") for ln in lines)


def _location_blocks(text: str):
    """Yield (header, own directives) for each location, nested ones excluded."""
    for match in re.finditer(r"^\s*location\s+([^{]+)\{", text, re.MULTILINE):
        depth, i, own = 1, match.end(), []
        start = i
        while depth:
            ch = text[i]
            if ch == "{":
                own.append(text[start:i].rsplit("\n", 1)[0])
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    own.append(text[start:i])
                    break
                start = i + 1
            i += 1
        yield match.group(1).strip(), "\n".join(own)


def test_proxied_locations_send_each_security_header_once():
    # The server scope and every location restating it use add_header, which
    # appends to the api's own copy unless the upstream header is hidden.
    # A location declaring any proxy_hide_header stops inheriting the outer set,
    # so it has to list the pair itself.
    text = NGINX_CONF.read_text()
    blocks = dict(_location_blocks(text))
    for header, body in blocks.items():
        if "proxy_pass" not in body or "proxy_hide_header" not in body:
            continue
        for name in ("X-Content-Type-Options", "Referrer-Policy"):
            assert re.search(rf"proxy_hide_header\s+{name}\s*;", body), (
                f"location {header} proxies but does not hide upstream {name}"
            )
    assert "proxy_hide_header X-Content-Type-Options" in blocks["/api/"]
    assert "proxy_hide_header Referrer-Policy" in blocks["/api/"]


def test_api_referrer_policy_override_survives_the_proxy():
    # An api route that sets its own Referrer-Policy (the OAuth callback uses
    # no-referrer) must win over the nginx default rather than being dropped.
    text = NGINX_CONF.read_text()
    assert re.search(
        r"map\s+\$upstream_http_referrer_policy\s+\$geolens_referrer_policy\s*\{",
        text,
    )
    assert "add_header Referrer-Policy $geolens_referrer_policy always;" in text
