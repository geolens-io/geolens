"""Environment-driven NotificationSink that routes to configured channels (Phase 1229 NOTIF-04).

``EnvConfiguredNotificationSink`` reads ``app_settings`` at ``deliver()``
time and dispatches a ``Notification`` to whichever channels are
configured:

- **SMTP** (``send_email``) — when ``app_settings.smtp_host`` is set.
- **Webhook** (``post_webhook``) — when ``app_settings.notification_webhook_url`` is set.

When ``notifications_enabled`` is ``False`` or no channel is configured,
the call returns silently (zero outbound side-effects) — preserving the
byte-identical community default.

Fail-safe rules (NOTIF-04 / T-1229-07):
- Each channel is called inside its own ``try/except`` so one channel's
  failure cannot prevent the other from being attempted.
- If at least one channel succeeded, ``deliver()`` returns without raising
  (partial success = success).
- If ALL attempted channels failed, a ``NotificationDeliveryError`` is
  raised with a **secret-free** summary of which channels failed. The
  ``notify()`` facade (``__init__.py``) still wraps the entire sink call
  in its own ``try/except``, so this raise never reaches a request path.
- A safe error string contains only ``type(exc).__name__`` — never a raw
  SMTP password, webhook secret, or notification body (T-1229-04).

Registration:
- This sink is NOT auto-registered into the extension registry here.
  Plan 03's test-send endpoint instantiates it directly.  Operators who
  want it in the default fan-out can append it to
  ``_extensions["notification_sinks"]`` (setdefault + append pattern
  documented in ``protocols.py``).
"""

from __future__ import annotations

import structlog

# Import channel functions at module level so tests can monkeypatch them via
# `patch("app.platform.notifications.env_sink.send_email", ...)`.
# The settings object is still read lazily (at deliver() time) to avoid
# capturing the module-import-time values.
from app.platform.notifications.smtp_channel import send_email
from app.platform.notifications.webhook_channel import post_webhook

logger = structlog.stdlib.get_logger(__name__)


class NotificationDeliveryError(Exception):
    """Raised by EnvConfiguredNotificationSink when every attempted channel failed.

    The message contains only channel names and exception type names —
    never SMTP passwords, webhook secrets, or notification body text
    (T-1229-04 mitigation).
    """


class EnvConfiguredNotificationSink:
    """Dispatch a Notification to whichever channels are configured in app_settings.

    Structurally satisfies the ``NotificationSink`` Protocol (runtime
    ``isinstance`` check succeeds) without importing the Protocol at
    module load time (deferred-import discipline).
    """

    async def deliver(self, notification: object) -> None:
        """Route *notification* to all configured channels.

        Parameters
        ----------
        notification:
            A ``Notification`` instance (typed as ``object`` here so
            the Protocol's ``deliver`` signature is satisfied without
            a runtime import of ``Notification`` at module load).
        """
        # Deferred import of settings (Phase 214 discipline) — not paid at module load.
        # send_email / post_webhook are module-level imports (patchable in tests).
        from app.core.config import settings as app_settings

        # Master toggle: notifications_enabled=False ⇒ no channels attempted.
        if not app_settings.notifications_enabled:
            return

        # Build the list of configured channels in a deterministic order.
        channels: list[tuple[str, object]] = []
        if app_settings.smtp_host:
            channels.append(("smtp", send_email))
        if app_settings.notification_webhook_url:
            channels.append(("webhook", post_webhook))

        # Nothing configured ⇒ silent no-op.
        if not channels:
            return

        # Fan-out with per-channel isolation.
        successes: list[str] = []
        failures: list[str] = []

        for name, channel_fn in channels:
            try:
                await channel_fn(notification)  # type: ignore[call-arg]
                successes.append(name)
                logger.debug(
                    "Notification channel delivered",
                    channel=name,
                    event_type=getattr(notification, "event_type", "unknown"),
                )
            except Exception as exc:  # noqa: BLE001 — per-channel isolation
                # Safe error string: type name only — never the exception
                # message (which may echo the SMTP password or webhook URL).
                safe_msg = type(exc).__name__
                failures.append(f"{name}: {safe_msg}")
                logger.warning(
                    "Notification channel failed; continuing to next channel",
                    channel=name,
                    error_type=safe_msg,
                    event_type=getattr(notification, "event_type", "unknown"),
                )

        # Partial success (at least one channel delivered) = success.
        if successes:
            return

        # Every attempted channel failed — raise a secret-free aggregated error.
        # The notify() facade's per-sink try/except prevents this from
        # reaching any request path (NOTIF-04).
        raise NotificationDeliveryError(
            f"All {len(channels)} channel(s) failed: {', '.join(failures)}"
        )
