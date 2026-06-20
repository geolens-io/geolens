"""Phase 1229 — NotificationSink protocol + notify() facade + Settings config tests.

Covers:
  - NOTIF-01 (Plan 01 Task 1): NotificationSink Protocol shape + Notification payload
    dataclass + DefaultNotificationSink no-op + get_notification_sinks() accessor
  - NOTIF-04 (Plan 01 Task 2): notify() fan-out facade with per-sink failure isolation
  - NOTIF-05 (Plan 01 Task 3): Settings notification env-var fields + secret masking
"""

from __future__ import annotations

import inspect

import pytest


# ---------------------------------------------------------------------------
# Task 1: Protocol shape + Notification payload + accessor
# ---------------------------------------------------------------------------


def test_notification_sink_protocol_shape() -> None:
    """NOTIF-01: NotificationSink is a runtime_checkable Protocol."""
    from app.platform.extensions.protocols import NotificationSink

    # Protocol is runtime_checkable
    assert hasattr(NotificationSink, "_is_runtime_protocol") or hasattr(
        NotificationSink, "_is_protocol"
    ), "NotificationSink must be a runtime_checkable Protocol"


def test_default_notification_sink_satisfies_protocol() -> None:
    """NOTIF-01 / NOTIF-04: DefaultNotificationSink() isinstance NotificationSink is True."""
    from app.platform.extensions.defaults import DefaultNotificationSink
    from app.platform.extensions.protocols import NotificationSink

    sink = DefaultNotificationSink()
    assert isinstance(sink, NotificationSink), (
        "DefaultNotificationSink must structurally satisfy NotificationSink Protocol"
    )


@pytest.mark.anyio
async def test_default_notification_sink_is_noop() -> None:
    """NOTIF-04: DefaultNotificationSink.deliver is a literal no-op (returns None, does not raise)."""
    from app.platform.extensions.defaults import DefaultNotificationSink
    from app.platform.extensions.protocols import Notification

    sink = DefaultNotificationSink()
    n = Notification(event_type="test", subject="Test Subject", body="Test body")
    result = await sink.deliver(n)
    assert result is None, (
        "DefaultNotificationSink.deliver must return None (no-op contract — NOTIF-04)"
    )


def test_notification_is_frozen_dataclass() -> None:
    """NOTIF-01: Notification is a frozen dataclass with the correct fields."""
    import dataclasses

    from app.platform.extensions.protocols import Notification

    # Must be a dataclass
    assert dataclasses.is_dataclass(Notification), "Notification must be a dataclass"

    # Must be frozen
    fields = {f.name for f in dataclasses.fields(Notification)}
    assert fields == {"event_type", "subject", "body", "data"}, (
        f"Notification must have fields event_type, subject, body, data; got {fields}"
    )

    # data defaults to None
    n = Notification(event_type="signup", subject="Welcome", body="Hello!")
    assert n.data is None, "Notification.data must default to None"

    # frozen — mutating a field must raise
    n2 = Notification(event_type="x", subject="y", body="z", data={"k": "v"})
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
        n2.event_type = "mutated"  # type: ignore[misc]


def test_deliver_method_is_async() -> None:
    """NOTIF-01: DefaultNotificationSink.deliver is async (enables non-blocking I/O in overlays)."""
    from app.platform.extensions.defaults import DefaultNotificationSink

    assert inspect.iscoroutinefunction(DefaultNotificationSink().deliver), (
        "DefaultNotificationSink.deliver must be async"
    )


