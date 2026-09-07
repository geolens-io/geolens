"""Mint a short-lived ArcGIS portal token from a username and password.

Protocol half of ``POST /services/arcgis/signin/``; abuse controls live
next to the route in ``router.py``. Nothing here is persisted: the
password lives for one outbound POST, the token for one response only.

Non-obvious protocol facts:
* ``client=referer`` plus a ``referer`` FORM FIELD (not a ``Referer``
  header) is mandatory, or the portal accepts the token and the services
  host then refuses it with a 498.
* The referer value is fixed per instance (the token is bound to it),
  never derived from the caller's request.
* Never retry a refusal: ArcGIS locks a built-in account after five failed
  sign-ins in fifteen minutes.
* Request a 60-minute expiry: ArcGIS Online caps at fifteen days and
  Enterprise clamps to its own admin cap, so asking for longer only widens
  the blast radius of the one token that reaches the browser.

Invalid credentials and a locked account share one error code, since
"locked" already discloses that the account exists. The federated-identity
code stays separate because it names a real cause and a working
alternative.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import hashlib
import hmac
import ipaddress
import socket
import string

import httpx
import idna
import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings
from app.platform.security import (
    PROBE_TIMEOUT,
    SSRFError,
    SSRFResolutionError,
    make_safe_client,
    validate_url_for_ssrf,
)

logger = structlog.stdlib.get_logger(__name__)

# Minutes of validity to ask generateToken for. See the module docstring for
# why a larger number buys nothing.
SIGNIN_EXPIRATION_MINUTES = 60

# The D8 fallback: the value in Esri's own documented sample, used when the
# instance advertises no public URL of its own. Never a per-request value.
DEFAULT_SIGNIN_REFERER = "https://www.arcgis.com"

# Domain separation for the account digest. Changing either value re-buckets
# every in-flight attempt budget, which is harmless: the window is fifteen
# minutes and the digest is never stored for longer than that matters.
_ACCOUNT_KEY_SALT = b"geolens-arcgis-signin"
_ACCOUNT_KEY_INFO = b"account-digest-key"

# A token envelope is a few hundred bytes and a portal info document a few
# kilobytes. Anything past this is a web page, not an answer, and reading it
# to the end only helps the origin waste API memory.
_MAX_RESPONSE_BYTES = 256 * 1024

# fix(#1758): deadline is per phase, not the whole sign-in, so a
# cancellation can't land mid ledger/audit write and 500 without recording
# the outcome. httpx per-phase timeouts back DNS resolution; sum = 45s.
_DISCOVERY_DEADLINE_SECONDS = 20.0
_MINT_DEADLINE_SECONDS = 25.0

# Caller-facing codes. The two ArcGIS ones are the whole of this endpoint's
# new vocabulary; the other two are the shapes the probe endpoint already
# returns for the same conditions.
SIGNIN_REJECTED = "arcgis_signin_rejected"
SSO_ACCOUNT = "arcgis_sso_account"
SSRF_REFUSED = "ssrf_refused"
NETWORK_ERROR = "network_error"
# fix(#1758): not an ArcGIS outcome. GeoLens refuses before the
# password leaves the process, so it discloses nothing about the account.
NOT_HTTPS = "arcgis_portal_not_https"
# fix(#1758): likewise. A host nobody can canonicalize cannot be
# bucketed, and an unbucketable host is an unlimited one.
HOST_INVALID = "arcgis_portal_host_invalid"

_REJECTED_MESSAGE = (
    "ArcGIS did not accept that sign-in. Check the username and password, "
    "including capitalisation. Too many failed attempts also lock an ArcGIS "
    "account temporarily."
)
_SSO_MESSAGE = (
    "This account signs in through your organisation's identity provider, or "
    "has multifactor authentication turned on. Username and password sign-in "
    "will not work here. Paste a token or API key instead."
)
_SSRF_MESSAGE = (
    "That portal address is on a private or internal network, which GeoLens "
    "will not contact. A portal that is not reachable from the public "
    "internet cannot be used for sign-in or for a pasted token."
)
_UNREACHABLE_MESSAGE = (
    "Could not reach that ArcGIS portal. Check the portal URL and try again."
)
_TIMEOUT_MESSAGE = "The ArcGIS portal didn't respond in time. Try again."
_UNREADABLE_MESSAGE = (
    "That address answered, but not with an ArcGIS sign-in response. Check "
    "that it is the portal URL, for example https://your-org.maps.arcgis.com."
)
_REDIRECTED_MESSAGE = (
    "That portal answered the sign-in with a redirect instead of a token. "
    "GeoLens does not resend a password to a redirected address. Check that "
    "the portal URL is the one your organisation publishes."
)
_HOST_INVALID_MESSAGE = (
    "That portal address is not a usable hostname. Check the URL, for example "
    "https://your-org.maps.arcgis.com."
)
_PORTAL_NOT_HTTPS_MESSAGE = (
    "The portal URL must start with https. GeoLens will not send a password "
    "over an unencrypted connection."
)
_TOKEN_SERVICE_NOT_HTTPS_MESSAGE = (
    "That portal directs sign-in to an unencrypted address, so GeoLens did "
    "not send the password. The portal URL is https; the token service it "
    "names is not."
)

# Audit-only outcomes. The caller sees `arcgis_signin_rejected` for the first
# two of these and cannot tell them apart; the operator can.
AUDIT_SUCCESS = "success"
AUDIT_INVALID_CREDENTIALS = "invalid_credentials"
AUDIT_ACCOUNT_LOCKED = "account_locked"
AUDIT_SSO_ACCOUNT = "sso_account"
AUDIT_SSRF_BLOCKED = "ssrf_blocked"
AUDIT_UNREACHABLE = "unreachable"
AUDIT_TIMEOUT = "timeout"
AUDIT_UNREADABLE = "unreadable_response"
AUDIT_CONCURRENT = "concurrent_attempt"
AUDIT_RATE_LIMITED = "rate_limited"
AUDIT_PORTAL_NOT_HTTPS = "portal_not_https"
AUDIT_HOST_INVALID = "portal_host_invalid"
AUDIT_TOKEN_SERVICE_NOT_HTTPS = "token_service_not_https"
AUDIT_TOKEN_SERVICE_REDIRECT = "token_service_redirect"
# fix(#1758): discovery runs before a credential exists, so its
# failures are uncounted (`network_error` to the caller) — an unreachable
# portal must not spend a real account's attempt budget.
AUDIT_DISCOVERY_UNREACHABLE = "discovery_unreachable"
AUDIT_DISCOVERY_TIMEOUT = "discovery_timeout"
# fix(#1758): a NOTE on the sign-in's outcome, not a result itself
# — the attempt proceeds against the conventional endpoint. Records that
# the portal tried to redirect the password somewhere untrusted.
AUDIT_DISCOVERY_UNTRUSTED_DELEGATE = "discovery_untrusted_delegate"
# fix(#1775, audit): cancellation-only outcome (worker shutdown; a client
# disconnect never reaches here on pinned Starlette 1.6.0). The attempt is
# reserved BEFORE the POST, so no cancellation makes it free either way.
AUDIT_CANCELLED = "cancelled"

# The outcomes above that are NOT an attempt against ArcGIS, because GeoLens
# refused before any credential left the process. The route's shared attempt
# counter subtracts these; everything else counts, a transport failure
# included, because by then the POST had been made or was about to be.
UNCOUNTED_SIGNIN_RESULTS = frozenset(
    {
        AUDIT_CONCURRENT,
        AUDIT_RATE_LIMITED,
        AUDIT_SSRF_BLOCKED,
        AUDIT_PORTAL_NOT_HTTPS,
        AUDIT_TOKEN_SERVICE_NOT_HTTPS,
        AUDIT_HOST_INVALID,
        AUDIT_DISCOVERY_UNREACHABLE,
        AUDIT_DISCOVERY_TIMEOUT,
    }
)

# Phrases naming a federated identity vs a wrong password, matched over
# provider text that is classified then discarded (never logged/audited/
# returned). Plain membership tests, not a pattern — avoids quadratic input.
_FEDERATED_WORDS = frozenset({"sso", "saml", "mfa", "idp", "oauth"})
_FEDERATED_PHRASES = (
    "single sign",
    "identity provider",
    "federated",
    "multifactor",
    "multi-factor",
    "two-factor",
    "two factor",
    "enterprise login",
)
_LOCKOUT_PHRASES = (
    "locked",
    "too many",
    "disabled",
    "temporarily blocked",
)


@dataclass(frozen=True)
class MintedToken:
    """One portal token and the instant it stops working."""

    token: str
    expires_at: datetime


class ArcGISSignInError(Exception):
    """A sign-in attempt that produced no token, already classified.

    Carries only the classification: the code the caller sees, the prose the
    caller sees, the HTTP status, and the finer-grained outcome for the audit
    row. Provider text never reaches it, so neither an exception string nor a
    chained traceback can echo an ArcGIS message back to the browser.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        audit_result: str,
        field: str = "credential",
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.audit_result = audit_result
        self.field = field
        super().__init__(code)


