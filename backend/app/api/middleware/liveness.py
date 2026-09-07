"""The one definition of "this request is the liveness probe".

fix(#1778): ``/health/live`` lets an orchestrator ask whether the API
process is alive without asking whether its dependencies are, so the
request must not touch the DB, cache, or object storage — in
multi_tenant mode a DB-backed middleware once turned a database outage
into a ``403`` on the probe, the restart loop the split exists to
prevent.

The predicate lives here so a later DB-backed middleware has one
obvious thing to call (``tests/test_health_liveness_split_1778.py``
enforces it). Path matching is exact, not prefix-based:
``scope["path"]`` is ``/health/live`` directly or behind Nginx;
``/api/health/live`` is also accepted for an edge without that rewrite.
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
