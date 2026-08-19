"""nginx must not answer the bare ``/api`` with an absolute http://host:8080 redirect.

``location /api/`` is a slash-terminated prefix block with ``proxy_pass``, so
nginx itself redirects a request for ``/api`` to ``/api/`` with a 301 (no app
code is involved). With nginx's default ``absolute_redirect on`` that Location
header is built from the request host plus the port this server listens on
(8080) and the plain-http scheme, which behind a TLS edge sends clients to
``http://demo.getgeolens.com:8080/api/`` — unreachable. ``absolute_redirect
off`` makes nginx emit ``Location: /api/`` instead, which the client resolves
against the origin it used.

The assertion is structural (it reads the conf) and brace-aware: the directive
must sit at server scope, where the redirect is generated and from where every
``location`` inherits it. A copy inside some other location block does not
count, and a later ``absolute_redirect on`` anywhere in the file fails it too,
because the counterfactual is that a single stray re-enable or a misplaced
directive reintroduces the bug.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

_DIRECTIVE = re.compile(r"^\s*absolute_redirect\s+off\s*;")


def _without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _server_scope_lines(text: str) -> list[str]:
    """Lines that are direct children of the (first) ``server { ... }`` block.

    Braces are counted per line, so a ``${ENV}`` placeholder (balanced on its
    own line) is neutral and only block openers/closers move the depth.
    """
    depth = 0
    in_server = False
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        opens, closes = line.count("{"), line.count("}")
        if not in_server and depth == 0 and re.match(r"server\s*{$", stripped):
            in_server = True
            depth = 1
            continue
        if in_server and depth == 1 and opens == closes:
            lines.append(line)
        depth += opens - closes
        if in_server and depth == 0:
            break
    return lines


def _sets_absolute_redirect_off_at_server_scope(text: str) -> bool:
    return any(_DIRECTIVE.match(line) for line in _server_scope_lines(text))


def test_server_block_turns_absolute_redirect_off() -> None:
    text = _without_comments(NGINX_CONF.read_text())
    assert _sets_absolute_redirect_off_at_server_scope(text), (
        "frontend/nginx.conf: the server block must set `absolute_redirect off;` "
        "at server scope (not inside a location), or the bare /api request "
        "redirects to http://<host>:8080/api/"
    )
    assert not re.search(r"absolute_redirect\s+on\s*;", text), (
        "frontend/nginx.conf re-enables absolute_redirect somewhere; the /api "
        "slash redirect would again carry the container port and http scheme"
    )


def test_directive_inside_a_location_does_not_count() -> None:
    """Counterfactual for the scope check: relocate the directive into
    ``location /assets/`` and the parser must stop seeing it."""
    text = _without_comments(NGINX_CONF.read_text())
    moved = re.sub(r"^\s*absolute_redirect\s+off\s*;\n", "", text, count=1, flags=re.M)
    moved = moved.replace(
        "location /assets/ {", "location /assets/ {\n        absolute_redirect off;", 1
    )
    assert "absolute_redirect off;" in moved
    assert not _sets_absolute_redirect_off_at_server_scope(moved)
