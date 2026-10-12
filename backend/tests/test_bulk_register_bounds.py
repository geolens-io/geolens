"""Bulk registration caps the batch size and how many items run at once."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.processing.ingest import router as ingest_router

pytestmark = pytest.mark.anyio


def _items(count: int) -> list[dict]:
    return [{"table_name": f"bulk_{i}", "title": f"Bulk {i}"} for i in range(count)]


async def test_a_batch_over_the_cap_is_refused_before_any_registration(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    """A batch of 101 tables answers 422 and registers nothing."""
    register = AsyncMock()
    with patch.object(ingest_router, "register_existing_table", register):
        response = await client.post(
            "/ingest/register/bulk/",
            json={"tables": _items(101)},
            headers=admin_auth_header,
        )

    assert response.status_code == 422, response.text
    register.assert_not_called()


async def test_a_full_batch_never_runs_more_items_than_the_concurrency_cap(
    client: AsyncClient, admin_auth_header: dict
) -> None:
    """A 100-table batch registers every table with at most the cap in flight."""
    in_flight = 0
    peak = 0

    async def _register(_session, request, _user):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return SimpleNamespace(
            id=uuid.uuid4(), record=SimpleNamespace(title=request.title)
        )

    with patch.object(ingest_router, "register_existing_table", _register):
        response = await client.post(
            "/ingest/register/bulk/",
            json={"tables": _items(100)},
            headers=admin_auth_header,
        )

    assert response.status_code == 201, response.text
    results = response.json()["results"]
    assert [r["status"] for r in results] == ["success"] * 100
    assert peak == ingest_router._BULK_REGISTER_CONCURRENCY
