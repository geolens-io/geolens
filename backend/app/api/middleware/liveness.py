"""The one definition of "this request is the liveness probe".

fix(#1778 codex r7): ``/health/live`` exists so an orchestrator can ask whether
the API process is alive without asking whether its dependencies are. Answering
that question honestly means the request must not touch the database, the cache
or object storage on its way to the handler -- and the handler is only the last
step. Three middlewares on the request path have a DB-backed branch, and in
multi_tenant mode one of them turned a database outage into a ``403`` on the
probe, which is precisely the restart loop the readiness/liveness split was
added to prevent.

The predicate lives here, in one module, because the alternative is three
independent path checks that drift. A middleware added later with a DB-backed
branch has one obvious thing to call, and the structural test in
``tests/test_health_liveness_split_1778.py`` fails if it does not.

Path matching is exact rather than prefix-based. ``scope["path"]`` is what the
app sees, which is ``/health/live`` both directly and behind the bundled Nginx
(``location /api/`` rewrites ``^/api/(.*)`` to ``/$1`` before proxying).
``/api/health/live`` is accepted as well, for an edge that proxies without that
rewrite, and an ASGI ``root_path`` mount is stripped first, the way
``DynamicCORSMiddleware._request_path`` already does it.
"""

from __future__ import annotations

from typing import Any, Mapping

#: The app-side liveness route, and the form an un-rewriting edge would pass.
LIVENESS_PATHS: frozenset[str] = frozenset({"/health/live", "/api/health/live"})


def liveness_request_path(scope: Mapping[str, Any]) -> str:
    """The request path with any ASGI ``root_path`` prefix removed."""
    path = scope.get("path", "") or ""
    root_path = (scope.get("root_path", "") or "").rstrip("/")
    if root_path and path.startswith(root_path):
        path = path[len(root_path) :] or "/"
    return path


def is_liveness_request(scope: Mapping[str, Any]) -> bool:
    """True when this request is the liveness probe.

    Callers short-circuit their DB-backed work on it. The failure direction is
    deliberate: a false negative costs the probe a dependency lookup, while a
    false positive would only skip work on a route that returns a fixed
    ``{"status": "ok"}`` and reads no request state.

    No trailing-slash normalization: FastAPI is mounted with
    ``redirect_slashes=False``, so ``/health/live/`` is a 404 rather than a
    redirect, and treating it as the probe would skip middleware for a request
    that cannot reach the handler anyway.
    """
    if scope.get("type") != "http":
        return False
    return liveness_request_path(scope) in LIVENESS_PATHS
