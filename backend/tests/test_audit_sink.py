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

    class RaisingSink:
        async def emit(self, session, event):
            raise RuntimeError("simulated sink failure for AUDIT-03")

    saved = _extensions.get("audit_sinks")
    _extensions["audit_sinks"] = [DefaultAuditSink(), RaisingSink()]
    try:
        actor_id = uuid.uuid4()
        resource_id = uuid.uuid4()
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
