"""PERF-007 regression — vector quicklook CPU render must run off the event loop.

``app/processing/vector/quicklook.py``'s ``generate_vector_quicklook`` did the
Shapely ``make_valid`` + PIL drawing + PNG encode inline in the coroutine, with no
``await`` between the DB query and returning the bytes. ``asyncio.wait_for`` only
cancels at await points, so the advertised 10s timeout in
``generate_vector_quicklook_with_timeout`` could NOT interrupt a pathological
render — the loop blocked until the render finished regardless of the timeout.

The fix extracts the parse → make_valid → draw → encode work into the sync
``_render_quicklook_png`` helper and dispatches it via ``asyncio.to_thread``, so
(a) the loop stays responsive and (b) ``wait_for`` can fire at the to_thread await
boundary.

These tests pin both halves:

1. ``test_render_is_dispatched_to_thread`` — the render goes through
   ``asyncio.to_thread`` with ``_render_quicklook_png`` as the offloaded callable
   (not called inline).

2. ``test_slow_render_is_cancelled_by_timeout`` — a deliberately slow render run
   in a thread is actually cancelled by the ``wait_for`` timeout, returning the
   blank-canvas fallback. Pre-fix (inline render) this would have blocked past the
   timeout and returned the real bytes.

Requires the test DB (the entry point issues PostGIS queries).

Verify fail-before: inline the render back into ``generate_vector_quicklook``
(drop the ``await asyncio.to_thread(_render_quicklook_png, ...)``) and both tests
FAIL — test 1 sees no _render_quicklook_png dispatch; test 2's slow inline render
runs to completion past the timeout.
"""

from __future__ import annotations

import asyncio
import time
import uuid as _uuid

import pytest
from sqlalchemy import text

import app.processing.vector.quicklook as quicklook_module
from app.processing.vector.quicklook import (
    _blank_canvas,
    generate_vector_quicklook,
    generate_vector_quicklook_with_timeout,
)
from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_table_with_polygons(session, *, feature_count: int = 5) -> str:
    """Create a data.* table with `feature_count` small multipolygons. Returns table_name."""
    table_name = f"ql_perf007_{_uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f'CREATE TABLE data."{table_name}" ('
            "gid serial PRIMARY KEY, "
            "name text, "
            "geom_4326 geometry(MultiPolygon, 4326)"
            ")"
        )
    )
    rows = []
    for i in range(feature_count):
        x = -100 + (i % 10) * 0.5
        y = 30 + (i // 10) * 0.5
        wkt = (
            f"MULTIPOLYGON((("
            f"{x} {y}, {x + 0.1} {y}, {x + 0.1} {y + 0.1}, "
            f"{x} {y + 0.1}, {x} {y}"
            f")))"
        )
        rows.append(f"('row_{i}', ST_GeomFromText('{wkt}', 4326))")
    await session.execute(
        text(
            f'INSERT INTO data."{table_name}" (name, geom_4326) VALUES '
            + ", ".join(rows)
        )
    )
    await session.commit()
    return table_name


async def _drop_table(session, table_name: str) -> None:
    try:
        await session.execute(text(f'DROP TABLE IF EXISTS data."{table_name}"'))
        await session.commit()
    except Exception:
        await session.rollback()


# ---------------------------------------------------------------------------
# Test 1: render dispatched to a thread
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_render_is_dispatched_to_thread(test_db_session, monkeypatch):
    """The CPU render must be offloaded via asyncio.to_thread(_render_quicklook_png)."""
    session = test_db_session
    await get_user_id(session, "admin")  # ensure admin exists / warm fixtures
    table_name = await _create_table_with_polygons(session, feature_count=5)

    real_to_thread = asyncio.to_thread
    render_dispatches: list = []

    async def _spy(func, /, *args, **kwargs):
        if func is quicklook_module._render_quicklook_png:
            render_dispatches.append((func, args))
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(quicklook_module.asyncio, "to_thread", _spy)

    try:
        png = await generate_vector_quicklook(
            session, table_name, "MultiPolygon", size=256
        )
        assert isinstance(png, bytes) and len(png) > 0
        assert render_dispatches, (
            "_render_quicklook_png was not offloaded via asyncio.to_thread "
            "(PERF-007 regression — render ran inline on the event loop)"
        )
    finally:
        await _drop_table(session, table_name)


# ---------------------------------------------------------------------------
# Test 2: slow render actually cancelled by the wait_for timeout
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_slow_render_is_cancelled_by_timeout(test_db_session, monkeypatch):
    """A slow render run in a thread must be interruptible by wait_for's timeout.

    Patches ``_render_quicklook_png`` with a blocking sleep far longer than the
    timeout. Because the render is now dispatched via ``asyncio.to_thread``, the
    ``wait_for`` await boundary lets the TimeoutError fire and the wrapper returns
    the blank-canvas fallback well before the slow render would have finished.

    Pre-fix (inline render) the sleep ran on the event loop with no suspension
    point, so ``wait_for`` could not cancel it and the call would block ~2s.
    """
    session = test_db_session
    await get_user_id(session, "admin")
    table_name = await _create_table_with_polygons(session, feature_count=5)

    def _slow_render(geojson_strings, view_bounds, size):
        time.sleep(2.0)  # CPU/IO-bound block far exceeding the timeout
        return b"SHOULD-NOT-BE-RETURNED"

    monkeypatch.setattr(quicklook_module, "_render_quicklook_png", _slow_render)

    try:
        start = time.monotonic()
        result = await generate_vector_quicklook_with_timeout(
            session, table_name, "MultiPolygon", size=256, timeout=0.2
        )
        elapsed = time.monotonic() - start

        # Timeout fired → blank-canvas fallback, NOT the slow render's bytes.
        assert result == _blank_canvas(256), (
            "wait_for did not cancel the slow render — it returned the render's "
            "own bytes instead of the timeout fallback (PERF-007 regression)"
        )
        # The await boundary let the timeout fire long before the 2s sleep ended.
        assert elapsed < 1.5, (
            f"call blocked {elapsed:.2f}s — wait_for could not interrupt the "
            "render (PERF-007 regression: render not offloaded to a thread)"
        )
    finally:
        await _drop_table(session, table_name)
