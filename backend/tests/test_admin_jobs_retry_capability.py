"""Admin job responses expose the same retry contract as user job status."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.modules.admin import router as admin_router


@pytest.mark.anyio
async def test_admin_job_list_includes_retry_capability(monkeypatch) -> None:
    job = SimpleNamespace(
        id=uuid.uuid4(),
        status="failed",
        source_filename="roads.geojson",
        dataset_id=None,
        error_message="Import failed.",
        user_metadata={"service_auth_required": True},
        created_by=uuid.uuid4(),
        started_at=None,
        completed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        admin_router.AdminService,
        "list_jobs",
        AsyncMock(return_value=([(job, "editor")], 1)),
    )
    monkeypatch.setattr(
        admin_router,
        "get_retry_capability",
        AsyncMock(return_value=(False, "Fresh service credentials are required.")),
    )

    response = await admin_router.list_admin_jobs(db=AsyncMock())

    assert response.total == 1
    assert response.jobs[0].can_retry is False
    assert response.jobs[0].retry_reason == "Fresh service credentials are required."
