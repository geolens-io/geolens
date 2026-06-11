"""Regression test for SEC-006: nginx must scrub the api_key query-param
credential from its access log.

The ?api_key=<secret> fallback is a documented auth path (header > query > JWT >
anon). nginx logs the full request line ($request) by default, so on main —
where frontend/nginx.conf defined no scrubbing log_format — these long-lived,
non-expiring keys were persisted verbatim in the access log and any downstream
aggregation. These tests fail on main (no scrubbing map / no custom log_format).
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"


def test_nginx_defines_api_key_scrubbing_map():
    text = NGINX_CONF.read_text()
    # A `map $request $... { }` block redacts the api_key value from the logged
    # request line. Verified behaviorally to emit `api_key=REDACTED`.
    assert re.search(r"map\s+\$request\s+\$\w+\s*\{", text), (
        "expected a `map $request $... {` block scrubbing api_key (SEC-006)"
    )
    assert "api_key=REDACTED" in text, (
        "frontend/nginx.conf must redact the api_key value from the access log "
        "(SEC-006)"
    )


def test_nginx_wires_scrubbed_log_format_to_access_log():
    text = NGINX_CONF.read_text()
    # The scrubbed log_format must actually be referenced by an access_log
    # directive, otherwise the default $request (carrying the secret) is logged.
    m = re.search(r"log_format\s+(\w+)\s", text)
    assert m, "expected a custom log_format for api_key scrubbing (SEC-006)"
    fmt_name = m.group(1)
    assert re.search(rf"access_log\s+\S+\s+{re.escape(fmt_name)}\s*;", text), (
        f"the scrubbed log_format '{fmt_name}' must be wired to an access_log "
        f"directive (SEC-006)"
    )
