"""Tests for sortable GET /admin/jobs/ (sort + order query params).

Every assertion is scoped to jobs this test creates, via a unique token in the
source_filename that the endpoint's own search filter selects on. The
per-worker database is shared and other tests seed ingest jobs into it, so an
assertion about the whole list would be a claim about the worker rather than
about this test.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.modules.admin.service import AdminService, _job_sort_columns

from tests.factories import get_user_id


async def _create_job(
    session,
    *,
    created_by,
    source_filename,
    status="pending",
    started_at=None,
    completed_at=None,
):
    from app.platform.jobs.models import IngestJob

    job = IngestJob(
        status=status,
        created_by=created_by,
        source_filename=source_filename,
        started_at=started_at,
        completed_at=completed_at,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


def _filenames(rows) -> list[str]:
    return [job.source_filename for job, _username in rows]


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


async def test_sort_by_filename_orders_both_directions(test_db_session):
    """sort=source_filename returns the scoped jobs in alphabetical order."""
    admin_id = await get_user_id(test_db_session, "admin")
    token = f"jsrt{uuid.uuid4().hex[:10]}"
    # Deliberately not created in alphabetical order, so a response that merely
    # preserved insertion order would fail this test.
    for suffix in ("mike", "alpha", "zulu"):
        await _create_job(
            test_db_session, created_by=admin_id, source_filename=f"{token}_{suffix}"
        )

    svc = AdminService(test_db_session)
    asc, _ = await svc.list_jobs(search=token, sort="source_filename", order="asc")
    desc, _ = await svc.list_jobs(search=token, sort="source_filename", order="desc")

    assert _filenames(asc) == [f"{token}_alpha", f"{token}_mike", f"{token}_zulu"]
    assert _filenames(desc) == [f"{token}_zulu", f"{token}_mike", f"{token}_alpha"]


async def test_default_sort_is_unchanged_created_at_descending(test_db_session):
    """Omitting sort/order preserves the historical created_at DESC ordering."""
    admin_id = await get_user_id(test_db_session, "admin")
    token = f"jsrt{uuid.uuid4().hex[:10]}"
    created = [
        (
            await _create_job(
                test_db_session,
                created_by=admin_id,
                source_filename=f"{token}_{n}",
            )
        ).id
        for n in range(3)
    ]

    svc = AdminService(test_db_session)
    rows, _ = await svc.list_jobs(search=token)

    # Newest first: the reverse of the order they were created in.
    assert [job.id for job, _username in rows] == list(reversed(created))


async def test_duration_sorts_by_elapsed_time_not_by_timestamp(test_db_session):
    """sort=duration orders by completed_at - started_at, not by either end.

    The two are different orderings and a naive implementation could satisfy
    one while claiming the other, so the fixture below is built to separate
    them: the SHORTEST job starts last and finishes last.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    token = f"jsrt{uuid.uuid4().hex[:10]}"
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # (suffix, start offset minutes, duration minutes)
    fixtures = [
        ("long", 0, 90),
        ("medium", 30, 45),
        ("short", 120, 5),
    ]
    for suffix, start_offset, minutes in fixtures:
        started = base + timedelta(minutes=start_offset)
        await _create_job(
            test_db_session,
            created_by=admin_id,
            source_filename=f"{token}_{suffix}",
            status="complete",
            started_at=started,
            completed_at=started + timedelta(minutes=minutes),
        )

    svc = AdminService(test_db_session)
    asc, _ = await svc.list_jobs(search=token, sort="duration", order="asc")

    assert _filenames(asc) == [
        f"{token}_short",
        f"{token}_medium",
        f"{token}_long",
    ]
    # Guard against a vacuous pass: sorting by started_at ascending would have
    # produced long/medium/short, the exact reverse, so the assertion above
    # cannot be satisfied by ordering on either endpoint timestamp.
    by_created, _ = await svc.list_jobs(search=token, sort="created_at", order="asc")
    assert _filenames(by_created) != _filenames(asc)


