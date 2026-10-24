"""Total send lifetime controls using the real stdlib SMTP socket operations."""

import asyncio
import socket
import time
from unittest.mock import AsyncMock

import pytest

from app.platform.extensions.protocols import Notification
from app.platform.notifications import smtp_channel as smtp
from app.platform.notifications.deadline import _send_deadline, notification_deadline
from tests.fixtures.smtp_transport import SMTPTransport

pytestmark = pytest.mark.anyio
MESSAGE = Notification(event_type="health_alert", subject="Health", body="Degraded")


@pytest.mark.parametrize("phase", ["greeting", "data"])
async def test_deadline_aborts_continuation_replies_and_joins_the_worker(
    monkeypatch, phase
):
    import smtplib

    workers = []
    quits = []
    original = smtp._SocketAbort

    class TrackedSMTP(smtplib.SMTP):
        def quit(self):
            quits.append(True)
            return super().quit()

    class TrackedAbort(original):
        def __init__(self, *args):
            super().__init__(*args)
            workers.append(self)

    monkeypatch.setattr(smtp, "_SocketAbort", TrackedAbort)
    monkeypatch.setattr(smtplib, "SMTP", TrackedSMTP)
    with SMTPTransport(
        greeting=phase == "greeting", data=phase == "data", continuation=True
    ) as transport:
        transport.configure(monkeypatch)
        deadline = time.monotonic() + 0.25
        with notification_deadline(deadline):
            task = asyncio.create_task(smtp.send_email(MESSAGE))
        entered = transport.greeting if phase == "greeting" else transport.data
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            done, _ = await asyncio.wait({task}, timeout=0.5)
            completed_at = time.monotonic()
        finally:
            transport.release_greeting.set()
            transport.release_data.set()
            result = await asyncio.gather(task, return_exceptions=True)

        assert done, "continuation replies must not keep the SMTP worker alive"
        assert completed_at - deadline < 0.5
        assert isinstance(result[0], OSError)
        assert not transport.messages
        assert len(workers) == 1
        assert workers[0].expired.is_set()
        assert not workers[0]._timer.is_alive()
        assert workers[0]._socket is None
        assert quits == [], "an aborted connection cannot perform protocol cleanup"


async def test_a_live_send_can_succeed_near_its_deadline(monkeypatch):
    with SMTPTransport(data=True) as transport:
        transport.configure(monkeypatch)
        with notification_deadline(time.monotonic() + 1):
            task = asyncio.create_task(smtp.send_email(MESSAGE))
        try:
            assert await asyncio.to_thread(transport.data.wait, 1)
            await asyncio.sleep(0.7)
            pending = not task.done()
        finally:
            transport.release_data.set()
            result = await asyncio.gather(task, return_exceptions=True)
        assert pending
        assert result == [None]
        assert len(transport.messages) == 1


async def test_deadline_aborts_a_tls_handshake_after_socket_ownership_transfer(
    monkeypatch,
):
    from app.core.config import settings

    open_socket = smtp._open_deadline_socket
    with SMTPTransport(greeting=True) as transport:
        transport.configure(monkeypatch)
        monkeypatch.setattr(settings, "smtp_port", 465)

        async def connect_to_peer(host, port, deadline):
            return await open_socket(host, transport.server_address[1], deadline)

        monkeypatch.setattr(smtp, "_open_deadline_socket", connect_to_peer)
        with notification_deadline(time.monotonic() + 0.25):
            task = asyncio.create_task(smtp.send_email(MESSAGE))
        try:
            assert await asyncio.to_thread(transport.greeting.wait, 1)
            done, _ = await asyncio.wait({task}, timeout=0.5)
        finally:
            transport.release_greeting.set()
            result = await asyncio.gather(task, return_exceptions=True)
        assert done, "aborting the original socket must also interrupt SSL handshake"
        assert isinstance(result[0], OSError)
        assert not transport.messages


async def test_an_expired_deadline_never_connects(monkeypatch):
    preparations = []

    async def prepare(*args):
        preparations.append(True)

    monkeypatch.setattr(asyncio, "to_thread", prepare)
    with SMTPTransport() as transport:
        transport.configure(monkeypatch)
        with notification_deadline(time.monotonic() - 1):
            result = await asyncio.gather(
                smtp.send_email(MESSAGE), return_exceptions=True
            )
        assert isinstance(result[0], TimeoutError)
        assert transport.connections == 0
        assert preparations == []


