"""Mint a short-lived ArcGIS portal token from a username and a password.

This is the protocol half of ``POST /services/arcgis/signin/``; the abuse
controls that make the endpoint safe to expose live next to the route in
``router.py``. The user hands GeoLens a portal URL and their ArcGIS
credentials, GeoLens asks that portal's own token service for a token, and
the token goes straight back to the browser, which then puts it in the
``token`` field that probe, preview, commit and refresh already read. No
existing door changes.

Nothing here is persisted. The password exists for the duration of one
outbound POST and the token for the duration of one response: no row, no
cache, no task argument, no log field.

Four protocol facts that are not obvious from the vendor documentation and
that a reader will otherwise re-derive:

* ``client=referer`` plus a ``referer`` FORM FIELD is mandatory. A token
  minted with ``client=requestip`` is accepted by the portal and then
  refused with a 498 by the services hosts. That form field is not a
  ``Referer`` HEADER, and GeoLens still sends no such header on any data
  request; the two are independent and only the form field is wanted.
* The referer value must be stable per instance, because the token is bound
  to it. It is never derived from the caller's request.
* Never retry a refusal. ArcGIS locks a built-in account after five failed
  sign-ins in fifteen minutes, so a retry loop here locks a customer's real
  ArcGIS account with GeoLens as the proximate cause. There is no retry in
  this module, and the caller must not add one either.
* Sixty minutes is what to ask for. ArcGIS Online caps a token at fifteen
  days and an Enterprise portal clamps to its own admin cap, so a longer
  expiry postpones the problem of an import outliving its credential
  without solving it, while widening the blast radius of the one token that
  reaches the browser.

The caller-facing error vocabulary is deliberately small. Invalid
credentials and a locked account collapse into one code, because "locked"
proves both that the account exists and that someone has been guessing at
it; the distinction survives in the audit row, where it is the operator's
signal rather than an oracle. The federated-identity code is the one
deliberate disclosure and it stays, because it names a real cause and
points at the working alternative.
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

# One deadline per NETWORK phase, and deliberately not one around the whole
# sign-in. fix(#1758 codex r11): a single scope spanning both phases also
# spanned the caller's durable bookkeeping between them, so a cancellation
# could land inside the ledger insert, the audit flush or the commit. That
# leaves the request session in a failed transaction, and the refusal path
# then ran on an unusable session and 500'd without writing the row, so a
# slow portal could take a credential POST without the budget being spent.
# The phases are bounded; what records the outcome is not.
#
# The per-phase httpx timeouts are the primary bound. These are the backstop
# for what they cannot see, principally the guard transport's DNS resolution,
# and they sum to the 45 seconds the endpoint has always advertised.
_DISCOVERY_DEADLINE_SECONDS = 20.0
_MINT_DEADLINE_SECONDS = 25.0

# Caller-facing codes. The two ArcGIS ones are the whole of this endpoint's
# new vocabulary; the other two are the shapes the probe endpoint already
# returns for the same conditions.
SIGNIN_REJECTED = "arcgis_signin_rejected"
SSO_ACCOUNT = "arcgis_sso_account"
SSRF_REFUSED = "ssrf_refused"
NETWORK_ERROR = "network_error"
# fix(#1758 codex r1): not an ArcGIS outcome. GeoLens refuses before the
# password leaves the process, so it discloses nothing about the account.
NOT_HTTPS = "arcgis_portal_not_https"
# fix(#1758 codex r5): likewise. A host nobody can canonicalize cannot be
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
# fix(#1758 codex r7): discovery runs before any credential exists, so its
# failures are their own outcomes rather than the ones the mint uses. They
# read the same to the caller (`network_error`) and are uncounted, because
# an unreachable portal must not be able to spend a real account's budget.
AUDIT_DISCOVERY_UNREACHABLE = "discovery_unreachable"
AUDIT_DISCOVERY_TIMEOUT = "discovery_timeout"
# fix(#1758 codex r9): not a `result`, a NOTE on one. The sign-in carries on
# against the conventional endpoint, so the attempt has an outcome of its own;
# what this records is that the portal tried to send the password somewhere
# this instance would not follow.
AUDIT_DISCOVERY_UNTRUSTED_DELEGATE = "discovery_untrusted_delegate"

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

# Words and phrases in a refusal that name a federated identity rather than a
# wrong password. Matched over the provider's text, which is classified and
# then discarded: it is never logged, never audited and never returned.
# Plain membership tests rather than a pattern, so no input can make the
# classification quadratic.
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
    """fix(#1758 codex r2): the token service answered the POST with a 3xx.

    Counted as an attempt rather than as a GeoLens-side refusal, because the
    credential was already on the wire to the address the portal named. What
    must not happen is the SECOND request: httpx replays a form body on a 307
    or a 308, and the target is chosen by the response, so following one would
    resend the password wherever it points, cleartext and another origin
    included. The per-hop SSRF revalidation does not close this, because it
    asks whether the target is private and http on a public host is neither.
    """
    return ArcGISSignInError(
        code=NETWORK_ERROR,
        message=_REDIRECTED_MESSAGE,
        status_code=502,
        audit_result=AUDIT_TOKEN_SERVICE_REDIRECT,
        field="url",
    )


def _invalid_host() -> ArcGISSignInError:
    """fix(#1758 codex r5): the portal host does not canonicalize.

    Refused rather than passed through, because every limit on this endpoint
    is keyed on the host and a host that cannot be reduced to one spelling
    cannot be counted. Raised before anything is on the wire.
    """
    return ArcGISSignInError(
        code=HOST_INVALID,
        message=_HOST_INVALID_MESSAGE,
        status_code=422,
        audit_result=AUDIT_HOST_INVALID,
        field="url",
    )


def _not_https(message: str, audit_result: str) -> ArcGISSignInError:
    """fix(#1758 codex r1): refuse to post a password over cleartext.

    ``validate_url_for_ssrf`` allows both http and https, because most of what
    goes through it is a read of a public document where the scheme is the
    origin's business. A sign-in is not that: the password is in the request
    body, so http means handing it to anyone on the path. Refused for the
    portal URL the user typed and for the token service the portal advertises,
    and refused before the POST rather than after it.
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
    """The timeout twin of :func:`_discovery_unreachable`."""
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
    """The canonical dotted-quad for an IPv4 written in a shorthand form.

    ``ipaddress`` deliberately accepts only the full four-octet decimal form,
    but ``127.1``, ``0x7f.0.0.1`` and friends all reach 127.0.0.1 through the
    resolver, so they have to land in one bucket here too. ``inet_aton`` is
    the parser that knows those forms; it does no I/O, despite living in
    ``socket``.

    Guarded to strings that are unambiguously numeric and dotted, because
    ``inet_aton`` would also read a bare ``1`` as an address while the
    resolver would treat it as a hostname. Anything else answers ``None`` and
    goes down the IDNA path.
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

    fix(#1758 codex r5): every limit on this endpoint is keyed on the host,
    so two spellings of one destination were two budgets. ``bücher.example``
    and ``xn--bcher-kva.example`` are the same origin to httpx and were
    different locks and different ledger buckets here; so were ``EXAMPLE.test``
    and ``example.test.``, and ``127.1`` and ``127.0.0.1``.

    The reduction, in order: strip IPv6 brackets, drop one trailing root dot,
    take the canonical textual form if it is an IP literal (which collapses
    IPv6 leading zeros and shorthand IPv4 alike), otherwise IDNA/UTS 46 to the
    ASCII form and lowercase. Anything that survives none of that raises,
    because an unbucketable host is an unlimited one.
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

    fix(#1758 codex r12): ``httpx.URL`` is the class httpx builds the outbound
    request from, so deriving the scope from anything else let the two
    disagree. It removes dot segments, lowercases the scheme and host, decodes
    percent-encoding and applies IDNA, which is most of the normalization this
    endpoint needs and none of which ``urlsplit`` does: ``urlsplit`` kept
    ``/a/../sharing/rest`` verbatim while httpx sent the request to
    ``/sharing/rest``, so a caller could rotate ``/a/../``, ``/b/../`` and
    collect a fresh account key, lock and ledger bucket per spelling while
    every POST hit one ArcGIS account.

    The host still goes through :func:`canonical_host` on top, because httpx
    leaves a trailing root dot in place and DECODES punycode to Unicode,
    which is the opposite of the one spelling this endpoint keys on. Rebuilt
    with ``copy_with`` rather than compared, so the address that is hashed is
    the address that is contacted.
    """
    url = raw if isinstance(raw, httpx.URL) else httpx.URL(raw)
    # fix(#1758 codex r13): httpx DECODES `%2e` into `.` when it exposes the
    # path, but it removed dot segments before that decoding, so
    # `/a/%2e%2e/sharing` comes back as `/a/../sharing`. Re-parsing the
    # decoded form resolves it. Bounded and convergent: each pass strictly
    # shortens the path, and two are enough for anything a portal can write.
    for _ in range(4):
        reparsed = httpx.URL(f"{url.scheme}://{url.netloc.decode()}{url.path}")
        if reparsed.path == url.path:
            break
        url = url.copy_with(path=reparsed.path)
    return url.copy_with(host=canonical_host(url.host or ""))


def usable_service_url(raw: str | httpx.URL) -> httpx.URL | None:
    """THE canonicalizer. Every URL in this module goes through this one.

    fix(#1758 codex r12): refused rather than repaired. A URL that still holds
    a ``..`` or an empty segment after normalization, or that carries a query,
    a fragment or userinfo, is one whose scope and whose destination could
    still be argued about, and the conventional endpoint is always available
    instead. ``//sharing//rest`` and ``%2Fsharing`` both land here, and both
    end up at the same scope as ``/sharing/rest`` by way of that fallback.

    fix(#1758 codex r13): "every URL" is the point. The caller's portal URL
    used to reach the conventional endpoint through a separate ``urlsplit``
    path that resolves no percent-encoded dot segments, so ``/a/%2e%2e`` and
    ``/b/%2e%2e`` produced two scopes for one endpoint. Three inputs (the
    portal the caller typed, the token service a portal advertises, and the
    fallback composed from the first) now share one function, so no input can
    have a normalization of its own.
    """
    try:
        url = _canonical_url(raw)
    except (httpx.InvalidURL, ArcGISSignInError, ValueError, UnicodeError):
        return None
    if url.query or url.fragment or url.userinfo:
        return None
    if url.port == 0:
        # fix(#1758 codex r15): port zero addresses nothing. Every request to
        # it fails before it reaches ArcGIS, but it is FALSEY, so the scope
        # derivation read it as "no port given" and filed those failures under
        # the real :443 bucket. Three of them against a victim's username
        # therefore spent that account's cluster-global budget and 429'd
        # legitimate sign-ins across every tenant. Refused here, where every
        # URL in this module already passes, rather than guarded at the one
        # site that happened to collapse it.
        return None
    # segments[0] is the empty string before the leading slash on any absolute
    # path, so it is the only empty one that is legitimate. A bare root path
    # is "/" and therefore reads as one empty segment; that is the portal root
    # a user pastes, not an ambiguity.
    segments = url.path.split("/")[1:]
    if segments == [""]:
        segments = []
    if any(segment in ("", "..") for segment in segments):
        return None
    return url


def canonical_token_service_scope(url: str | httpx.URL) -> str:
    """The identity every sign-in limit is keyed on: ``host:port/webadaptor``.

    fix(#1758 codex r11): the host alone was not the account store. Two
    ArcGIS Enterprise portals can share one hostname and differ only by https
    port or by web-adaptor path, and they are independent installations with
    independent user directories, so keying on the host made three attempts
    against one exhaust and serialize the other.

    The port is always explicit, filled in from the scheme when the URL omits
    it, so ``https://gis.test`` and ``https://gis.test:443`` are one scope.
    The path keeps its case, because a web adaptor's path is case-sensitive
    to the server that serves it, and loses the trailing ``/generateToken``,
    which is the endpoint rather than the installation.

    The delegate bound in :func:`_is_trusted_delegate` still works on the
    HOST part: which installation this is and which domain may vouch for it
    are different questions.
    """
    normalized = _canonical_url(url)
    # `.host` reads back DECODED: httpx stores the ASCII form it will send but
    # renders punycode as Unicode, so the ASCII spelling this endpoint keys on
    # has to be asked for again rather than read off the object.
    host = canonical_host(normalized.host or "")
    if ":" in host:  # an IPv6 literal needs its brackets back in an authority
        host = f"[{host}]"
    # `is None`, never a truthiness test: a falsey-but-explicit port must not
    # alias the scheme default. `usable_service_url` refuses port zero, and
    # this is the second half of that fix, so no future caller can reintroduce
    # the collapse by reaching this function another way.
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

    fix(#1758 codex r3): the lockout budget belongs to the ARCGIS account, not
    to the GeoLens user spending it. Esri locks after five failed sign-ins in
    fifteen minutes and counts them per account, so two GeoLens users with
    three attempts each add up to six against one colleague's account. This is
    what both the shared counter and the advisory lock are keyed on, so the
    two budgets are the target's rather than the callers'.

    Keyed rather than plain: a bare SHA-256 of a hostname and a username is a
    dictionary away from being the username, and this value is written to an
    audit row that outlives the request. The username itself is never stored,
    never logged and never returned; only this digest is.

    The username is casefolded because ArcGIS sign-in is case-insensitive, so
    two spellings of one account must land in one bucket or the limit is
    trivially sidestepped. The two parts are length-prefixed so no pair of
    (host, username) can collide with another by moving the boundary.
    """
    normalized = username.strip().casefold()
    message = f"{len(host)}:{host}:{len(normalized)}:{normalized}".encode()
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

    Accepts the portal root (``https://org.maps.arcgis.com``) and the REST
    base itself (``.../sharing/rest``), which are the two forms a user has to
    hand. Split and rejoin rather than pattern-match: a URL regex is a ReDoS
    surface on a field the caller controls, and there is nothing here that
    splitting cannot do.

    fix(#1758 codex r13): takes the ``httpx.URL`` that
    :func:`usable_service_url` already produced, rather than re-parsing the
    caller's string. It used to run its own ``urlsplit``, which resolves no
    percent-encoded dot segments, so the conventional endpoint composed from
    ``/a/%2e%2e`` and from ``/b/%2e%2e`` came out as two scopes for one
    destination. Nothing in this module parses a URL except through that one
    function now.
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

    ``None`` covers every body this module cannot act on: a page instead of a
    document, a document too large to be one, and a compressed one. Streaming
    with a byte cap rather than ``response.json()`` so a portal that answers a
    sign-in with a hundred-megabyte page cannot make the API pay for it, and
    the cap is applied to RAW transport bytes so a small compressed body
    cannot expand past it inside a decoder (fix(#1758 codex r14)).

    ``data`` is form-encoded by httpx, which percent-escapes every value. A
    password therefore cannot smuggle a field separator into the body, which
    is why this path needs no character policy of its own.

    ``follow_redirects`` is a PER-REQUEST override on the shared safe client
    (fix(#1758 codex r2)) rather than a second client: ``make_safe_client`` is
    the only sanctioned constructor here, and building another one would lose
    the guard transport and trip the Rule 2 hook besides. The credential POST
    passes ``False``; see :func:`_redirected` for why.
    """
    raw = bytearray()
    async with client.stream(
        method,
        url,
        data=data,
        # fix(#1758 codex r14): `identity` because nothing here benefits from
        # compression and a compressed body is a bomb waiting for a decoder.
        # Every document this module reads is a JSON envelope of a few hundred
        # bytes.
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
        except ValueError:
            return response.status_code, None
        try:
            return response.status_code, json.loads(raw)
        except ValueError:
            return response.status_code, None


_ARCGIS_ONLINE_DOMAIN = "arcgis.com"


def _is_trusted_delegate(portal: str, delegate: str) -> bool:
    """Whether *portal* may hand the password to *delegate*.

    fix(#1758 codex r9): ``tokenServicesUrl`` was followed to any host that
    passed https and SSRF, which made the discovery document a way to
    redirect a credential.

    fix(#1758 codex r13): and the sibling allowance that replaced it was a
    public-suffix bug wearing a disguise. "The portal host minus its leftmost
    label" is the organisation domain only when the portal has exactly one
    label above its suffix: for ``agency.co.uk`` it yields ``co.uk``, so
    ``attacker.co.uk`` read as a sibling and got the password. Nothing short
    of a public-suffix list can tell those apart, and this module is not
    going to carry one.

    So the bound is now what can be decided from the two strings alone: the
    same host, a SUBDOMAIN of the portal host, or anything under
    ``arcgis.com``, which is where ArcGIS Online delegates. An Enterprise
    federation whose token service is a sibling rather than a subdomain falls
    back to the portal's own ``generateToken``, which works: the fallback is
    the same endpoint every other refused delegation already uses.
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

    ``authInfo.tokenServicesUrl`` is the documented discovery route and is
    what a federated ArcGIS Enterprise deployment answers with, which can
    legitimately be a different host from the portal. That is exactly why the
    advertised value is re-validated for SSRF before it is followed: the
    portal is not trusted to name its own token service, and the guard
    transport's connect-time check would report the refusal as a transport
    failure rather than as the policy decision it is.

    A discovery request that fails at the transport level falls back to the
    conventional URL rather than failing here, so the sign-in has exactly one
    failure path to classify instead of two that say the same thing.

    fix(#1758 codex r9): the discovery GET does not follow redirects, and any
    3xx falls back. The safe client's per-hop check refuses a PRIVATE target,
    which is a different question from the one that matters here: an
    https-to-http hop hands the discovery document to anyone on the path, and
    a rewritten document names an attacker's https token service that then
    passes every check this function makes and receives the password. Not
    following at all is both stricter and simpler than judging each hop.

    Returns the URL to post to and, when the portal named a delegate this
    instance will not follow, a note for the audit row.
    """
    # fix(#1758 codex r13): composed from the canonical portal and put through
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
        # fix(#1758 codex r16): `make_safe_client`'s `_revalidate_redirect`
        # hook runs on EVERY response, whether or not redirects are followed,
        # so a 3xx here whose Location is private or unresolvable raises out
        # of the request before the status can be read. That is the same fact
        # as the branch below and deserves the same answer: discovery turned
        # up nothing usable, so use the conventional endpoint on the portal
        # origin phase one already validated. Refusing instead reported
        # `ssrf_refused` for a portal that is merely misconfigured.
        #
        # Discovery ONLY. The credential POST catches this separately and
        # must keep refusing: by then the password is on the wire, and a
        # rejected hop there is a redirect outcome that counts.
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
    # fix(#1758 codex r12): normalized ONCE, here, into the object the POST is
    # later sent with, so the scope, the delegate check and the destination
    # are all readings of one value rather than three parses of a string.
    normalized = usable_service_url(candidate)
    if normalized is None:
        # An advertised URL nobody can parse, or one that still argues with
        # itself after normalization, is no more usable than an absent one,
        # and the conventional URL is what the portal would have meant.
        return fallback, None
    # fix(#1758 codex r14): the delegate check FIRST, because it is the only
    # one of the three that is pure. Judging a candidate on https and then
    # RESOLVING it before asking whether it would ever be contacted turned an
    # untrusted delegate that happens to be private, split-horizon or simply
    # unresolvable into `ssrf_refused` or a discovery network error, when the
    # honest answer is the same clean fallback any other untrusted delegate
    # gets. Only a candidate this instance will actually contact is worth
    # refusing over its scheme or its address.
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

    The return value is read by the two predicates below and then dropped. It
    is never logged, never written to an audit row and never returned to the
    caller: provider prose about somebody's account is the thing this
    endpoint exists to keep out of a response body.
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
    """Whether a refusal names a federated identity rather than a bad password."""
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

    ``portals/self`` carries ``canSignInArcGIS`` for the organisation, which
    is the org-wide half of the federated-identity signal; the message half is
    what catches an individual account with multifactor authentication turned
    on. Asked only after a refusal, so the happy path pays no extra request,
    and it is a plain anonymous GET carrying no credential.

    Any failure answers "no". This runs while a refusal is already being
    classified, and a portal that will not answer an anonymous question is not
    evidence about how its members sign in.
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
    """Turn an ArcGIS error envelope into one of the two caller-facing codes."""
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
    """Read a token and its expiry out of a generateToken success envelope."""
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

    fix(#1758 codex r7): the sign-in is two phases because the LIMITS need it
    to be. Discovery is credential-free and its whole job is to answer "which
    host will actually receive this password", and every lock and budget is
    keyed on that answer rather than on the address the caller typed. A caller
    who owns a wildcard domain can point a hundred hostnames at one victim's
    token service; keyed on the portal they typed, that was a hundred fresh
    three-attempt buckets against one ArcGIS account.

    Phase one therefore hands back this object, the caller takes its locks and
    reads its budgets against :attr:`host`, and only then calls :meth:`mint`.
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
        #: an ``httpx.URL`` (fix(#1758 codex r12)) because that is what the
        #: scope was derived from, so the two cannot diverge.
        self.token_service = token_service
        #: The canonical ``host:port/webadaptor`` of the destination that
        #: will receive the password, and the only thing this endpoint's
        #: limits are keyed on. An installation, not just a hostname: see
        #: :func:`canonical_token_service_scope`.
        self.scope = scope

    async def mint(self, username: str, password: str) -> MintedToken:
        """Post the credentials and return the token, or raise a classified error.

        Raises :class:`ArcGISSignInError` for every failure. No exception from
        httpx, from the SSRF guard or from anywhere else escapes: an
        ``httpx.RequestError`` holds the request whose encoded body is the
        password, so a foreign exception reaching a traceback renderer that
        prints frame locals is a leak with no upside. Nothing is chained
        either, for the same reason.

        fix(#1758 codex r11): the deadline is HERE, around the network call,
        rather than around the caller's whole block. What runs after this
        method returns is the ledger insert and the audit commit, and a
        cancellation landing in those leaves the request session in a failed
        transaction with the outcome unrecorded, which is a credential POST
        the budget never paid for. The outcome is decided inside the scope and
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
            # fix(#1758 codex r4): the safe client's per-hop hook runs on
            # EVERY response, redirects followed or not, so a 3xx whose
            # Location is private raises here before the branch below can see
            # the status. Left to the outer handler it recorded
            # `ssrf_blocked`, which is excluded from the attempt budget on the
            # grounds that nothing reached ArcGIS. That is wrong on this one
            # request: the password was already on the wire. Same caller-facing
            # answer as any other redirect, and it counts.
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
    scope, the portal's REST base and any note discovery left behind. Every failure here is classified as a DISCOVERY failure, and every
    discovery failure is uncounted, because no credential has been anywhere
    near the wire yet: counting them would let an unreachable portal spend a
    real account's lockout budget.
    """
    try:
        # fix(#1758 codex r13): the caller's URL takes the same road as every
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

    fix(#1758 codex r11): the deadline covers DISCOVERY only, and the yield is
    outside it. It used to span the caller's block too, so a cancellation
    could land in the ledger insert, the audit flush or the commit that the
    caller runs between the phases; that leaves the request session in a
    failed transaction, and the refusal path then ran on an unusable session
    and 500'd with nothing recorded, which is a sign-in that reached the wire
    and never spent its budget. The mint carries its own deadline for the same
    reason. Only ``TimeoutError`` is converted here; anything else the caller
    raises inside the block, including the HTTPException a refusal becomes,
    passes through untouched.
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


# fix(#1758 codex r1): the in-flight guard that used to live here was a
# process-local set, which is worth nothing on an install that runs two
# uvicorn workers. It is now a PostgreSQL advisory lock next to the route,
# because the shared state a stock install has is the database.
