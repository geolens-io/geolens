"""Phase 1230 Plan 01 Tasks 2 & 3 — per-event toggle Settings + events.py helper tests.

Covers Task 2:
  - Settings per-event toggle fields (notify_on_signup, notify_on_ingest_complete,
    notify_on_ingest_failed, notify_on_health_alert) all default False.
  - Env binding flips a toggle on (NOTIFY_ON_SIGNUP=true -> notify_on_signup=True).
  - notification_admin_email defaults to None; blank env string normalizes to None.

Covers Task 3:
  - event_enabled(event_key) returns False when the toggle is off; True when on.
  - build_event_notification() returns a Notification with the resolved recipient in
    data["to"] and the failure reason in body+data when reason is given.
  - emit_event_safe() with toggle OFF does NOT invoke the build callable.
  - emit_event_safe() never raises even when build() or notify() throws.
"""

from __future__ import annotations

import os

import pytest


# ===========================================================================
# Task 2: per-event toggle Settings fields
# ===========================================================================


class TestPerEventToggleDefaults:
    """All four per-event toggles must default to False (EVENT-05)."""

    def test_notify_on_signup_default_false(self) -> None:
        from app.core.config import Settings

        fields = Settings.model_fields
        assert "notify_on_signup" in fields, "Settings must have notify_on_signup field"
        assert fields["notify_on_signup"].default is False, (
            "notify_on_signup must default to False"
        )

    def test_notify_on_ingest_complete_default_false(self) -> None:
        from app.core.config import Settings

        fields = Settings.model_fields
        assert "notify_on_ingest_complete" in fields, (
            "Settings must have notify_on_ingest_complete field"
        )
        assert fields["notify_on_ingest_complete"].default is False, (
            "notify_on_ingest_complete must default to False"
        )

    def test_notify_on_ingest_failed_default_false(self) -> None:
        from app.core.config import Settings

        fields = Settings.model_fields
        assert "notify_on_ingest_failed" in fields, (
            "Settings must have notify_on_ingest_failed field"
        )
        assert fields["notify_on_ingest_failed"].default is False, (
            "notify_on_ingest_failed must default to False"
        )

    def test_notify_on_health_alert_default_false(self) -> None:
        from app.core.config import Settings

        fields = Settings.model_fields
        assert "notify_on_health_alert" in fields, (
            "Settings must have notify_on_health_alert field"
        )
        assert fields["notify_on_health_alert"].default is False, (
            "notify_on_health_alert must default to False"
        )


def test_settings_toggle_env_binding() -> None:
    """Setting NOTIFY_ON_SIGNUP=true must make settings.notify_on_signup == True (pydantic env binding)."""
    old_env = os.environ.copy()
    os.environ["NOTIFY_ON_SIGNUP"] = "true"
    try:
        from app.core.config import Settings

        s = Settings(
            postgres_password="test-password-for-unit-test",
            jwt_secret_key="a" * 32,
            geolens_admin_username="admin",
            geolens_admin_password="admin1234!",
        )
        assert s.notify_on_signup is True, (
            f"NOTIFY_ON_SIGNUP=true must bind to notify_on_signup=True; "
            f"got {s.notify_on_signup!r}"
        )
    finally:
        for key in list(os.environ.keys()):
            if key not in old_env:
                del os.environ[key]
            else:
                os.environ[key] = old_env[key]


def test_notification_admin_email_default_none() -> None:
    """notification_admin_email must default to None in Settings.model_fields."""
    from app.core.config import Settings

    fields = Settings.model_fields
    assert "notification_admin_email" in fields, (
        "Settings must have notification_admin_email field"
    )
    assert fields["notification_admin_email"].default is None, (
        "notification_admin_email must default to None"
    )


def test_notification_admin_email_blank_env_normalizes_to_none() -> None:
    """NOTIFICATION_ADMIN_EMAIL='' (blank) must normalize to None via empty_str_to_none validator."""
    old_env = os.environ.copy()
    os.environ["NOTIFICATION_ADMIN_EMAIL"] = ""
    try:
        from app.core.config import Settings

        s = Settings(
            postgres_password="test-password-for-unit-test",
            jwt_secret_key="a" * 32,
            geolens_admin_username="admin",
            geolens_admin_password="admin1234!",
        )
        assert s.notification_admin_email is None, (
            f"Blank NOTIFICATION_ADMIN_EMAIL must normalize to None; "
            f"got {s.notification_admin_email!r}"
        )
    finally:
        for key in list(os.environ.keys()):
            if key not in old_env:
                del os.environ[key]
            else:
                os.environ[key] = old_env[key]


