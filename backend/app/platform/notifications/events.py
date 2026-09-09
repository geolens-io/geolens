"""Per-event notification helpers for GeoLens (EVENT-05).

Three call-site helpers: ``event_enabled()`` (cheap toggle gate),
``build_event_notification()`` (consistent Notification shape), and
``emit_event_safe()`` (defensive wrapper — never raises into the caller).

``notify`` is imported at module level so tests can monkeypatch it here;
``app_settings`` is imported lazily inside each function (Phase 214) for
the same reason. ``notify()`` takes no DB/session argument by design.
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

    Reads the matching ``notify_on_*`` field (deferred import, Phase 214).
    Unknown keys return False rather than erroring, so a new event type is
    silently suppressed until wired up.
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

    Recipient is ``notification_admin_email or smtp_from_address`` (either
    may be None) in ``data["to"]``. *reason* (EVENT-03 failure path) is
    appended to *body* and placed in ``data["reason"]`` — it's the job's
    error_message surfaced to the dataset owner, not a secret (T-1230-01).
    A reason the door stored as a code becomes the sentence it stands for.
    *extra* is merged into ``data`` last for structured context (job_id,
    dataset name, etc.).
    """
    # Deferred import — Phase 214 discipline.
    from app.core.config import settings as app_settings
    from app.core.failure_reason import describe_failure_reason
    from app.platform.extensions.protocols import Notification

    recipient: str | None = getattr(
        app_settings, "notification_admin_email", None
    ) or getattr(app_settings, "smtp_from_address", None)

    # fix(#2010): mail is a reader like the web app, and a code is not a
    # sentence. Mapped here rather than at each call site, so a new event
    # that carries a reason cannot reintroduce the raw identifier.
    reason = describe_failure_reason(reason) if reason else reason

    final_body = body
    if reason:
        final_body = f"{body}\n\nReason: {reason}"

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

    Returns immediately if ``event_enabled(event_key)`` is False — no
    payload built, no I/O (EVENT-05). Otherwise calls ``build()`` then
    ``await notify(notification)`` inside one try/except that logs the
    exception type only (never payload/secrets) and swallows it, so a
    thrown *builder* — unlike ``notify()``'s own fail-safety — can never
    escape to the caller (T-1230-01/T-1230-02).
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
