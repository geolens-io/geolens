"""BUG-026: AdminService.list_jobs source_filename ILIKE must escape %, _, and \\.

list_jobs() composed its filename filter as
``IngestJob.source_filename.ilike(f"%{search}%")`` with no escaping, so a search
of "%" produced the pattern "%%" and matched EVERY job regardless of filename
(over-broad), and "_" matched any single character. Every sibling search surface
(list_users, maps/audit/embed-token) already applies escape_ilike + escape="\\".

Fix: ``IngestJob.source_filename.ilike(f"%{escape_ilike(search)}%", escape="\\")``.

DB-backed integration test: seed jobs whose filenames contain literal % / _ and
plain text, then confirm a literal "%"/"_" search matches only the intended row
(not all rows).
"""

import uuid

from app.modules.admin.service import AdminService

from tests.factories import get_user_id


async def _create_job(session, *, created_by, source_filename):
    from app.platform.jobs.models import IngestJob

    job = IngestJob(
        status="pending",
        created_by=created_by,
        source_filename=source_filename,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


class TestAdminJobsEscapeIlike:
    async def test_percent_literal_not_wildcard(self, test_db_session):
        """search='<tag>%' must match only filenames literally containing '<tag>%'."""
        admin_id = await get_user_id(test_db_session, "admin")
        tag = uuid.uuid4().hex[:8]
        literal = await _create_job(
            test_db_session,
            created_by=admin_id,
            source_filename=f"{tag}100%_done.zip",
        )
        other = await _create_job(
            test_db_session,
            created_by=admin_id,
            source_filename=f"{tag}plain.geojson",
        )

        svc = AdminService(test_db_session)
        rows, total = await svc.list_jobs(search=f"{tag}100%")

        # rows are (IngestJob, username) tuples
        ids = {job.id for job, _username in rows}
        assert literal.id in ids, "literal '%'-bearing filename should match"
        assert other.id not in ids, (
            "plain filename must NOT match a literal '%' search "
            "(would happen if '%' leaked as a wildcard)"
        )
        assert total == 1, f"expected exactly 1 literal match, got {total}"

    async def test_underscore_literal_not_wildcard(self, test_db_session):
        """search using '_' must treat it literally, not as match-any-char."""
        admin_id = await get_user_id(test_db_session, "admin")
        tag = uuid.uuid4().hex[:8]
        literal = await _create_job(
            test_db_session,
            created_by=admin_id,
            source_filename=f"{tag}a_b.tif",
        )
        # 'aXb' would match the wildcard pattern 'a_b' but not the literal 'a_b'
        decoy = await _create_job(
            test_db_session,
            created_by=admin_id,
            source_filename=f"{tag}aXb.tif",
        )

        svc = AdminService(test_db_session)
        rows, total = await svc.list_jobs(search=f"{tag}a_b")

        ids = {job.id for job, _username in rows}
        assert literal.id in ids, "literal '_'-bearing filename should match"
        assert decoy.id not in ids, (
            "'aXb' must NOT match a literal 'a_b' search "
            "(would happen if '_' leaked as single-char wildcard)"
        )
        assert total == 1, f"expected exactly 1 literal match, got {total}"

    async def test_plain_text_search_still_matches(self, test_db_session):
        """A normal substring search continues to match as before."""
        admin_id = await get_user_id(test_db_session, "admin")
        tag = uuid.uuid4().hex[:8]
        job = await _create_job(
            test_db_session,
            created_by=admin_id,
            source_filename=f"{tag}parcels.geojson",
        )

        svc = AdminService(test_db_session)
        rows, _ = await svc.list_jobs(search=f"{tag}parcels")

        assert job.id in {j.id for j, _username in rows}
