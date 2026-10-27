# SPDX-License-Identifier: Apache-2.0
"""HTTP client for one ArcGIS portal's ``/sharing/rest`` API, and redaction.

Hand-maintained. Shared by ``geolens arcgis inventory`` and the commands that
build on it. Egress contract: a ``PortalClient`` sends requests only to the
portal root it was built with, never to the services an item points at and
never to GeoLens; redirects are refused so a credential can't follow one to
another host. The one exception is a file download, which may take a single
redirect to https on the portal's own host or ArcGIS storage (``arcgis.com``
and its subdomains) and sends no credential there. A notebook's item-data read
may also take one redirect, to the portal's own host and effective port, and
sends the credential there. A command that also needs
GeoLens reaches it only through the SDK client for the configured instance,
so it contacts the portal, its ArcGIS storage and GeoLens. Tokens and passwords stay in memory, and every error message is
redacted when it is built.
"""

from __future__ import annotations

import email.utils
import getpass
import http.client
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import (
    parse_qsl,
    quote,
    quote_plus,
    unquote_plus,
    urlencode,
    urljoin,
    urlsplit,
)

# AGOL and Enterprise 10.5.1+ read the token from this header. Not
# `Authorization`, which a web tier in front of Enterprise may consume.
ESRI_AUTHORIZATION_HEADER = "X-Esri-Authorization"
MIN_REQUEST_INTERVAL = 0.1
SOCKET_TIMEOUT = 10.0
REQUEST_DEADLINE = 30.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# A data file can be large; the whole transfer, not one read, gets this long.
DOWNLOAD_DEADLINE = 3600.0
_ENVELOPE_PROBE_BYTES = 64
_ENVELOPE_START = re.compile(rb'\s*\{\s*"error"\s*:')
GET_ATTEMPTS = 3
MAX_RETRY_AFTER = 60.0
TOKEN_EXPIRATION_MINUTES = 60

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})
_TOKEN_REQUIRED = 499
_TOKEN_INVALID = 498
TOKEN_CHARS = re.compile(r"[\x21-\x7e]+")
_CREDENTIAL_PARAM = re.compile(r"((?:token|password)=)[^&;#\s]+", re.IGNORECASE)

# One matcher names a credential in a JSON key and in a URL parameter. Names
# are compared lower-cased with separators removed; the parts below match
# anywhere in a name, so compound names such as accessToken are covered, and
# the exact names are too short to match as parts.
_CREDENTIAL_NAME_PARTS = (
    "token",
    "password",
    "passwd",
    "passphrase",
    "secret",
    "apikey",
    "accesskey",
    "subscriptionkey",
    "saskey",
    "privatekey",
    "credential",
    "authorization",
    "authcode",
    "bearer",
    "signature",
    "customparameters",
)
_CREDENTIAL_NAME_EXACT = frozenset({"sig", "auth", "pwd"})
_URL_PARAM = re.compile(r"(^|[?&;#,(\s])([^=&;?/\s\"'#]+)=([^&;#\s]+)")
# A key that is a URL or an assignment holds text to scrub, not a bare name.
_COMPOUND_KEY = re.compile(r"(?:[a-z][a-z0-9+.-]*:)?//|[=&?]", re.IGNORECASE)
_URL_USERINFO = re.compile(r"(//)[^/@\s]+@")


