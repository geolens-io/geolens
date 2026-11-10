# SPDX-License-Identifier: Apache-2.0
"""Browser sign-in to an ArcGIS portal with OAuth 2.0.

Hand-maintained. Authorization code with PKCE (S256) for a public client whose
client ID the organization registered itself. The portal's own login page
signs the user in, so accounts that use SAML or OpenID Connect, which can't
use ``generateToken``, can sign in here. The browser returns to a one-shot
listener on 127.0.0.1, and the code is exchanged at the portal's token
endpoint through the run's ``PortalClient``.

The access token stays in memory. The refresh token is stored in the OS
keyring (credentials.toml, mode 0600, when there is no keyring) under the
portal and client ID, renews the access token during the run, and signs the
next run in without the browser. Codes, verifiers and tokens are never
printed or logged and are redacted from every error.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import socket
import socketserver
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from . import auth as _auth
from .arcgis_portal import PortalClient, PortalError, Redactor

CALLBACK_PATH = "/callback"
SIGN_IN_TIMEOUT = 300.0
# The token endpoint's default when an answer omits expires_in.
DEFAULT_LIFETIME = 1800
# The longest one connection may take, however slowly it sends.
_REQUEST_TIMEOUT = 10.0
_POLL = 0.5
_ERROR_TEXT_LIMIT = 300

_DONE_PAGE = (
    b"<!doctype html><meta charset=utf-8><title>GeoLens</title>"
    b"<p>Signed in to ArcGIS. You can close this tab and return to the terminal.</p>"
)
_REFUSED_PAGE = (
    b"<!doctype html><meta charset=utf-8><title>GeoLens</title>"
    b"<p>The sign-in was not completed. Return to the terminal for details.</p>"
)


def pkce_pair() -> tuple[str, str]:
    """A fresh (code_verifier, S256 code_challenge) pair, RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _account(root: str, client_id: str) -> str:
    return f"arcgis-oauth:{client_id}@{root}"


