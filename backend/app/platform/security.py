"""SSRF validation, URL scheme checking, and IP resolution blocking."""

import asyncio
import ipaddress
import re
import socket
from types import ModuleType
from urllib.parse import unquote, unquote_plus, urlparse

import httpx
import httpx2

ALLOWED_SCHEMES = frozenset({"http", "https"})

PROBE_TIMEOUT = httpx.Timeout(connect=10.0, read=10.0, write=10.0, pool=10.0)


class SSRFError(ValueError):
    """URL targets a private/internal network or uses a disallowed scheme."""


class CredentialRedirectError(SSRFError):
    """A redirect would carry a credential to a different origin."""


class SSRFResolutionError(SSRFError):
    """The hostname did not resolve at all.

    A subclass, not a sibling: NXDOMAIN reports ``network_error`` (dead
    DNS), a policy refusal reports
    ``blocked_by_policy``; collapsing them misdirects an operator to audit
    egress policy for a domain that no longer exists.
    """


# Ranges is_private/is_reserved miss but must be blocked for SSRF.
# CGNAT 100.64.0.0/10 (not flagged by is_private on Python <=3.10); IPv6 ULA
# fc00::/7 (missed on some older builds); NAT64 64:ff9b::/96 (embeds an IPv4
# address that may itself be private).
_EXTRA_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 CGNAT
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64 well-known prefix
)


def _is_blocked_ip(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    ):
        return True
    for network in _EXTRA_BLOCKED_NETWORKS:
        if ip in network:
            return True
    return False


async def _resolve_and_validate(host: str, port: int | None) -> str:
    """Resolve *host*, validate every resolved IP, and return one validated IP.

    The caller pins the connection to this address, closing the gap
    between validation-time and connect-time DNS. Raises SSRFError if
    resolution fails or any resolved address is blocked.
    """
    return (await _resolve_all_and_validate(host, port))[0]


