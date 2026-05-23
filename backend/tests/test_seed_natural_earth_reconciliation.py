"""OPS-01 / Phase 1091-03 — seed-natural-earth.py post-loop reconciliation.

Pins the reconciliation function added by Plan 1091-03 against the gap
documented in quick task ``260523-at1`` SUMMARY Issue §1: the seed
script's "Succeeded: N, Failed: M" summary was a per-dataset heuristic
that could disagree with the persisted worker job-row status. After
the polling loop completes, ``reconcile_failed_jobs`` queries
``/api/admin/jobs/?status=failed`` (scoped to the run window) and
returns any rows the per-dataset heuristic missed. The Import Summary
block prints a failed-job table and the script exits non-zero when the
reconciliation finds failures; otherwise the script preserves its
existing exit-zero + green-summary behavior.

Four tests pin the four branches:

1. ``test_reconciliation_surfaces_failed_jobs`` — admin endpoint
   returns one failed job whose ``started_at`` falls inside the run
   window. The function must return a non-empty list containing the
   row's identifying keys.

2. ``test_reconciliation_clean_when_no_failures`` — admin endpoint
   returns an empty job list. The function must return ``[]``.

3. ``test_reconciliation_filters_by_run_window`` — admin endpoint
   returns a job whose ``started_at`` predates the run window. The
   function must drop it and return ``[]``. This guards against
   surfacing stale failures from prior runs.

4. ``test_reconciliation_handles_admin_endpoint_failure`` — admin
   endpoint raises ``httpx.TransportError``. The function must log a
   warning, return ``[]``, and never propagate the exception (the
   reconciliation is additive defense, not the sole gate — the
   per-dataset polling stays the primary signal).

The script lives at ``scripts/seed-natural-earth.py`` (hyphenated path,
not a Python package). The module-load helper at the top of this file
uses ``importlib.util.spec_from_file_location`` to import it as
``seed_natural_earth``. The helper is cached so the spec is only
loaded once per session.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# Module loader — scripts/seed-natural-earth.py is not a package
# ---------------------------------------------------------------------------

_SEED_MODULE: types.ModuleType | None = None


def _load_seed_module() -> types.ModuleType:
    """Load scripts/seed-natural-earth.py as a Python module.

    The script has a hyphen in its filename (``seed-natural-earth.py``)
    so it cannot be a plain ``import`` target. Use
    ``importlib.util.spec_from_file_location`` with the canonical Python
    recipe. The loaded module is cached at module level so subsequent
    test runs in the same session reuse it.
    """
    global _SEED_MODULE
    if _SEED_MODULE is not None:
        return _SEED_MODULE

    # tests/ -> backend/ -> repo root -> scripts/seed-natural-earth.py
    script_path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "scripts"
        / "seed-natural-earth.py"
    )
    assert script_path.exists(), f"seed script not found at {script_path}"

    spec = importlib.util.spec_from_file_location("seed_natural_earth", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_natural_earth"] = module
    spec.loader.exec_module(module)
    _SEED_MODULE = module
    return module


# ---------------------------------------------------------------------------
# Helpers — build a stub httpx client whose .get() returns a known response
# ---------------------------------------------------------------------------


def _stub_client_returning(payload: dict) -> AsyncMock:
    """Return an AsyncMock httpx client whose .get() returns a response

    that yields ``payload`` from ``.json()`` and is a no-op on
    ``.raise_for_status()``.
    """
    response = MagicMock()
    response.json = MagicMock(return_value=payload)
    response.raise_for_status = MagicMock(return_value=None)
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    return client


def _stub_client_raising(exc: Exception) -> AsyncMock:
    """Return an AsyncMock httpx client whose .get() raises ``exc``."""
    client = AsyncMock()
    client.get = AsyncMock(side_effect=exc)
    return client


# ---------------------------------------------------------------------------
# Tests — four branches of reconcile_failed_jobs
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reconciliation_surfaces_failed_jobs() -> None:
    """When admin endpoint returns a failed job inside the run window,
    reconcile_failed_jobs returns a non-empty list with the row's
    identifying keys (source_filename, dataset_id, error_message)."""
    seed = _load_seed_module()
    run_start = datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc)
    job_started_at = (run_start + timedelta(minutes=5)).isoformat()
    payload = {
        "jobs": [
            {
                "id": "11111111-2222-3333-4444-555555555555",
                "status": "failed",
                "source_filename": "ne_10m_urban_areas_landscan.zip",
                "dataset_id": "ffcba726-d61c-48e9-8786-3b41b5fc96f8",
                "error_message": (
                    "MissingGreenlet: greenlet_spawn has not been called; "
                    "can't call await_only() here."
                ),
                "started_at": job_started_at,
                "completed_at": (run_start + timedelta(minutes=6)).isoformat(),
            }
        ],
        "total": 1,
    }
    client = _stub_client_returning(payload)

    result = await seed.reconcile_failed_jobs(
        client,
        base_url="http://localhost:8080",
        api_key="test-api-key",
        run_start_time=run_start,
    )

    assert len(result) == 1, f"expected 1 failure, got {result!r}"
    row = result[0]
    assert row["source_filename"] == "ne_10m_urban_areas_landscan.zip"
    assert row["dataset_id"] == "ffcba726-d61c-48e9-8786-3b41b5fc96f8"
    assert "MissingGreenlet" in row["error_message"]
    # The function should also surface the job id so operators can grep logs.
    assert row["id"] == "11111111-2222-3333-4444-555555555555"

    # Confirm the GET targeted the admin jobs endpoint with status=failed.
    call_args = client.get.call_args
    assert call_args is not None
    url = call_args[0][0]
    params = call_args[1].get("params", {})
    assert "/api/admin/jobs/" in url
    assert params.get("status") == "failed"


@pytest.mark.anyio
async def test_reconciliation_clean_when_no_failures() -> None:
    """When admin endpoint returns an empty job list, reconcile_failed_jobs
    returns []. This preserves the script's current exit-zero +
    green-summary behavior on the happy path."""
    seed = _load_seed_module()
    run_start = datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc)
    client = _stub_client_returning({"jobs": [], "total": 0})

    result = await seed.reconcile_failed_jobs(
        client,
        base_url="http://localhost:8080",
        api_key="test-api-key",
        run_start_time=run_start,
    )

    assert result == []


@pytest.mark.anyio
async def test_reconciliation_filters_by_run_window() -> None:
    """When admin endpoint returns a job whose started_at predates the
    run_start_time, reconcile_failed_jobs drops it. This prevents
    surfacing stale failures from prior seed runs."""
    seed = _load_seed_module()
    run_start = datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc)
    # Job started ONE HOUR before this run began.
    stale_started_at = (run_start - timedelta(hours=1)).isoformat()
    payload = {
        "jobs": [
            {
                "id": "deadbeef-0000-0000-0000-000000000000",
                "status": "failed",
                "source_filename": "stale-from-previous-run.zip",
                "dataset_id": None,
                "error_message": "old failure that predates this run",
                "started_at": stale_started_at,
                "completed_at": stale_started_at,
            }
        ],
        "total": 1,
    }
    client = _stub_client_returning(payload)

    result = await seed.reconcile_failed_jobs(
        client,
        base_url="http://localhost:8080",
        api_key="test-api-key",
        run_start_time=run_start,
    )

    assert result == [], (
        "reconciliation surfaced a failure that predated the run window: "
        f"{result!r}"
    )


@pytest.mark.anyio
async def test_reconciliation_handles_admin_endpoint_failure(caplog) -> None:
    """When the admin endpoint GET raises a transport error,
    reconcile_failed_jobs must log a warning, return [], and never
    propagate. The reconciliation is additive defense; the script's
    per-dataset polling stays the primary signal."""
    seed = _load_seed_module()
    run_start = datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc)
    client = _stub_client_raising(httpx.TransportError("connection refused"))

    with caplog.at_level("WARNING"):
        result = await seed.reconcile_failed_jobs(
            client,
            base_url="http://localhost:8080",
            api_key="test-api-key",
            run_start_time=run_start,
        )

    assert result == []
    rendered = "\n".join(rec.getMessage() for rec in caplog.records).lower()
    # Reconciliation warning must mention either the function name (reconcile)
    # OR the endpoint path so the operator can identify the warning source.
    assert "reconcile" in rendered or "/admin/jobs" in rendered, (
        f"warning did not mention reconcile or /admin/jobs: caplog records = "
        f"{[r.getMessage() for r in caplog.records]!r}"
    )