def _ssrf_refused() -> ArcGISSignInError:
    return ArcGISSignInError(
        code=SSRF_REFUSED,
        message=_SSRF_MESSAGE,
        status_code=400,
        audit_result=AUDIT_SSRF_BLOCKED,
        field="url",
    )


def _unreachable() -> ArcGISSignInError:
    return ArcGISSignInError(
        code=NETWORK_ERROR,
        message=_UNREACHABLE_MESSAGE,
        status_code=502,
        audit_result=AUDIT_UNREACHABLE,
        field="url",
    )


def _timed_out() -> ArcGISSignInError:
    return ArcGISSignInError(
        code=NETWORK_ERROR,
        message=_TIMEOUT_MESSAGE,
        status_code=504,
        audit_result=AUDIT_TIMEOUT,
        field="url",
    )


def _redirected() -> ArcGISSignInError:
    """fix(#1758): token service answered with a 3xx.

    Counted as an attempt, not a refusal, since the credential was already
    on the wire. Never follow it: httpx replays the form body on a 307/308
    to a response-chosen target, resending the password cross-origin in
    cleartext — SSRF revalidation doesn't catch this since http-on-public
    isn't a private-target violation.
    """
    return ArcGISSignInError(
        code=NETWORK_ERROR,
        message=_REDIRECTED_MESSAGE,
        status_code=502,
        audit_result=AUDIT_TOKEN_SERVICE_REDIRECT,
        field="url",
    )


def _invalid_host() -> ArcGISSignInError:
    """fix(#1758): the portal host does not canonicalize.

    Refused before anything is on the wire — every limit here is keyed on
    the host, and a host with no single spelling can't be counted.
    """
    return ArcGISSignInError(
        code=HOST_INVALID,
        message=_HOST_INVALID_MESSAGE,
        status_code=422,
        audit_result=AUDIT_HOST_INVALID,
        field="url",
    )


