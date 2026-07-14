"""Phase 1229 Plan 03 — Admin notification status + test-send endpoint tests.

Covers:
  - NOTIF-05: GET /settings/notifications/status/ returns booleans only, no secrets.
  - NOTIF-06: POST /settings/notifications/test/ invokes configured channels, returns
              per-channel reachable/error in a 200 body (never 5xx on channel failure).
  - T-1229-08: Both endpoints require manage_settings permission (non-admin → 403).
  - T-1229-09: Neither response body contains SMTP password, webhook URL, or webhook secret.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from pydantic import SecretStr


# ---------------------------------------------------------------------------
# Helpers / constants
# ---------------------------------------------------------------------------

_SECRET_SMTP_PASSWORD = "smtp-s3cr3t-do-not-leak"
_SECRET_WEBHOOK_URL = "https://hooks.example.com/services/secret-token"
_SECRET_WEBHOOK_SECRET = "webhook-hmac-s3cr3t"

STATUS_URL = "/settings/notifications/status/"
TEST_URL = "/settings/notifications/test/"


# ---------------------------------------------------------------------------
# GET /settings/notifications/status/
# ---------------------------------------------------------------------------


class TestNotificationStatus:
    async def test_status_returns_booleans(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Status endpoint returns the three boolean fields with 200."""
        resp = await client.get(STATUS_URL, headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "notifications_enabled" in data
        assert "smtp_configured" in data
        assert "webhook_configured" in data
        assert isinstance(data["notifications_enabled"], bool)
        assert isinstance(data["smtp_configured"], bool)
        assert isinstance(data["webhook_configured"], bool)

    async def test_status_reflects_smtp_configured(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """smtp_configured=True when smtp_host is set."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        resp = await client.get(STATUS_URL, headers=admin_auth_header)
        assert resp.status_code == 200
        assert resp.json()["smtp_configured"] is True

    async def test_status_reflects_smtp_not_configured(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """smtp_configured=False when smtp_host is None."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "smtp_host", None)
        resp = await client.get(STATUS_URL, headers=admin_auth_header)
        assert resp.status_code == 200
        assert resp.json()["smtp_configured"] is False

    async def test_status_reflects_webhook_configured(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """webhook_configured=True when notification_webhook_url is set."""
        from app.core.config import settings

        monkeypatch.setattr(
            settings, "notification_webhook_url", "https://hooks.example.com/x"
        )
        resp = await client.get(STATUS_URL, headers=admin_auth_header)
        assert resp.status_code == 200
        assert resp.json()["webhook_configured"] is True

    async def test_status_requires_admin(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """Non-admin (editor) gets 403 on status endpoint."""
        resp = await client.get(STATUS_URL, headers=editor_auth_header)
        assert resp.status_code == 403

    async def test_status_unauthenticated(self, client: AsyncClient):
        """Unauthenticated request gets 401."""
        resp = await client.get(STATUS_URL)
        assert resp.status_code == 401

    async def test_status_no_slash_alias_returns_same(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """No-slash URL shape returns 200 (not 307)."""
        resp = await client.get(
            "/settings/notifications/status", headers=admin_auth_header
        )
        assert resp.status_code == 200
        assert "notifications_enabled" in resp.json()

    async def test_status_no_secret_in_response(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Response body must not contain SMTP password, webhook URL, or webhook secret."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(settings, "smtp_password", SecretStr(_SECRET_SMTP_PASSWORD))
        monkeypatch.setattr(settings, "notification_webhook_url", _SECRET_WEBHOOK_URL)
        monkeypatch.setattr(
            settings, "notification_webhook_secret", SecretStr(_SECRET_WEBHOOK_SECRET)
        )

        resp = await client.get(STATUS_URL, headers=admin_auth_header)
        assert resp.status_code == 200
        body = resp.text
        assert _SECRET_SMTP_PASSWORD not in body
        assert _SECRET_WEBHOOK_URL not in body
        assert _SECRET_WEBHOOK_SECRET not in body


# ---------------------------------------------------------------------------
# POST /settings/notifications/test/
# ---------------------------------------------------------------------------


class TestNotificationTestSend:
    async def test_no_channel_returns_sent_false(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """When no channel is configured, test-send returns sent=False and 200."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", None)
        monkeypatch.setattr(settings, "notification_webhook_url", None)

        with patch(
            "app.modules.settings.router.audit_emit", new_callable=AsyncMock
        ) as audit_emit:
            resp = await client.post(TEST_URL, headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is False
        assert data["channels"] == []
        assert "No notification channel" in data["message"]
        audit_emit.assert_not_awaited()

    async def test_notifications_disabled_returns_sent_false(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """When notifications_enabled=False, test-send returns sent=False and 200."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", False)
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")

        with patch(
            "app.modules.settings.router.audit_emit", new_callable=AsyncMock
        ) as audit_emit:
            resp = await client.post(TEST_URL, headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is False
        assert "disabled" in data["message"].lower()
        audit_emit.assert_not_awaited()

    async def test_channel_success_returns_ok_true(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """When SMTP channel succeeds, test-send returns sent=True and ok=True."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(settings, "notification_webhook_url", None)

        with (
            patch(
                "app.modules.settings.router.send_email",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.modules.settings.router.audit_emit", new_callable=AsyncMock
            ) as audit_emit,
        ):
            resp = await client.post(TEST_URL, headers=admin_auth_header)

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        assert len(data["channels"]) == 1
        assert data["channels"][0]["channel"] == "smtp"
        assert data["channels"][0]["ok"] is True
        assert data["channels"][0]["error"] is None
        event = audit_emit.await_args.args[1]
        assert event.action == "notification.test_sent"
        assert event.ip_address is not None

    async def test_channel_raises_returns_ok_false_safe_error(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """When SMTP channel raises, test-send returns 200 with ok=False and safe error string."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(settings, "smtp_password", SecretStr(_SECRET_SMTP_PASSWORD))
        monkeypatch.setattr(settings, "notification_webhook_url", None)

        with patch(
            "app.modules.settings.router.send_email",
            new=AsyncMock(side_effect=ConnectionRefusedError("Connection refused")),
        ):
            resp = await client.post(TEST_URL, headers=admin_auth_header)

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is False
        assert len(data["channels"]) == 1
        result = data["channels"][0]
        assert result["channel"] == "smtp"
        assert result["ok"] is False
        assert result["error"] is not None
        # Safe error: contains type name, not the SMTP password
        assert "ConnectionRefusedError" in result["error"]
        assert _SECRET_SMTP_PASSWORD not in result["error"]

    async def test_channel_raises_no_secret_in_response(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """Neither the response body nor logs contain smtp_password or webhook_secret."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(settings, "smtp_password", SecretStr(_SECRET_SMTP_PASSWORD))
        monkeypatch.setattr(settings, "notification_webhook_url", _SECRET_WEBHOOK_URL)
        monkeypatch.setattr(
            settings, "notification_webhook_secret", SecretStr(_SECRET_WEBHOOK_SECRET)
        )

        with (
            patch(
                "app.modules.settings.router.send_email",
                new=AsyncMock(side_effect=OSError("smtp failed")),
            ),
            patch(
                "app.modules.settings.router.post_webhook",
                new=AsyncMock(side_effect=OSError("webhook failed")),
            ),
            caplog.at_level(logging.WARNING),
        ):
            resp = await client.post(TEST_URL, headers=admin_auth_header)

        assert resp.status_code == 200
        body = resp.text
        # T-1229-09: no secrets in response body
        assert _SECRET_SMTP_PASSWORD not in body
        assert _SECRET_WEBHOOK_URL not in body
        assert _SECRET_WEBHOOK_SECRET not in body
        # T-1229-09: no secrets in captured logs
        log_text = caplog.text
        assert _SECRET_SMTP_PASSWORD not in log_text
        assert _SECRET_WEBHOOK_SECRET not in log_text

    async def test_both_channels_one_fails_one_succeeds(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Partial success (one channel ok, one fails) → sent=True, both results present."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
        monkeypatch.setattr(
            settings, "notification_webhook_url", "https://hooks.example.com/x"
        )

        with (
            patch(
                "app.modules.settings.router.send_email",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "app.modules.settings.router.post_webhook",
                new=AsyncMock(side_effect=ValueError("bad webhook")),
            ),
        ):
            resp = await client.post(TEST_URL, headers=admin_auth_header)

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        assert len(data["channels"]) == 2
        smtp_result = next(r for r in data["channels"] if r["channel"] == "smtp")
        webhook_result = next(r for r in data["channels"] if r["channel"] == "webhook")
        assert smtp_result["ok"] is True
        assert webhook_result["ok"] is False
        assert "ValueError" in webhook_result["error"]

    async def test_webhook_channel_success(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Webhook channel success path: sent=True, ok=True, error=None."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", None)
        monkeypatch.setattr(
            settings, "notification_webhook_url", "https://hooks.example.com/x"
        )

        with patch(
            "app.modules.settings.router.post_webhook",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.post(TEST_URL, headers=admin_auth_header)

        assert resp.status_code == 200
        data = resp.json()
        assert data["sent"] is True
        assert len(data["channels"]) == 1
        assert data["channels"][0]["channel"] == "webhook"
        assert data["channels"][0]["ok"] is True

    async def test_test_send_requires_admin(
        self, client: AsyncClient, editor_auth_header: dict
    ):
        """Non-admin (editor) gets 403 on test-send endpoint."""
        resp = await client.post(TEST_URL, headers=editor_auth_header)
        assert resp.status_code == 403

    async def test_test_send_unauthenticated(self, client: AsyncClient):
        """Unauthenticated request gets 401."""
        resp = await client.post(TEST_URL)
        assert resp.status_code == 401

    async def test_test_send_no_slash_alias_returns_same(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """No-slash URL shape returns 200 (not 307)."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "notifications_enabled", True)
        monkeypatch.setattr(settings, "smtp_host", None)
        monkeypatch.setattr(settings, "notification_webhook_url", None)

        resp = await client.post(
            "/settings/notifications/test", headers=admin_auth_header
        )
        assert resp.status_code == 200