class Redactor:
    """Replaces known secrets, and any ``token=``/``password=`` value, in text."""

    def __init__(self) -> None:
        self._forms: list[str] = []

    def add(self, secret: str | None) -> None:
        if not secret:
            return
        forms = [*self._forms, secret, quote(secret, safe=""), quote_plus(secret)]
        # Replaced whole, not sorted in place: a token renewed mid-run is added
        # while other threads redact, and an in-place sort hides every form.
        self._forms = sorted(dict.fromkeys(forms), key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for form in self._forms:
            text = text.replace(form, "[REDACTED]")
        return _CREDENTIAL_PARAM.sub(r"\1[REDACTED]", text)


def _is_credential_name(name: str) -> bool:
    """Whether a JSON key or URL parameter name holds a credential."""
    normal = re.sub(r"[^a-z0-9]", "", name.lower())
    return normal in _CREDENTIAL_NAME_EXACT or any(
        part in normal for part in _CREDENTIAL_NAME_PARTS
    )


def _scrub_param(match: re.Match[str]) -> str:
    lead, name, value = match.groups()
    if _is_credential_name(unquote_plus(name)):
        value = "[REDACTED]"
    return f"{lead}{name}={value}"


_HEADER_NAME = r"(?:proxy-)?authorization|cookie|set-cookie|(?:x[-_]?)?api[-_]?key"
_HEADER_SEP = r"\s*[:=]\s*"
_QUOTED = r"\"(?:[^\"\\\r\n]|\\.?)*(?:\"|(?=[\r\n])|$)|'(?:[^'\\\r\n]|\\.?)*(?:'|(?=[\r\n])|$)"
# After ?, & # or ; the match is a URL parameter and ends at the next
# delimiter. An authorization value may hold spaces, commas and quoted parts
# ("Digest u=x, r=y"); a cookie value holds spaces, semicolons and quoted parts.
_HEADER = re.compile(
    rf"(?<=[?&#;])(?P<aname>(?:x-esri-|proxy-)?authorization)(?P<asep>{_HEADER_SEP})(?:{_QUOTED}|[^&#;\r\n\"'])*"
    rf"|(?<=[?&#;])(?P<cname>(?:set-)?cookie)(?P<csep>{_HEADER_SEP})(?:{_QUOTED}|[^&#\r\n\"'])*"
    rf"|(?<=[?&#;])(?P<uname>{_HEADER_NAME})(?P<usep>{_HEADER_SEP})[^&#;\s]*"
    rf"|\b(?P<name>x-esri-authorization|{_HEADER_NAME})(?P<sep>{_HEADER_SEP})[^\r\n]+",
    re.IGNORECASE,
)
_SCHEME_CREDENTIAL = re.compile(
    r"((?:[=:]\s*)?)\b(Bearer|Basic|Token|Digest)(\s+)([A-Za-z0-9._~+/=-]{12,}[^\s<>\"'`{}|()\[\],;&?#]*)",
    re.IGNORECASE,
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*")
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)",
    re.DOTALL,
)
_AWS_KEY_ID = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_JSON_PAIR = re.compile(r'"([^"\\]{1,64})"(\s*:\s*)"(?:[^"\\]|\\.)*"')
_MAX_EMBEDDED_DEPTH = 3


def _scrub_scheme(match: re.Match[str]) -> str:
    assigned, scheme, space, value = match.groups()
    # Bearer is rarely prose; the other schemes also open ordinary sentences
    # ("Basic configuration options"), so a lowercase word after them is left
    # alone, except as the value of an assignment, whose name may be encoded.
    if scheme.lower() != "bearer" and not assigned and re.fullmatch(r"[a-z]+", value):
        return match.group(0)
    return f"{assigned}{scheme}{space}[REDACTED]"


def _scrub_header(match: re.Match[str]) -> str:
    groups = match.groupdict()
    for key in ("a", "c", "u", ""):
        if groups[f"{key}name"] is not None:
            return f"{groups[f'{key}name']}{groups[f'{key}sep']}[REDACTED]"
    raise AssertionError("unreachable")


def _scrub_pair(match: re.Match[str]) -> str:
    name, colon = match.group(1), match.group(2)
    return (
        f'"{name}"{colon}"[REDACTED]"' if _is_credential_name(name) else match.group(0)
    )


def _scrub_text(text: str, redact: Redactor, depth: int = 0) -> str:
    """*text* with every credential shape this module knows masked.

    JSON held inside a string is parsed and scrubbed like the document around
    it; any other text goes through the shape patterns, which cover query and
    assignment forms, URL userinfo, auth headers and schemes, JWTs, private
    keys and cloud access key ids.
    """
    stripped = text.lstrip()
    if depth < _MAX_EMBEDDED_DEPTH and stripped[:1] in ("{", "["):
        try:
            embedded = json.loads(stripped)
        except (ValueError, RecursionError):
            embedded = None
        if isinstance(embedded, dict | list):
            return json.dumps(_redact_json(embedded, redact, depth + 1))
    text = redact(text)
    text = _PEM.sub("[REDACTED]", text)
    text = _HEADER.sub(_scrub_header, text)
    text = _SCHEME_CREDENTIAL.sub(_scrub_scheme, text)
    text = _JWT.sub("[REDACTED]", text)
    text = _AWS_KEY_ID.sub("[REDACTED]", text)
    if "=" in text or "//" in text:
        text = _URL_PARAM.sub(_scrub_param, text)
        text = _URL_USERINFO.sub(r"\1[REDACTED]@", text)
    if '":' in text or '" :' in text:
        text = _JSON_PAIR.sub(_scrub_pair, text)
    return text


def redact_json(value: Any, redact: Redactor) -> Any:
    """A copy of *value* that is safe to write to disk (see ``_redact_json``)."""
    return _redact_json(value, redact, 0)


