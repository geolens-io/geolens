"""Phase 1230 Plan 01 Task 1 — EnvConfiguredNotificationSink registration tests.

Covers:
  - After register_builtin_notification_sinks() runs, get_notification_sinks()
    includes EnvConfiguredNotificationSink (alongside DefaultNotificationSink).
  - Registration is idempotent — two calls do NOT duplicate the sink.
  - bootstrap(app=None) (worker path) results in EnvConfiguredNotificationSink
    being present — the split-brain proof.
  - bootstrap(app=<FastAPI>) also registers the sink (API path parity).
  - With notifications_enabled=True + a stubbed channel, notify() reports
    attempted >= 1 after sink registration.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helper: isolate the notification_sinks slot for each test.
# ---------------------------------------------------------------------------


def _save_and_clear_slot():
    """Return a context that saves + clears notification_sinks and restores on exit."""
    from app.platform.extensions import _extensions

    return _extensions.get("notification_sinks")


def _restore_slot(saved):
    from app.platform.extensions import _extensions

    if saved is not None:
        _extensions["notification_sinks"] = saved
    else:
        _extensions.pop("notification_sinks", None)


# ---------------------------------------------------------------------------
# Task 1.1: register_builtin_notification_sinks() exists + wires the sink
# ---------------------------------------------------------------------------


def test_register_builtin_notification_sinks_function_exists() -> None:
    """register_builtin_notification_sinks must be importable from bootstrap."""
    from app.platform.extensions.bootstrap import register_builtin_notification_sinks

    assert callable(register_builtin_notification_sinks), (
        "register_builtin_notification_sinks must be a callable in bootstrap.py"
    )


def test_register_builtin_notification_sinks_adds_env_sink() -> None:
    """After register_builtin_notification_sinks(), get_notification_sinks() includes EnvConfiguredNotificationSink."""
    from app.platform.extensions import get_notification_sinks
    from app.platform.extensions.bootstrap import register_builtin_notification_sinks
    from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

    saved = _save_and_clear_slot()
    try:
        register_builtin_notification_sinks()
        sinks = get_notification_sinks()
        env_sinks = [s for s in sinks if isinstance(s, EnvConfiguredNotificationSink)]
        assert len(env_sinks) >= 1, (
            f"After register_builtin_notification_sinks(), get_notification_sinks() "
            f"must include at least one EnvConfiguredNotificationSink; got {[type(s).__name__ for s in sinks]}"
        )
    finally:
        _restore_slot(saved)


def test_register_builtin_notification_sinks_preserves_default_sink() -> None:
    """DefaultNotificationSink must still be present after registration (additive contract)."""
    from app.platform.extensions import get_notification_sinks
    from app.platform.extensions.bootstrap import register_builtin_notification_sinks
    from app.platform.extensions.defaults import DefaultNotificationSink

    saved = _save_and_clear_slot()
    try:
        register_builtin_notification_sinks()
        sinks = get_notification_sinks()
        default_sinks = [s for s in sinks if isinstance(s, DefaultNotificationSink)]
        assert len(default_sinks) >= 1, (
            f"DefaultNotificationSink must still be present after sink registration "
            f"(NOTIF-01 additive contract); got {[type(s).__name__ for s in sinks]}"
        )
    finally:
        _restore_slot(saved)


# ---------------------------------------------------------------------------
# Task 1.2: idempotency — two calls must not duplicate the sink
# ---------------------------------------------------------------------------


def test_register_builtin_notification_sinks_is_idempotent() -> None:
    """Calling register_builtin_notification_sinks() twice must NOT add a second EnvConfiguredNotificationSink."""
    from app.platform.extensions import get_notification_sinks
    from app.platform.extensions.bootstrap import register_builtin_notification_sinks
    from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

    saved = _save_and_clear_slot()
    try:
        register_builtin_notification_sinks()
        register_builtin_notification_sinks()  # second call — must be idempotent
        sinks = get_notification_sinks()
        env_sinks = [s for s in sinks if isinstance(s, EnvConfiguredNotificationSink)]
        assert len(env_sinks) == 1, (
            f"Idempotency violated: expected exactly 1 EnvConfiguredNotificationSink "
            f"after two registration calls; got {len(env_sinks)}"
        )
    finally:
        _restore_slot(saved)


# ---------------------------------------------------------------------------
# Task 1.3: worker-path proof — bootstrap(app=None) registers the sink
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_bootstrap_worker_path_registers_env_sink(monkeypatch) -> None:
    """bootstrap(app=None) (worker path) must result in EnvConfiguredNotificationSink in get_notification_sinks().

    This is the split-brain proof: the worker entrypoint calls bootstrap(app=None),
    so any registration inside bootstrap() is guaranteed to run in the worker.
    """
    from app.platform.extensions import get_notification_sinks
    from app.platform.extensions.bootstrap import bootstrap
    from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

    # Stub out side-effectful bootstrap steps so we don't need a real DB/S3/cache.
    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.load_extensions", lambda: None
    )
    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.check_enterprise_overlay_requested",
        lambda exts: None,
    )
    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.check_tenancy_mode_supported",
        lambda exts: None,
    )
    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.init_edition", lambda exts: None
    )
    monkeypatch.setattr("app.platform.extensions.bootstrap.list_extensions", lambda: [])

    from app.core.edition import EditionInfo

    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.get_edition",
        lambda: EditionInfo(edition="community", features=frozenset()),
    )
    monkeypatch.setattr("app.platform.extensions.bootstrap.init_storage", lambda: None)
    monkeypatch.setattr("app.platform.extensions.bootstrap.init_cache", lambda: None)
    # Stub RLS application (requires live DB)
    monkeypatch.setattr(
        "app.core.db.rls.apply_tenancy_rls_from_engine",
        _async_noop,
    )

    saved = _save_and_clear_slot()
    try:
        await bootstrap(app=None)
        sinks = get_notification_sinks()
        env_sinks = [s for s in sinks if isinstance(s, EnvConfiguredNotificationSink)]
        assert len(env_sinks) >= 1, (
            f"bootstrap(app=None) (worker path) must register EnvConfiguredNotificationSink; "
            f"got sinks: {[type(s).__name__ for s in sinks]}"
        )
    finally:
        _restore_slot(saved)


@pytest.mark.anyio
async def test_bootstrap_api_path_registers_env_sink(monkeypatch) -> None:
    """bootstrap(app=<FastAPI>) (API path) must also register EnvConfiguredNotificationSink."""
    from fastapi import FastAPI

    from app.platform.extensions import get_notification_sinks
    from app.platform.extensions.bootstrap import bootstrap
    from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.load_extensions", lambda: None
    )
    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.check_enterprise_overlay_requested",
        lambda exts: None,
    )
    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.check_tenancy_mode_supported",
        lambda exts: None,
    )
    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.init_edition", lambda exts: None
    )
    monkeypatch.setattr("app.platform.extensions.bootstrap.list_extensions", lambda: [])
    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.get_extension_routers", lambda: []
    )

    from app.core.edition import EditionInfo

    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.get_edition",
        lambda: EditionInfo(edition="community", features=frozenset()),
    )
    monkeypatch.setattr("app.platform.extensions.bootstrap.init_storage", lambda: None)
    monkeypatch.setattr("app.platform.extensions.bootstrap.init_cache", lambda: None)
    monkeypatch.setattr(
        "app.platform.extensions.bootstrap.get_billing_extensions", lambda: []
    )
    monkeypatch.setattr(
        "app.core.db.rls.apply_tenancy_rls_from_engine",
        _async_noop,
    )

    app = FastAPI()
    saved = _save_and_clear_slot()
    try:
        await bootstrap(app=app)
        sinks = get_notification_sinks()
        env_sinks = [s for s in sinks if isinstance(s, EnvConfiguredNotificationSink)]
        assert len(env_sinks) >= 1, (
            f"bootstrap(app=<FastAPI>) (API path) must register EnvConfiguredNotificationSink; "
            f"got sinks: {[type(s).__name__ for s in sinks]}"
        )
    finally:
        _restore_slot(saved)


# ---------------------------------------------------------------------------
# Task 1.4: delivery proof — notify() reports attempted >= 1 after registration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_notify_attempted_nonzero_after_registration(monkeypatch) -> None:
    """After sink registration with notifications_enabled=True + stubbed channel, notify() reports attempted >= 1."""
    from app.platform.extensions.bootstrap import register_builtin_notification_sinks
    from app.platform.extensions.protocols import Notification
    from app.platform.notifications import notify

    # Stub send_email to avoid real SMTP — just record the call.
    calls: list = []

    async def fake_send_email(notification) -> None:
        calls.append(notification)

    async def fake_post_webhook(notification) -> None:
        pass

    monkeypatch.setattr(
        "app.platform.notifications.env_sink.send_email", fake_send_email
    )
    monkeypatch.setattr(
        "app.platform.notifications.env_sink.post_webhook", fake_post_webhook
    )

    # Patch settings so notifications_enabled=True + smtp_host is set.

    class _FakeSettings:
        notifications_enabled = True
        smtp_host = "smtp.example.com"
        notification_webhook_url = None

    monkeypatch.setattr(
        "app.core.config.settings",
        _FakeSettings(),
        raising=False,
    )

    saved = _save_and_clear_slot()
    try:
        register_builtin_notification_sinks()
        n = Notification(
            event_type="signup",
            subject="New signup",
            body="A user signed up",
            data={"to": "admin@example.com"},
        )
        result = await notify(n)
        assert result.attempted >= 1, (
            f"After sink registration with notifications_enabled=True, "
            f"notify() must report attempted >= 1; got attempted={result.attempted}"
        )
    finally:
        _restore_slot(saved)


# ---------------------------------------------------------------------------
# Shared async no-op helper
# ---------------------------------------------------------------------------


async def _async_noop(*args, **kwargs) -> None:
    """Async no-op stub for monkeypatching async functions."""
    return None