async def _resolve_all_and_validate(host: str, port: int | None) -> list[str]:
    """Every address *host* resolves to, in resolver order, once each, after
    the same checks as :func:`_resolve_and_validate`."""
    try:
        results = await asyncio.to_thread(
            socket.getaddrinfo, host, port, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror:
        raise SSRFResolutionError(f"Could not resolve hostname: {host}")
    if not results:
        raise SSRFResolutionError(f"Could not resolve hostname: {host}")
    for _family, _type, _proto, _canon, sockaddr in results:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise SSRFError("URLs targeting private/internal networks are not allowed")
    return list(dict.fromkeys(str(ipaddress.ip_address(r[4][0])) for r in results))


async def validate_url_for_ssrf(url: str) -> None:
    """Validate a URL is safe to fetch (no SSRF).

    Checks:
    1. Scheme is http or https
    2. Hostname is present
    3. Hostname resolves to non-private IP addresses

    Raises SSRFError with a user-friendly message on failure.
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SSRFError("Only http and https URLs are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("Invalid URL: no hostname found")

    # asyncio.to_thread avoids blocking the event loop on slow DNS.
    try:
        results = await asyncio.to_thread(
            socket.getaddrinfo, hostname, parsed.port, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror:
        raise SSRFResolutionError(f"Could not resolve hostname: {hostname}")

    if not results:
        raise SSRFResolutionError(f"Could not resolve hostname: {hostname}")

    for family, _, _, _, sockaddr in results:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked_ip(ip):
            raise SSRFError("URLs targeting private/internal networks are not allowed")


# Include 305 (Use Proxy) for completeness even though RFC 7231
# deprecated it and httpx doesn't follow it by default. Cheap defense-in-depth.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 305, 307, 308})

# Default ports so `https://host` and `https://host:443` are one origin.
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Headers that ARE a credential regardless of caller declaration. httpx
# strips `Authorization` on a cross-origin redirect already; it forwards
# this one unless refused explicitly.
_ALWAYS_CREDENTIAL_HEADERS = frozenset({"x-esri-authorization"})

# ArcGIS's query-string credential, matched by name in any case. httpx never
# copies a query across a redirect, so it travels only if the Location names it.
_CREDENTIAL_QUERY_PARAM = "token"
# Each round must change the string; the ``+`` pass adds one more decode, so an
# echo encoded up to five times is found.
_MAX_DECODE_ROUNDS = 4
# Request extensions, which httpx hands on to every redirect request. The first
# holds each token the chain has carried, so a same-origin hop that moves one
# out of ``token=`` can't launder it for the next hop.
_CARRIED_TOKENS = "geolens_carried_query_tokens"
# Set by a caller that put the credential into the URL itself: any cross-origin
# hop is refused, as for a credential header.
QUERY_CREDENTIAL = "geolens_query_credential"

# Names the policy, never the credential: this reaches a response body, a
# log line, and a job row.
CROSS_ORIGIN_CREDENTIAL_POLICY = (
    "Refusing to send a credential to a different origin after a "
    "redirect. Point the source at the address that answers directly, or ask "
    "the service operator why it redirects a credentialed request elsewhere."
)


def _origin(url: httpx.URL) -> tuple[str, str, int | None]:
    """Scheme, host and port, with the scheme's default port filled in."""
    scheme = (url.scheme or "").lower()
    return (scheme, (url.host or "").lower(), url.port or _DEFAULT_PORTS.get(scheme))


def same_origin(first: str, second: str) -> bool:
    """Whether two URLs address the same origin: scheme, host and port.

    The public form of the redirect hook's rule, for callers
    (e.g. an adapter following a link from a response document) that issue
    a fresh request no redirect hook ever sees. Total: an unparseable URL
    is never the same origin as anything, including itself, so a caller
    deciding whether to send a credential never sends one on a parse error.
    """
    try:
        return _origin(httpx.URL(first)) == _origin(httpx.URL(second))
    except (httpx.InvalidURL, ValueError, TypeError):
        return False


def _carried_tokens(request: httpx.Request) -> set[str]:
    """Every query-string token this redirect chain has carried, this hop's too."""
    carried = request.extensions.setdefault(_CARRIED_TOKENS, set())
    carried.update(
        value.lower()
        for name, value in request.url.params.multi_items()
        if name.lower() == _CREDENTIAL_QUERY_PARAM and value
    )
    return carried


def _names_query_credential(tokens: set[str], target: httpx.URL) -> bool:
    """Whether *target* spells out one of *tokens*, which are lowercased.

    Anywhere in the URL, at every percent-decoding depth up to the cap, with
    ``+`` read both ways, and ignoring case, since httpx lowercases the host.
    A match must not continue a run of letters or digits, Unicode ones included,
    so a short token is not found inside an unrelated value (``a`` in ``sig=abc``).
    """
    if not tokens:
        return False
    spellings = [str(target)]
    for _ in range(_MAX_DECODE_ROUNDS):
        decoded = unquote(spellings[-1])
        if decoded == spellings[-1]:
            break
        spellings.append(decoded)
    spellings += [unquote_plus(spelled) for spelled in spellings]
    # A match may not start on the hex digits of a %XX escape: they aren't
    # content, and the next spelling holds what the escape encodes.
    patterns = [
        re.compile(rf"(?<![^\W_])(?!(?<=%)[0-9a-f]{{2}}){re.escape(token)}(?![^\W_])")
        for token in tokens
    ]
    return any(
        pattern.search(spelled.lower()) for pattern in patterns for spelled in spellings
    )


def _refuse_cross_origin_credential(
    response: httpx.Response, watched: frozenset[str]
) -> None:
    """Keep a credential on the origin it was given to.

    httpx strips `Authorization` on a cross-origin redirect but
    forwards any other header unchanged, so a caller-named key (`X-API-Key`,
    `Ocp-Apim-Subscription-Key`) follows a 302 to an origin that is public
    and SSRF-valid but not the service it was issued to. A request marked
    ``QUERY_CREDENTIAL`` is refused on any cross-origin hop too. Otherwise a
    query-string ``token`` the chain carried is refused when the Location
    spells it out, as a ``$request_uri`` rewrite does. Runs from the response
    hook, before httpx follows the redirect, so the next request is never
    issued.
    """
    if response.status_code not in _REDIRECT_STATUSES:
        return
    location = response.headers.get("Location")
    if not location:
        return
    request = response.request
    tokens = _carried_tokens(request)
    target = httpx.URL(response.url).join(location)
    if _origin(target) == _origin(request.url):
        return
    # Headers membership is case-insensitive: `X-API-Key` matches `x-api-key`.
    if (
        any(name in request.headers for name in watched)
        or request.extensions.get(QUERY_CREDENTIAL)
        or _names_query_credential(tokens, target)
    ):
        raise CredentialRedirectError(CROSS_ORIGIN_CREDENTIAL_POLICY)


async def _revalidate_redirect(response: httpx.Response) -> None:
    """httpx response hook: re-validate the Location target on every redirect hop.

    `follow_redirects=True` silently retargets to attacker-controlled
    internal IPs on a 302; `validate_url_for_ssrf` runs at submission time but
    not per-hop, so this hook closes the gap. Raising SSRFError here aborts
    further redirect-following.

    It also refuses a hop carrying a credential to a
    different origin, checked first since it needs no DNS lookup and the
    Location may otherwise be a perfectly SSRF-valid public host.
    """
    _refuse_cross_origin_credential(response, _ALWAYS_CREDENTIAL_HEADERS)
    if response.status_code not in _REDIRECT_STATUSES:
        return
    location = response.headers.get("Location")
    if not location:
        return
    # Resolve relative redirects against the original response URL.
    target = str(httpx.URL(response.url).join(location))
    await validate_url_for_ssrf(target)


def _redirect_hook(credential_header: str | None):
    """Response hook a client installs, for the header it declared.

    A closure rather than another parameter on ``_revalidate_redirect``:
    that function is named directly by AGENTS.md Rule 2 and by tests, so it
    stays a plain single-argument coroutine.
    """
    if not credential_header:
        return _revalidate_redirect

    watched = _ALWAYS_CREDENTIAL_HEADERS | {credential_header.lower()}

    async def _hook(response: httpx.Response) -> None:
        _refuse_cross_origin_credential(response, watched)
        await _revalidate_redirect(response)

    return _hook


# The statuses httpx follows when the response names a Location.
_FOLLOWED_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

# Headers that describe a body the redirect no longer has.
_REDIRECT_BODY_HEADERS = frozenset(
    {b"content-length", b"content-encoding", b"transfer-encoding"}
)


async def _without_redirect_body(response, http: ModuleType):
    """The same redirect with its body discarded unread, or *response* as is.

    With ``follow_redirects`` on, httpx reads each redirect's body in full,
    decompressed, before it follows the Location, ahead of any size limit the
    caller applies to the response it actually wants. Nothing reads a redirect
    body usefully, so the upstream stream is closed here and the caller gets
    an empty one under the same status and headers. *http* is the library
    (httpx or httpx2) that *response* belongs to.
    """
    if (
        response.status_code not in _FOLLOWED_REDIRECT_STATUSES
        or "location" not in response.headers
    ):
        return response
    await response.aclose()
    return http.Response(
        response.status_code,
        headers=[
            (name, value)
            for name, value in response.headers.raw
            if name.lower() not in _REDIRECT_BODY_HEADERS
        ],
        stream=http.ByteStream(b""),
        extensions={
            key: value
            for key, value in response.extensions.items()
            if key in ("http_version", "reason_phrase")
        },
    )


class _SSRFGuard:
    """Transport that re-resolves, re-validates, and PINS the IP at connect time.

    `validate_url_for_ssrf` resolves DNS once at submission time,
    but the client does its own lookup at connect time — a low-TTL attacker
    domain can answer public at validation and private at connect (DNS
    rebinding). This transport resolves + validates immediately before
    connecting and pins by rewriting the URL host to the validated IP, while
    keeping the original hostname for the Host header and TLS SNI. httpx
    builds a fresh request per redirect hop, so every hop is re-pinned.
    """

    _http: ModuleType

    async def handle_async_request(self, request):
        original_url = request.url
        host = original_url.host
        validated_ip = await _resolve_and_validate(host, original_url.port)
        # sni_hostname keeps the hostname for TLS SNI/verification.
        request.url = original_url.copy_with(host=validated_ip)
        request.extensions["sni_hostname"] = host
        try:
            return await _without_redirect_body(
                await super().handle_async_request(request), self._http
            )
        finally:
            # Restore the hostname after connect — leaving the
            # pinned IP would break relative-redirect resolution (next hop's
            # SNI would be the IP, failing TLS) and leak the IP into
            # response.url, cookies, and caller-side URL derivation.
            request.url = original_url


class _SSRFGuardTransport(_SSRFGuard, httpx.AsyncHTTPTransport):
    """The guard for clients built on httpx."""

    _http = httpx


class _SSRFGuardTransportHttpx2(_SSRFGuard, httpx2.AsyncHTTPTransport):
    """The guard for clients built on httpx2."""

    _http = httpx2


def make_safe_transport() -> httpx.AsyncBaseTransport:
    """Return an HTTP transport that blocks SSRF and DNS rebinding.

    Transport-level counterpart to :func:`make_safe_client`, for libraries
    that build their own ``httpx`` client but accept a transport via kwargs.
    """
    return _SSRFGuardTransport()


def make_safe_httpx2_transport() -> httpx2.AsyncBaseTransport:
    """:func:`make_safe_transport` for a client built on ``httpx2``.

    Authlib's OAuth client is one: authlib builds on httpx2 whenever it is
    installed, and a transport only works inside a client of its own library.
    """
    return _SSRFGuardTransportHttpx2()


def make_safe_client(
    timeout: float | httpx.Timeout = PROBE_TIMEOUT,
    credential_header: str | None = None,
) -> httpx.AsyncClient:
    """Construct an httpx.AsyncClient with SSRF IP-pinning and per-hop revalidation.

    Use this factory instead of `httpx.AsyncClient(
    follow_redirects=True, ...)` for any handler that fetches user-supplied
    URLs. Uses `_SSRFGuardTransport`, which re-resolves, validates,
    and pins at connect time, so a DNS-rebinding answer after submission-time
    validation can't reach an internal IP; `_revalidate_redirect` re-validates
    each 3xx Location and the transport re-pins each hop.

    Pass ``credential_header`` when the request carries a
    service-chosen credential name, so a 302 can't carry it cross-origin;
    ``X-Esri-Authorization`` is refused on a cross-origin hop whether or not
    it was declared. ``token`` query values are carried across the whole
    redirect chain, and a cross-origin hop whose target repeats any of them is
    refused. A request marked ``QUERY_CREDENTIAL`` (see ``bounded_probe_read``)
    is refused on any cross-origin hop.
    """
    return httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=5,
        event_hooks={"response": [_redirect_hook(credential_header)]},
        transport=make_safe_transport(),
    )