def _not_https(message: str, audit_result: str) -> ArcGISSignInError:
    """fix(#1758): refuse to POST a password over cleartext.

    ``validate_url_for_ssrf`` allows http for reads, but a password in the
    request body over http hands it to anyone on the path. Checked for
    both the portal URL and its advertised token service, before the POST.
    """
    return ArcGISSignInError(
        code=NOT_HTTPS,
        message=message,
        status_code=422,
        audit_result=audit_result,
        field="url",
    )


def _discovery_unreachable() -> ArcGISSignInError:
    """The portal could not be reached while working out where to send the
    password. Same answer to the caller as any other unreachable portal, and
    uncounted, because nothing was sent."""
    return ArcGISSignInError(
        code=NETWORK_ERROR,
        message=_UNREACHABLE_MESSAGE,
        status_code=502,
        audit_result=AUDIT_DISCOVERY_UNREACHABLE,
        field="url",
    )


def _discovery_timed_out() -> ArcGISSignInError:
    return ArcGISSignInError(
        code=NETWORK_ERROR,
        message=_TIMEOUT_MESSAGE,
        status_code=504,
        audit_result=AUDIT_DISCOVERY_TIMEOUT,
        field="url",
    )


def _unreadable() -> ArcGISSignInError:
    return ArcGISSignInError(
        code=NETWORK_ERROR,
        message=_UNREADABLE_MESSAGE,
        status_code=502,
        audit_result=AUDIT_UNREADABLE,
        field="url",
    )


def _numeric_ipv4(host: str) -> str | None:
    """Canonical dotted-quad for an IPv4 written in shorthand.

    ``ipaddress`` only accepts full four-octet decimal, but the resolver
    also reaches 127.0.0.1 via ``127.1``, ``0x7f.0.0.1`` etc., so those
    must bucket the same. ``inet_aton`` parses these forms (no I/O despite
    living in ``socket``), guarded to unambiguously numeric/dotted input
    since it would also accept a bare ``1`` that the resolver treats as a
    hostname; anything else returns None and falls through to IDNA.
    """
    labels = host.split(".")
    if len(labels) < 2:
        return None
    for label in labels:
        if label.isdigit():
            continue
        lowered = label.lower()
        if (
            lowered.startswith("0x")
            and len(lowered) > 2
            and all(character in "0123456789abcdef" for character in lowered[2:])
        ):
            continue
        return None
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return None
    return str(ipaddress.ip_address(packed))


def canonical_host(raw: str) -> str:
    """One spelling per destination, for hashing, locking and comparing.

    fix(#1758): host-keyed limits need one bucket per destination.
    IDNA/ASCII form, case, a trailing root dot, and IPv4/IPv6 literal
    shorthand (e.g. ``127.1``) can all name the same origin differently.

    Order: strip IPv6 brackets, drop a trailing root dot, take the IP
    literal's canonical form if applicable, else IDNA/UTS 46 + lowercase.
    Raises on anything unbucketable — an unlimited host is not a safe one.
    """
    host = raw.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host.endswith(".") and not host.endswith(".."):
        host = host[:-1]
    if not host:
        raise _invalid_host()
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    numeric = _numeric_ipv4(host)
    if numeric is not None:
        return numeric
    try:
        # uts46=True applies the mapping (case folding, width, disallowed
        # characters) rather than only the ToASCII conversion.
        return idna.encode(host, uts46=True).decode("ascii").lower()
    except (idna.IDNAError, UnicodeError, ValueError):
        raise _invalid_host() from None


def _canonical_url(raw: str | httpx.URL) -> httpx.URL:
    """One normalized ``httpx.URL``, host included.

    fix(#1758): scope must come from ``httpx.URL`` itself, since
    it removes dot segments, lowercases scheme/host, decodes percent-
    encoding and applies IDNA — ``urlsplit`` does none of that and kept
    ``/a/../sharing/rest`` verbatim while httpx sent it to ``/sharing/rest``,
    letting a caller rotate ``/a/../``, ``/b/../`` for a fresh key/lock/
    ledger bucket per spelling while every POST hit one ArcGIS account.

    Still passed through :func:`canonical_host`, since httpx keeps a
    trailing root dot and decodes punycode to Unicode — the opposite of
    the one spelling this endpoint keys on. Rebuilt with ``copy_with``,
    not compared, so the hashed address is the address contacted.
    """
    url = raw if isinstance(raw, httpx.URL) else httpx.URL(raw)
    # fix(#1758): httpx decodes `%2e` to `.` in the exposed path,
    # but removes dot segments before that decode, so `/a/%2e%2e/sharing`
    # survives as `/a/../sharing`. Re-parsing the decoded form fixes it.
    #
    # fix(#1758): iterate to a FIXED POINT, not N passes — 10-deep
    # encoding bypassed the old 4-pass cap, hit the wire as `%252e%252e`, and
    # a proxy+ArcGIS decoded it to `..` between them. Bound = input length,
    # since each effective pass strictly shortens the path.
    for _ in range(len(url.path) + 1):
        reparsed = httpx.URL(f"{url.scheme}://{url.netloc.decode()}{url.path}")
        if reparsed.path == url.path:
            break
        url = url.copy_with(path=reparsed.path)
    return url.copy_with(host=canonical_host(url.host or ""))


