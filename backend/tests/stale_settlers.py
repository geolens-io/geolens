"""The callers of the stale-job settlement pass, for parametrized tests."""

from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


async def _lifespan_sweep(session: AsyncSession, *_jobs) -> None:
    from app.platform.jobs.sweep import fail_stale_jobs

    await fail_stale_jobs(session)
    session.expire_all()


async def _startup_recovery(session: AsyncSession, *_jobs) -> None:
    from app.platform.jobs.worker import recover_stale_jobs

    await recover_stale_jobs()
    session.expire_all()


async def _job_status_poll(session: AsyncSession, *jobs) -> None:
    from app.platform.jobs.router import get_job_status

    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    for job in jobs:
        # The owner, so the handler's access check passes without a policy read.
        owner = SimpleNamespace(id=job.created_by)
        await get_job_status(job.id, request, owner, session)
    session.expire_all()


# Gives a test a `settle(session)` argument, run once per caller.
STALE_SETTLERS = pytest.mark.parametrize(
    "settle", [_lifespan_sweep, _startup_recovery], ids=["sweep", "recovery"]
)

# Gives a test a `settle(session, *jobs)` argument; the poll reads each job.
EVERY_SETTLER = pytest.mark.parametrize(
    "settle",
    [_lifespan_sweep, _startup_recovery, _job_status_poll],
    ids=["sweep", "recovery", "poll"],
)