async def test_abort_before_worker_start_prevents_smtp_construction(monkeypatch):
    import smtplib

    original = smtp._SocketAbort
    constructors = []

    class AlreadyAborted(original):
        def __init__(self, *args):
            super().__init__(*args)
            self.abort()

    class TrackedSMTP(smtplib.SMTP):
        def __init__(self, *args, **kwargs):
            constructors.append(True)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(smtp, "_SocketAbort", AlreadyAborted)
    monkeypatch.setattr(smtplib, "SMTP", TrackedSMTP)
    with SMTPTransport() as transport:
        transport.configure(monkeypatch)
        with notification_deadline(time.monotonic() + 1):
            result = await asyncio.gather(
                smtp.send_email(MESSAGE), return_exceptions=True
            )
        assert isinstance(result[0], TimeoutError)
        assert constructors == []
        assert not transport.messages


async def test_cancellation_aborts_and_drains_an_active_deadline_send(monkeypatch):
    with SMTPTransport(data=True) as transport:
        transport.configure(monkeypatch)
        with notification_deadline(time.monotonic() + 10):
            task = asyncio.create_task(smtp.send_email(MESSAGE))
        try:
            assert await asyncio.to_thread(transport.data.wait, 1)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=0.3)
        finally:
            transport.release_data.set()
            result = await asyncio.gather(task, return_exceptions=True)
        assert done
        assert isinstance(result[0], asyncio.CancelledError)
        assert not transport.messages


async def test_unset_deadline_preserves_the_existing_unbounded_drain(monkeypatch):
    with SMTPTransport(data=True) as transport:
        transport.configure(monkeypatch)
        task = asyncio.create_task(smtp.send_email(MESSAGE))
        try:
            assert await asyncio.to_thread(transport.data.wait, 1)
            task.cancel()
            await asyncio.sleep(0.05)
            pending = not task.done()
        finally:
            transport.release_data.set()
            result = await asyncio.gather(task, return_exceptions=True)
        assert pending
        assert isinstance(result[0], asyncio.CancelledError)
        assert len(transport.messages) == 1


def test_completed_abort_handle_cannot_shutdown_a_later_operation():
    connection, peer = socket.socketpair()
    abort = smtp._SocketAbort(connection, time.monotonic() + 0.5)
    error = None
    try:
        started = time.monotonic()
        abort.close()
        elapsed = time.monotonic() - started
        try:
            abort.abort()
            peer.sendall(b"x")
        except Exception as exc:
            error = exc
        assert error is None
        assert elapsed < 0.2, (
            "completion must disarm the timer without waiting for expiry"
        )
        assert not abort.expired.is_set()
        assert not abort._timer.is_alive()
        connection.settimeout(0.1)
        assert connection.recv(1) == b"x"
    finally:
        abort.close()
        connection.close()
        peer.close()


def test_aborting_an_already_closed_socket_is_harmless():
    connection, peer = socket.socketpair()
    abort = smtp._SocketAbort(connection, time.monotonic() + 10)
    error = None
    try:
        abort._socket.close()
        try:
            abort.abort()
        except OSError as exc:
            error = exc
        assert error is None
        assert abort.expired.is_set()
        assert abort._socket is None
    finally:
        abort.close()
        connection.close()
        peer.close()


def test_deadline_scopes_restore_after_success_and_failure():
    assert _send_deadline.get() is None
    with notification_deadline(123):
        assert _send_deadline.get() == 123
        with notification_deadline():
            assert _send_deadline.get() is None
        assert _send_deadline.get() == 123
        try:
            with notification_deadline(456):
                raise ValueError("delivery failed")
        except ValueError:
            pass
        assert _send_deadline.get() == 123
    assert _send_deadline.get() is None


async def test_pending_connect_is_closed_at_the_deadline(monkeypatch):
    loop = asyncio.get_running_loop()
    connections = []

    async def stalled_connect(connection, address):
        connections.append(connection)
        await asyncio.Event().wait()

    monkeypatch.setattr(loop, "sock_connect", stalled_connect)
    result = await asyncio.gather(
        smtp._open_deadline_socket("127.0.0.1", 25, time.monotonic() + 0.05),
        return_exceptions=True,
    )
    assert isinstance(result[0], TimeoutError)
    assert connections and all(item.fileno() == -1 for item in connections)


