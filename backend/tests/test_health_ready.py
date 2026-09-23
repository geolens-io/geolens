"""The API's readiness probe checks the database and nothing else.

`/health` gathers the database, the object store and the cache and 503s when
any of them is degraded. As an orchestrator readiness probe it takes every
replica out of service at once during a cache or object-store outage, although
the cache falls back to memory and the object store is shared by every
replica, so pulling one of them fixes nothing.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.observability.health import service


async def _answers() -> None:
    return None


async def _unreachable() -> None:
    raise ConnectionError("unreachable")


async def _get_ready():
    from app.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        return await http.get("/health/ready")


@pytest.mark.anyio
async def test_ready_while_cache_and_object_store_are_down(monkeypatch):
    monkeypatch.setattr(service, "_check_database", _answers)
    monkeypatch.setattr(service, "_check_cache", _unreachable)
    monkeypatch.setattr(service, "_check_storage", _unreachable)

    resp = await _get_ready()

    assert resp.status_code == 200
    assert resp.json() == {"status": "ready"}


@pytest.mark.anyio
async def test_not_ready_when_the_database_is_unreachable(monkeypatch):
    monkeypatch.setattr(service, "_check_database", _unreachable)

    resp = await _get_ready()

    assert resp.status_code == 503
    assert resp.json() == {"status": "not_ready"}


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _Connection:
    def __init__(self, regclass):
        self._regclass = regclass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, statement):
        return _Result(self._regclass if "to_regclass" in str(statement) else 1)


class _Engine:
    """Answers queries, with `to_regclass` resolving to ``regclass``."""

    def __init__(self, regclass):
        self._regclass = regclass

    def connect(self):
        return _Connection(self._regclass)


@pytest.mark.anyio
async def test_not_ready_when_the_catalog_table_is_missing(monkeypatch):
    """PostgreSQL returns NULL, not an error, for a relation that is gone."""
    import app.core.db as db

    monkeypatch.setattr(db, "engine", _Engine(None))

    assert await service.check_readiness() == {"status": "not_ready"}


@pytest.mark.anyio
async def test_ready_when_the_catalog_table_resolves(monkeypatch):
    import app.core.db as db

    monkeypatch.setattr(db, "engine", _Engine("catalog.datasets"))

    assert await service.check_readiness() == {"status": "ready"}


def test_health_ready_stays_out_of_the_published_contract():
    """Infrastructure surface, like /health/live, so no SDK regeneration."""
    from app.api.main import app

    assert "/health/ready" not in app.openapi()["paths"]