def usable_service_url(raw: str | httpx.URL) -> httpx.URL | None:
    """THE canonicalizer. Every URL in this module goes through this one.

    fix(#1758): refused, not repaired — a URL still holding
    ``..``, an empty segment, a query, fragment or userinfo after
    normalization has an ambiguous scope, and the conventional endpoint is
    always available instead.

    fix(#1758): "every URL" is the point — the portal URL, its
    advertised token service, and the composed fallback used to each get
    their own normalization (e.g. a separate ``urlsplit`` path that missed
    percent-encoded dot segments), giving one endpoint several scopes.
    """
    try:
        url = _canonical_url(raw)
    except (httpx.InvalidURL, ArcGISSignInError, ValueError, UnicodeError):
        return None
    if url.query or url.fragment or url.userinfo:
        return None
    # fix(#1758): whatever survives the fixed point could still be
    # decoded downstream. `%2e`/`%2f`/`%5c` change what path is addressed,
    # so a stable form keeping one — or an incomplete escape — is refused.
    stable_path = url.path
    for index, character in enumerate(stable_path):
        if character != "%":
            continue
        escape = stable_path[index : index + 3]
        if len(escape) < 3 or not all(c in string.hexdigits for c in escape[1:]):
            return None
        if escape.lower() in ("%2e", "%2f", "%5c"):
            return None
    if "\\" in stable_path:
        # httpx decodes `%5c` to a literal backslash, which IIS (many
        # ArcGIS Enterprise adaptors) treats as a path separator, colliding
        # `/\\sharing` with `/sharing` under two scopes.
        return None
    if url.port == 0:
        # fix(#1758): port 0 addresses nothing but is FALSEY, so
        # scope derivation read "no port" and filed those failures under
        # the real :443 bucket — 3 against a victim's username exhausted
        # that account's cluster-global budget and 429'd every tenant.
        return None
    # segments[0] is "" before a leading slash on any absolute path — the
    # only legitimate empty one. A bare root path "/" is that one segment.
    segments = url.path.split("/")[1:]
    if segments == [""]:
        segments = []
    if any(segment in ("", "..") for segment in segments):
        return None
    return url


def canonical_token_service_scope(url: str | httpx.URL) -> str:
    """The identity every sign-in limit is keyed on: ``host:port/webadaptor``.

    fix(#1758): host alone isn't the account store — two Enterprise
    portals can share a hostname and differ only by port or web-adaptor
    path, as independent installations with independent user directories,
    so host-only keying let attempts against one exhaust/serialize the other.

    Port is always made explicit from the scheme; path keeps its case
    (server-sensitive) but drops a trailing ``/generateToken``. The
    :func:`_is_trusted_delegate` binding still uses the host alone —
    installation identity and delegation trust are different questions.
    """
    normalized = _canonical_url(url)
    # `.host` reads back DECODED: httpx stores the ASCII form it will send but
    # renders punycode as Unicode, so the ASCII spelling this endpoint keys on
    # has to be asked for again rather than read off the object.
    host = canonical_host(normalized.host or "")
    if ":" in host:  # an IPv6 literal needs its brackets back in an authority
        host = f"[{host}]"
    # `is None`, never truthy: a falsey-but-explicit port must not alias the
    # scheme default. Second half of the port-0 fix in `usable_service_url`.
    default_port = 443 if normalized.scheme == "https" else 80
    port = default_port if normalized.port is None else normalized.port
    path = normalized.path
    if path.lower().endswith("/generatetoken"):
        path = path[: -len("/generateToken")]
    path = path.rstrip("/")
    return f"{host}:{port}{path}"


def canonical_portal_host(portal_url: str) -> str:
    """The canonical host of *portal_url*, or a refusal.

    Never the path, never a query, never userinfo: this value is written to
    an audit row and used as a lock and budget key, and all three want the
    origin rather than the address.
    """
    try:
        host = urlsplit(portal_url).hostname
    except ValueError:
        raise _invalid_host() from None
    if not host:
        raise _invalid_host()
    return canonical_host(host)


def portal_host(portal_url: str) -> str:
    """The non-raising form, for the rate-limit key only.

    The SlowAPI key function runs before the handler and must not fail the
    request it is describing, so an unusable host answers ``"unknown"`` there
    and is refused a moment later by :func:`canonical_portal_host`.
    """
    try:
        return canonical_portal_host(portal_url)
    except ArcGISSignInError:
        return "unknown"


def _account_digest_key() -> bytes:
    """The HMAC key for :func:`signin_account_key`, derived from the JWT secret.

    Derived rather than used directly, following the HKDF pattern at
    ``modules/auth/oauth/encryption.py:14-27``, so this digest shares no key
    material with anything else that secret protects. Not cached: the secret
    is process configuration, and a cache would outlive a test or a rotation
    that changes it while costing a few microseconds to skip.
    """
    kdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_ACCOUNT_KEY_SALT,
        info=_ACCOUNT_KEY_INFO,
    )
    return kdf.derive(settings.jwt_secret_key.get_secret_value().encode())


def signin_account_key(host: str, username: str) -> str:
    """A stable, non-reversible handle for the ArcGIS account being signed into.

    fix(#1758): keyed to the ARCGIS account, not the GeoLens user —
    Esri locks after 5 failed sign-ins per account in 15 minutes, so two
    GeoLens users at 3 attempts each would otherwise total 6 against one
    colleague's account. Both the counter and the advisory lock use this.

    HMAC, not a bare hash: a plain SHA-256 of host+username is a dictionary
    away from the username, and this digest is written to an audit row that
    outlives the request. Username itself is never stored, logged or
    returned. Casefolded (ArcGIS sign-in is case-insensitive) and
    length-prefixed so two spellings bucket together and no (host, username)
    pair collides by boundary-shifting.
    """
    normalized = username.strip().casefold()
    message = f"{len(host)}:{host}:{len(normalized)}:{normalized}".encode()
    return hmac.new(_account_digest_key(), message, hashlib.sha256).hexdigest()


