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
portal and client ID, with the span it is valid for. It renews the access
token during the run and signs the next run in without the browser; once it
is past half of its life, a run exchanges it for a new one, so a sign-in used
within its lifetime does not lapse. Codes, verifiers and tokens are never
printed or logged and are redacted from every error.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import socketserver
import sys
import threading
import time
import webbrowser
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from . import auth as _auth
from . import config as _config
from .arcgis_portal import PortalClient, PortalError, Redactor

if os.name == "nt":
    import msvcrt
else:
    import fcntl

CALLBACK_PATH = "/callback"
SIGN_IN_TIMEOUT = 300.0
# The token endpoint's default when an answer omits expires_in.
_DEFAULT_LIFETIME = 1800
# The longest one connection may take, however slowly it sends.
_REQUEST_TIMEOUT = 10.0
_POLL = 0.5
_ERROR_TEXT_LIMIT = 300
# Long enough for a holder's exchange, fallback refresh and save to finish.
_LOCK_WAIT = 60.0
_LOCK_POLL = 0.1
_now = time.time
_UNSAVED = (
    "Warning: the ArcGIS sign-in could not be saved, and any sign-in saved "
    "earlier no longer works. This run continues; the next run signs in "
    "through the browser."
)


def _page(message: str) -> bytes:
    return (
        f"<!doctype html><meta charset=utf-8><title>GeoLens</title><p>{message}</p>"
    ).encode()


_DONE_PAGE = _page(
    "Signed in to ArcGIS. You can close this tab and return to the terminal."
)
_REFUSED_PAGE = _page(
    "The sign-in was not completed. Return to the terminal for details."
)


def pkce_pair() -> tuple[str, str]:
    """A fresh (code_verifier, S256 code_challenge) pair, RFC 7636."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _account(root: str, client_id: str) -> str:
    return f"arcgis-oauth:{client_id}@{root}"


def _redirect_uri(port: int) -> str:
    return f"http://127.0.0.1:{port}{CALLBACK_PATH}"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _notify(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _seconds(value: Any) -> float | None:
    # bool is an int subclass; True is no number of seconds.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


@dataclass(frozen=True)
class _Saved:
    """A stored refresh token, the wall-clock span it is valid for and the
    redirect URI its sign-in used, each when known."""

    token: str = field(repr=False)
    issued_at: float | None = None
    expires_at: float | None = None
    redirect_uri: str | None = None

    @classmethod
    def parse(cls, value: str) -> _Saved:
        """Read a stored value; a bare token, as saved before the rest was
        recorded, has none of it."""
        try:
            data = json.loads(value)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return cls(value)
        token = data.get("refresh_token")
        if not isinstance(token, str) or not token:
            return cls(value)
        redirect_uri = data.get("redirect_uri")
        return cls(
            token,
            _seconds(data.get("issued_at")),
            _seconds(data.get("expires_at")),
            redirect_uri if isinstance(redirect_uri, str) and redirect_uri else None,
        )

    def dump(self) -> str:
        return json.dumps(
            {
                "refresh_token": self.token,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "redirect_uri": self.redirect_uri,
            }
        )

    def due(self, now: float) -> bool:
        """Past half of its life, or of a life that isn't known."""
        if self.issued_at is None or self.expires_at is None:
            return True
        return now >= (self.issued_at + self.expires_at) / 2


def _load(account: str) -> list[tuple[str, _Saved]]:
    return [(b, _Saved.parse(v)) for b, v in _auth.load_secrets(account)]


def _try_lock(fd: int) -> bool | None:
    """True when locked, False when another process holds it, None when the
    file system can't lock."""
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    except OSError:
        return None
    return True


