"""fix(#1778): the API needs a liveness probe distinct from readiness.

`/health` gathers a database, an object-store and a cache probe and 503s when
any of them is degraded. The cache provider is explicitly engineered to survive
a Valkey outage (in-memory fallback behind a circuit breaker), so an outage the
API serves straight through still marked the container unhealthy -- and that
probe is what gates `frontend: depends_on: api: service_healthy`, so a restart
during the outage left the UI down because the cache was down. Under an
orchestrator with an HTTP liveness probe on `/health` the pod is killed and
restarted in a loop while the API can serve catalog reads.

The worker has had this split since it was written
(`observability/health/worker.py`: `/health/live` and `/health/ready`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.anyio
async def test_health_live_answers_without_probing_any_dependency():
    from app.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.get("/health/live")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_live_is_registered_and_readiness_is_unchanged():
    from app.api.main import app

    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert "/health/live" in paths
    assert "/health" in paths, "readiness must keep its existing path"


def test_health_live_stays_out_of_the_published_contract():
    """Infrastructure surface, like the worker's own probes.

    Keeping it unpublished is what lets this land without an SDK regeneration;
    if that changes, the snapshot and both SDKs have to move with it.
    """
    from app.api.main import app

    for route in app.routes:
        if getattr(route, "path", None) == "/health/live":
            assert route.include_in_schema is False
            break
    else:  # pragma: no cover - the route assertion above already covers this
        pytest.fail("/health/live route not found")


def test_container_liveness_probes_target_the_liveness_route():
    """The Dockerfile and compose probes are the reason the split matters."""
    dockerfile = (_REPO_ROOT / "Dockerfile").read_text()
    api_probe = re.search(
        r"urlopen\('http://localhost:8000/health(?P<suffix>[^']*)'\)", dockerfile
    )
    assert api_probe is not None, "api stage lost its HEALTHCHECK"
    assert api_probe.group("suffix") == "/live", (
        "the api image healthcheck must probe liveness, not readiness"
    )

    compose = (_REPO_ROOT / "docker-compose.yml").read_text()
    assert "urlopen('http://localhost:8000/health/live')" in compose
    assert "urlopen('http://localhost:8000/health')" not in compose


def test_the_runbook_sends_liveness_to_the_liveness_route():
    """fix(#1778 codex r6): the docs were still the old contract.

    RUNBOOK.md told operators "Uptime/liveness checks must target
    `/api/health`" -- the endpoint this PR reclassified as readiness, which
    fails on a degraded cache and answers 429 under a one-second probe. A
    split the runbook contradicts is not a split.
    """
    runbook = (_REPO_ROOT / "RUNBOOK.md").read_text()

    assert "/api/health/live" in runbook, "RUNBOOK.md never names the liveness endpoint"

    # A line that mentions liveness and points at the readiness endpoint is an
    # offender only if it never names the liveness one: prose contrasting the
    # two ("liveness is X, readiness is Y") is exactly what this section is for.
    # `/api/health/live` contains `/api/health`, so strip the longer form
    # before looking for the shorter one.
    offenders = [
        line.strip()
        for line in runbook.splitlines()
        if "liveness" in line.lower()
        and "/api/health" in line.replace("/api/health/live", "")
        and "/api/health/live" not in line
    ]
    assert not offenders, (
        f"RUNBOOK.md points a liveness check at the readiness endpoint: {offenders}"
    )


# ---------------------------------------------------------------------------
# fix(#1778 codex r7): the probe must not touch a dependency on the way in
# ---------------------------------------------------------------------------
#
# The handler answering without a dependency is only the last step. Three
# middlewares on the request path have a DB-backed branch, and in multi_tenant
# mode TenantContextMiddleware turned a database outage into a 403 on the
# probe -- an orchestrator then restarts an API that is alive and serving
# catalog reads, which is the restart loop this whole split exists to prevent.

#: Every middleware that reaches the database, the cache or object storage on
#: the request path, and therefore has to let the probe past. Kept as data so
#: the structural test below names what it checked rather than grepping the
#: package and asserting nothing when a rename lands.
_DB_BACKED_MIDDLEWARE = {
    "app/api/middleware/tenant_context.py": "public tenant-host registry lookup",
    "app/api/middleware/cors.py": "CORS_ALLOWED_ORIGINS persistent-config read",
    "app/api/middleware/body_limit.py": "UPLOAD_MAX_SIZE_MB persistent-config read",
}


def test_every_db_backed_middleware_lets_the_probe_past():
    """Structural: each one calls the shared predicate, and none rolls its own.

    A path check copied into three middlewares is three things that drift; the
    predicate lives in api/middleware/liveness.py so a fourth middleware with a
    DB branch has one obvious thing to call.
    """
    for rel, why in _DB_BACKED_MIDDLEWARE.items():
        src = (_REPO_ROOT / "backend" / rel).read_text()
        # The call, not the import: `is_liveness_request` on its own is
        # satisfied by the import line alone, so removing the only call site
        # would leave this passing. The paren is what makes it a use.
        assert "is_liveness_request(" in src, (
            f"{rel} performs a {why} without exempting the liveness probe"
        )
        # It must be the shared one, not a local re-spelling of the path.
        assert "from app.api.middleware.liveness import is_liveness_request" in src, (
            f"{rel} must use the shared predicate"
        )
        assert '"/health/live"' not in src, (
            f"{rel} hardcodes the liveness path instead of calling the predicate"
        )


def test_the_db_backed_middleware_list_is_the_whole_set():
    """The list above must not go stale as middlewares gain DB branches.

    Anything under api/middleware/ that reaches app.core.db is either on the
    list or this fails naming it.
    """
    middleware_dir = _REPO_ROOT / "backend" / "app" / "api" / "middleware"
    touches_db = {
        f"app/api/middleware/{path.name}"
        for path in sorted(middleware_dir.glob("*.py"))
        if "from app.core.db import" in path.read_text()
    }
    assert touches_db, "no middleware reads app.core.db -- the scan found nothing"
    unlisted = touches_db - set(_DB_BACKED_MIDDLEWARE)
    assert not unlisted, (
        "middleware reaching the database without an entry in "
        f"_DB_BACKED_MIDDLEWARE: {sorted(unlisted)}"
    )


def test_the_liveness_route_takes_no_dependencies():
    """The handler itself: no Depends(get_db), nothing to resolve."""
    from app.api.main import app

    for route in app.routes:
        if getattr(route, "path", None) == "/health/live":
            assert route.dependant.dependencies == [], (
                "the liveness handler acquired a dependency; get_db would put a "
                "pool checkout on the one route that must not need one"
            )
            break
    else:  # pragma: no cover - the registration test already covers this
        pytest.fail("/health/live route not found")


def test_the_liveness_route_is_exempt_from_the_rate_limiter():
    """slowapi's middleware short-circuits an exempt route before any counter.

    A one-second probe would otherwise exhaust a 60/minute budget on its own,
    and a 429 reads as a dead process. Exemption also keeps the probe off the
    limiter's storage, which is Redis when REDIS_URL is set.
    """
    from slowapi.middleware import _get_route_name

    from app.api.main import health_live
    from app.platform.ratelimit import limiter

    assert _get_route_name(health_live) in limiter._exempt_routes


@pytest.mark.anyio
async def test_liveness_answers_200_in_multi_tenant_with_the_database_down(
    monkeypatch,
):
    """The reproduction: multi_tenant, tenant hostname, database unreachable.

    Before this, TenantContextMiddleware resolved the host through the public
    registry, got nothing back because the database was down, and answered 403.
    """
    import app.api.middleware.tenant_context as tenant_context

    calls: list[str | None] = []

    async def _registry_is_down(signal):
        calls.append(signal)
        raise OSError("connection refused")

    monkeypatch.setattr(tenant_context, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_context.settings, "tenant_base_domain", "geolens.app")
    monkeypatch.setattr(tenant_context.settings, "tenant_trusted_hosts", "testserver")
    monkeypatch.setattr(tenant_context, "_resolve_tenant_uuid", _registry_is_down)

    from app.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.get("/health/live", headers={"host": "acme.geolens.app"})

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}
    assert calls == [], (
        "the probe reached the tenant registry; with the database down that is "
        "a 403 and a restarted container"
    )


@pytest.mark.anyio
async def test_readiness_still_resolves_the_tenant_in_multi_tenant(monkeypatch):
    """The counterweight: the exemption is scoped to the liveness path only.

    /health is the readiness view and stays behind tenant resolution, so a
    blanket path skip would show up here.
    """
    import app.api.middleware.tenant_context as tenant_context

    calls: list[str | None] = []

    async def _resolve(signal):
        calls.append(signal)
        return None

    monkeypatch.setattr(tenant_context, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_context.settings, "tenant_base_domain", "geolens.app")
    monkeypatch.setattr(tenant_context.settings, "tenant_trusted_hosts", "testserver")
    monkeypatch.setattr(tenant_context, "_resolve_tenant_uuid", _resolve)

    from app.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        resp = await http.get("/health", headers={"host": "acme.geolens.app"})

    assert calls == ["acme"], "readiness must still resolve the tenant host"
    assert resp.status_code == 403


def test_the_predicate_matches_the_probe_and_nothing_else():
    from app.api.middleware.liveness import is_liveness_request

    for path in ("/health/live", "/api/health/live"):
        assert is_liveness_request({"type": "http", "path": path}), path
    # Behind an ASGI root_path mount.
    assert is_liveness_request(
        {"type": "http", "path": "/geolens/health/live", "root_path": "/geolens"}
    )
    for path in (
        "/health",
        "/api/health",
        "/health/live/",
        "/health/liveness",
        "/datasets/health/live",
        "",
    ):
        assert not is_liveness_request({"type": "http", "path": path}), path
    # Not an HTTP request at all (websocket, lifespan).
    assert not is_liveness_request({"type": "websocket", "path": "/health/live"})
