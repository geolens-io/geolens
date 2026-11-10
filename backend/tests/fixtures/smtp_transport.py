"""A loopback SMTP peer with gates at actual socket I/O boundaries."""

import socketserver
import threading
import time


class SMTPTransport(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, *, greeting=False, data=False, continuation=False, fail=False):
        self.greeting = threading.Event()
        self.data = threading.Event()
        self.release_greeting = threading.Event()
        self.release_data = threading.Event()
        if not greeting:
            self.release_greeting.set()
        if not data:
            self.release_data.set()
        self.continuation = continuation
        self.fail = fail
        self.messages = []
        self.connections = 0
        super().__init__(("127.0.0.1", 0), _SMTPHandler)
        self.thread = threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.01}
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.release_greeting.set()
        self.release_data.set()
        self.shutdown()
        self.server_close()
        self.thread.join()

    def configure(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "smtp_host", self.server_address[0])
        monkeypatch.setattr(settings, "smtp_port", self.server_address[1])
        monkeypatch.setattr(settings, "smtp_use_tls", False)
        monkeypatch.setattr(settings, "smtp_username", None)
        monkeypatch.setattr(settings, "smtp_from_address", "alerts@example.com")


async def warm_up_smtp_send(monkeypatch):
    """Send one message through the deadline path to an ungated peer.

    The first send in a process and event loop pays for imports, the TLS
    context and the worker threads. On a loaded runner that alone can outlast
    a sub-second deadline before the peer sees the command a test gates on.
    """
    from app.platform.extensions.protocols import Notification
    from app.platform.notifications.deadline import notification_deadline
    from app.platform.notifications.smtp_channel import send_email

    with SMTPTransport() as peer:
        peer.configure(monkeypatch)
        with notification_deadline(time.monotonic() + 30):
            await send_email(
                Notification(event_type="health_alert", subject="warm", body="up")
            )


class _SMTPHandler(socketserver.StreamRequestHandler):
    def _gate(self, entered, release, code):
        entered.set()
        # A finite fail-safe also lets a missing-abort mutant finish for assertion.
        until = time.monotonic() + 1.5
        while not release.wait(0.01) and time.monotonic() < until:
            if self.server.continuation:
                self.wfile.write(f"{code}-still waiting\r\n".encode())

    def handle(self):
        self.connection.settimeout(2)
        self.server.connections += 1
        try:
            self._gate(self.server.greeting, self.server.release_greeting, 220)
            self.wfile.write(b"220 localhost ready\r\n")
            while line := self.rfile.readline():
                command = line.split(b" ", 1)[0].strip().upper()
                if command == b"DATA":
                    self._gate(self.server.data, self.server.release_data, 354)
                    self.wfile.write(b"354 send message\r\n")
                    body = []
                    while (line := self.rfile.readline()) not in (b".\r\n", b""):
                        body.append(line)
                    if not line:
                        return
                    self.server.messages.append(b"".join(body))
                    if self.server.fail:
                        return
                    self.wfile.write(b"250 accepted\r\n")
                elif command == b"QUIT":
                    self.wfile.write(b"221 goodbye\r\n")
                    return
                else:
                    self.wfile.write(b"250 ok\r\n")
        except OSError:
            pass  # Socket shutdown at the deadline is an expected peer disconnect.
