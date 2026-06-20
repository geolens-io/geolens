"""Phase 1229 Plan 02 — SMTP channel + webhook channel + EnvConfiguredNotificationSink tests.

Covers:
  - NOTIF-02 (Task 1): SMTP channel (stdlib smtplib, STARTTLS/SSL, asyncio.to_thread)
  - NOTIF-03 (Task 2): Webhook channel (httpx, Slack-compatible JSON, bounded timeout)
  - NOTIF-04 (Task 3): EnvConfiguredNotificationSink fail-safe routing
  - NOTIF-05 (all tasks): Secrets revealed only at call boundary, never in logs
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch

import pytest

from app.platform.extensions.protocols import Notification

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_NOTIFICATION = Notification(
    event_type="test.event",
    subject="Test Subject",
    body="Test body text",
    data=None,
)

_SECRET_PASSWORD = "s3cr3t-smtp-pass"
_SECRET_WEBHOOK = "webhook-hmac-secret"


# ---------------------------------------------------------------------------
# Task 1: SMTP channel
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_smtp_sends_message_with_starttls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTIF-02: send_email builds correct message, calls starttls, calls login, sends."""
    import smtplib

    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "user@example.com")
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "smtp_password", SecretStr(_SECRET_PASSWORD))
    monkeypatch.setattr(settings, "smtp_from_address", "user@example.com")
    monkeypatch.setattr(settings, "smtp_use_tls", True)

    calls: dict[str, Any] = {
        "starttls": False,
        "login_user": None,
        "login_pass": None,
        "send_message": None,
        "quit": False,
    }

    class FakeSMTP:
        def __init__(self, host: str, port: int) -> None:
            calls["host"] = host
            calls["port"] = port

        def starttls(self) -> None:
            calls["starttls"] = True

        def login(self, user: str, password: str) -> None:
            calls["login_user"] = user
            calls["login_pass"] = password

        def send_message(self, msg: Any) -> None:
            calls["send_message"] = msg

        def quit(self) -> None:
            calls["quit"] = True

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    from app.platform.notifications.smtp_channel import send_email

    await send_email(_TEST_NOTIFICATION)

    assert calls["starttls"] is True, "starttls() must be called when smtp_use_tls=True"
    assert calls["login_user"] == "user@example.com"
    assert calls["login_pass"] == _SECRET_PASSWORD, (
        "revealed password must be passed to login()"
    )
    assert calls["send_message"] is not None
    assert calls["quit"] is True

    msg = calls["send_message"]
    assert msg["Subject"] == "Test Subject"
    assert msg["From"] == "user@example.com"


@pytest.mark.anyio
async def test_smtp_uses_smtp_ssl_on_port_465(monkeypatch: pytest.MonkeyPatch) -> None:
    """NOTIF-02: Port 465 → SMTP_SSL (implicit TLS), no starttls() call."""
    import smtplib

    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 465)
    monkeypatch.setattr(settings, "smtp_username", "user@example.com")
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "smtp_password", SecretStr(_SECRET_PASSWORD))
    monkeypatch.setattr(settings, "smtp_from_address", "user@example.com")
    monkeypatch.setattr(settings, "smtp_use_tls", True)

    ssl_calls: dict[str, Any] = {"starttls": False, "used_ssl": False}

    class FakeSMTPSSL:
        def __init__(self, host: str, port: int) -> None:
            ssl_calls["used_ssl"] = True

        def starttls(self) -> None:
            ssl_calls["starttls"] = True

        def login(self, user: str, password: str) -> None:
            pass

        def send_message(self, msg: Any) -> None:
            pass

        def quit(self) -> None:
            pass

    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTPSSL)
    # ensure plain SMTP is not used
    monkeypatch.setattr(
        smtplib,
        "SMTP",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Should not use SMTP for port 465")
        ),
    )

    from app.platform.notifications.smtp_channel import send_email

    await send_email(_TEST_NOTIFICATION)

    assert ssl_calls["used_ssl"] is True, "SMTP_SSL must be used on port 465"
    assert ssl_calls["starttls"] is False, (
        "starttls() must NOT be called when using SMTP_SSL"
    )


@pytest.mark.anyio
async def test_smtp_no_login_when_no_username(monkeypatch: pytest.MonkeyPatch) -> None:
    """NOTIF-02: No login() call when smtp_username is None."""
    import smtplib

    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", None)
    monkeypatch.setattr(settings, "smtp_password", None)
    monkeypatch.setattr(settings, "smtp_from_address", "noreply@example.com")
    monkeypatch.setattr(settings, "smtp_use_tls", False)

    login_called = {"v": False}

    class FakeSMTP:
        def __init__(self, host: str, port: int) -> None:
            pass

        def starttls(self) -> None:
            pass

        def login(self, user: str, password: str) -> None:
            login_called["v"] = True

        def send_message(self, msg: Any) -> None:
            pass

        def quit(self) -> None:
            pass

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    from app.platform.notifications.smtp_channel import send_email

    await send_email(_TEST_NOTIFICATION)

    assert login_called["v"] is False, (
        "login() must not be called when smtp_username is None"
    )