# ===========================================================================
# Task 3: events.py helper — event_enabled, build_event_notification, emit_event_safe
# ===========================================================================


class TestEventEnabled:
    """event_enabled() maps event_key to the matching notify_on_* toggle."""

    def test_event_enabled_signup_false_by_default(self, monkeypatch) -> None:
        """event_enabled('signup') returns False when notify_on_signup is False."""

        class _FakeSettings:
            notify_on_signup = False
            notify_on_ingest_complete = False
            notify_on_ingest_failed = False
            notify_on_health_alert = False

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications.events import event_enabled

        assert event_enabled("signup") is False, (
            "event_enabled('signup') must return False when notify_on_signup is False"
        )

    def test_event_enabled_signup_true_when_toggled(self, monkeypatch) -> None:
        """event_enabled('signup') returns True when notify_on_signup is True."""

        class _FakeSettings:
            notify_on_signup = True
            notify_on_ingest_complete = False
            notify_on_ingest_failed = False
            notify_on_health_alert = False

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications.events import event_enabled

        assert event_enabled("signup") is True, (
            "event_enabled('signup') must return True when notify_on_signup is True"
        )

    def test_event_enabled_ingest_complete(self, monkeypatch) -> None:
        class _FakeSettings:
            notify_on_signup = False
            notify_on_ingest_complete = True
            notify_on_ingest_failed = False
            notify_on_health_alert = False

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications.events import event_enabled

        assert event_enabled("ingest_complete") is True

    def test_event_enabled_unknown_key_returns_false(self, monkeypatch) -> None:
        """event_enabled() returns False for unknown event keys."""

        class _FakeSettings:
            notify_on_signup = True
            notify_on_ingest_complete = True
            notify_on_ingest_failed = True
            notify_on_health_alert = True

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications.events import event_enabled

        assert event_enabled("nonexistent_event") is False, (
            "event_enabled() must return False for unknown event keys"
        )


class TestBuildEventNotification:
    """build_event_notification() returns a correct Notification payload."""

    def test_build_puts_admin_email_in_data_to(self, monkeypatch) -> None:
        """data['to'] must equal notification_admin_email when set."""

        class _FakeSettings:
            notification_admin_email = "admin@example.com"
            smtp_from_address = "from@example.com"

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications.events import build_event_notification

        n = build_event_notification(
            "signup", subject="New signup", body="Someone signed up"
        )
        assert n.data is not None
        assert n.data.get("to") == "admin@example.com", (
            f"data['to'] must be notification_admin_email when set; got {n.data.get('to')!r}"
        )

    def test_build_falls_back_to_smtp_from_address(self, monkeypatch) -> None:
        """data['to'] falls back to smtp_from_address when notification_admin_email is None."""

        class _FakeSettings:
            notification_admin_email = None
            smtp_from_address = "from@example.com"

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications.events import build_event_notification

        n = build_event_notification("signup", subject="New signup", body="body text")
        assert n.data is not None
        assert n.data.get("to") == "from@example.com", (
            f"data['to'] must fall back to smtp_from_address; got {n.data.get('to')!r}"
        )

    def test_build_includes_reason_in_body_and_data(self, monkeypatch) -> None:
        """When reason is given, it appears in body text and data['reason'] (EVENT-03)."""

        class _FakeSettings:
            notification_admin_email = "admin@example.com"
            smtp_from_address = None

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications.events import build_event_notification

        n = build_event_notification(
            "ingest_failed",
            subject="Ingest failed",
            body="The ingest job failed.",
            reason="Out of memory",
        )
        assert "Out of memory" in n.body, (
            f"reason must be included in the body text; body={n.body!r}"
        )
        assert n.data is not None
        assert n.data.get("reason") == "Out of memory", (
            f"reason must be in data['reason']; got {n.data.get('reason')!r}"
        )

    def test_build_merges_extra_dict(self, monkeypatch) -> None:
        """Extra kwargs are merged into data."""

        class _FakeSettings:
            notification_admin_email = "admin@example.com"
            smtp_from_address = None

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications.events import build_event_notification

        n = build_event_notification(
            "ingest_complete",
            subject="Ingest done",
            body="Job finished.",
            extra={"job_id": "abc-123", "dataset": "parcels"},
        )
        assert n.data is not None
        assert n.data.get("job_id") == "abc-123"
        assert n.data.get("dataset") == "parcels"

    def test_build_returns_notification_instance(self, monkeypatch) -> None:
        """build_event_notification returns a Notification dataclass instance."""

        class _FakeSettings:
            notification_admin_email = None
            smtp_from_address = None

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.extensions.protocols import Notification
        from app.platform.notifications.events import build_event_notification

        n = build_event_notification("health_alert", subject="Health", body="Degraded")
        assert isinstance(n, Notification), (
            f"build_event_notification must return Notification; got {type(n).__name__}"
        )