def signin_user_key(user_id: object, scope: str) -> str:
    """A keyed handle for the CALLER half of the budget, and its destination.

    fix(#1775): budget counts from the ledger, not ``audit_logs`` — under
    reserve-then-settle the audit row is written only after the POST, so a
    cancelled request would undercount there.

    fix(#1758): keyed and length-prefixed like
    :func:`signin_account_key`, under the same derived key, because
    ``arcgis_signin_attempts`` sits outside the tenant RLS boundary and must
    hold no plaintext caller/tenant identifier.

    Digests user_id AND token-service scope together — the budget is per
    (caller, scope), matching the advisory lock key
    ``user:<id>:host:<scope>``; digesting the id alone would silently widen
    a per-destination limit into a global one. A distinct domain tag keeps
    this from colliding with :func:`signin_account_key`'s digest.
    """
    ident = str(user_id)
    message = f"signin-user:{len(ident)}:{ident}:{len(scope)}:{scope}".encode()
    return hmac.new(_account_digest_key(), message, hashlib.sha256).hexdigest()


def signin_referer() -> str:
    """The ``referer`` form value generateToken binds the token to (D8).

    The instance's own public URL when it has one, otherwise the constant in
    Esri's documented sample. Stable per instance by construction, because a
    token bound to a value that varies per request is a token that works once
    and then does not.
    """
    for candidate in (settings.public_base_url, settings.public_app_url):
        if candidate and candidate.strip():
            return candidate.strip()
    return DEFAULT_SIGNIN_REFERER


def _rest_base(portal: httpx.URL) -> httpx.URL:
    """The ``/sharing/rest`` base of an ALREADY canonical portal URL.

    Accepts both the portal root and the REST base itself. Split and
    rejoin, not pattern-match — a URL regex is a ReDoS surface on
    caller-controlled input.

    fix(#1758): takes the ``httpx.URL`` :func:`usable_service_url`
    already produced rather than re-parsing the string — its own prior
    ``urlsplit`` resolved no percent-encoded dot segments, so
    ``/a/%2e%2e`` and ``/b/%2e%2e`` gave one destination two scopes.
    """
    segments = [segment for segment in portal.path.split("/") if segment]
    lowered = [segment.lower() for segment in segments]
    if lowered[-2:] == ["sharing", "rest"]:
        segments = segments[:-2]
    elif lowered[-1:] == ["sharing"]:
        segments = segments[:-1]
    return portal.copy_with(path="/" + "/".join([*segments, "sharing", "rest"]))


async def _fetch_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    data: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> tuple[int, Any | None]:
    """Fetch *url* and return its status and its parsed body, or ``None``.

    ``None`` covers anything unusable: a page instead of a document, a body
    too large, or a compressed one. Streamed with a byte cap on RAW
    transport bytes (fix(#1758)) rather than ``response.json()``,
    so a compressed body can't expand past the cap inside the decoder.

    ``data`` is form-encoded by httpx (percent-escaped), so a password
    can't smuggle a field separator — no extra character policy needed.

    ``follow_redirects`` is a PER-REQUEST override on the shared safe
    client (fix(#1758)), not a second client — ``make_safe_client``
    is the only sanctioned constructor and a second one would lose the
    guard transport and trip the Rule 2 hook. The credential POST passes
    ``False``; see :func:`_redirected`.
    """
    raw = bytearray()
    async with client.stream(
        method,
        url,
        data=data,
        # fix(#1758): `identity` — nothing here benefits from
        # compression, and a compressed body is a decoder bomb risk.
        headers={"Accept": "application/json", "Accept-Encoding": "identity"},
        follow_redirects=follow_redirects,
    ) as response:
        # A portal is free to ignore the header, so the answer is checked too.
        # Refused rather than decoded: `aiter_bytes` decodes each transport
        # chunk BEFORE yielding it, so a few kilobytes of gzip becomes hundreds
        # of megabytes inside the decoder before any cap on the output can
        # look at it. There is nothing to salvage from a body this module
        # asked not to be sent.
        encoding = response.headers.get("content-encoding", "").strip().lower()
        if encoding and encoding != "identity":
            return response.status_code, None
        # `aiter_raw`, not `aiter_bytes`: the cap has to bound what arrives on
        # the wire rather than what a decoder produces from it.
        async for chunk in response.aiter_raw():
            raw.extend(chunk)
            if len(raw) > _MAX_RESPONSE_BYTES:
                # Leaving the context manager closes the response, so nothing
                # keeps arriving. At most one chunk is read past the cap.
                return response.status_code, None
        try:
            return response.status_code, json.loads(raw)
        except (ValueError, RecursionError):
            # fix(#1858): `RecursionError` joins `ValueError` — nested JSON
            # can hit CPython's stack limit (~120k levels measured on 3.14)
            # before the `_MAX_RESPONSE_BYTES` cap (~131k levels) does. As a
            # `RuntimeError`, it used to escape into the transport handler
            # as `unreachable`, mislabeling a portal that answered fine;
            # `unreadable_response` is correct here.
            return response.status_code, None