def _notify(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def sign_in(
    client: PortalClient,
    client_id: str,
    redact: Redactor,
    *,
    redirect_port: int | None = None,
    open_browser: Callable[[str], Any] | None = None,
    notify: Callable[[str], None] = _notify,
) -> None:
    """Give *client* an access token for *client_id* that renews itself.

    A stored refresh token is tried first; when the portal refuses it, it is
    forgotten and the browser signs in again. ``PortalError`` of kind
    ``auth`` when the sign-in fails, ``usage`` when the listener can't start.
    """
    account = _account(client.root, client_id)
    saved = _auth.load_secrets(account)
    for backend, stored in saved:
        redact.add(stored)
        session = _Session(client, client_id, account, redact, stored, notify)
        try:
            session.refresh()
            return
        except PortalError as exc:
            if exc.kind != "auth":
                raise
        _auth.delete_secret(account, backend)
    if saved:
        notify("The saved ArcGIS sign-in was refused; signing in through the browser.")
    verifier, challenge = pkce_pair()
    redact.add(verifier)
    code, redirect_uri = _authorize(
        client.root,
        client_id,
        challenge,
        redact,
        redirect_port,
        open_browser or webbrowser.open,
        notify,
    )
    data = client.oauth_token(
        {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        }
    )
    session = _Session(client, client_id, account, redact, None, notify)
    session.adopt(data)


class _Session:
    """The refresh token behind a client's access token."""

    def __init__(
        self,
        client: PortalClient,
        client_id: str,
        account: str,
        redact: Redactor,
        refresh_token: str | None,
        notify: Callable[[str], None],
    ) -> None:
        self._client = client
        self._client_id = client_id
        self._account = account
        self._redact = redact
        self._refresh_token = refresh_token
        self._notify = notify

    def refresh(self) -> None:
        self.adopt(
            self._client.oauth_token(
                {
                    "client_id": self._client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token or "",
                }
            )
        )

    def adopt(self, data: Mapping[str, Any]) -> None:
        refresh = data.get("refresh_token")
        if isinstance(refresh, str) and refresh:
            self._redact.add(refresh)
        lifetime = data.get("expires_in")
        if not isinstance(lifetime, int) or isinstance(lifetime, bool) or lifetime <= 0:
            lifetime = DEFAULT_LIFETIME
        if isinstance(refresh, str) and refresh and refresh != self._refresh_token:
            self._refresh_token = refresh
            self._save(refresh)
        renew = self.refresh if self._refresh_token else None
        self._client.use_token(data.get("access_token"), lifetime, renew)

    def _save(self, refresh: str) -> None:
        try:
            _auth.store_secret(self._account, refresh)
        except (_auth.CredentialsFileCorrupt, OSError):
            self._notify(
                "Warning: the ArcGIS sign-in could not be saved, so the next "
                "run signs in through the browser again."
            )


def forget(root: str, client_id: str) -> tuple[list[str], list[str]]:
    """Delete the saved sign-in for *client_id* at the portal *root*; returns
    (backends it was removed from, backends still holding it)."""
    account = _account(root, client_id)
    before = [backend for backend, _ in _auth.load_secrets(account)]
    _auth.delete_secret(account)
    after = [backend for backend, _ in _auth.load_secrets(account)]
    return [b for b in before if b not in after], after


class _Listener(socketserver.TCPServer):
    allow_reuse_address = False

    def __init__(self, port: int, state: str) -> None:
        super().__init__(("127.0.0.1", port), _Callback)
        self.state = state
        self.outcome: tuple[str | None, str | None] | None = None
        self.deadline = float("inf")
        self.cut = threading.Event()

    def finish_request(self, request: Any, client_address: Any) -> None:
        # The handler's socket timeout bounds each read, not the whole request,
        # so a client sending a byte at a time is cut off at a fixed time.
        limit = min(self.deadline - time.monotonic(), _REQUEST_TIMEOUT)
        self.cut = threading.Event()
        timer = threading.Timer(max(limit, 0.0), _cut_off, (request, self.cut))
        timer.daemon = True
        timer.start()
        try:
            super().finish_request(request, client_address)
        finally:
            timer.cancel()

    def handle_error(self, request: Any, client_address: Any) -> None:
        return


def _cut_off(request: socket.socket, cut: threading.Event) -> None:
    cut.set()
    try:
        request.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


class _Callback(BaseHTTPRequestHandler):
    timeout = _REQUEST_TIMEOUT
    server: _Listener

    def do_GET(self) -> None:
        if self.server.cut.is_set():
            return
        parts = urlsplit(self.path)
        if parts.path != CALLBACK_PATH or self.server.outcome is not None:
            self.send_error(404)
            return
        self.server.outcome = _read_callback(parse_qs(parts.query), self.server.state)
        code, _problem = self.server.outcome
        page = _DONE_PAGE if code else _REFUSED_PAGE
        self.send_response(200 if code else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, format: str, *args: Any) -> None:
        # The request line carries the authorization code.
        return


def _read_callback(
    params: Mapping[str, list[str]], state: str
) -> tuple[str | None, str | None]:
    """(code, None) for a valid callback, else (None, why it was refused)."""

    def one(name: str) -> str | None:
        values = params.get(name)
        return values[0] if values and len(values) == 1 else None

    got = one("state")
    if got is None or not secrets.compare_digest(got.encode(), state.encode()):
        return None, (
            "the sign-in callback did not carry this sign-in's state, so it "
            "was refused; run the command again"
        )
    if "error" in params:
        error = one("error") or "error"
        description = one("error_description") or ""
        text = f"{error}: {description}" if description else error
        text = "".join(c if c.isprintable() else " " for c in text)
        return None, f"the portal refused the sign-in ({text[:_ERROR_TEXT_LIMIT]})"
    code = one("code")
    if not code:
        return None, "the sign-in callback carried no authorization code"
    return code, None


def _authorize(
    root: str,
    client_id: str,
    challenge: str,
    redact: Redactor,
    redirect_port: int | None,
    open_browser: Callable[[str], Any],
    notify: Callable[[str], None],
) -> tuple[str, str]:
    """Run the browser leg and return (code, redirect_uri)."""
    state = secrets.token_urlsafe(32)
    try:
        listener = _Listener(redirect_port or 0, state)
    except OSError as exc:
        raise PortalError(
            f"can't listen on 127.0.0.1 port {redirect_port or 0} for the "
            f"sign-in ({exc.strerror or exc}); pass a free --redirect-port",
            kind="usage",
        ) from None
    with listener:
        port = listener.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
        url = f"{root}/sharing/rest/oauth2/authorize?" + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        notify(f"Sign in to ArcGIS in your browser. If it doesn't open, visit:\n{url}")
        listener.deadline = time.monotonic() + SIGN_IN_TIMEOUT
        # A browser command run in the foreground returns only when it exits.
        threading.Thread(
            target=_open_quietly, args=(open_browser, url), daemon=True
        ).start()
        code, problem = _wait(listener, SIGN_IN_TIMEOUT)
    if code is None:
        raise PortalError(redact(problem or "the sign-in did not finish"), kind="auth")
    redact.add(code)
    return code, redirect_uri


def _open_quietly(open_browser: Callable[[str], Any], url: str) -> None:
    try:
        open_browser(url)
    except Exception:  # broad: a missing browser leaves the printed URL
        pass


def _wait(listener: _Listener, timeout: float) -> tuple[str | None, str | None]:
    while listener.outcome is None:
        remaining = listener.deadline - time.monotonic()
        if remaining <= 0:
            return None, (
                f"no sign-in arrived within {timeout:g} seconds; run the command again"
            )
        listener.timeout = min(remaining, _POLL)
        listener.handle_request()
    return listener.outcome