class TestEmitEventSafe:
    """emit_event_safe() is cheap when disabled and never raises."""

    @pytest.mark.anyio
    async def test_emit_event_safe_does_not_call_build_when_toggle_off(
        self, monkeypatch
    ) -> None:
        """emit_event_safe() with toggle OFF must NOT invoke the build callable."""

        class _FakeSettings:
            notify_on_signup = False
            notify_on_ingest_complete = False
            notify_on_ingest_failed = False
            notify_on_health_alert = False
            notification_admin_email = None
            smtp_from_address = None

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications.events import emit_event_safe

        build_called = []

        def _build():
            build_called.append(True)
            from app.platform.extensions.protocols import Notification

            return Notification(event_type="signup", subject="s", body="b")

        await emit_event_safe(event_key="signup", build=_build)
        assert build_called == [], (
            "emit_event_safe() must NOT invoke the build callable when toggle is OFF"
        )

    @pytest.mark.anyio
    async def test_emit_event_safe_never_raises_on_throwing_build(
        self, monkeypatch
    ) -> None:
        """emit_event_safe() must swallow exceptions from the build callable."""

        class _FakeSettings:
            notify_on_signup = True
            notify_on_ingest_complete = False
            notify_on_ingest_failed = False
            notify_on_health_alert = False
            notification_admin_email = None
            smtp_from_address = None

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        # Also stub notify() to avoid needing a registered sink.
        from app.platform.notifications import events as events_mod

        async def _fake_notify(n):
            pass

        monkeypatch.setattr(events_mod, "notify", _fake_notify)

        from app.platform.notifications.events import emit_event_safe

        def _bad_build():
            raise RuntimeError("builder exploded")

        # Must NOT raise — caller continues normally.
        await emit_event_safe(event_key="signup", build=_bad_build)

    @pytest.mark.anyio
    async def test_emit_event_safe_never_raises_on_throwing_notify(
        self, monkeypatch
    ) -> None:
        """emit_event_safe() must swallow exceptions from notify()."""

        class _FakeSettings:
            notify_on_signup = True
            notify_on_ingest_complete = False
            notify_on_ingest_failed = False
            notify_on_health_alert = False
            notification_admin_email = "admin@example.com"
            smtp_from_address = None

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications import events as events_mod

        async def _raising_notify(n):
            raise RuntimeError("notify blew up")

        monkeypatch.setattr(events_mod, "notify", _raising_notify)

        from app.platform.extensions.protocols import Notification
        from app.platform.notifications.events import emit_event_safe

        def _good_build():
            return Notification(event_type="signup", subject="s", body="b")

        # Must NOT raise.
        await emit_event_safe(event_key="signup", build=_good_build)

    @pytest.mark.anyio
    async def test_emit_event_safe_calls_notify_when_toggle_on(
        self, monkeypatch
    ) -> None:
        """emit_event_safe() calls notify() when toggle is ON and build succeeds."""

        class _FakeSettings:
            notify_on_signup = True
            notify_on_ingest_complete = False
            notify_on_ingest_failed = False
            notify_on_health_alert = False
            notification_admin_email = "admin@example.com"
            smtp_from_address = None

        monkeypatch.setattr("app.core.config.settings", _FakeSettings(), raising=False)

        from app.platform.notifications import events as events_mod

        notify_calls = []

        async def _fake_notify(n):
            notify_calls.append(n)

        monkeypatch.setattr(events_mod, "notify", _fake_notify)

        from app.platform.extensions.protocols import Notification
        from app.platform.notifications.events import emit_event_safe

        def _build():
            return Notification(event_type="signup", subject="s", body="b")

        await emit_event_safe(event_key="signup", build=_build)
        assert len(notify_calls) == 1, (
            "emit_event_safe() must call notify() when toggle is ON"
        )
