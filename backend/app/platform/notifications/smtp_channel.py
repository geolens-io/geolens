"""SMTP email channel for GeoLens outbound notifications (NOTIF-02).

Sends an ``email.message.EmailMessage`` via stdlib ``smtplib``.

Connection: port 465 uses ``SMTP_SSL`` (implicit TLS); other ports with
``smtp_use_tls=True`` use ``SMTP`` + ``starttls()``; other ports with it
False use plain ``SMTP`` (dev/test only).

Credentials are revealed only at the ``login()`` call boundary via
``reveal()`` so the raw password never appears in a log line, exception,
or traceback (T-1229-04). The blocking smtplib sequence runs inside
``asyncio.to_thread()``.

Re-raises on any smtplib exception — the caller
(``EnvConfiguredNotificationSink``) owns per-channel isolation (T-1229-07).
"""

from __future__ import annotations


async def send_email(notification: "Notification") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Send *notification* as an email via stdlib smtplib.

    Imports are deferred (Phase 214) so this module pays no import cost
    for deployments that never call it.

    Raises:
        smtplib.SMTPException: on SMTP-level failures.
        OSError: on connection failures (host unreachable, timeout, ...).
    """
    import asyncio
    import smtplib
    import ssl
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
    # Self-send fallback: without a per-event recipient in
    # Notification.data["to"], mail goes to the from-address (admin test-send).
    to_address = (
        notification.data.get("to") if notification.data else None
    ) or from_address
    msg["To"] = to_address
    msg["Subject"] = notification.subject
    msg.set_content(notification.body)

    def _blocking_send() -> None:
        """Blocking smtplib sequence — runs in a thread via asyncio.to_thread."""
        use_ssl = port == 465
        # WR-01: verify the server cert against the system trust store —
        # smtplib's default omits a context, exposing the password to a MITM.
        ssl_context = ssl.create_default_context()
        # WR-02: bound connect/socket time so an unreachable host can't pin a thread.
        timeout = 15.0

        if use_ssl:
            conn: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=timeout, context=ssl_context
            )
        else:
            conn = smtplib.SMTP(host, port, timeout=timeout)

        try:
            if not use_ssl and use_tls:
                conn.starttls(context=ssl_context)
            if username:
                # Reveal the password only at the login() boundary; never stored/logged.
                conn.login(username, reveal(password) or "")
            conn.send_message(msg)
        finally:
            conn.quit()

    await asyncio.to_thread(_blocking_send)
