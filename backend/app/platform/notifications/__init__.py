"""Outbound notification facade for GeoLens (NOTIF-01/NOTIF-04).

Mirrors ``app.platform.audit.audit_emit()``: ``notify()`` fans out to every
registered ``NotificationSink``, isolating each sink in its own try/except
so a raising sink is logged and swallowed, never propagated. The no-op
``DefaultNotificationSink`` is excluded from the attempted/delivered counts
so a no-channel deployment reports ``attempted == 0``.

``notify(notification)`` takes no DB/session argument — safe to call
fire-and-forget from any request context.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app.platform.extensions import get_notification_sinks
from app.platform.extensions.protocols import Notification

logger = structlog.stdlib.get_logger(__name__)

__all__ = ["notify", "Notification", "NotificationResult"]


@dataclass(frozen=True)
class NotificationResult:
    """Summary of a notify() fan-out call.

    ``attempted``/``delivered`` count non-default sinks. ``errors`` holds
    SAFE strings only (type name + short message) — never the raw
    notification body, SMTP password, or webhook URL/secret.
    ``failed_channels`` names each channel that did not deliver: a channel
    of a sink that reports its channels, or else the sink's class name.
    """

    attempted: int
    delivered: int
    errors: list[str] = field(default_factory=list)
    failed_channels: frozenset[str] = frozenset()


async def notify(
    notification: Notification, *, channels: frozenset[str] | None = None
) -> NotificationResult:
    """Fan out a notification to every registered sink with per-sink failure isolation.

    Skips ``DefaultNotificationSink`` from the attempted/delivered counts.
    Wraps each non-default sink's ``deliver()`` in try/except — success
    increments ``delivered``, failure appends a SAFE error string and logs
    (mirrors ``audit_emit``). Never re-raises: the caller's request path is
    always unaffected (NOTIF-04). A sink with ``deliver_channels()`` counts
    as delivered when any of its channels delivered, as its ``deliver()``
    does. With ``channels``, only the channels named there are sent to.
    """
    # Deferred import to avoid a module-level edge to defaults (Phase 214).
    from app.platform.extensions.defaults import DefaultNotificationSink
    from app.platform.notifications.env_sink import NotificationDeliveryError

    attempted = 0
    delivered = 0
    errors: list[str] = []
    failed_channels: set[str] = set()

    for sink in get_notification_sinks():
        if isinstance(sink, DefaultNotificationSink):
            try:
                await sink.deliver(notification)
            except Exception:  # noqa: BLE001 - no-op must never raise
                logger.exception(
                    "DefaultNotificationSink raised unexpectedly; suppressed",
                    sink=type(sink).__name__,
                    event_type=notification.event_type,
                )
            continue

        per_channel = getattr(sink, "deliver_channels", None)
        name = type(sink).__name__
        if per_channel is None and channels is not None and name not in channels:
            continue
        attempted += 1
        try:
            if per_channel is None:
                await sink.deliver(notification)
            else:
                sent, failures = await per_channel(notification, channels)
                failed_channels.update(channel for channel, _error in failures)
                if failures and not sent:
                    raise NotificationDeliveryError("every channel failed")
            delivered += 1
        except Exception as exc:  # noqa: BLE001 - sinks must not break callers
            # SAFE error only: type name + short message. NEVER interpolate
            # notification.body, smtp_password, webhook_url, or any other
            # secret/payload value (T-1229-01/T-1229-03).
            safe_error = f"{type(exc).__name__}: sink delivery failed"
            errors.append(safe_error)
            if per_channel is None:
                failed_channels.add(name)
            logger.exception(
                "Notification sink raised; suppressed per NOTIF-04",
                sink=type(sink).__name__,
                event_type=notification.event_type,
            )

    return NotificationResult(
        attempted=attempted,
        delivered=delivered,
        errors=errors,
        failed_channels=frozenset(failed_channels),
    )