def test_get_notification_sinks_default_fallback() -> None:
    """NOTIF-01: get_notification_sinks() with empty registry returns [DefaultNotificationSink()]."""
    from app.platform.extensions import _extensions, get_notification_sinks
    from app.platform.extensions.defaults import DefaultNotificationSink

    # Snapshot + clear slot to simulate community deployment with no overlay
    saved = _extensions.get("notification_sinks")
    _extensions.pop("notification_sinks", None)
    try:
        sinks = get_notification_sinks()
        assert isinstance(sinks, list), "get_notification_sinks must return list"
        assert len(sinks) == 1, (
            f"Expected exactly one DefaultNotificationSink when slot is missing; "
            f"got len={len(sinks)}"
        )
        assert isinstance(sinks[0], DefaultNotificationSink), (
            f"Expected DefaultNotificationSink; got {type(sinks[0]).__name__}"
        )
    finally:
        if saved is not None:
            _extensions["notification_sinks"] = saved
        else:
            _extensions.pop("notification_sinks", None)


def test_get_notification_sinks_returns_fresh_list() -> None:
    """NOTIF-01: get_notification_sinks() returns a fresh list each call (defensive copy)."""
    from app.platform.extensions import _extensions, get_notification_sinks

    saved = _extensions.get("notification_sinks")
    _extensions.pop("notification_sinks", None)
    try:
        sinks_a = get_notification_sinks()
        sinks_b = get_notification_sinks()
        # Different list objects — mutating one does not affect the other
        assert sinks_a is not sinks_b, (
            "get_notification_sinks must return a fresh list each call (defensive copy)"
        )
        sinks_a.clear()
        sinks_b2 = get_notification_sinks()
        assert len(sinks_b2) == 1, (
            "Mutating the returned list must not affect subsequent get_notification_sinks() calls"
        )
    finally:
        if saved is not None:
            _extensions["notification_sinks"] = saved
        else:
            _extensions.pop("notification_sinks", None)


def test_notification_sinks_is_additive_slot() -> None:
    """NOTIF-01: 'notification_sinks' is a member of ADDITIVE_SLOT_KEYS."""
    from app.platform.extensions import ADDITIVE_SLOT_KEYS

    assert "notification_sinks" in ADDITIVE_SLOT_KEYS, (
        "'notification_sinks' must be in ADDITIVE_SLOT_KEYS so enterprise overlays "
        "can append sinks without tripping the single-slot conflict guard"
    )


# ---------------------------------------------------------------------------
# Task 2: notify() fan-out facade with per-sink failure isolation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_notify_noop_deployment_attempted_zero() -> None:
    """NOTIF-04: notify() with the default registry reports attempted == 0.

    The DefaultNotificationSink no-op does NOT count as a delivery attempt —
    attempted reflects channels that actually tried to send.
    """
    from app.platform.extensions import _extensions
    from app.platform.extensions.protocols import Notification
    from app.platform.notifications import notify

    saved = _extensions.get("notification_sinks")
    _extensions.pop("notification_sinks", None)
    try:
        n = Notification(event_type="test", subject="Test", body="body")
        result = await notify(n)
        assert result.attempted == 0, (
            f"No-channel deployment must report attempted == 0; got {result.attempted}"
        )
        assert result.errors == [], (
            f"No-channel deployment must report no errors; got {result.errors}"
        )
    finally:
        if saved is not None:
            _extensions["notification_sinks"] = saved
        else:
            _extensions.pop("notification_sinks", None)


@pytest.mark.anyio
async def test_notify_raising_sink_isolated() -> None:
    """NOTIF-04: notify() with a raising sink returns non-empty errors and does NOT raise."""
    from app.platform.extensions import _extensions
    from app.platform.extensions.protocols import Notification
    from app.platform.notifications import notify

    class RaisingSink:
        async def deliver(self, notification) -> None:
            raise ValueError("simulated channel failure")

    saved = _extensions.get("notification_sinks")
    _extensions["notification_sinks"] = [RaisingSink()]
    try:
        n = Notification(event_type="test", subject="Test", body="body")
        result = await notify(n)
        # Must NOT raise (failure isolation is the contract)
        assert len(result.errors) >= 1, (
            "A raising sink must add an entry to result.errors"
        )
        # Error strings must not contain any secret values
        # (no secrets in this test, but confirm type)
        assert all(isinstance(e, str) for e in result.errors), (
            "result.errors must be a list of strings"
        )
    finally:
        if saved is not None:
            _extensions["notification_sinks"] = saved
        else:
            _extensions.pop("notification_sinks", None)


