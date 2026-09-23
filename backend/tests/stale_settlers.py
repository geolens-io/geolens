"""The two callers of the stale-job settlement pass, for parametrized tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


async def _lifespan_sweep(session: AsyncSession) -> None:
    from app.platform.jobs.sweep import fail_stale_jobs

    await fail_stale_jobs(session)
    session.expire_all()


async def _startup_recovery(session: AsyncSession) -> None:
    from app.platform.jobs.worker import recover_stale_jobs

    await recover_stale_jobs()
    session.expire_all()


# Gives a test a `settle(session)` argument, run once per caller.
STALE_SETTLERS = pytest.mark.parametrize(
    "settle", [_lifespan_sweep, _startup_recovery], ids=["sweep", "recovery"]
)