async def test_connect_retries_addresses_and_closes_failed_sockets(monkeypatch):
    loop = asyncio.get_running_loop()
    connections = []
    address = (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 25))
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=[address, address]))

    async def connect(connection, address):
        connections.append(connection)
        if len(connections) == 1:
            raise ConnectionError("address unavailable")

    monkeypatch.setattr(loop, "sock_connect", connect)
    results = await asyncio.gather(
        smtp._open_deadline_socket("localhost", 25, time.monotonic() + 1),
        return_exceptions=True,
    )
    result = results[0]
    try:
        assert isinstance(result, socket.socket)
        assert result is connections[1]
        assert result.getblocking()
        assert connections[0].fileno() == -1
    finally:
        for connection in connections:
            connection.close()


@pytest.mark.parametrize("addresses", [[], [False]])
async def test_no_usable_address_reports_connection_failure(monkeypatch, addresses):
    loop = asyncio.get_running_loop()
    address = (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 25))
    monkeypatch.setattr(
        loop, "getaddrinfo", AsyncMock(return_value=[address] if addresses else [])
    )
    monkeypatch.setattr(loop, "sock_connect", AsyncMock(side_effect=ConnectionError))
    result = await asyncio.gather(
        smtp._open_deadline_socket("localhost", 25, time.monotonic() + 1),
        return_exceptions=True,
    )
    assert isinstance(result[0], OSError)


def test_preconnected_ssl_preserves_context_and_server_name():
    from unittest.mock import MagicMock

    connection = object()
    context = MagicMock()

    class SSLConnection:
        def __init__(self):
            self.context = context

    factory = smtp._connected_smtp_type(SSLConnection, connection, True)
    result = factory()._get_socket("smtp.example.com", 465, 15)
    context.wrap_socket.assert_called_once_with(
        connection, server_hostname="smtp.example.com"
    )
    assert result is context.wrap_socket.return_value


@pytest.mark.parametrize(
    ("family", "address", "expected"),
    [
        (socket.AF_INET, "127.0.0.1", "[127.0.0.1]"),
        (socket.AF_INET6, "::1", "[IPv6:::1]"),
    ],
)
def test_preconnected_smtp_uses_an_address_literal_without_reverse_dns(
    family, address, expected
):
    from types import SimpleNamespace

    connection = SimpleNamespace(family=family, getsockname=lambda: (address, 25))
    assert smtp._local_hostname(connection) == expected


@pytest.mark.parametrize("message_sent", [True, False])
@pytest.mark.parametrize("quit_failure", ["os", "smtp", "unexpected"])
@pytest.mark.parametrize("deadline_set", [False, True])
async def test_quit_failure_only_fails_before_a_completed_send(
    monkeypatch, message_sent, quit_failure, deadline_set
):
    import smtplib

    error_type = {
        "os": OSError,
        "smtp": smtplib.SMTPException,
        "unexpected": RuntimeError,
    }[quit_failure]
    error = error_type("QUIT failed")
    connections = []
    closed = []
    quits = []

    class QuitFailureSMTP(smtplib.SMTP):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            connections.append(self)

        def quit(self):
            quits.append(True)
            raise error

        def close(self):
            closed.append(True)
            super().close()

    monkeypatch.setattr(smtplib, "SMTP", QuitFailureSMTP)
    with SMTPTransport(data=True, fail=not message_sent) as transport:
        transport.configure(monkeypatch)
        deadline = time.monotonic() + 2 if deadline_set else None
        with notification_deadline(deadline):
            task = asyncio.create_task(smtp.send_email(MESSAGE))
        try:
            assert await asyncio.to_thread(transport.data.wait, 1)
        finally:
            transport.release_data.set()
            result = await asyncio.gather(task, return_exceptions=True)
            closed_before_cleanup = bool(closed)
            for connection in connections:
                connection.close()

        assert quits == [True]
        assert len(transport.messages) == 1
        if message_sent and quit_failure != "unexpected":
            assert result == [None]
            assert closed_before_cleanup
        else:
            assert result[0] is error
