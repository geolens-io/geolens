"""Environment-driven NotificationSink that routes to configured channels (NOTIF-04).

``EnvConfiguredNotificationSink`` reads ``app_settings`` at ``deliver()``
time and dispatches to whichever channels are configured: SMTP
(``send_email``, when ``smtp_host`` is set) and webhook (``post_webhook``,
when ``notification_webhook_url`` is set). If disabled or nothing is
configured, ``deliver()`` returns silently.

Fail-safe rules (NOTIF-04/T-1229-07): each channel runs in its own
try/except so one failure can't block another; partial success (>=1
channel) counts as success; if ALL attempted channels fail, raises
``NotificationDeliveryError`` with a secret-free summary — the ``notify()``
facade's own try/except still keeps this off any request path. Error
strings carry only ``type(exc).__name__``, never a raw secret or body
(T-1229-04).

Not auto-registered: Plan 03's test-send endpoint instantiates it
directly. To include it in the default fan-out, append to
``_extensions["notification_sinks"]`` (see ``protocols.py``).
"""

from __future__ import annotations

import structlog

# Imported at module level so tests can monkeypatch send_email/post_webhook;
# settings are still read lazily (in deliver()) to avoid stale values.
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
    ``isinstance`` succeeds) without importing the Protocol at module load
    (deferred-import discipline).
    """

    async def deliver(self, notification: object) -> None:
        """Route *notification* to all configured channels.

        *notification* is typed as ``object`` so the Protocol's ``deliver``
        signature is satisfied without importing ``Notification`` at module
        load.
        """
        # Deferred import of settings (Phase 214) — not paid at module load.
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

        # All channels failed: raise a secret-free error. notify()'s own
        # try/except keeps this off any request path (NOTIF-04).
        raise NotificationDeliveryError(
            f"All {len(channels)} channel(s) failed: {', '.join(failures)}"
        )
