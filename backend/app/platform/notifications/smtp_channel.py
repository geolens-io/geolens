"""SMTP email channel for GeoLens outbound notifications (Phase 1229 NOTIF-02).

Sends an ``email.message.EmailMessage`` via stdlib ``smtplib``.

Connection strategy:
- Port 465 → ``smtplib.SMTP_SSL`` (implicit TLS).
- Other ports + ``smtp_use_tls=True`` → ``smtplib.SMTP`` + ``starttls()`` (explicit TLS / STARTTLS).
- Other ports + ``smtp_use_tls=False`` → ``smtplib.SMTP`` plain (dev/test only).

Credentials are read from ``app_settings`` and revealed **only** at the
``login()`` call boundary via ``reveal()`` so the raw password never
appears in any log line, exception message, or traceback
(T-1229-04 mitigated).

The blocking smtplib sequence runs inside ``asyncio.to_thread()`` so it
does not block the async event loop (T-1229-05 partial mitigation).

On any smtplib exception the function re-raises — the caller
(``EnvConfiguredNotificationSink``) is responsible for per-channel
isolation (T-1229-07).
"""

from __future__ import annotations


async def send_email(notification: "Notification") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Send *notification* as an email via stdlib smtplib.

    Imports are deferred (Phase 214 deferred-import discipline) so this
    module does not pay import cost for deployments that never call it.

    Raises:
        smtplib.SMTPException: on SMTP-level failures (auth, server error, …).
        OSError: on connection failures (host unreachable, timeout, …).
    """
    import asyncio
    import smtplib
    from email.message import EmailMessage

    from app.core.config import reveal
    from app.core.config import settings as app_settings
    from app.platform.extensions.protocols import Notification  # noqa: F401 (type guard)

    host = app_settings.smtp_host  # already str | None; caller verified it is set
    port = app_settings.smtp_port
    username = app_settings.smtp_username
    password = app_settings.smtp_password  # SecretStr | None — never log
    from_address = app_settings.smtp_from_address or username or ""
    use_tls = app_settings.smtp_use_tls

    msg = EmailMessage()
    msg["From"] = from_address
    # Phase 1229 baseline: send to the operator's own from-address (self-send).
    # Phase 1230 will supply per-event recipients via Notification.data["to"]
    # or a dedicated field; for now the channel accepts the from-address as
    # the default recipient so the admin test-send (Plan 03) works without
    # a recipient seam.
    to_address = (
        notification.data.get("to") if notification.data else None
    ) or from_address
    msg["To"] = to_address
    msg["Subject"] = notification.subject
    msg.set_content(notification.body)

    def _blocking_send() -> None:
        """Blocking smtplib sequence — runs in a thread via asyncio.to_thread."""
        use_ssl = port == 465

        if use_ssl:
            conn: smtplib.SMTP = smtplib.SMTP_SSL(host, port)
        else:
            conn = smtplib.SMTP(host, port)

        try:
            if not use_ssl and use_tls:
                conn.starttls()
            if username:
                # Reveal the password ONLY at the login() boundary.
                # The raw string is never stored in a local variable or logged.
                conn.login(username, reveal(password) or "")
            conn.send_message(msg)
        finally:
            conn.quit()

    await asyncio.to_thread(_blocking_send)
