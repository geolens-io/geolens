"""The audit and user exports read in bounded batches, not whole result sets.

Each test records the statements the engine executes and the execution options
they ran with: ``yield_per`` is what makes the driver fetch in batches, and a
``LIMIT`` is what keeps a capped export from reading rows it will discard.
"""

import uuid
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import event

from app.modules.audit.models import AuditLog
from app.modules.audit.service import stream_audit_logs

pytestmark = pytest.mark.anyio


@contextmanager
def _recorded_statements(session):
    seen: list[tuple[str, dict]] = []

    def _record(conn, cursor, statement, params, context, executemany):
        seen.append((statement, dict(context.execution_options)))

    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


async def test_audit_stream_limits_the_query_and_fetches_in_batches(test_db_session):
    """A capped stream sends LIMIT to the database and reads in batches."""
    action = f"export.bounded.{uuid.uuid4().hex}"
    for _ in range(5):
        test_db_session.add(
            AuditLog(action=action, resource_type="dataset", resource_id=uuid.uuid4())
        )
    await test_db_session.commit()

    with _recorded_statements(test_db_session) as seen:
        rows = [
            row
            async for row in stream_audit_logs(
                test_db_session, action=action, max_rows=3
            )
        ]

    assert len(rows) == 3
    audit_selects = [s for s in seen if "FROM catalog.audit_logs" in s[0]]
    assert audit_selects, seen
    statement, options = audit_selects[-1]
    assert "LIMIT" in statement
    assert options.get("yield_per") == 100


async def test_audit_stream_without_a_cap_still_fetches_in_batches(test_db_session):
    """Omitting max_rows adds no LIMIT but keeps the batched fetch."""
    with _recorded_statements(test_db_session) as seen:
        _ = [
            row
            async for row in stream_audit_logs(
                test_db_session, action=f"export.none.{uuid.uuid4().hex}"
            )
        ]

    statement, options = [s for s in seen if "FROM catalog.audit_logs" in s[0]][-1]
    assert "LIMIT" not in statement
    assert options.get("yield_per") == 100


async def test_user_csv_export_fetches_in_batches(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The user CSV export reads users with a batched fetch."""
    with _recorded_statements(test_db_session) as seen:
        resp = await client.get("/admin/users/export.csv", headers=admin_auth_header)

    assert resp.status_code == 200
    user_selects = [s for s in seen if ".users" in s[0] and "ORDER BY" in s[0]]
    assert user_selects, [s[0][:80] for s in seen]
    assert all(opts.get("yield_per") == 100 for _, opts in user_selects)