_ARCGIS_ONLINE_DOMAIN = "arcgis.com"


def _is_trusted_delegate(portal: str, delegate: str) -> bool:
    """Whether *portal* may hand the password to *delegate*.

    fix(#1758): ``tokenServicesUrl`` used to be followed to any
    https+SSRF-clean host, making discovery a credential redirect vector.

    fix(#1758): the replacement ("portal host minus its leftmost
    label") was a public-suffix bug in disguise — for ``agency.co.uk`` it
    yields ``co.uk``, so ``attacker.co.uk`` read as a sibling. No string-only
    rule fixes that without a public-suffix list, which this module won't
    carry.

    Bound is now decidable from the two strings alone: same host, a
    subdomain of the portal host, or anything under ``arcgis.com`` (where
    ArcGIS Online delegates). A sibling Enterprise federation host falls
    back to the portal's own ``generateToken`` — the same fallback every
    other refused delegation uses.
    """
    if not portal or not delegate:
        return False
    if delegate == portal:
        return True
    if delegate == _ARCGIS_ONLINE_DOMAIN or delegate.endswith(
        f".{_ARCGIS_ONLINE_DOMAIN}"
    ):
        return True
    return delegate.endswith(f".{portal}")


async def _discover_token_service(
    client: httpx.AsyncClient, rest_base: httpx.URL
) -> tuple[httpx.URL, str | None]:
    """The portal's advertised token service, or the conventional default.

    ``authInfo.tokenServicesUrl`` is the documented route, legitimately a
    different host for federated Enterprise. Re-validated for SSRF before
    being followed — the portal isn't trusted to name its own token
    service — separately from the guard transport's connect-time check,
    which would report the refusal as a transport failure, not a policy one.

    A transport-level discovery failure falls back to the conventional URL
    rather than failing here, giving sign-in one failure path to classify.

    fix(#1758): discovery GET never follows redirects — any 3xx
    falls back. An https-to-http hop would hand the discovery document to
    anyone on the path, and a rewritten response could name an attacker's
    https token service that passes every later check. Not following at
    all is stricter and simpler than judging each hop.

    Returns the URL to POST to and, when the portal named a delegate this
    instance won't follow, a note for the audit row.
    """
    # fix(#1758): composed from the canonical portal and put through
    # the same function every other URL here takes, so the endpoint a caller
    # falls back to cannot be a spelling of its own.
    fallback = usable_service_url(f"{rest_base}/generateToken")
    if fallback is None:  # unreachable: rest_base is already canonical
        raise _invalid_host()
    try:
        status_code, payload = await _fetch_json(
            client, "GET", f"{rest_base}/info?f=json", follow_redirects=False
        )
    except httpx.HTTPError:
        return fallback, None
    except SSRFError:
        # fix(#1758): `_revalidate_redirect` fires on every
        # response, so a 3xx with a private/unresolvable Location raises
        # before the status can be read — same case as the 3xx branch
        # below: fall back rather than report `ssrf_refused` for a portal
        # that's merely misconfigured. Discovery ONLY; the credential POST
        # still refuses on this, since by then the password is on the wire.
        return fallback, None
    if 300 <= status_code < 400:
        # Never followed. The conventional endpoint on the portal origin that
        # was already validated is what this falls back to.
        return fallback, None
    if status_code >= 400 or not isinstance(payload, dict):
        return fallback, None
    auth_info = payload.get("authInfo")
    candidate = (
        auth_info.get("tokenServicesUrl") if isinstance(auth_info, dict) else None
    )
    if not isinstance(candidate, str):
        return fallback, None
    candidate = candidate.strip()
    if not candidate or len(candidate) > 2048:
        return fallback, None
    # fix(#1758): normalized ONCE, here, into the object the POST is
    # later sent with, so the scope, the delegate check and the destination
    # are all readings of one value rather than three parses of a string.
    normalized = usable_service_url(candidate)
    if normalized is None:
        # An advertised URL nobody can parse, or one that still argues with
        # itself after normalization, is no more usable than an absent one,
        # and the conventional URL is what the portal would have meant.
        return fallback, None
    # fix(#1758): delegate check FIRST — it's the only pure one
    # of the three. Checking https/resolving before delegate-trust turned
    # an untrusted-but-private/unresolvable candidate into `ssrf_refused`
    # or a network error, instead of the same clean fallback any other
    # untrusted delegate gets.
    if not _is_trusted_delegate(
        canonical_host(rest_base.host), canonical_host(normalized.host)
    ):
        return fallback, AUDIT_DISCOVERY_UNTRUSTED_DELEGATE
    if normalized.scheme != "https":
        raise _not_https(
            _TOKEN_SERVICE_NOT_HTTPS_MESSAGE, AUDIT_TOKEN_SERVICE_NOT_HTTPS
        )
    # The fallback needs no check of its own here: it sits on the portal
    # origin, which `_resolve_token_service` validated before discovery ran.
    await validate_url_for_ssrf(str(normalized))
    return normalized, None


def _provider_text(error: Any) -> str:
    """The lowercased text of an ArcGIS error envelope, for classification.

    Read by the two predicates below then dropped — never logged, audited
    or returned: provider prose about an account is what this endpoint
    exists to keep out of a response body.
    """
    if not isinstance(error, dict):
        return ""
    pieces: list[str] = []
    message = error.get("message")
    if isinstance(message, str):
        pieces.append(message)
    details = error.get("details")
    if isinstance(details, list):
        pieces.extend(item for item in details if isinstance(item, str))
    elif isinstance(details, str):
        pieces.append(details)
    return " ".join(pieces).lower()


