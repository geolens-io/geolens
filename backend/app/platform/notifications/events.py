"""Per-event notification helpers for GeoLens (Phase 1230 EVENT-05).

Three thin functions that Wave-2 call sites use:

- ``event_enabled(event_key)`` — cheap toggle gate before any payload is built.
  Returns the matching ``notify_on_*`` Settings bool or False for unknown keys.

- ``build_event_notification(event_type, ...)`` — constructs a ``Notification``
  with a consistent shape: recipient in ``data["to"]``, optional failure reason
  in ``body`` and ``data["reason"]``, and any extra structured metadata merged
  into ``data``.

- ``emit_event_safe(*, event_key, build)`` — defensive async call-site wrapper.
  Short-circuits immediately when the toggle is OFF (no payload built, no I/O).
  Wraps ``build()`` and ``await notify(...)`` in a try/except that logs at
  WARNING (exception type name only — never the payload or any secret) and
  swallows everything, so a notification error can NEVER break or wedge the
  originating request/task (T-1230-02 mitigation).

Design notes:
- ``app_settings`` is imported lazily inside each function (Phase 214 deferred-
  import discipline) so tests can monkeypatch ``app.core.config.settings``.
- ``notify`` is imported at module level so tests can monkeypatch the reference
  on this module (``app.platform.notifications.events.notify``).
- No DB/session argument is accepted — ``notify()`` is session-free by 1229 design.
- Recipient resolution rule: ``notification_admin_email or smtp_from_address``.
  Both may be None in a no-channel deployment; the Notification is still built
  (data["to"] = None) and will be swallowed by the sink's master-toggle check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.platform.notifications import notify

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.platform.extensions.protocols import Notification

logger = structlog.stdlib.get_logger(__name__)

__all__ = ["build_event_notification", "emit_event_safe", "event_enabled"]

# Mapping from event_key -> Settings attribute name.
_EVENT_KEY_TO_TOGGLE: dict[str, str] = {
    "signup": "notify_on_signup",
    "ingest_complete": "notify_on_ingest_complete",
    "ingest_failed": "notify_on_ingest_failed",
    "health_alert": "notify_on_health_alert",
}


def event_enabled(event_key: str) -> bool:
    """Return True if the per-event toggle for *event_key* is enabled in settings.

    Reads the matching ``notify_on_*`` field from ``app_settings`` (deferred
    import — Phase 214 discipline). Returns False for unknown event keys so new
    event types are silently suppressed rather than erroring at an unknown key.

    Args:
        event_key: One of "signup", "ingest_complete", "ingest_failed",
            "health_alert". Any other value returns False.

    Returns:
        True if the toggle is set; False otherwise.
    """
    # Deferred import so tests can monkeypatch app.core.config.settings.
    from app.core.config import settings as app_settings

    toggle_attr = _EVENT_KEY_TO_TOGGLE.get(event_key)
    if toggle_attr is None:
        return False
    return bool(getattr(app_settings, toggle_attr, False))


def build_event_notification(
    event_type: str,
    *,
    subject: str,
    body: str,
    reason: str | None = None,
    extra: dict[str, object] | None = None,
) -> "Notification":
    """Build a ``Notification`` with a consistent shape for event call sites.

    Recipient is resolved as ``notification_admin_email or smtp_from_address``
    and placed in ``data["to"]``. Both may be None in a no-channel deployment.

    When *reason* is given (EVENT-03 failure path), it is appended to *body*
    and placed in ``data["reason"]``. The reason text is the job error_message
    surfaced to the dataset owner — it is NOT a secret value (T-1230-01).

    *extra* (optional dict) is merged into ``data`` after ``to`` and ``reason``
    so call sites can attach structured context (job_id, dataset name, etc.)
    without secrets.

    Args:
        event_type: Short identifier for the event (e.g., "signup", "ingest_failed").
        subject:    Human-readable subject line (used as SMTP subject / webhook title).
        body:       Human-readable body text.
        reason:     Optional failure reason string (EVENT-03). Appended to body
                    and included in data["reason"].
        extra:      Optional dict of extra structured metadata merged into data.

    Returns:
        A frozen ``Notification`` dataclass instance.
    """
    # Deferred import — Phase 214 discipline.
    from app.core.config import settings as app_settings
    from app.platform.extensions.protocols import Notification

    # Recipient resolution: notification_admin_email -> smtp_from_address -> None.
    recipient: str | None = getattr(
        app_settings, "notification_admin_email", None
    ) or getattr(app_settings, "smtp_from_address", None)

    # Build the body, optionally appending the failure reason.
    final_body = body
    if reason:
        final_body = f"{body}\n\nReason: {reason}"

    # Build data dict: start with recipient, then add reason, then merge extra.
    data: dict[str, object] = {"to": recipient}
    if reason:
        data["reason"] = reason
    if extra:
        data.update(extra)

    return Notification(
        event_type=event_type,
        subject=subject,
        body=final_body,
        data=data,
    )


async def emit_event_safe(
    *,
    event_key: str,
    build: "Callable[[], Notification]",
) -> None:
    """Defensive async wrapper for firing a single event notification.

    Step 1 — toggle gate: if ``event_enabled(event_key)`` is False, return
    immediately. No payload is built; no I/O is performed (EVENT-05 "keep emit
    cheap when disabled" constraint).

    Step 2 — guarded delivery: call ``build()`` to construct the ``Notification``,
    then ``await notify(notification)``. Both calls are inside a single try/except
    that:
    - Logs at WARNING level using the exception type name only (never the payload
      or any secret value — T-1230-01 / T-1230-02 mitigation).
    - Swallows the exception so the originating request/task path is never broken.

    This is belt-and-suspenders over ``notify()``'s own fail-safety (NOTIF-04):
    ``notify()`` never re-raises sink errors, but a thrown *builder* would escape
    without this wrapper.

    Args:
        event_key:  Event key for the toggle check (e.g. "signup").
        build:      Zero-argument callable returning a ``Notification`` instance.
                    Called ONLY when the toggle is on; otherwise never invoked.
    """
    if not event_enabled(event_key):
        return

    try:
        notification = build()
        await notify(notification)
    except Exception as exc:  # noqa: BLE001 — notification must never break callers
        # Log only the exception type — never the notification body or any secret.
        logger.warning(
            "emit_event_safe: notification failed; suppressed",
            event_key=event_key,
            error_type=type(exc).__name__,
        )
