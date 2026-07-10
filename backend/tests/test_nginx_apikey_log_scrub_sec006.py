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