def _names_federated_identity(text: str) -> bool:
    if any(phrase in text for phrase in _FEDERATED_PHRASES):
        return True
    words = {
        word
        for word in "".join(
            character if character.isalnum() else " " for character in text
        ).split()
    }
    return bool(words & _FEDERATED_WORDS)


def _names_lockout(text: str) -> bool:
    """Whether a refusal names a locked account. Audit-only; see the docstring."""
    return any(phrase in text for phrase in _LOCKOUT_PHRASES)


async def _portal_blocks_builtin_signin(
    client: httpx.AsyncClient, rest_base: str
) -> bool:
    """Whether the portal reports that built-in ArcGIS sign-in is turned off.

    ``portals/self``'s ``canSignInArcGIS`` is the org-wide federated signal;
    the message half catches per-account MFA. Asked only after a refusal
    (no extra request on the happy path), anonymous, no credential.

    Any failure answers "no" — a portal that won't answer an anonymous
    question is not evidence about how its members sign in.
    """
    try:
        status_code, payload = await _fetch_json(
            client, "GET", f"{rest_base}/portals/self?f=json"
        )
    except (httpx.HTTPError, SSRFError):
        return False
    if status_code >= 400 or not isinstance(payload, dict):
        return False
    return payload.get("canSignInArcGIS") is False


async def _classify_refusal(
    client: httpx.AsyncClient, rest_base: str, error: Any
) -> ArcGISSignInError:
    text = _provider_text(error)
    if _names_federated_identity(text) or await _portal_blocks_builtin_signin(
        client, rest_base
    ):
        return ArcGISSignInError(
            code=SSO_ACCOUNT,
            message=_SSO_MESSAGE,
            status_code=400,
            audit_result=AUDIT_SSO_ACCOUNT,
        )
    return ArcGISSignInError(
        code=SIGNIN_REJECTED,
        message=_REJECTED_MESSAGE,
        status_code=400,
        audit_result=(
            AUDIT_ACCOUNT_LOCKED if _names_lockout(text) else AUDIT_INVALID_CREDENTIALS
        ),
    )


def _minted_from(payload: Any) -> MintedToken:
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise _unreadable()
    expires = payload.get("expires")
    if isinstance(expires, (int, float)) and not isinstance(expires, bool):
        try:
            # ArcGIS reports the expiry as epoch MILLISECONDS.
            return MintedToken(token, datetime.fromtimestamp(expires / 1000, tz=UTC))
        except (OverflowError, OSError, ValueError):
            pass
    return MintedToken(
        token,
        datetime.now(tz=UTC) + timedelta(minutes=SIGNIN_EXPIRATION_MINUTES),
    )


class PortalSignIn:
    """One portal, resolved to its token service and ready to be signed in to.

    fix(#1758): two phases because the LIMITS need it — discovery
    is credential-free and answers "which host receives this password",
    with every lock/budget keyed on that host, not the address the caller
    typed. Otherwise a caller with a wildcard domain could point a hundred
    hostnames at one victim's token service for a hundred fresh budgets.

    Phase one hands back this object; the caller takes its locks and reads
    budgets against :attr:`host`, then calls :meth:`mint`.
    """

    __slots__ = ("_client", "_rest_base", "discovery_note", "scope", "token_service")

    def __init__(
        self,
        client: httpx.AsyncClient,
        token_service: httpx.URL,
        scope: str,
        rest_base: httpx.URL,
        discovery_note: str | None = None,
    ) -> None:
        self._client = client
        self._rest_base = rest_base
        #: Set when the portal named a delegate this instance would not
        #: follow. The sign-in went on against the conventional endpoint; this
        #: is what tells an operator the portal tried.
        self.discovery_note = discovery_note
        #: The URL the credential POST goes to, already normalized. Held as
        #: an ``httpx.URL`` (fix(#1758)) because that is what the
        #: scope was derived from, so the two cannot diverge.
        self.token_service = token_service
        #: The canonical ``host:port/webadaptor`` of the destination that
        #: will receive the password, and the only thing this endpoint's
        #: limits are keyed on. An installation, not just a hostname: see
        #: :func:`canonical_token_service_scope`.
        self.scope = scope

    async def mint(self, username: str, password: str) -> MintedToken:
        """Post the credentials and return the token, or raise a classified error.

        Raises :class:`ArcGISSignInError` for everything; no other exception
        escapes — an ``httpx.RequestError`` holds the request whose encoded
        body is the password, so a foreign traceback with frame locals is a
        leak. Nothing is chained either, for the same reason.

        fix(#1758): deadline is HERE, around the network call, not
        the caller's whole block — what runs after is the ledger insert and
        audit commit, and a cancellation there leaves a failed transaction
        with the outcome unrecorded. Outcome decided inside the scope,
        written outside it.
        """
        form = {
            "f": "json",
            "username": username,
            "password": password,
            # Both mandatory and paired: see the module docstring.
            "client": "referer",
            "referer": signin_referer(),
            "expiration": str(SIGNIN_EXPIRATION_MINUTES),
        }
        try:
            async with asyncio.timeout(_MINT_DEADLINE_SECONDS):
                return await self._post_credentials(form)
        except ArcGISSignInError:
            raise
        except SSRFResolutionError:
            raise _unreachable() from None
        except SSRFError:
            raise _ssrf_refused() from None
        except (TimeoutError, httpx.TimeoutException):
            raise _timed_out() from None
        except Exception as exc:  # broad: see the docstring, nothing escapes
            logger.warning(
                "ArcGIS sign-in transport failure",
                token_service_host=self.scope,
                error_type=type(exc).__name__,
            )
            raise _unreachable() from None

    async def _post_credentials(self, form: dict[str, str]) -> MintedToken:
        """The one credential POST, and the reading of what came back."""
        # One POST, and never a second one, for two reasons that end in the
        # same rule. A retry loop locks a customer's real ArcGIS account, and
        # a followed redirect replays the form body, so the second request
        # would carry the password to an address the response picked.
        try:
            status_code, payload = await _fetch_json(
                self._client,
                "POST",
                self.token_service,
                data=form,
                follow_redirects=False,
            )
        except SSRFError:
            # fix(#1758): the safe client's per-hop hook fires on
            # every response, so a 3xx with a private Location raises here
            # before the status is seen. Left to the outer handler this
            # would record `ssrf_blocked` (excluded from budget) — wrong
            # here, since the password was already on the wire; same
            # caller-facing answer as any redirect, and it counts.
            raise _redirected() from None
        if 300 <= status_code < 400:
            raise _redirected()
        if status_code >= 400 or payload is None:
            raise _unreadable()
        error = payload.get("error") if isinstance(payload, dict) else None
        if error is not None:
            raise await _classify_refusal(self._client, self._rest_base, error)
        return _minted_from(payload)


