"""Outbound notification facade for GeoLens (Phase 1229 NOTIF-01 / NOTIF-04).

Mirrors ``app.platform.audit`` (``audit_emit()``) in structure:
- ``notify()`` fans out to every registered ``NotificationSink`` via
  ``get_notification_sinks()``.
- Each sink call is wrapped in a per-sink try/except so a raising or broken
  sink is logged and swallowed — never propagated to the caller.
- ``DefaultNotificationSink`` (the community no-op) is excluded from the
  attempted/delivered counts so a no-channel deployment reports
  ``attempted == 0`` (NOTIF-04 byte-identical community default).

This module is the stable seam Phase 1230 (EVENT) calls to fire
signup/lead, ingest-done/failed, and health notifications. The signature
``notify(notification)`` carries no DB/session argument — it is safe to call
fire-and-forget from any request context.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from app.platform.extensions import get_notification_sinks
from app.platform.extensions.protocols import Notification

logger = structlog.stdlib.get_logger(__name__)


@dataclass(frozen=True)
class NotificationResult:
    """Summary of a notify() fan-out call.

    ``attempted`` counts non-default sinks that were asked to deliver.
    ``delivered`` counts sinks that delivered without raising.
    ``errors`` is a list of SAFE error strings (type-name + short message only —
    never the raw notification body, SMTP password, or webhook URL/secret).
    """

    attempted: int
    delivered: int
    errors: list[str] = field(default_factory=list)


async def notify(notification: Notification) -> NotificationResult:
    """Fan out a notification to every registered sink with per-sink failure isolation.

    - Skips ``DefaultNotificationSink`` instances from the attempted/delivered
      counts so a no-channel deployment reports ``attempted == 0``.
    - Wraps every non-default sink's ``deliver()`` in try/except: on success,
      increments ``delivered``; on exception, appends a SAFE error string and
      calls ``logger.exception`` (mirrors ``audit_emit``'s failure-isolation shape).
    - NEVER re-raises. The caller's request path is always unaffected (NOTIF-04).
    """
    # Deferred import to identify the no-op default without a module-level edge
    # (Phase 214 deferred-import discipline).
    from app.platform.extensions.defaults import DefaultNotificationSink

    attempted = 0
    delivered = 0
    errors: list[str] = []

    for sink in get_notification_sinks():
        # DefaultNotificationSink is the community no-op; exclude from counts so
        # a no-channel deployment reports attempted == 0 (NOTIF-04 contract).
        if isinstance(sink, DefaultNotificationSink):
            try:
                await sink.deliver(notification)
            except Exception:  # noqa: BLE001 - no-op should never raise, but be safe
                logger.exception(
                    "DefaultNotificationSink raised unexpectedly; suppressed",
                    sink=type(sink).__name__,
                    event_type=notification.event_type,
                )
            continue

        attempted += 1
        try:
            await sink.deliver(notification)
            delivered += 1
        except Exception as exc:  # noqa: BLE001 - notification sinks must not break callers
            # Build a SAFE error string: type name + short message only.
            # NEVER interpolate notification.body, smtp_password, webhook_url,
            # or any other secret/payload value (T-1229-01 / T-1229-03).
            safe_error = f"{type(exc).__name__}: sink delivery failed"
            errors.append(safe_error)
            logger.exception(
                "Notification sink raised; suppressed per NOTIF-04",
                sink=type(sink).__name__,
                event_type=notification.event_type,
            )

    return NotificationResult(attempted=attempted, delivered=delivered, errors=errors)