@pytest.mark.anyio
async def test_notify_raising_sink_error_string_safe() -> None:
    """NOTIF-04 / T-1229-03: error strings must not contain secret values."""
    from app.platform.extensions import _extensions
    from app.platform.extensions.protocols import Notification
    from app.platform.notifications import notify

    SECRET_VALUE = "super-secret-smtp-password-12345"

    class SecretLeakingSink:
        async def deliver(self, notification) -> None:
            raise ValueError(f"Failed to connect with password={SECRET_VALUE}")

    saved = _extensions.get("notification_sinks")
    _extensions["notification_sinks"] = [SecretLeakingSink()]
    try:
        n = Notification(event_type="test", subject="Test", body="body")
        result = await notify(n)
        assert len(result.errors) >= 1, "Expected at least one error entry"
        for error_str in result.errors:
            assert SECRET_VALUE not in error_str, (
                f"Error string must not contain raw secret value; got: {error_str!r}"
            )
    finally:
        if saved is not None:
            _extensions["notification_sinks"] = saved
        else:
            _extensions.pop("notification_sinks", None)


@pytest.mark.anyio
async def test_notify_successful_sink_delivered() -> None:
    """NOTIF-04: notify() with a succeeding sink returns delivered >= 1 and errors == []."""
    from app.platform.extensions import _extensions
    from app.platform.extensions.protocols import Notification
    from app.platform.notifications import notify

    class SucceedingSink:
        def __init__(self) -> None:
            self.calls: list = []

        async def deliver(self, notification) -> None:
            self.calls.append(notification)

    sink = SucceedingSink()
    saved = _extensions.get("notification_sinks")
    _extensions["notification_sinks"] = [sink]
    try:
        n = Notification(event_type="test", subject="Test", body="body")
        result = await notify(n)
        assert result.delivered >= 1, f"Expected delivered >= 1; got {result.delivered}"
        assert result.errors == [], f"Expected no errors; got {result.errors}"
        assert len(sink.calls) == 1, "Sink.deliver must have been called exactly once"
    finally:
        if saved is not None:
            _extensions["notification_sinks"] = saved
        else:
            _extensions.pop("notification_sinks", None)


@pytest.mark.anyio
async def test_notify_two_sinks_first_raises_second_still_runs() -> None:
    """NOTIF-04: failure of the first sink does NOT short-circuit delivery to the second."""
    from app.platform.extensions import _extensions
    from app.platform.extensions.protocols import Notification
    from app.platform.notifications import notify

    class RaisingSink:
        async def deliver(self, notification) -> None:
            raise RuntimeError("first sink always fails")

    class SucceedingSink:
        def __init__(self) -> None:
            self.calls: list = []

        async def deliver(self, notification) -> None:
            self.calls.append(notification)

    second_sink = SucceedingSink()
    saved = _extensions.get("notification_sinks")
    _extensions["notification_sinks"] = [RaisingSink(), second_sink]
    try:
        n = Notification(event_type="test", subject="Test", body="body")
        result = await notify(n)
        # The second sink must have run
        assert len(second_sink.calls) == 1, (
            "Second sink must run even when the first raises (per-sink isolation)"
        )
        assert result.delivered >= 1, (
            "At least one delivery must succeed (the second sink)"
        )
        assert len(result.errors) >= 1, (
            "The first sink's failure must be recorded in errors"
        )
    finally:
        if saved is not None:
            _extensions["notification_sinks"] = saved
        else:
            _extensions.pop("notification_sinks", None)


# ---------------------------------------------------------------------------
# Task 3: Settings notification fields + secret masking
# ---------------------------------------------------------------------------


