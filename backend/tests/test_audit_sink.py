"""Phase 222 — AuditSink protocol tests.

Covers AUDIT-01 (Plan 01: this test), AUDIT-03 (Plan 02: raising-sink test),
AUDIT-04 (Plan 04: fixture-sink test). AUDIT-02 architecture guard lives in
test_layering.py (Plan 05).
"""

from __future__ import annotations

import dataclasses
import logging
import uuid

import pytest


def test_audit_sink_protocol_shape() -> None:
    """AUDIT-01: AuditSink Protocol + DefaultAuditSink + AuditEvent exist with correct shape."""
    from app.modules.audit.events import AuditEvent
    from app.platform.extensions.defaults import DefaultAuditSink
    from app.platform.extensions.protocols import AuditSink

    # Protocol is runtime_checkable
    assert hasattr(AuditSink, "_is_runtime_protocol") or hasattr(
        AuditSink, "_is_protocol"
    ), "AuditSink must be a runtime_checkable Protocol (D-01)"

    # DefaultAuditSink satisfies the protocol structurally
    assert isinstance(DefaultAuditSink(), AuditSink), (
        "DefaultAuditSink must structurally satisfy AuditSink Protocol"
    )

    # AuditEvent has the 6 expected fields (D-02 — 1:1 with log_action signature)
    fields = {f.name for f in dataclasses.fields(AuditEvent)}
    assert fields == {
        "user_id",
        "action",
        "resource_type",
        "resource_id",
        "details",
        "ip_address",
    }, f"AuditEvent fields must mirror log_action() parameter surface 1:1 (D-02); got {fields}"


@pytest.mark.anyio
async def test_raising_sink_does_not_break_business_op(test_db_session, caplog) -> None:
    """AUDIT-03 / D-06 / D-07 / D-13: a sink that raises must NOT propagate.

    Verifies the audit_emit() facade contract:
      (a) RaisingSink.emit() raises RuntimeError;
      (b) audit_emit() does NOT propagate (the await returns normally);
      (c) DefaultAuditSink still wrote its audit_logs row (per-sink try/except,
          NOT whole-iteration try/except — the raising sink does not poison the
          iteration);
      (d) structlog.exception() emitted a record with the swallowed-failure
          message and structured fields (sink, action, resource_type).

    Calls audit_emit() directly (not via HTTP endpoint) so this test does not
    depend on Plan 03's 65-site call-site rewrite. Plan 04 covers the
    end-to-end integration via the admin user.create endpoint.
    """
    from app.modules.audit.events import AuditEvent
    from app.modules.audit.models import AuditLog
    from app.modules.audit.service import audit_emit
    from app.platform.extensions import _extensions
    from app.platform.extensions.defaults import DefaultAuditSink
    from sqlalchemy import select

    from tests.factories import get_user_id

    class RaisingSink:
        async def emit(self, session, event):
            raise RuntimeError("simulated sink failure for AUDIT-03")

    # Use the seeded admin user so audit_logs FK (user_id → users.id) does not fire.
    actor_id = await get_user_id(test_db_session, "admin")
    resource_id = uuid.uuid4()

    saved = _extensions.get("audit_sinks")
    _extensions["audit_sinks"] = [DefaultAuditSink(), RaisingSink()]
    try:
        event = AuditEvent(
            user_id=actor_id,
            action="audit_sink.test_raising",
            resource_type="audit_test",
            resource_id=resource_id,
            details={"marker": "raising-sink-test"},
            ip_address="127.0.0.1",
        )

        # (b) audit_emit must return normally despite RaisingSink raising
        with caplog.at_level(logging.ERROR, logger="app.modules.audit.service"):
            await audit_emit(test_db_session, event)
        await test_db_session.flush()

        # (c) DefaultAuditSink wrote its row even though RaisingSink raised
        row = (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "audit_sink.test_raising",
                    AuditLog.resource_id == resource_id,
                )
            )
        ).scalar_one_or_none()
        assert row is not None, (
            "DefaultAuditSink did not write its row; per-sink try/except violated "
            "(D-06: each sink's emit() must run independently)"
        )

        # (d) structlog logged the swallowed exception with context fields
        swallowed_records = [
            r
            for r in caplog.records
            if "Audit sink raised" in r.getMessage()
            or "suppressed" in r.getMessage().lower()
        ]
        assert swallowed_records, (
            "structlog.exception() did not emit a record for the failed sink "
            "(D-06: failures must be logged, not silent)"
        )
    finally:
        if saved is None:
            _extensions.pop("audit_sinks", None)
        else:
            _extensions["audit_sinks"] = saved


