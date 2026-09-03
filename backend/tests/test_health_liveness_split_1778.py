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