@pytest.mark.anyio
async def test_smtp_password_not_in_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """T-1229-04: SMTP password must not appear in any log output."""
    import smtplib

    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "user@example.com")
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "smtp_password", SecretStr(_SECRET_PASSWORD))
    monkeypatch.setattr(settings, "smtp_from_address", "user@example.com")
    monkeypatch.setattr(settings, "smtp_use_tls", True)

    class FakeSMTP:
        def __init__(self, host: str, port: int) -> None:
            pass

        def starttls(self) -> None:
            pass

        def login(self, user: str, password: str) -> None:
            pass

        def send_message(self, msg: Any) -> None:
            pass

        def quit(self) -> None:
            pass

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    from app.platform.notifications.smtp_channel import send_email

    with caplog.at_level(logging.DEBUG):
        await send_email(_TEST_NOTIFICATION)

    for record in caplog.records:
        assert _SECRET_PASSWORD not in record.getMessage(), (
            f"SMTP password must not appear in log: {record.getMessage()!r}"
        )


@pytest.mark.anyio
async def test_smtp_uses_to_from_notification_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTIF-02: When Notification.data contains 'to', it is used as the To address."""
    import smtplib

    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "user@example.com")
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "smtp_password", SecretStr(_SECRET_PASSWORD))
    monkeypatch.setattr(settings, "smtp_from_address", "user@example.com")
    monkeypatch.setattr(settings, "smtp_use_tls", False)

    received_to: dict[str, Any] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int) -> None:
            pass

        def login(self, user: str, password: str) -> None:
            pass

        def send_message(self, msg: Any) -> None:
            received_to["to"] = msg["To"]

        def quit(self) -> None:
            pass

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    notif_with_recipient = Notification(
        event_type="test.event",
        subject="Hello",
        body="World",
        data={"to": "recipient@example.com"},
    )

    from app.platform.notifications.smtp_channel import send_email

    await send_email(notif_with_recipient)

    assert received_to["to"] == "recipient@example.com"


# ---------------------------------------------------------------------------
# Task 2: Webhook channel
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_webhook_posts_correct_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """NOTIF-03: post_webhook POSTs JSON with event_type, subject, body, data, and text."""
    import httpx

    from app.core.config import settings

    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/webhook"
    )
    monkeypatch.setattr(settings, "notification_webhook_secret", None)

    captured: dict[str, Any] = {}

    class FakeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            import json as _json

            captured["url"] = str(request.url)
            captured["body"] = _json.loads(request.content)
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, text="ok")

    with patch(
        "httpx.AsyncClient",
        lambda **kw: httpx.AsyncClient(
            transport=FakeTransport(),
            **{k: v for k, v in kw.items() if k != "transport"},
        ),
    ):
        from app.platform.notifications.webhook_channel import post_webhook

        await post_webhook(_TEST_NOTIFICATION)

    assert captured["url"] == "https://hooks.example.com/webhook"
    body = captured["body"]
    assert body["event_type"] == "test.event"
    assert body["subject"] == "Test Subject"
    assert body["body"] == "Test body text"
    assert body["data"] == {}
    assert "text" in body, "Slack-compatible 'text' field must be present"
    assert "Test Subject" in body["text"]
    assert "Test body text" in body["text"]


@pytest.mark.anyio
async def test_webhook_sends_secret_as_header_not_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-1229-04 + NOTIF-03: Webhook secret is sent as X-Webhook-Secret header, never in the URL."""
    import httpx
    from pydantic import SecretStr

    from app.core.config import settings

    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/webhook"
    )
    monkeypatch.setattr(
        settings, "notification_webhook_secret", SecretStr(_SECRET_WEBHOOK)
    )

    captured: dict[str, Any] = {}

    class FakeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, text="ok")

    with patch(
        "httpx.AsyncClient",
        lambda **kw: httpx.AsyncClient(
            transport=FakeTransport(),
            **{k: v for k, v in kw.items() if k != "transport"},
        ),
    ):
        from app.platform.notifications.webhook_channel import post_webhook

        await post_webhook(_TEST_NOTIFICATION)

    # Secret must be in X-Webhook-Secret header
    assert "x-webhook-secret" in captured["headers"], (
        "Webhook secret must be sent as X-Webhook-Secret header"
    )
    assert captured["headers"]["x-webhook-secret"] == _SECRET_WEBHOOK

    # Secret must NOT appear in the URL
    assert _SECRET_WEBHOOK not in captured["url"], (
        "Webhook secret must NOT appear in the request URL"
    )