@pytest.mark.anyio
async def test_fixture_sink_receives_events_alongside_default(
    client,
    admin_auth_header,
    test_db_session,
) -> None:
    """AUDIT-04 / D-12: enterprise-shape AuditSink + DefaultAuditSink coexist.

    End-to-end integration: a fixture sink registered via direct
    ``_extensions["audit_sinks"]`` append receives every audit event AND the
    DefaultAuditSink still writes its row. Proves the multi-sink subscription
    contract works through the rewritten call path (Plan 03's
    ``audit_emit + AuditEvent`` flow at ``admin/router.py:113``).

    Uses the registry-level fixture pattern (mirrors ``saml_overlay_registered``
    at ``conftest.py:454-484`` — save snapshot, set new state, restore in
    ``finally``). No entry-point round-trip needed; the test runs without
    requiring ``geolens-enterprise`` to be installed.

    Pitfall C: BOTH ``DefaultAuditSink()`` AND ``FixtureSink()`` must be in
    the slot. If only the fixture sink is registered, the AUDIT-05 default-row
    assertion fails (DefaultAuditSink is missing from the iteration).
    """
    from sqlalchemy import select

    from app.modules.audit.events import AuditEvent
    from app.modules.audit.models import AuditLog
    from app.platform.extensions import _extensions
    from app.platform.extensions.defaults import DefaultAuditSink

    class FixtureSink:
        """Stand-in for a future enterprise audit-export sink (S3, SIEM, syslog)."""

        def __init__(self) -> None:
            self.received: list[AuditEvent] = []

        async def emit(self, session, event):
            self.received.append(event)

    fixture_sink = FixtureSink()
    saved = _extensions.get("audit_sinks")
    # Pitfall C: seed BOTH default + fixture so DefaultAuditSink also runs.
    _extensions["audit_sinks"] = [DefaultAuditSink(), fixture_sink]
    try:
        # Use a deterministic username so the assertion query is precise.
        unique_username = f"audit-sink-test-multi-{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/admin/users/",
            json={
                "username": unique_username,
                "password": "test-password-12345",
                "role": "viewer",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, (
            f"POST /admin/users/ failed: {resp.status_code} {resp.text}. "
            f"If this fails with the request body shape, refresh the field "
            f"names from backend/app/modules/admin/schemas.py::AdminUserCreate."
        )

        # AUDIT-04: FixtureSink received the user.create event.
        user_create_events = [
            e for e in fixture_sink.received if e.action == "user.create"
        ]
        assert user_create_events, (
            f"FixtureSink.received did not contain a user.create event. "
            f"Saw: {[e.action for e in fixture_sink.received]}. "
            f"If empty, Plan 03 may not have rewritten admin/router.py:113 "
            f"to route through audit_emit() — check that admin/router.py "
            f"contains 'audit_emit' and not 'log_action' near line 113."
        )
        evt = user_create_events[0]
        assert evt.resource_type == "user"
        assert evt.details is not None
        assert evt.details.get("username") == unique_username
        assert evt.details.get("role") == "viewer"

        # AUDIT-05 (default still ran): DefaultAuditSink wrote its audit_logs row.
        # The request handler committed, so committing test_db_session starts a new
        # READ COMMITTED transaction that sees the committed audit row.
        await test_db_session.commit()
        row = (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.create",
                    AuditLog.details.contains({"username": unique_username}),
                )
            )
        ).scalar_one_or_none()
        assert row is not None, (
            "DefaultAuditSink did not write its audit_logs row "
            "(multi-sink coexistence broken — the FixtureSink did not "
            "displace the default, but the default did not run). "
            "Verify _extensions['audit_sinks'] was seeded with BOTH "
            "DefaultAuditSink() and fixture_sink (Pitfall C)."
        )
    finally:
        if saved is None:
            _extensions.pop("audit_sinks", None)
        else:
            _extensions["audit_sinks"] = saved