def _redact_json(value: Any, redact: Redactor, depth: int) -> Any:
    """A copy of *value* that is safe to write to disk.

    The value under any key named like a credential becomes ``[REDACTED]`` at
    any depth, and every other string passes through *redact*. The walk is
    iterative so a deeply nested document can't exhaust the stack.
    """
    if not isinstance(value, dict | list):
        return _scrub_text(value, redact, depth) if isinstance(value, str) else value
    root: Any = {} if isinstance(value, dict) else []
    stack = [(value, root)]
    while stack:
        source, target = stack.pop()
        pairs = source.items() if isinstance(source, dict) else enumerate(source)
        for key, item in pairs:
            if (
                isinstance(source, dict)
                and isinstance(key, str)
                and not _COMPOUND_KEY.search(key)
                and _is_credential_name(key)
            ):
                out: Any = "[REDACTED]"
            elif isinstance(item, dict | list):
                out = {} if isinstance(item, dict) else []
                stack.append((item, out))
            else:
                out = (
                    _scrub_text(item, redact, depth) if isinstance(item, str) else item
                )
            if isinstance(source, dict):
                name = _scrub_text(key, redact, depth) if isinstance(key, str) else key
                # Two keys can scrub to the same text; keep both values.
                while name in target:
                    name = f"{name}#"
                target[name] = out
            else:
                target.append(out)
    return root