@pytest.mark.anyio
async def test_webhook_raises_on_non_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """NOTIF-03: post_webhook raises on non-2xx response."""
    import httpx

    from app.core.config import settings

    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/webhook"
    )
    monkeypatch.setattr(settings, "notification_webhook_secret", None)

    class FakeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Server Error")

    with patch(
        "httpx.AsyncClient",
        lambda **kw: httpx.AsyncClient(
            transport=FakeTransport(),
            **{k: v for k, v in kw.items() if k != "transport"},
        ),
    ):
        from app.platform.notifications.webhook_channel import post_webhook

        with pytest.raises(httpx.HTTPStatusError):
            await post_webhook(_TEST_NOTIFICATION)


@pytest.mark.anyio
async def test_webhook_secret_not_in_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """T-1229-04: Webhook secret must not appear in any log output."""
    import httpx
    from pydantic import SecretStr

    from app.core.config import settings

    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/webhook"
    )
    monkeypatch.setattr(
        settings, "notification_webhook_secret", SecretStr(_SECRET_WEBHOOK)
    )

    class FakeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="ok")

    with patch(
        "httpx.AsyncClient",
        lambda **kw: httpx.AsyncClient(
            transport=FakeTransport(),
            **{k: v for k, v in kw.items() if k != "transport"},
        ),
    ):
        from app.platform.notifications.webhook_channel import post_webhook

        with caplog.at_level(logging.DEBUG):
            await post_webhook(_TEST_NOTIFICATION)

    for record in caplog.records:
        assert _SECRET_WEBHOOK not in record.getMessage(), (
            f"Webhook secret must not appear in log: {record.getMessage()!r}"
        )


@pytest.mark.anyio
async def test_webhook_no_secret_header_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTIF-03: When no webhook secret is configured, X-Webhook-Secret header is absent."""
    import httpx

    from app.core.config import settings

    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/webhook"
    )
    monkeypatch.setattr(settings, "notification_webhook_secret", None)

    captured: dict[str, Any] = {}

    class FakeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, text="ok")

    with patch(
        "httpx.AsyncClient",
        lambda **kw: httpx.AsyncClient(
            transport=FakeTransport(),
            **{k: v for k, v in kw.items() if k != "transport"},
        ),
    ):
        from app.platform.notifications.webhook_channel import post_webhook

        await post_webhook(_TEST_NOTIFICATION)

    assert "x-webhook-secret" not in captured["headers"], (
        "X-Webhook-Secret must not be sent when no secret is configured"
    )


# ---------------------------------------------------------------------------
# Task 3: EnvConfiguredNotificationSink
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_env_sink_disabled_when_notifications_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTIF-04: With notifications_enabled=False, no channel is called."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "notifications_enabled", False)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/w"
    )

    send_email_called = {"v": False}
    post_webhook_called = {"v": False}

    async def fake_send_email(n: Any) -> None:
        send_email_called["v"] = True

    async def fake_post_webhook(n: Any) -> None:
        post_webhook_called["v"] = True

    with (
        patch("app.platform.notifications.env_sink.send_email", fake_send_email),
        patch("app.platform.notifications.env_sink.post_webhook", fake_post_webhook),
    ):
        from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

        sink = EnvConfiguredNotificationSink()
        await sink.deliver(_TEST_NOTIFICATION)

    assert send_email_called["v"] is False, (
        "send_email must not be called when disabled"
    )
    assert post_webhook_called["v"] is False, (
        "post_webhook must not be called when disabled"
    )


@pytest.mark.anyio
async def test_env_sink_only_smtp_when_only_smtp_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTIF-04: With only smtp_host set, only SMTP channel is called."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "notifications_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "notification_webhook_url", None)

    send_email_called = {"v": False}
    post_webhook_called = {"v": False}

    async def fake_send_email(n: Any) -> None:
        send_email_called["v"] = True

    async def fake_post_webhook(n: Any) -> None:
        post_webhook_called["v"] = True

    with (
        patch("app.platform.notifications.env_sink.send_email", fake_send_email),
        patch("app.platform.notifications.env_sink.post_webhook", fake_post_webhook),
    ):
        from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

        sink = EnvConfiguredNotificationSink()
        await sink.deliver(_TEST_NOTIFICATION)

    assert send_email_called["v"] is True, (
        "send_email must be called when smtp_host is set"
    )
    assert post_webhook_called["v"] is False, (
        "post_webhook must NOT be called when webhook_url is None"
    )


@pytest.mark.anyio
async def test_env_sink_partial_success_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTIF-04: When webhook fails but SMTP succeeds, deliver() does not raise."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "notifications_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/w"
    )

    async def fake_send_email(n: Any) -> None:
        pass  # succeeds

    async def fake_post_webhook(n: Any) -> None:
        raise ConnectionError("hook unreachable")

    with (
        patch("app.platform.notifications.env_sink.send_email", fake_send_email),
        patch("app.platform.notifications.env_sink.post_webhook", fake_post_webhook),
    ):
        from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

        sink = EnvConfiguredNotificationSink()
        # Must NOT raise — partial success (SMTP delivered) is success
        await sink.deliver(_TEST_NOTIFICATION)


@pytest.mark.anyio
async def test_env_sink_all_channels_failed_raises_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTIF-04: When ALL configured channels fail, raises NotificationDeliveryError without secrets."""
    from pydantic import SecretStr

    from app.core.config import settings

    monkeypatch.setattr(settings, "notifications_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_password", SecretStr(_SECRET_PASSWORD))
    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/w"
    )
    monkeypatch.setattr(
        settings, "notification_webhook_secret", SecretStr(_SECRET_WEBHOOK)
    )

    async def failing_send_email(n: Any) -> None:
        raise ConnectionRefusedError("smtp refused")

    async def failing_post_webhook(n: Any) -> None:
        raise ConnectionRefusedError("hook unreachable")

    with (
        patch("app.platform.notifications.env_sink.send_email", failing_send_email),
        patch("app.platform.notifications.env_sink.post_webhook", failing_post_webhook),
    ):
        from app.platform.notifications.env_sink import (
            EnvConfiguredNotificationSink,
            NotificationDeliveryError,
        )

        sink = EnvConfiguredNotificationSink()
        with pytest.raises(NotificationDeliveryError) as exc_info:
            await sink.deliver(_TEST_NOTIFICATION)

    error_str = str(exc_info.value)
    assert _SECRET_PASSWORD not in error_str, (
        "SMTP password must not appear in error message"
    )
    assert _SECRET_WEBHOOK not in error_str, (
        "Webhook secret must not appear in error message"
    )


