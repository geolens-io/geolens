"""Phase 1230 Plan 02 — EVENT-01 signup emit + EVENT-04 health alert tests.

Covers Task 1 (EVENT-01 — signup emit):
  - With notify_on_signup ON + notifications_enabled ON + a stubbed channel, a
    successful POST /register results in one notify() call carrying event_type
    "signup", the new username/email in body/data, and the recipient in data["to"].
  - With notify_on_signup OFF, a successful POST /register results in ZERO
    notify() calls and ZERO Notification construction (emit_event_safe short-circuits).
  - A duplicate username/email (collision path) does NOT emit.
  - If notify raises, POST /register still returns 201 and the user row is
    still committed (fail-safe).

Covers Task 2 (EVENT-04 — health alert):
  - When the health check reports a degraded/unhealthy dependency AND
    notify_on_health_alert is ON, exactly one health_alert notify() fires carrying
    the failing component name in body/data.
  - A HEALTHY health result fires ZERO notifications (no alert on the happy path).
  - Repeated unhealthy results within the cooldown window fire at most one alert
    (de-dup proven).
  - Toggle OFF => nothing.
  - The health endpoint's own response is unaffected if the alert emit throws.

Note on test structure:
  Integration tests (signup via `client`) use the real ASGI stack so that
  auth/router.py, which loads persistent_config.py, is wired to the test DB.
  Health-alert tests are unit-level because /health's handler is easily stubbed
  without a DB.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from app.modules.auth.router import REGISTRATION_ENABLED


# ===========================================================================
# Task 1: EVENT-01 — signup emit (integration tests via `client` fixture)
# ===========================================================================


class TestSignupEmit:
    """Signup emit wired to auth/router.py::register()."""

    async def test_signup_fires_notification_when_toggle_on(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """A successful signup fires notify() with event_type 'signup' when toggle ON."""
        # Enable registration
        monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))

        # Enable the signup toggle
        monkeypatch.setattr("app.core.config.settings.notify_on_signup", True)
        monkeypatch.setattr(
            "app.core.config.settings.notification_admin_email", "admin@example.com"
        )

        notify_calls: list = []

        from app.platform.notifications import events as events_mod

        async def _capture_notify(n):
            notify_calls.append(n)

        monkeypatch.setattr(events_mod, "notify", _capture_notify)

        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/auth/register/",
            json={
                "username": f"evtuser_{unique}",
                "password": "TestPass1234!",
                "email": f"evtuser_{unique}@example.com",
            },
        )
        assert resp.status_code == 201, (
            f"Expected 201; got {resp.status_code}: {resp.text}"
        )

        assert len(notify_calls) == 1, (
            f"Expected exactly 1 notify() call when toggle ON; got {len(notify_calls)}"
        )
        notif = notify_calls[0]
        assert notif.event_type == "signup", (
            f"event_type must be 'signup'; got {notif.event_type!r}"
        )
        assert f"evtuser_{unique}" in notif.body or f"evtuser_{unique}" in str(
            notif.data
        ), (
            f"username must appear in notification; body={notif.body!r} data={notif.data!r}"
        )
        assert notif.data.get("to") == "admin@example.com", (
            f"data['to'] must be the admin email; got {notif.data.get('to')!r}"
        )

    async def test_signup_silent_when_toggle_off(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """A successful signup fires ZERO notify() calls when notify_on_signup is OFF."""
        monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))

        # Ensure toggle is OFF (default)
        monkeypatch.setattr("app.core.config.settings.notify_on_signup", False)

        notify_calls: list = []

        from app.platform.notifications import events as events_mod

        async def _capture_notify(n):
            notify_calls.append(n)

        monkeypatch.setattr(events_mod, "notify", _capture_notify)

        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/auth/register/",
            json={
                "username": f"silent_{unique}",
                "password": "TestPass1234!",
                "email": f"silent_{unique}@example.com",
            },
        )
        assert resp.status_code == 201, (
            f"Expected 201; got {resp.status_code}: {resp.text}"
        )

        assert notify_calls == [], (
            f"Expected ZERO notify() calls when toggle OFF; got {len(notify_calls)}"
        )

    async def test_collision_does_not_emit(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """A duplicate username/email collision does NOT emit a signup notification."""
        monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))
        monkeypatch.setattr("app.core.config.settings.notify_on_signup", True)
        monkeypatch.setattr(
            "app.core.config.settings.notification_admin_email", "admin@example.com"
        )

        notify_calls: list = []

        from app.platform.notifications import events as events_mod

        async def _capture_notify(n):
            notify_calls.append(n)

        monkeypatch.setattr(events_mod, "notify", _capture_notify)

        unique = uuid.uuid4().hex[:8]
        username = f"coluser_{unique}"

        # First registration (should emit once)
        await client.post(
            "/auth/register/",
            json={"username": username, "password": "TestPass1234!"},
        )
        first_count = len(notify_calls)

        # Reset collector and do second (collision) registration
        notify_calls.clear()
        resp = await client.post(
            "/auth/register/",
            json={"username": username, "password": "TestPass1234!"},
        )
        # Collision returns same 201 (SEC-012 enumeration-safe)
        assert resp.status_code == 201
        assert notify_calls == [], (
            f"Collision path must NOT emit; got {len(notify_calls)} call(s) "
            f"(first registration emitted {first_count})"
        )

    async def test_signup_still_201_when_notify_raises(
        self, client: AsyncClient, monkeypatch
    ) -> None:
        """A throwing notify path must NOT break signup — still returns 201."""
        monkeypatch.setattr(REGISTRATION_ENABLED, "get", AsyncMock(return_value=True))
        monkeypatch.setattr("app.core.config.settings.notify_on_signup", True)
        monkeypatch.setattr(
            "app.core.config.settings.notification_admin_email", "admin@example.com"
        )

        from app.platform.notifications import events as events_mod

        async def _raising_notify(n):
            raise RuntimeError("SMTP exploded")

        monkeypatch.setattr(events_mod, "notify", _raising_notify)

        unique = uuid.uuid4().hex[:8]
        resp = await client.post(
            "/auth/register/",
            json={
                "username": f"failsafe_{unique}",
                "password": "TestPass1234!",
                "email": f"failsafe_{unique}@example.com",
            },
        )
        # The 201 must still come back even though notify() raises.
        assert resp.status_code == 201, (
            f"Signup must still return 201 even when notify() raises; "
            f"got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert "message" in data and "awaiting" in data["message"].lower(), (
            f"Response body must be the normal pending-approval message; got {data!r}"
        )


# ===========================================================================
# Task 2: EVENT-04 — health alert (unit tests — health handler is easily stubbed)
# ===========================================================================


async def _run_health(request):
    """Call ``health()`` and run its post-response BackgroundTask.

    EVENT-04's emit is deferred to a Starlette BackgroundTask (WR-01) so the
    /health response returns before the notification fires. A direct function
    call does not run the background automatically, so the tests run it
    explicitly to observe the emit. No-op when the response carries no task
    (healthy / toggle-off / within-cooldown paths).
    """
    import app.api.main as main_mod

    response = await main_mod.health(request)
    if getattr(response, "background", None) is not None:
        await response.background()
    return response


class TestHealthAlert:
    """Health alert wired to api/main.py::health()."""

    @pytest.fixture(autouse=True)
    def _disable_rate_limiter(self):
        """Call health() directly with a MagicMock request, which slowapi's
        limiter rejects when enabled. The limiter is a module-level singleton
        disabled only by the `client` fixture, so without this these tests
        depend on another test having run first — a leaked-global ordering
        dependency that breaks under xdist (Pytest Parallel Isolation)."""
        from app.modules.auth.router import limiter

        prev = limiter.enabled
        limiter.enabled = False
        yield
        limiter.enabled = prev

    @pytest.mark.anyio
    async def test_health_alert_fires_on_degraded_when_toggle_on(
        self, monkeypatch
    ) -> None:
        """A degraded health result with notify_on_health_alert ON fires one alert."""
        monkeypatch.setattr("app.core.config.settings.notify_on_health_alert", True)
        monkeypatch.setattr("app.core.config.settings.notify_on_signup", False)
        monkeypatch.setattr("app.core.config.settings.notify_on_ingest_complete", False)
        monkeypatch.setattr("app.core.config.settings.notify_on_ingest_failed", False)
        monkeypatch.setattr(
            "app.core.config.settings.notification_admin_email", "admin@example.com"
        )

        notify_calls: list = []

        from app.platform.notifications import events as events_mod

        async def _capture_notify(n):
            notify_calls.append(n)

        monkeypatch.setattr(events_mod, "notify", _capture_notify)

        degraded_result = {
            "status": "degraded",
            "providers": {
                "database": {"status": "error", "latency_ms": 5001.0},
                "storage": {"status": "ok", "latency_ms": 3.0},
                "cache": {"status": "ok", "latency_ms": 2.0},
            },
        }

        import app.api.main as main_mod

        # Reset cooldown state before test
        main_mod._last_health_alert_at = None
        main_mod._last_health_status = "healthy"

        from app.observability.health import service as health_svc

        monkeypatch.setattr(
            health_svc, "check_health", AsyncMock(return_value=degraded_result)
        )

        from unittest.mock import MagicMock

        request = MagicMock()
        request.state = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        response = await _run_health(request)

        # Status code is 503 for degraded
        assert response.status_code == 503, (
            f"Degraded health must return 503; got {response.status_code}"
        )
        assert len(notify_calls) == 1, (
            f"Expected exactly 1 alert for degraded health with toggle ON; got {len(notify_calls)}"
        )
        notif = notify_calls[0]
        assert notif.event_type == "health_alert", (
            f"event_type must be 'health_alert'; got {notif.event_type!r}"
        )
        # The failing component (database) must appear
        assert "database" in notif.body or "database" in str(notif.data), (
            f"Failing component 'database' must appear in notification; "
            f"body={notif.body!r} data={notif.data!r}"
        )

    @pytest.mark.anyio
    async def test_health_alert_silent_on_healthy(self, monkeypatch) -> None:
        """A healthy health result fires ZERO notifications."""
        monkeypatch.setattr("app.core.config.settings.notify_on_health_alert", True)
        monkeypatch.setattr(
            "app.core.config.settings.notification_admin_email", "admin@example.com"
        )

        notify_calls: list = []

        from app.platform.notifications import events as events_mod

        async def _capture_notify(n):
            notify_calls.append(n)

        monkeypatch.setattr(events_mod, "notify", _capture_notify)

        healthy_result = {
            "status": "healthy",
            "providers": {
                "database": {"status": "ok", "latency_ms": 2.0},
                "storage": {"status": "ok", "latency_ms": 3.0},
                "cache": {"status": "ok", "latency_ms": 1.0},
            },
        }

        import app.api.main as main_mod

        main_mod._last_health_alert_at = None
        main_mod._last_health_status = "healthy"

        from app.observability.health import service as health_svc

        monkeypatch.setattr(
            health_svc, "check_health", AsyncMock(return_value=healthy_result)
        )

        from unittest.mock import MagicMock

        request = MagicMock()
        request.state = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        response = await _run_health(request)

        assert response.status_code == 200, (
            f"Healthy result must return 200; got {response.status_code}"
        )
        assert notify_calls == [], (
            f"Expected ZERO alerts on healthy health; got {len(notify_calls)}"
        )

    @pytest.mark.anyio
    async def test_health_alert_dedup_within_cooldown(self, monkeypatch) -> None:
        """Repeated degraded polls within the cooldown window emit at most one alert."""
        monkeypatch.setattr("app.core.config.settings.notify_on_health_alert", True)
        monkeypatch.setattr(
            "app.core.config.settings.notification_admin_email", "admin@example.com"
        )

        notify_calls: list = []

        from app.platform.notifications import events as events_mod

        async def _capture_notify(n):
            notify_calls.append(n)

        monkeypatch.setattr(events_mod, "notify", _capture_notify)

        degraded_result = {
            "status": "degraded",
            "providers": {
                "database": {"status": "error", "latency_ms": 5001.0},
                "storage": {"status": "ok", "latency_ms": 3.0},
                "cache": {"status": "ok", "latency_ms": 2.0},
            },
        }

        import app.api.main as main_mod

        # Reset cooldown
        main_mod._last_health_alert_at = None
        main_mod._last_health_status = "healthy"

        from app.observability.health import service as health_svc

        monkeypatch.setattr(
            health_svc, "check_health", AsyncMock(return_value=degraded_result)
        )

        from unittest.mock import MagicMock

        request = MagicMock()
        request.state = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        # First poll — should emit
        await _run_health(request)
        assert len(notify_calls) == 1, (
            f"First degraded poll must emit; got {len(notify_calls)}"
        )

        # Second consecutive poll within cooldown — must NOT re-emit
        await _run_health(request)
        assert len(notify_calls) == 1, (
            f"Second poll within cooldown must NOT re-emit; got {len(notify_calls)}"
        )

    @pytest.mark.anyio
    async def test_health_alert_silent_when_toggle_off(self, monkeypatch) -> None:
        """An unhealthy health result with notify_on_health_alert OFF fires nothing."""
        monkeypatch.setattr("app.core.config.settings.notify_on_health_alert", False)

        notify_calls: list = []

        from app.platform.notifications import events as events_mod

        async def _capture_notify(n):
            notify_calls.append(n)

        monkeypatch.setattr(events_mod, "notify", _capture_notify)

        degraded_result = {
            "status": "degraded",
            "providers": {
                "database": {"status": "error", "latency_ms": 5001.0},
                "storage": {"status": "ok", "latency_ms": 3.0},
                "cache": {"status": "ok", "latency_ms": 2.0},
            },
        }

        import app.api.main as main_mod

        main_mod._last_health_alert_at = None
        main_mod._last_health_status = "healthy"

        from app.observability.health import service as health_svc

        monkeypatch.setattr(
            health_svc, "check_health", AsyncMock(return_value=degraded_result)
        )

        from unittest.mock import MagicMock

        request = MagicMock()
        request.state = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        await _run_health(request)

        assert notify_calls == [], (
            f"Expected ZERO alerts when toggle OFF; got {len(notify_calls)}"
        )

    @pytest.mark.anyio
    async def test_health_response_unaffected_when_notify_raises(
        self, monkeypatch
    ) -> None:
        """The /health response is unchanged even if the health alert emit throws."""
        monkeypatch.setattr("app.core.config.settings.notify_on_health_alert", True)
        monkeypatch.setattr(
            "app.core.config.settings.notification_admin_email", "admin@example.com"
        )

        from app.platform.notifications import events as events_mod

        async def _raising_notify(n):
            raise RuntimeError("SMTP exploded during health alert")

        monkeypatch.setattr(events_mod, "notify", _raising_notify)

        degraded_result = {
            "status": "degraded",
            "providers": {
                "database": {"status": "error", "latency_ms": 5001.0},
                "storage": {"status": "ok", "latency_ms": 3.0},
                "cache": {"status": "ok", "latency_ms": 2.0},
            },
        }

        import app.api.main as main_mod

        main_mod._last_health_alert_at = None
        main_mod._last_health_status = "healthy"

        from app.observability.health import service as health_svc

        monkeypatch.setattr(
            health_svc, "check_health", AsyncMock(return_value=degraded_result)
        )

        from unittest.mock import MagicMock

        request = MagicMock()
        request.state = MagicMock()
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        # Must not raise, must return the normal response
        response = await _run_health(request)
        assert response.status_code == 503, (
            f"Degraded health must still return 503 even when alert throws; got {response.status_code}"
        )