class PortalError(Exception):
    """A portal request failed; ``kind`` picks the exit code.

    The message is redacted when the error is built, so ``str()`` is safe to
    print anywhere. ``redirect_to`` is the raw ``Location`` of a redirect, which
    can carry a pre-signed query: read it, never print it.
    """

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        http_status: int | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
        redirect_to: str | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after = retry_after
        self.redirect_to = redirect_to


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Watchdog:
    """Shuts a request's connection down when its deadline passes.

    It keeps a duplicate of the connection's descriptor. TLS wrapping
    detaches the original socket object from the descriptor, but shutting
    down any descriptor of a connection ends it for every reader, so the
    duplicate still interrupts a TLS handshake or read.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dup: socket.socket | None = None
        self.fired = False

    def attach(self, sock: socket.socket) -> socket.socket:
        with self._lock:
            self._close_dup()
            self._dup = sock.dup()
            if self.fired:
                _shutdown(self._dup)
        return sock

    def fire(self) -> None:
        with self._lock:
            self.fired = True
            if self._dup is not None:
                _shutdown(self._dup)

    def release(self) -> None:
        with self._lock:
            self._close_dup()

    def _close_dup(self) -> None:
        if self._dup is not None:
            self._dup.close()
            self._dup = None


def _shutdown(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass


class _WatchedConnections:
    """Hands each new connection's socket to the request's watchdog.

    http.client opens the socket through the connection's private
    ``_create_connection`` attribute, before any TLS wrapping, so the
    watchdog covers the handshake, status line, headers, chunk framing and
    body alike.
    """

    def do_open(self, http_class, req, **kwargs):
        watchdog = getattr(req, "watchdog", None)

        def connection(host, **conn_kwargs):
            conn = http_class(host, **conn_kwargs)
            if watchdog is not None:
                create = conn._create_connection
                conn._create_connection = lambda *a, **k: watchdog.attach(
                    create(*a, **k)
                )
            return conn

        return super().do_open(connection, req, **kwargs)


class _WatchedHTTPHandler(_WatchedConnections, urllib.request.HTTPHandler):
    pass


class _WatchedHTTPSHandler(_WatchedConnections, urllib.request.HTTPSHandler):
    pass


def build_opener(
    context: ssl.SSLContext | None = None,
) -> urllib.request.OpenerDirector:
    """An opener that refuses redirects and honors per-request deadlines.

    A redirect would carry the credential header to wherever the portal
    points, so none is followed. *context* overrides the default TLS
    verification context.
    """
    return urllib.request.build_opener(
        _RefuseRedirects(),
        _WatchedHTTPHandler(),
        _WatchedHTTPSHandler(context=context),
    )


class PortalClient:
    """JSON reads against one portal's ``/sharing/rest`` API."""

    def __init__(
        self,
        root_url: str,
        *,
        opener: Any,
        redact: Redactor,
        token: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        on_request: Callable[[str, str], None] | None = None,
    ) -> None:
        self.root = root_url.rstrip("/")
        self.token = token
        self._opener = opener
        self._redact = redact
        self._sleep = sleep
        self._clock = clock
        self._on_request = on_request
        self._form_token = False
        self._download_end = 0.0
        self._referer: str | None = None
        self._sign_in: tuple[str, str] | None = None
        self._lock = threading.Lock()
        self._renew_lock = threading.Lock()
        self._next_slot = 0.0
        # The Date header of the latest response: the portal's own clock.
        self.server_date: str | None = None

    def _error(self, message: str, **kwargs: Any) -> PortalError:
        return PortalError(self._redact(message), **kwargs)

    def get_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        array_ok: bool = False,
        follow_same_host: bool = False,
    ) -> Any:
        """GET ``/sharing/rest/<path>`` as a JSON object, retrying transient
        failures; with *array_ok* a JSON array is returned too.

        With *follow_same_host* one redirect to https on the portal's own host
        is followed, with the same credential; any other redirect is refused.

        An error envelope in a 200 body raises ``PortalError``. A 499 "token
        required", as an envelope or an HTTP status, with the header present
        means a pre-10.5.1 server ignored it; from then on the token goes in a
        POST form field, never the URL. When the portal rejects a token minted
        from a password with 498 or 499, a new one is minted and the read is
        retried once with it.
        """
        query = {**(params or {}), "f": "json"}
        url = f"{self.root}/sharing/rest/{path}"
        try:
            return self._get_json_renewing(path, url, query, array_ok)
        except PortalError as exc:
            if not follow_same_host or exc.http_status not in _REDIRECT_STATUSES:
                raise
            target = self._same_host_target(url, exc.redirect_to)
            if target is None:
                raise
        # One hop only: a second redirect is refused like any other.
        parts = urlsplit(target)
        hop_query = {**dict(parse_qsl(parts.query)), **query}
        return self._get_json_renewing(
            path, f"{parts.scheme}://{parts.netloc}{parts.path}", hop_query, array_ok
        )

    def _get_json_renewing(
        self, path: str, url: str, query: dict[str, Any], array_ok: bool
    ) -> Any:
        token = self.token
        try:
            return self._get_json_sent(path, url, query, array_ok)
        except PortalError as exc:
            rejected = exc.http_status in (_TOKEN_INVALID, _TOKEN_REQUIRED)
            if not rejected or not self._renew_token(token):
                raise
        return self._get_json_sent(path, url, query, array_ok)

    def _same_host_target(self, base: str, location: str | None) -> str | None:
        """*location* resolved against *base* when it is https on the portal's
        own host and effective port with no userinfo, else None."""
        target, host, allowed = self._redirect_target(base, location)
        if not allowed:
            return None
        # The credential goes along, so the port must match too, not just be a
        # default one.
        port = urlsplit(target).port or 443
        portal = urlsplit(self.root)
        same = host == (portal.hostname or "").lower() and port == (portal.port or 443)
        return target if same else None

    def _get_json_sent(
        self, path: str, url: str, query: dict[str, Any], array_ok: bool
    ) -> Any:
        sent_as_form = self._form_token
        try:
            return self._get_json_once(path, url, query, array_ok)
        except PortalError as exc:
            if exc.http_status != _TOKEN_REQUIRED or not self.token or sent_as_form:
                raise
        self._form_token = True
        return self._get_json_once(path, url, query, array_ok)

    def _renew_token(self, rejected: str | None) -> bool:
        """Mint a replacement for the rejected token; False when there is none.

        Reads that saw the same token share one sign-in. A failed sign-in ends
        renewal for the run, since ArcGIS locks an account after five.
        """
        with self._renew_lock:
            if self.token != rejected:
                return True
            if self._sign_in is None:
                return False
            username, password = self._sign_in
            try:
                self.generate_token(username, password)
            except PortalError:
                self._sign_in = None
                return False
            return True

    def renew_token(self) -> bool:
        """Mint a replacement for the current token from the held sign-in;
        False when there is none or the sign-in fails."""
        return self._renew_token(self.token)

    def switch_to_form_token(self) -> bool:
        """Send the token as a POST form field from now on; False if it
        already was, or there is no token."""
        if not self.token or self._form_token:
            return False
        self._form_token = True
        return True

    def _get_json_once(
        self, path: str, url: str, query: dict[str, Any], array_ok: bool
    ) -> Any:
        """One read, retrying a transient error envelope like an HTTP status."""
        for attempt in range(1, GET_ATTEMPTS + 1):
            data = self._read(url, query, array_ok)
            if isinstance(data, list):
                return data
            code = _envelope_code(data)
            if code is None:
                return data
            error = self._envelope_error(path, data, code)
            if not error.retryable or attempt == GET_ATTEMPTS:
                raise error
            self._sleep(0.5 * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def generate_token(self, username: str, password: str) -> str:
        """Mint a 60-minute token bound to the portal origin as its referer,
        and keep the sign-in in memory to mint its replacement.

        Never retried: ArcGIS locks an account after five failed sign-ins in
        fifteen minutes. Every later request sends that referer, since a
        portal enforcing the binding rejects the token without it.
        """
        referer = _origin(self.root)
        fields = {
            "username": username,
            "password": password,
            "client": "referer",
            "referer": referer,
            "expiration": str(TOKEN_EXPIRATION_MINUTES),
            "f": "json",
        }
        url = f"{self.root}/sharing/rest/generateToken"
        try:
            data = self._exchange("POST", url, fields, {}, attempts=1)
        except PortalError as exc:
            if exc.kind != "auth":
                raise
            data = {}
        token = data.get("token")
        if _envelope_code(data) is not None or not isinstance(token, str) or not token:
            detail = _envelope_message(data, self._redact) or "no token in the response"
            raise self._error(
                f"sign-in failed: {detail}. Accounts that sign in through SAML "
                "or OpenID Connect cannot use a password here; pass a token "
                "with --token, ARCGIS_TOKEN or --token-stdin instead.",
                kind="auth",
            )
        if not TOKEN_CHARS.fullmatch(token):
            raise self._error(
                "the portal returned a token with unexpected characters",
                kind="auth",
            )
        self._redact.add(token)
        self.token = token
        self._referer = referer
        self._sign_in = (username, password)
        return token

    def download(self, path: str, dest: Path, max_bytes: int | None) -> int:
        """GET ``/sharing/rest/<path>`` into the file *dest*, returning its size.

        For item data, which is a file rather than JSON. The body is streamed
        and counted, never held in memory, and a body over *max_bytes* raises
        ``PortalError`` of kind ``too_large`` after at most one chunk past the
        limit. Redirects are refused and a token is handled as in ``get_json``;
        a 200 carrying an error envelope raises as it does there.
        """
        # The whole transfer, retries and a token renewal included, shares one
        # deadline.
        self._download_end = self._clock() + DOWNLOAD_DEADLINE
        token = self.token
        try:
            return self._download_sent(path, dest, max_bytes)
        except PortalError as exc:
            rejected = exc.http_status in (_TOKEN_INVALID, _TOKEN_REQUIRED)
            if not rejected or not self._renew_token(token):
                raise
        return self._download_sent(path, dest, max_bytes)

    def _download_sent(self, path: str, dest: Path, max_bytes: int | None) -> int:
        sent_as_form = self._form_token
        try:
            return self._download_attempts(path, dest, max_bytes)
        except PortalError as exc:
            if exc.http_status != _TOKEN_REQUIRED or not self.token or sent_as_form:
                raise
        self._form_token = True
        return self._download_attempts(path, dest, max_bytes)

    def _download_attempts(self, path: str, dest: Path, max_bytes: int | None) -> int:
        url = f"{self.root}/sharing/rest/{path}"
        headers = {"Referer": self._referer} if self._referer else {}
        body = None
        if self.token and self._form_token:
            body = urlencode({"token": self.token}).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif self.token:
            headers[ESRI_AUTHORIZATION_HEADER] = f"Bearer {self.token}"
        for attempt in range(1, GET_ATTEMPTS + 1):
            self._wait_turn()
            if self._on_request:
                self._on_request("POST" if body else "GET", urlsplit(url).path)
            request = urllib.request.Request(
                url, data=body, headers=headers, method="POST" if body else "GET"
            )
            try:
                return self._download_once(request, path, dest, max_bytes)
            except PortalError as exc:
                if not exc.retryable or attempt == GET_ATTEMPTS:
                    raise
                delay = exc.retry_after
                self._sleep(delay if delay is not None else 0.5 * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    def _download_once(
        self,
        request: urllib.request.Request,
        path: str,
        dest: Path,
        max_bytes: int | None,
        *,
        may_redirect: bool = True,
    ) -> int:
        deadline = self._download_end
        redirect: tuple[int, str | None] | None = None
        watchdog = _Watchdog()
        request.watchdog = watchdog
        timer = threading.Timer(max(0.0, deadline - self._clock()), watchdog.fire)
        timer.daemon = True
        timer.start()
        try:
            with self._opener.open(request, timeout=SOCKET_TIMEOUT) as response:
                size = self._stream(response, path, dest, max_bytes, deadline)
        except urllib.error.HTTPError as exc:
            if not (may_redirect and exc.code in _REDIRECT_STATUSES):
                raise self._http_error(exc, path) from None
            redirect = (exc.code, exc.headers.get("Location"))
            exc.close()
        except PortalError:
            raise
        except Exception as exc:  # broad: a shut socket can surface as any I/O error
            if watchdog.fired:
                raise self._error(
                    f"{path} took longer than {DOWNLOAD_DEADLINE:g} s",
                    kind="network",
                    retryable=True,
                ) from None
            if isinstance(
                exc, urllib.error.URLError | OSError | http.client.HTTPException
            ):
                # The redirected hop's URL carries a credential, which an
                # exception's text may repeat.
                reason = (
                    (getattr(exc, "reason", None) or exc) if may_redirect else "failed"
                )
                raise self._error(
                    f"network error on {path}: {reason}", kind="network", retryable=True
                ) from None
            raise
        finally:
            timer.cancel()
            watchdog.release()
        if redirect is not None:
            return self._follow_download(
                request.full_url, path, redirect, dest, max_bytes
            )
        if watchdog.fired:
            raise self._error(
                f"{path} took longer than {DOWNLOAD_DEADLINE:g} s",
                kind="network",
                retryable=True,
            )
        return size

    def _redirect_target(
        self, base: str, location: str | None
    ) -> tuple[str, str, bool]:
        """The absolute redirect target, its host, and whether a download may
        follow it: https to the portal's own origin or to ArcGIS storage on
        the default port, with no userinfo. A malformed target is refused."""
        try:
            target = urljoin(base, location) if location else ""
            parts = urlsplit(target)
            host = (parts.hostname or "").lower()
            port = parts.port
            portal = urlsplit(self.root)
            portal_host, portal_port = (portal.hostname or "").lower(), portal.port
        except ValueError:
            return "", "", False
        own = host == portal_host and port in (None, 443, portal_port)
        storage = port in (None, 443) and (
            host == "arcgis.com"
            or (host.endswith(".arcgis.com") and len(host) > len(".arcgis.com"))
        )
        clean = all(" " < c < "\x7f" for c in target)
        allowed = (
            clean
            and parts.scheme == "https"
            and not parts.username
            and (own or storage)
        )
        return target, host, allowed

    def _follow_download(
        self,
        base: str,
        path: str,
        redirect: tuple[int, str | None],
        dest: Path,
        max_bytes: int | None,
    ) -> int:
        """The one redirect a file download may take: to https on the portal's
        own host or ArcGIS storage, sent with no credential of any kind.

        The target's query is a pre-signed credential, so only its host and
        path are ever named in a message or logged.
        """
        status, location = redirect
        target, host, allowed = self._redirect_target(base, location)
        if not allowed:
            where = host or "an unreadable address"
            raise self._error(
                f"{path} answered with a redirect (HTTP {status}) to {where}, "
                "which is neither the portal nor its ArcGIS storage over https; "
                "redirects elsewhere are refused so the credential stays on the "
                "portal origin.",
                kind="redirect",
                http_status=status,
            )
        parts = urlsplit(target)
        shown = f"{host}{parts.path}"
        self._wait_turn()
        if self._on_request:
            self._on_request("GET", parts.path)
        request = urllib.request.Request(target, method="GET")
        return self._download_once(request, shown, dest, max_bytes, may_redirect=False)

    def _stream(
        self,
        response: Any,
        path: str,
        dest: Path,
        max_bytes: int | None,
        deadline: float,
    ) -> int:
        length = response.headers.get("Content-Length")
        if max_bytes is not None and length and length.isdigit():
            if int(length) > max_bytes:
                raise self._error(f"{path} is {int(length)} bytes", kind="too_large")
        total = 0
        first = True
        # Mode 0600: a downloaded file is the organization's data.
        try:
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.chmod(dest, 0o600)
            out = os.fdopen(fd, "wb")
        except OSError as exc:
            raise self._local_error(exc) from None
        with out:
            while True:
                if self._clock() > deadline:
                    raise self._error(
                        f"{path} took longer than {DOWNLOAD_DEADLINE:g} s",
                        kind="network",
                        retryable=True,
                    )
                chunk = response.read1(64 * 1024)
                if first:
                    first = False
                    # A short first read can't tell an error envelope from
                    # data, so read until the prefix is long enough to.
                    while chunk and len(chunk) < _ENVELOPE_PROBE_BYTES:
                        more = response.read1(64 * 1024)
                        if not more:
                            break
                        chunk += more
                    if _ENVELOPE_START.match(chunk):
                        chunk += response.read(MAX_RESPONSE_BYTES)
                        self._raise_envelope(path, chunk)
                if not chunk:
                    break
                total += len(chunk)
                if max_bytes is not None and total > max_bytes:
                    raise self._error(
                        f"{path} is over {max_bytes} bytes", kind="too_large"
                    )
                try:
                    out.write(chunk)
                except OSError as exc:
                    raise self._local_error(exc) from None
        if length and length.isdigit() and total != int(length):
            raise self._error(
                f"{path} ended after {total} of {int(length)} bytes",
                kind="network",
                retryable=True,
            )
        return total

    def _local_error(self, exc: OSError) -> PortalError:
        """A failure writing the download to disk: not a network problem, so
        it is never retried."""
        return self._error(
            f"can't write the download: {exc.strerror or type(exc).__name__}",
            kind="local",
        )

    def _raise_envelope(self, path: str, raw: bytes) -> None:
        """Raise the error a 200 body carries; a body that only looks like one
        is left to be saved."""
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            return
        code = _envelope_code(data) if isinstance(data, dict) else None
        if code is not None:
            raise self._envelope_error(path, data, code)

    def _read(self, url: str, query: dict[str, Any], array_ok: bool) -> Any:
        headers = {"Referer": self._referer} if self._referer else {}
        if self.token and self._form_token:
            return self._exchange(
                "POST",
                url,
                {**query, "token": self.token},
                headers,
                attempts=GET_ATTEMPTS,
                array_ok=array_ok,
            )
        if self.token:
            headers[ESRI_AUTHORIZATION_HEADER] = f"Bearer {self.token}"
        return self._exchange(
            "GET",
            f"{url}?{urlencode(query)}",
            None,
            headers,
            attempts=GET_ATTEMPTS,
            array_ok=array_ok,
        )

    def _exchange(
        self,
        method: str,
        url: str,
        form: Mapping[str, Any] | None,
        headers: dict[str, str],
        *,
        attempts: int,
        array_ok: bool = False,
    ) -> Any:
        body = urlencode(form).encode() if form is not None else None
        if body is not None:
            headers = {**headers, "Content-Type": "application/x-www-form-urlencoded"}
        path = urlsplit(url).path
        for attempt in range(1, attempts + 1):
            self._wait_turn()
            if self._on_request:
                self._on_request(method, path)
            request = urllib.request.Request(
                url,
                data=body,
                headers={**headers, "Accept": "application/json"},
                method=method,
            )
            try:
                raw = self._open_once(request, path)
            except PortalError as exc:
                if not exc.retryable or attempt == attempts:
                    raise
                delay = exc.retry_after
                self._sleep(delay if delay is not None else 0.5 * 2 ** (attempt - 1))
                continue
            return self._parse(raw, path, array_ok)
        raise AssertionError("unreachable")

    def _wait_turn(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next_slot - now
            self._next_slot = max(now, self._next_slot) + MIN_REQUEST_INTERVAL
        if wait > 0:
            self._sleep(wait)

    def _open_once(self, request: urllib.request.Request, path: str) -> bytes:
        """One request, bounded end to end by ``REQUEST_DEADLINE``.

        A timer shuts the socket down at the deadline, so a server that
        trickles any part of the response can't hold the request open.
        """
        deadline = self._clock() + REQUEST_DEADLINE
        watchdog = _Watchdog()
        request.watchdog = watchdog
        timer = threading.Timer(REQUEST_DEADLINE, watchdog.fire)
        timer.daemon = True
        timer.start()
        try:
            raw = self._open_and_read(request, path, deadline)
        except Exception:  # broad: a shut socket can surface as any I/O error
            if watchdog.fired:
                raise self._deadline_error(path) from None
            raise
        finally:
            timer.cancel()
            watchdog.release()
        # A shut socket also reads as a clean end of body, cutting it short.
        if watchdog.fired:
            raise self._deadline_error(path)
        return raw

    def _deadline_error(self, path: str) -> PortalError:
        return self._error(
            f"{path} took longer than {REQUEST_DEADLINE:g} s",
            kind="network",
            retryable=True,
        )

    def _open_and_read(
        self, request: urllib.request.Request, path: str, deadline: float
    ) -> bytes:
        try:
            with self._opener.open(request, timeout=SOCKET_TIMEOUT) as response:
                self.server_date = response.headers.get("Date") or self.server_date
                return self._read_capped(response, path, deadline)
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc, path) from None
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            reason = getattr(exc, "reason", None) or exc
            raise self._error(
                f"network error on {path}: {reason}", kind="network", retryable=True
            ) from None

    def _http_error(self, exc: urllib.error.HTTPError, path: str) -> PortalError:
        status = exc.code
        exc.close()
        if 300 <= status < 400:
            return self._error(
                f"{path} answered with a redirect (HTTP {status}). Redirects "
                "are refused so the credential stays on the portal origin; "
                "pass the final portal URL with --portal-url.",
                kind="redirect",
                http_status=status,
                redirect_to=exc.headers.get("Location"),
            )
        if status in (401, _TOKEN_INVALID, _TOKEN_REQUIRED):
            kind = "auth"
        else:
            kind = "server" if status >= 500 else "refused"
        return self._error(
            f"HTTP {status} from {path}",
            kind=kind,
            http_status=status,
            retryable=status in _RETRYABLE_STATUSES,
            retry_after=_retry_after(exc.headers),
        )

    def _read_capped(self, response: Any, path: str, deadline: float) -> bytes:
        length = response.headers.get("Content-Length")
        if length and length.isdigit() and int(length) > MAX_RESPONSE_BYTES:
            raise self._too_large(path)
        chunks: list[bytes] = []
        total = 0
        while True:
            if self._clock() > deadline:
                raise self._deadline_error(path)
            # read1 returns after one socket read; read(n) would keep reading
            # until n bytes arrive.
            chunk = response.read1(64 * 1024)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise self._too_large(path)
            chunks.append(chunk)

    def _too_large(self, path: str) -> PortalError:
        return self._error(
            f"{path} is larger than {MAX_RESPONSE_BYTES // (1024 * 1024)} MiB",
            kind="invalid",
        )

    def _parse(self, raw: bytes, path: str, array_ok: bool) -> Any:
        if not raw.strip():
            raise self._error(f"{path} returned an empty body", kind="empty")
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            raise self._error(f"{path} did not return JSON", kind="not_json") from None
        if isinstance(data, dict) or (array_ok and isinstance(data, list)):
            return data
        raise self._error(f"{path} did not return a JSON object", kind="invalid")

    def _envelope_error(self, path: str, data: dict, code: int) -> PortalError:
        message = _envelope_message(data, self._redact) or "no message"
        if code in (_TOKEN_INVALID, _TOKEN_REQUIRED):
            kind = "auth"
        elif code >= 500:
            kind = "server"
        else:
            kind = "refused"
        return self._error(
            f"{path} returned error {code}: {message}",
            kind=kind,
            http_status=code,
            retryable=code in _RETRYABLE_STATUSES,
        )


def _envelope_code(data: Mapping[str, Any]) -> int | None:
    error = data.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, int) and not isinstance(code, bool) else 0


def _envelope_message(data: Mapping[str, Any], redact: Redactor) -> str:
    """The envelope's message and details, redacted and then shortened.

    Redacting first matters: a cut through a secret leaves a prefix that no
    longer matches it.
    """
    error = data.get("error")
    if not isinstance(error, dict):
        return ""
    parts = [str(error.get("message") or "")]
    details = error.get("details")
    if isinstance(details, list):
        parts.extend(str(d) for d in details if d)
    return redact(" ".join(p for p in parts if p))[:500]


def _retry_after(headers: Any) -> float | None:
    """Seconds to wait from ``Retry-After`` (delay-seconds or HTTP-date),
    capped at ``MAX_RETRY_AFTER``; None when absent or unreadable."""
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        seconds = float(value)
    else:
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(tz=UTC)).total_seconds()
    return min(max(seconds, 0.0), MAX_RETRY_AFTER)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def sanitize_url(url: Any) -> str | None:
    """Scheme, host and path only: a stored service URL can carry a token in
    its query string or credentials in its userinfo."""
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urlsplit(url)
        host = parts.hostname
        parts.port  # raises ValueError for a malformed port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    # netloc rather than hostname keeps template placeholders like
    # {subDomain} intact; only the userinfo is dropped.
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}{parts.path}"


