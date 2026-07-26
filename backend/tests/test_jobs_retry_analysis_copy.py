"""Analysis jobs get analysis retry copy, not import copy (ux(#698)).

Analysis materialize rows carry ``file_path=""`` and no ``source_url``, so
before this branch they fell through to the generic staging-file message and
told the user their "source" was gone and to "start the import again" — for a
job that was never an import.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.platform.jobs.router import get_retry_capability


def _job(**overrides) -> SimpleNamespace:
    base = {
        "id": uuid.uuid4(),
        "status": "failed",
        "file_path": "",
        "source_url": None,
        "user_metadata": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.anyio
async def test_failed_analysis_job_is_not_retryable_with_analysis_copy() -> None:
    job = _job(user_metadata={"analysis": {"operation": "buffer"}})

    can_retry, reason = await get_retry_capability(job)

    assert can_retry is False
    assert reason is not None
    assert "analysis" in reason.lower()
    # Names where to go instead, and never claims a missing import source.
    assert "map builder" in reason.lower()
    assert "The source is no longer available" not in reason


@pytest.mark.anyio
async def test_non_analysis_job_keeps_the_import_copy() -> None:
    """The generic staging-file message is unchanged for real imports."""
    job = _job(user_metadata={})

    can_retry, reason = await get_retry_capability(job)

    assert can_retry is False
    assert reason == "The source is no longer available. Start the import again."


@pytest.mark.anyio
async def test_analysis_branch_does_not_fire_on_a_succeeded_job() -> None:
    """Only failed jobs are retry candidates at all."""
    job = _job(status="complete", user_metadata={"analysis": {"operation": "clip"}})

    can_retry, reason = await get_retry_capability(job)

    assert can_retry is False
    assert reason is None