def _unlock(fd: int) -> None:
    if os.name == "nt":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def _exchange_lock(account: str) -> Iterator[bool]:
    """Hold *account*'s sign-in lock across processes; yields False when it
    can't be had within ``_LOCK_WAIT`` seconds.

    The operating system releases the lock when its holder exits, so a
    process that crashed holding it does not block later runs.
    """
    name = hashlib.sha256(account.encode()).hexdigest()[:16]
    path = _config.credentials_path().parent / f"arcgis-oauth-{name}.lock"
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        yield False
        return
    try:
        deadline = time.monotonic() + _LOCK_WAIT
        locked = _try_lock(fd)
        while locked is False and time.monotonic() < deadline:
            time.sleep(_LOCK_POLL)
            locked = _try_lock(fd)
        if not locked:
            yield False
            return
        try:
            yield True
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


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

    A stored refresh token is tried first, exchanged for a new one when it is
    past half of its life; when the portal refuses it, it is forgotten and the
    browser signs in again. ``PortalError`` of kind ``auth`` when the sign-in
    fails, ``usage`` when the listener can't start.
    """
    account = _account(client.root, client_id)
    session = _Session(client, client_id, account, redact, notify, redirect_port)
    # Read under the lock: a run that waited for another's exchange sees the
    # token that exchange saved, not the one it invalidated.
    with _exchange_lock(account) as locked:
        saved = _load(account)
        for backend, stored in saved:
            redact.add(stored.token)
            try:
                session.resume(stored, exchange=locked)
                return
            except PortalError as exc:
                if exc.kind != "auth":
                    raise
            # Without the lock, another run may be saving its new token here.
            if locked:
                session.forget_if_unchanged(backend, stored.token)
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
    session.refresh_token = ""
    session.redirect_uri = redirect_uri
    session.adopt(data)


class _Session:
    """The refresh token behind a client's access token."""

    def __init__(
        self,
        client: PortalClient,
        client_id: str,
        account: str,
        redact: Redactor,
        notify: Callable[[str], None],
        redirect_port: int | None,
    ) -> None:
        self._client = client
        self._client_id = client_id
        self._account = account
        self._redact = redact
        self._notify = notify
        self._redirect_port = redirect_port
        self.redirect_uri: str | None = None
        self.refresh_token = ""
        self._username: str | None = None

    def resume(self, stored: _Saved, *, exchange: bool) -> None:
        """Sign in with *stored*, and exchange it for a new one when
        *exchange* is allowed and it is due.

        The refresh grant runs first, so a token the portal refuses is never
        written back, and the exchange, which invalidates the token, runs only
        once the store has taken a write. A failed exchange keeps the refresh
        grant's answer.
        """
        self.refresh_token = stored.token
        self.redirect_uri = stored.redirect_uri
        data = self._refresh_grant()
        if exchange and stored.due(_now()) and self._store_takes(stored):
            data = self._exchange() or data
        self.adopt(data)

    def _refresh_grant(self, token: str | None = None) -> Mapping[str, Any]:
        return self._client.oauth_token(
            {
                "client_id": self._client_id,
                "grant_type": "refresh_token",
                "refresh_token": token or self.refresh_token,
            }
        )

    def _exchange(self) -> Mapping[str, Any] | None:
        try:
            redirect_uri = self.redirect_uri or _redirect_uri(
                self._redirect_port or _free_port()
            )
            data = self._client.oauth_token(
                {
                    "client_id": self._client_id,
                    "grant_type": "exchange_refresh_token",
                    "refresh_token": self.refresh_token,
                    "redirect_uri": redirect_uri,
                }
            )
        except (PortalError, OSError):
            return None
        self.redirect_uri = redirect_uri
        return data

    def _store_takes(self, stored: _Saved) -> bool:
        """Write *stored* back as it is; True when the store took it."""
        try:
            _auth.store_secret(self._account, stored.dump())
        except (_auth.CredentialsFileCorrupt, OSError):
            return False
        return True

    def refresh(self) -> None:
        self.adopt(self._refresh_grant())

    def _renew(self) -> None:
        """Refresh during the run."""
        try:
            self.refresh()
        except PortalError as exc:
            if exc.kind != "auth":
                raise
            self._follow_stored(exc)

    def _follow_stored(self, refused: PortalError) -> None:
        """Continue with a token another run stored after exchanging this
        one, waiting for its save; re-raise *refused* when none works."""
        tried = {self.refresh_token}
        with _exchange_lock(self._account):
            for _, stored in _load(self._account):
                if stored.token in tried:
                    continue
                tried.add(stored.token)
                self._redact.add(stored.token)
                try:
                    data = self._refresh_grant(stored.token)
                except PortalError as exc:
                    if exc.kind != "auth":
                        raise
                    continue
                # The store is keyed by portal and client ID, so it can hold a
                # sign-in another user has made since.
                if data.get("username") != self._username:
                    continue
                self.refresh_token = stored.token
                self.redirect_uri = stored.redirect_uri
                self.adopt(data)
                return
        raise refused

    def adopt(self, data: Mapping[str, Any]) -> None:
        if self._username is None:
            self._username = data.get("username")
        refresh = data.get("refresh_token")
        if isinstance(refresh, str) and refresh:
            self._redact.add(refresh)
            if refresh != self.refresh_token:
                self.refresh_token = refresh
                lifetime = _seconds(data.get("refresh_token_expires_in"))
                self._save(self._saved(refresh, lifetime))
        expires_in = data.get("expires_in")
        # bool is an int subclass; True is no lifetime.
        valid = isinstance(expires_in, int) and not isinstance(expires_in, bool)
        lifetime = expires_in if valid and expires_in > 0 else _DEFAULT_LIFETIME
        renew = self._renew if self.refresh_token else None
        self._client.use_token(data.get("access_token"), lifetime, renew)

    def _saved(self, refresh: str, lifetime: float | None) -> _Saved:
        if lifetime is None or lifetime <= 0:
            return _Saved(refresh, redirect_uri=self.redirect_uri)
        now = _now()
        return _Saved(refresh, now, now + lifetime, self.redirect_uri)

    def _save(self, saved: _Saved) -> None:
        try:
            _auth.store_secret(self._account, saved.dump())
        except (_auth.CredentialsFileCorrupt, OSError):
            # The run keeps the new token in memory; an unwritable stderr must
            # not end it.
            try:
                self._notify(_UNSAVED)
            except (OSError, ValueError):
                pass

    def forget_if_unchanged(self, backend: str, token: str) -> None:
        """Delete the refused *token* from *backend*, unless another run has
        saved a different one there since it was read."""
        for where, stored in _load(self._account):
            if where == backend and stored.token == token:
                _auth.delete_secret(self._account, backend)


