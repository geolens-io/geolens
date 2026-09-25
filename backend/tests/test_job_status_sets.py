"""The job status sets match the database's CHECK and the published status types."""

import re
from typing import get_args

import pytest
from sqlalchemy import text

from app.modules.admin.schemas import JobStatus
from app.platform.jobs.models import (
    ACTIVE_STATUSES,
    ALL_STATUSES,
    TERMINAL_STATUSES,
    IngestJob,
)
from app.platform.jobs.schemas import JobStatusResponse

_QUOTED = re.compile(r"'([a-z_]+)'")


@pytest.mark.anyio
async def test_all_statuses_are_what_the_check_allows(test_db_session) -> None:
    """ALL_STATUSES is chk_ingest_jobs_status's value list, in the database and the model."""
    definition = await test_db_session.scalar(
        text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
            "JOIN pg_namespace n ON n.oid = c.connamespace "
            "WHERE c.conname = 'chk_ingest_jobs_status' AND n.nspname = 'catalog'"
        )
    )
    assert definition is not None
    assert tuple(_QUOTED.findall(definition)) == ALL_STATUSES

    [check] = [
        constraint
        for constraint in IngestJob.__table__.constraints
        if constraint.name == "chk_ingest_jobs_status"
    ]
    assert tuple(_QUOTED.findall(str(check.sqltext))) == ALL_STATUSES


def test_the_published_status_types_offer_every_status() -> None:
    """The admin job list's and the job poll's status types list ALL_STATUSES."""
    assert get_args(JobStatus) == ALL_STATUSES
    assert get_args(JobStatusResponse.model_fields["status"].annotation) == ALL_STATUSES


def test_active_and_terminal_statuses_split_all_of_them() -> None:
    """Every status is either active or terminal, never both."""
    assert set(ACTIVE_STATUSES).isdisjoint(TERMINAL_STATUSES)
    assert set(ACTIVE_STATUSES) | set(TERMINAL_STATUSES) == set(ALL_STATUSES)
