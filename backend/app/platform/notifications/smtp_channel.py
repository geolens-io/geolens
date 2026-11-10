"""SMTP email channel for GeoLens outbound notifications.

Sends an ``email.message.EmailMessage`` via stdlib ``smtplib``.

Connection: port 465 uses ``SMTP_SSL`` (implicit TLS); other ports with
``smtp_use_tls=True`` use ``SMTP`` + ``starttls()``; other ports with it
False use plain ``SMTP`` (dev/test only).

Credentials are revealed only at the ``login()`` call boundary via
``reveal()`` so the raw password never appears in a log line, exception,
or traceback. The blocking smtplib sequence runs inside
``asyncio.to_thread()``.

Re-raises connection/send failures — the caller
(``EnvConfiguredNotificationSink``) owns per-channel isolation. Network and
SMTP errors during QUIT are suppressed after a successful send.
"""

from __future__ import annotations


# Socket shutdown wakes blocking protocol I/O; reserve time for worker teardown.
SMTP_ABORT_CLEANUP_SECS = 5.0


class _SocketAbort:
    """Abort the underlying connection, including across an SSL socket swap."""

    def __init__(self, connection, deadline: float) -> None:
        import threading
        import time

        # A duplicate survives SSL's ownership transfer of the original fd.
        self._socket = connection.dup()
        self._lock = threading.Lock()
        self.expired = threading.Event()
        self._timer = threading.Timer(max(0, deadline - time.monotonic()), self.abort)
        self._timer.daemon = True
        self._timer.start()

    def abort(self) -> None:
        import socket

        with self._lock:
            if self._socket is None:
                return
            self.expired.set()
            try:
                self._socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                # A concurrently closed/disconnected socket is already unusable.
                pass
            self._socket.close()
            self._socket = None

    def close(self) -> None:
        self._timer.cancel()
        self._timer.join()
        with self._lock:
            if self._socket is not None:
                self._socket.close()
                self._socket = None

    def check(self) -> None:
        if self.expired.is_set():
            raise TimeoutError("Notification send deadline expired")


async def _open_deadline_socket(host: str, port: int, deadline: float):
    """Resolve/connect within the budget, before starting any SMTP worker."""
    import asyncio
    import socket
    import time

    loop = asyncio.get_running_loop()
    error = OSError("SMTP host did not resolve to a usable address")
    async with asyncio.timeout(max(0, deadline - time.monotonic())):
        addresses = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        for family, kind, protocol, _name, address in addresses:
            connection = socket.socket(family, kind, protocol)
            connection.setblocking(False)
            try:
                await loop.sock_connect(connection, address)
            except OSError as exc:
                connection.close()
                error = exc
            except BaseException:  # cleanup: cancellation must close the pending socket
                connection.close()
                raise
            else:
                connection.setblocking(True)
                return connection
    raise error


def _connected_smtp_type(base, connection, use_ssl: bool):
    """Let stdlib SMTP own the protocol while exposing its socket before greeting."""

    class ConnectedSMTP(base):
        def _get_socket(self, host, port, timeout):
            if use_ssl:
                return self.context.wrap_socket(connection, server_hostname=host)
            return connection

    return ConnectedSMTP


def _local_hostname(connection) -> str:
    import socket

    address = connection.getsockname()[0]
    if connection.family == socket.AF_INET6:
        return f"[IPv6:{address}]"
    return f"[{address}]"


def _quit_after_send(connection, message_sent: bool) -> None:
    """Preserve send success when QUIT has a network or SMTP failure."""
    import smtplib

    try:
        connection.quit()
    except (OSError, smtplib.SMTPException):
        connection.close()
        if not message_sent:
            raise


async def send_email(notification: "Notification") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Send *notification* as an email via stdlib smtplib.

    Imports are deferred so this module pays no import cost
    for deployments that never call it.

    Caller cancellation waits for the blocking send to finish before propagating.
    An opt-in notification deadline shuts down the connection at expiry,
    waking greeting, TLS and message I/O and preventing subsequent socket I/O.
    The worker and abort timer are joined before this call finishes.
    Network/SMTP QUIT failures close the connection and propagate if sending failed.

    Raises:
        smtplib.SMTPException: on SMTP-level failures.
        OSError: on connection failures (host unreachable, timeout, ...).
    """
    import asyncio
    import smtplib
    import ssl
    import time
    from email.message import EmailMessage

    from app.platform.notifications.deadline import _send_deadline
    from app.core.config import reveal
    from app.core.config import settings as app_settings
    from app.platform.extensions.protocols import Notification  # noqa: F401 (type guard)

    deadline = _send_deadline.get()
    if deadline is not None and deadline <= time.monotonic():
        raise TimeoutError("Notification send deadline expired")

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

    connection = None
    abort = None
    prepared_context = None
    if deadline is not None:
        # Preparation cannot start a send after its coroutine has timed out.
        async with asyncio.timeout(max(0, deadline - time.monotonic())):
            prepared_context = await asyncio.to_thread(ssl.create_default_context)
            connection = await _open_deadline_socket(host, port, deadline)
        abort = _SocketAbort(connection, deadline)

    def _blocking_send() -> None:
        """Run the existing SMTP protocol, with an optional connection abort."""
        try:
            if abort is not None:
                abort.check()
            use_ssl = port == 465
            ssl_context = prepared_context or ssl.create_default_context()
            factory = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
            kwargs = {"timeout": 15.0}
            if use_ssl:
                kwargs["context"] = ssl_context
            if connection is not None:
                factory = _connected_smtp_type(factory, connection, use_ssl)
                # Avoid unbounded reverse-DNS work inside the SMTP worker.
                kwargs["local_hostname"] = _local_hostname(connection)
            conn = factory(host, port, **kwargs)
            message_sent = False
            try:
                if not use_ssl and use_tls:
                    conn.starttls(context=ssl_context)
                if username:
                    conn.login(username, reveal(password) or "")
                conn.send_message(msg)
                message_sent = True
            finally:
                if abort is not None and abort.expired.is_set():
                    conn.close()
                else:
                    _quit_after_send(conn, message_sent)
        finally:
            if abort is not None:
                abort.close()
                connection.close()

    # Cancelling an executor await cannot stop its thread. Join it before
    # propagating cancellation so callers can retain ownership until it exits.
    worker = asyncio.create_task(asyncio.to_thread(_blocking_send))
    finished = asyncio.gather(worker, return_exceptions=True)
    cancelled = False
    while not finished.done():
        try:
            await asyncio.shield(finished)
        except asyncio.CancelledError:
            cancelled = True
            if abort is not None:
                abort.abort()
    if cancelled:
        raise asyncio.CancelledError
    worker.result()