@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_unfinished_jobs_sort_last_by_duration(test_db_session, order):
    """A job with no completed_at has a NULL duration and stays at the bottom.

    Postgres puts NULLs first on DESC by default, which would fill the top of a
    "longest first" view with jobs that have not finished at all.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    token = f"jsrt{uuid.uuid4().hex[:10]}"
    started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await _create_job(
        test_db_session,
        created_by=admin_id,
        source_filename=f"{token}_done",
        status="complete",
        started_at=started,
        completed_at=started + timedelta(minutes=10),
    )
    await _create_job(
        test_db_session,
        created_by=admin_id,
        source_filename=f"{token}_running",
        status="running",
        started_at=started,
    )
    await _create_job(
        test_db_session,
        created_by=admin_id,
        source_filename=f"{token}_pending",
        status="pending",
    )

    svc = AdminService(test_db_session)
    rows, _ = await svc.list_jobs(search=token, sort="duration", order=order)
    names = _filenames(rows)

    # Only meaningful if the scoped set really mixes finished and unfinished.
    assert f"{token}_done" in names, names
    assert len(names) == 3, names
    assert names[0] == f"{token}_done", (
        f"{order}: an unfinished job outranked a finished one: {names}"
    )


@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_null_filename_sorts_last_in_both_directions(test_db_session, order):
    """source_filename is nullable (URL ingests); nulls stay at the bottom."""
    admin_id = await get_user_id(test_db_session, "admin")
    token = f"jsrt{uuid.uuid4().hex[:10]}"
    named = await _create_job(
        test_db_session, created_by=admin_id, source_filename=f"{token}_named"
    )
    unnamed = await _create_job(
        test_db_session, created_by=admin_id, source_filename=None
    )

    svc = AdminService(test_db_session)
    # The search filter is on source_filename, so it cannot reach the NULL row.
    # Scope by id instead and assert only on the two rows this test owns.
    rows, _ = await svc.list_jobs(sort="source_filename", order=order, limit=200)
    positions = {
        job.id: i
        for i, (job, _username) in enumerate(rows)
        if job.id in (named.id, unnamed.id)
    }

    assert len(positions) == 2, "both fixtures must be on the first page"
    assert positions[named.id] < positions[unnamed.id], (
        f"{order}: a NULL filename outranked a real one"
    )


async def test_sort_composes_with_status_filter(test_db_session):
    """sort applies on top of the status filter rather than replacing it."""
    admin_id = await get_user_id(test_db_session, "admin")
    token = f"jsrt{uuid.uuid4().hex[:10]}"
    for suffix, status in (
        ("mike", "failed"),
        ("alpha", "failed"),
        ("zulu", "pending"),
    ):
        await _create_job(
            test_db_session,
            created_by=admin_id,
            source_filename=f"{token}_{suffix}",
            status=status,
        )

    svc = AdminService(test_db_session)
    rows, total = await svc.list_jobs(
        search=token, status="failed", sort="source_filename", order="desc"
    )

    assert _filenames(rows) == [f"{token}_mike", f"{token}_alpha"]
    assert total == 2


async def test_paging_a_non_unique_sort_key_never_repeats_a_row(test_db_session):
    """Paging by `status` (identical for every row) yields each job once.

    OFFSET paging over a non-unique ORDER BY key is free to return a row on two
    consecutive pages; the id tiebreak makes the ordering total.
    """
    admin_id = await get_user_id(test_db_session, "admin")
    token = f"jsrt{uuid.uuid4().hex[:10]}"
    expected = {
        (
            await _create_job(
                test_db_session, created_by=admin_id, source_filename=f"{token}_{n}"
            )
        ).id
        for n in range(6)
    }

    svc = AdminService(test_db_session)
    seen: list = []
    for skip in (0, 2, 4):
        rows, _ = await svc.list_jobs(
            search=token, sort="status", order="asc", skip=skip, limit=2
        )
        seen.extend(job.id for job, _username in rows)

    assert len(seen) == len(set(seen)), f"a row appeared on two pages: {seen}"
    assert set(seen) == expected


def test_ordering_clause_carries_a_unique_tiebreak_and_pins_nulls():
    """Assert the ORDER BY shape directly, because behaviour cannot prove it.

    The paging test above passes with or without the id tiebreak: at these row
    counts Postgres seq-scans and happens to return a stable order, so it
    cannot detect the regression it describes. Compiling the clause can.
    """
    from app.modules.admin.service import _NULLABLE_JOB_SORT_COLUMNS
    from app.platform.jobs.models import IngestJob

    for field in _job_sort_columns():
        for order in ("asc", "desc"):
            clauses = AdminService._job_ordering(field, order)
            assert clauses[-1] is IngestJob.id, (
                f"{field}/{order} has no unique tiebreak: {[str(c) for c in clauses]}"
            )
            assert order.upper() in str(clauses[0]).upper(), str(clauses[0])

            rendered = str(clauses[0]).upper()
            if field in _NULLABLE_JOB_SORT_COLUMNS:
                assert "NULLS LAST" in rendered, f"{field}/{order}: {rendered}"
            else:
                assert "NULLS LAST" not in rendered, f"{field}/{order}: {rendered}"

    # The nullable set must not have drifted out of the allowlist it annotates.
    assert _NULLABLE_JOB_SORT_COLUMNS <= set(_job_sort_columns())


def test_duration_is_an_interval_expression_not_a_timestamp():
    """sort=duration must order by the elapsed time, not by an endpoint.

    A regression that quietly aliased duration to completed_at would still
    order rows, still pass the allowlist tests, and only be visible on data
    where start times and durations disagree.
    """
    rendered = str(_job_sort_columns()["duration"])

    assert "completed_at" in rendered and "started_at" in rendered, rendered
    assert "-" in rendered, rendered


# ---------------------------------------------------------------------------
# Allowlist enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bogus_sort",
    [
        "file_path",  # a real column, deliberately not sortable
        "can_retry",  # computed per page after the query, not a column
        "created_at; DROP TABLE catalog.ingest_jobs",
        "(SELECT 1)",
        "",
    ],
)
@pytest.mark.anyio
async def test_unknown_sort_field_is_refused_not_executed(
    client: AsyncClient,
    admin_auth_header: dict,
    bogus_sort: str,
):
    """A sort field outside the allowlist is a 422, never a silent default."""
    resp = await client.get(
        "/admin/jobs/",
        params={"sort": bogus_sort, "limit": 1},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, f"{bogus_sort!r} -> {resp.status_code} {resp.text}"


@pytest.mark.parametrize("bogus_order", ["sideways", "ASC; --", "1"])
@pytest.mark.anyio
async def test_unknown_sort_order_is_refused(
    client: AsyncClient,
    admin_auth_header: dict,
    bogus_order: str,
):
    """A direction outside asc/desc is a 422."""
    resp = await client.get(
        "/admin/jobs/",
        params={"order": bogus_order, "limit": 1},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422, f"{bogus_order!r} -> {resp.status_code}"


@pytest.mark.anyio
async def test_every_advertised_sort_field_is_accepted(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """The refusal tests above must not be passing by refusing everything."""
    assert _job_sort_columns(), "allowlist is empty; the tests above prove nothing"
    for field in _job_sort_columns():
        for order in ("asc", "desc"):
            resp = await client.get(
                "/admin/jobs/",
                params={"sort": field, "order": order, "limit": 1},
                headers=admin_auth_header,
            )
            assert resp.status_code == 200, f"{field}/{order} -> {resp.text}"


async def test_service_layer_rejects_unmapped_sort_key(test_db_session):
    """The service refuses an unmapped key even if the router is bypassed."""
    svc = AdminService(test_db_session)
    with pytest.raises(ValueError, match="Unsupported sort field"):
        await svc.list_jobs(sort="file_path")
    with pytest.raises(ValueError, match="Unsupported sort order"):
        await svc.list_jobs(order="sideways")
