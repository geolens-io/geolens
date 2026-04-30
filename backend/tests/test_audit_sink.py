"""Phase 222 — AuditSink protocol tests.

Covers AUDIT-01 (Plan 01: this test), AUDIT-03 (Plan 02: raising-sink test),
AUDIT-04 (Plan 04: fixture-sink test). AUDIT-02 architecture guard lives in
test_layering.py (Plan 05).
"""

from __future__ import annotations

import dataclasses


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