def forget(root: str, client_id: str) -> tuple[list[str], list[str], list[str]]:
    """Delete the saved sign-in for *client_id* at the portal *root*; returns
    (backends it was removed from, backends still holding it, backends that
    could not be read, so may still hold it)."""
    account = _account(root, client_id)
    # Under the lock, an exchange in flight saves its token before this
    # deletes it, not after.
    with _exchange_lock(account):
        before = [backend for backend, _ in _auth.load_secrets(account)]
        _auth.delete_secret(account)
    found, unreadable = _auth.probe_secrets(account)
    after = [backend for backend, _ in found]
    return [b for b in before if b not in after], after, unreadable


class _Listener(socketserver.TCPServer):
    allow_reuse_address = False
    # Set when the connection being handled was cut off at its time limit.
    cut: threading.Event

    def __init__(self, port: int, state: str, deadline: float) -> None:
        super().__init__(("127.0.0.1", port), _Callback)
        self.state = state
        self.deadline = deadline
        self.outcome: tuple[str | None, str | None] | None = None

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
        outcome = _read_callback(parse_qs(parts.query), self.server.state)
        self.server.outcome = outcome
        signed_in = outcome[0] is not None
        page = _DONE_PAGE if signed_in else _REFUSED_PAGE
        self.send_response(200 if signed_in else 400)
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
        listener = _Listener(
            redirect_port or 0, state, time.monotonic() + SIGN_IN_TIMEOUT
        )
    except OSError as exc:
        raise PortalError(
            f"can't listen on 127.0.0.1 port {redirect_port or 0} for the "
            f"sign-in ({exc.strerror or exc}); pass a free --redirect-port",
            kind="usage",
        ) from None
    with listener:
        port = listener.server_address[1]
        redirect_uri = _redirect_uri(port)
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
        # A browser command run in the foreground returns only when it exits.
        threading.Thread(
            target=_open_quietly, args=(open_browser, url), daemon=True
        ).start()
        code, problem = _wait(listener)
    if code is None:
        raise PortalError(redact(problem or "the sign-in did not finish"), kind="auth")
    redact.add(code)
    return code, redirect_uri


def _open_quietly(open_browser: Callable[[str], Any], url: str) -> None:
    try:
        open_browser(url)
    except Exception:  # broad: a missing browser leaves the printed URL
        pass


def _wait(listener: _Listener) -> tuple[str | None, str | None]:
    while listener.outcome is None:
        remaining = listener.deadline - time.monotonic()
        if remaining <= 0:
            return None, (
                f"no sign-in arrived within {SIGN_IN_TIMEOUT:g} seconds; run the command again"
            )
        listener.timeout = min(remaining, _POLL)
        listener.handle_request()
    return listener.outcome