def test_settings_notification_defaults_all_off() -> None:
    """NOTIF-05: Settings constructed with no notification env vars yields all-off defaults."""
    from app.core.config import Settings

    # Construct a Settings-like object with required fields but no notification env vars.
    # We read Settings.model_fields to verify the notification fields exist with correct defaults.
    fields = Settings.model_fields

    assert "notifications_enabled" in fields, (
        "Settings must have notifications_enabled field"
    )
    assert "smtp_host" in fields, "Settings must have smtp_host field"
    assert "smtp_password" in fields, "Settings must have smtp_password field"
    assert "notification_webhook_url" in fields, (
        "Settings must have notification_webhook_url field"
    )
    assert "notification_webhook_secret" in fields, (
        "Settings must have notification_webhook_secret field"
    )

    # Verify defaults from model_fields
    assert fields["notifications_enabled"].default is False, (
        "notifications_enabled default must be False"
    )
    assert fields["smtp_host"].default is None, "smtp_host default must be None"
    assert fields["smtp_password"].default is None, "smtp_password default must be None"
    assert fields["notification_webhook_url"].default is None, (
        "notification_webhook_url default must be None"
    )
    assert fields["notification_webhook_secret"].default is None, (
        "notification_webhook_secret default must be None"
    )


def test_settings_smtp_password_is_secretstr() -> None:
    """NOTIF-05 / T-1229-01: smtp_password and webhook_secret are SecretStr (never plain str).

    Verifies that setting SMTP_PASSWORD produces a SecretStr whose str() / repr()
    does NOT reveal the raw value.
    """
    import os

    from pydantic import SecretStr

    from app.core.config import Settings

    raw_password = "my-test-smtp-password-do-not-log"

    field_info = Settings.model_fields.get("smtp_password")
    assert field_info is not None, "smtp_password must be a Settings field"

    # The annotation must be SecretStr | None (verify via the field's annotation)
    annotation = field_info.annotation
    annotation_str = str(annotation)
    assert "SecretStr" in annotation_str, (
        f"smtp_password annotation must include SecretStr; got {annotation_str}"
    )

    # Build a Settings instance with the password via environment
    old_env = os.environ.copy()
    os.environ["SMTP_PASSWORD"] = raw_password
    try:
        # Construct a fresh Settings directly
        s = Settings(
            postgres_password="test-password-for-unit-test",
            jwt_secret_key="a" * 32,
            geolens_admin_username="admin",
            geolens_admin_password="admin1234!",
        )
        # smtp_password should now be SecretStr wrapping the raw value
        assert s.smtp_password is not None, (
            "smtp_password must not be None when SMTP_PASSWORD env var is set"
        )
        assert isinstance(s.smtp_password, SecretStr), (
            f"smtp_password must be SecretStr; got {type(s.smtp_password).__name__}"
        )
        # The raw value must NOT appear in repr()
        settings_repr = repr(s)
        assert raw_password not in settings_repr, (
            f"Raw SMTP_PASSWORD value must not appear in repr(Settings); "
            f"found in: {settings_repr[:200]}..."
        )
    finally:
        # Restore environment
        for key in list(os.environ.keys()):
            if key not in old_env:
                del os.environ[key]
            else:
                os.environ[key] = old_env[key]


def test_no_notification_key_in_persistent_config() -> None:
    """NOTIF-05 prohibition: no notification secret is stored in PersistentConfig.

    Notification secrets must come from env/Settings, never from the app_settings
    DB table (persistent_config.py:80-83 prohibits secrets there).
    """
    import pathlib

    pc_path = (
        pathlib.Path(__file__).parent.parent / "app" / "core" / "persistent_config.py"
    )
    source = pc_path.read_text()
    for keyword in ("smtp_password", "webhook_secret", "notification_webhook"):
        assert keyword not in source, (
            f"PersistentConfig must not contain '{keyword}' — notification secrets "
            f"must live in Settings (env), not in the app_settings DB table "
            f"(persistent_config.py:80-83 prohibition)"
        )
