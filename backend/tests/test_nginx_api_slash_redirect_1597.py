"""nginx must not answer the bare ``/api`` with an absolute http://host:8080 redirect.

``location /api/`` is a slash-terminated prefix block with ``proxy_pass``, so
nginx itself redirects a request for ``/api`` to ``/api/`` with a 301 (no app
code is involved). With nginx's default ``absolute_redirect on`` that Location
header is built from the request host plus the port this server listens on
(8080) and the plain-http scheme, which behind a TLS edge sends clients to
``http://demo.getgeolens.com:8080/api/`` — unreachable. ``absolute_redirect
off`` makes nginx emit ``Location: /api/`` instead, which the client resolves
against the origin it used.

The assertion is structural (it reads the conf), so it pins the directive at
server scope where the redirect is generated; a later ``absolute_redirect on``
anywhere in the file fails it too, because the counterfactual is that a single
stray re-enable reintroduces the bug.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"


def _without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_server_block_turns_absolute_redirect_off() -> None:
    text = _without_comments(NGINX_CONF.read_text())
    server_start = text.index("server {")
    api_location = text.index("location /api/", server_start)
    server_scope = text[server_start:api_location]
    assert re.search(r"^\s*absolute_redirect\s+off\s*;", server_scope, re.M), (
        "frontend/nginx.conf: the server block must set `absolute_redirect off;` "
        "before `location /api/`, or the bare /api request redirects to "
        "http://<host>:8080/api/"
    )
    assert not re.search(r"absolute_redirect\s+on\s*;", text), (
        "frontend/nginx.conf re-enables absolute_redirect somewhere; the /api "
        "slash redirect would again carry the container port and http scheme"
    )