async def _resolve_token_service(
    client: httpx.AsyncClient, portal_url: str
) -> tuple[httpx.URL, str, httpx.URL, str | None]:
    """Phase one: where will the password actually go, and is that allowed.

    Returns the token-service URL, its canonical ``host:port/webadaptor``
    scope, the portal's REST base and any discovery note. Every failure
    here classifies as a DISCOVERY failure and is uncounted, since no
    credential is anywhere near the wire — counting it would let an
    unreachable portal spend a real account's lockout budget.
    """
    try:
        # fix(#1758): the caller's URL takes the same road as every
        # other URL in this module, and it takes it FIRST. Before the SSRF
        # check, so neither refusal costs a DNS lookup, and long before
        # anything is on the wire.
        portal = usable_service_url(portal_url)
        if portal is None:
            raise _invalid_host()
        if portal.scheme != "https":
            raise _not_https(_PORTAL_NOT_HTTPS_MESSAGE, AUDIT_PORTAL_NOT_HTTPS)
        await validate_url_for_ssrf(str(portal))
        rest_base = _rest_base(portal)
        # `_discover_token_service` re-validates the advertised URL for https
        # and for SSRF before it is returned, so the host below is one this
        # instance is allowed to send a password to.
        token_service, note = await _discover_token_service(client, rest_base)
        return (
            token_service,
            canonical_token_service_scope(token_service),
            rest_base,
            note,
        )
    except ArcGISSignInError:
        raise
    except SSRFResolutionError:
        # A name that does not resolve is a fact about the ORIGIN, not a
        # GeoLens policy refusal. Reporting it as the latter sends an operator
        # to audit egress policy for a portal that is simply misspelled.
        raise _discovery_unreachable() from None
    except SSRFError:
        raise _ssrf_refused() from None
    except (TimeoutError, httpx.TimeoutException):
        raise _discovery_timed_out() from None
    except ValueError:
        # A malformed authority, such as a non-numeric port or a broken IPv6
        # literal, which both urlsplit and .port raise on. Ordered after the
        # SSRF clauses because SSRFError is itself a ValueError.
        raise _discovery_unreachable() from None
    except Exception as exc:  # broad: nothing foreign escapes this module
        logger.warning(
            "ArcGIS sign-in discovery failure",
            error_type=type(exc).__name__,
        )
        raise _discovery_unreachable() from None


@contextlib.asynccontextmanager
async def open_portal_signin(portal_url: str) -> AsyncIterator[PortalSignIn]:
    """Resolve a portal's token service and hold the client open for the mint.

    fix(#1758): deadline covers DISCOVERY only; the yield is
    outside it. It used to span the caller's block too, so a cancellation
    could land in the ledger insert or audit commit between phases, leaving
    a failed transaction and a 500 with nothing recorded — a sign-in that
    reached the wire without spending its budget. The mint carries its own
    deadline for the same reason. Only ``TimeoutError`` is converted here;
    anything else the caller raises inside the block passes through
    untouched.
    """
    async with make_safe_client(timeout=PROBE_TIMEOUT) as client:
        try:
            async with asyncio.timeout(_DISCOVERY_DEADLINE_SECONDS):
                token_service, scope, rest_base, note = await _resolve_token_service(
                    client, portal_url
                )
        except ArcGISSignInError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise _discovery_timed_out() from None
        yield PortalSignIn(client, token_service, scope, rest_base, note)


async def mint_portal_token(
    portal_url: str, username: str, password: str
) -> MintedToken:
    """Both phases in one call, for callers that need no scope in between.

    The route does not use this: it needs the token-service scope from phase
    one to key its locks and budgets before phase two runs. This is the shape
    the rest of the codebase and the tests can hold on to.
    """
    async with open_portal_signin(portal_url) as portal:
        return await portal.mint(username, password)


# fix(#1758): the in-flight guard that used to live here was a
# process-local set, which is worth nothing on an install that runs two
# uvicorn workers. It is now a PostgreSQL advisory lock next to the route,
# because the shared state a stock install has is the database.