def portal_root(
    url: str, allow_insecure_http: bool, *, label: str = "--portal-url"
) -> str:
    """The portal's root URL (no ``/sharing/rest`` or ``/home``); ``ValueError``
    names *label* when *url* is not an https URL without credentials."""
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
    except ValueError:
        host = None
        parts = None
    if parts is None or not host:
        raise ValueError(f"{label} must be an absolute URL")
    if parts.scheme != "https" and not (parts.scheme == "http" and allow_insecure_http):
        raise ValueError(
            f"{label} must use https (http only with --allow-insecure-http)"
        )
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(
            f"{label} must not carry credentials, a query string or a fragment"
        )
    path = parts.path.rstrip("/")
    for suffix in ("/sharing/rest", "/home"):
        if path.lower().endswith(suffix):
            path = path[: -len(suffix)]
    return f"{parts.scheme}://{parts.netloc}{path}"


def read_credentials(
    token: str | None, token_stdin: bool, username: str | None, password_stdin: bool
) -> tuple[str | None, str | None]:
    """(token, password) from the options, stdin, ``ARCGIS_PASSWORD`` or a
    prompt; both None for an anonymous run. ``ValueError`` on a bad mix."""
    token = token or None
    if token_stdin and token:
        raise ValueError("pass the token once: --token/ARCGIS_TOKEN or --token-stdin")
    if username and (token or token_stdin):
        raise ValueError("use either a token or --username, not both")
    if password_stdin and not username:
        raise ValueError("--password-stdin needs --username")
    if token_stdin:
        token = sys.stdin.readline().strip()
        if not token:
            raise ValueError("--token-stdin read an empty line")
    if token is not None:
        if not TOKEN_CHARS.fullmatch(token):
            raise ValueError(
                "the ArcGIS token holds whitespace or non-ASCII characters, "
                "which no ArcGIS token has"
            )
        return token, None
    if not username:
        return None, None
    if password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = os.environ.get("ARCGIS_PASSWORD") or getpass.getpass(
            "ArcGIS password: "
        )
    if not password:
        raise ValueError("an empty password was given")
    return None, password