@pytest.mark.anyio
async def test_env_sink_no_channels_configured_returns_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOTIF-04: When no channel is configured, deliver() returns without raising."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "notifications_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", None)
    monkeypatch.setattr(settings, "notification_webhook_url", None)

    from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

    sink = EnvConfiguredNotificationSink()
    # Must NOT raise
    await sink.deliver(_TEST_NOTIFICATION)


@pytest.mark.anyio
async def test_env_sink_all_failed_error_message_has_no_secrets_in_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """T-1229-04: Secrets must not appear in logs during channel failures."""
    from pydantic import SecretStr

    from app.core.config import settings

    monkeypatch.setattr(settings, "notifications_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_password", SecretStr(_SECRET_PASSWORD))
    monkeypatch.setattr(
        settings, "notification_webhook_url", "https://hooks.example.com/w"
    )
    monkeypatch.setattr(
        settings, "notification_webhook_secret", SecretStr(_SECRET_WEBHOOK)
    )

    async def failing_send_email(n: Any) -> None:
        raise RuntimeError(
            f"error with password {_SECRET_PASSWORD}"
        )  # simulates a leaky error

    async def failing_post_webhook(n: Any) -> None:
        raise RuntimeError(f"error with secret {_SECRET_WEBHOOK}")

    with (
        patch("app.platform.notifications.env_sink.send_email", failing_send_email),
        patch("app.platform.notifications.env_sink.post_webhook", failing_post_webhook),
    ):
        from app.platform.notifications.env_sink import (
            EnvConfiguredNotificationSink,
            NotificationDeliveryError,
        )

        sink = EnvConfiguredNotificationSink()
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(NotificationDeliveryError):
                await sink.deliver(_TEST_NOTIFICATION)

    for record in caplog.records:
        msg = record.getMessage()
        assert _SECRET_PASSWORD not in msg, f"Password in log: {msg!r}"
        assert _SECRET_WEBHOOK not in msg, f"Webhook secret in log: {msg!r}"


@pytest.mark.anyio
async def test_env_sink_satisfies_notification_sink_protocol() -> None:
    """NOTIF-04: EnvConfiguredNotificationSink is isinstance NotificationSink."""
    from app.platform.extensions.protocols import NotificationSink
    from app.platform.notifications.env_sink import EnvConfiguredNotificationSink

    sink = EnvConfiguredNotificationSink()
    assert isinstance(sink, NotificationSink), (
        "EnvConfiguredNotificationSink must satisfy NotificationSink Protocol"
    )
