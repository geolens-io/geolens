"""A write to a row another transaction deleted answers 409 catalog_lock_conflict."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm.exc import StaleDataError

from app.api.main import app


async def test_a_stale_row_answers_409_through_the_registered_handler():
    probe = FastAPI()
    probe.add_exception_handler(StaleDataError, app.exception_handlers[StaleDataError])

    @probe.put("/thing")
    async def write_a_gone_row():
        raise StaleDataError("UPDATE statement on table 'x' expected 1 row; 0 matched")

    async with AsyncClient(
        transport=ASGITransport(app=probe, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        resp = await client.put("/thing")

    assert resp.status_code == 409
    assert resp.json() == {
        "type": "about:blank",
        "title": "Catalog entry is busy",
        "status": 409,
        "detail": {
            "code": "catalog_lock_conflict",
            "message": "Another request changed this record. Retry.",
        },
        "code": "catalog_lock_conflict",
    }
