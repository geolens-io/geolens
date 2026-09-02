"""Helpers for resolving public app/API URLs across deployment environments."""

from __future__ import annotations

import ipaddress
import time
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db.models import AppSetting
from app.core.tenancy import is_multi_tenant

PUBLIC_APP_URL_KEY = "public_app_url"
PUBLIC_API_URL_KEY = "public_api_url"
LEGACY_PUBLIC_API_URL_KEY = "public_base_url"

_DEFAULT_PUBLIC_APP_URL = "http://localhost:8080"
_DEFAULT_PUBLIC_API_URL = "http://localhost:8000"


class PublicUrlNotConfiguredError(RuntimeError):
    """Phase 268 H-27: raised when a caller asks for an external-use URL
    (e.g. OAuth redirect_uri) but neither PUBLIC_APP_URL nor PUBLIC_API_URL
    is configured. The request-origin fallback is unsafe for redirect_uri
    because the IdP receives whatever the attacker sets in
    ``X-Forwarded-Host`` / ``Origin`` / ``Referer``, enabling an
    auth-code-stealing attack against IdPs with permissive redirect-URI
    policies. Forcing explicit configuration closes that path."""


def is_usable_public_origin(value: str | None) -> bool:
    """Is this a value a browser could actually be sent to?

    fix(#1548 review r8): ONE shape rule for ``PUBLIC_APP_URL``, stated here and
    mirrored by ``parseUsablePublicUrl`` in ``frontend/src/lib/public-urls.ts``.
    The rule: an absolute HTTP(S) URL, with a host, and no query or fragment.

    Everything else is untrusted, and each consumer already knows what to do
    with untrusted — the backend refuses to issue a domain lock, the frontend
    falls back for ordinary shares and suppresses a locked preview.

    Why each clause is load-bearing, since none of them is hypothetical:

    * ABSOLUTE, WITH A SCHEME AND HOST. ``_normalize_origin`` prepends
      ``https://`` to anything that does not already start with http(s), so an
      environment value of ``ftp://maps.example.com`` becomes the pseudo-origin
      ``https://ftp:``, ``mailto:ops@example.com`` becomes
      ``https://mailto:ops@example.com`` and ``file:///etc/hosts`` becomes
      ``https://file:``. Each is non-loopback, so the domain-lock gate read the
      deployment as configured and issued a lock no embed shell could ever
      satisfy — this PR's original bug, returning through the check added to
      prevent it.
    * NO QUERY OR FRAGMENT. The backend drops them when it normalizes, so its
      own comparison survives, but the frontend appends ``/m/<token>`` to the
      configured string — putting the path inside the query or after the
      fragment and producing links nobody can open.
    * NO ``/api`` PATH. fix(#1555): the same clause the persistent-setting
      validator has always had (``validate_public_app_url``, "must point to the
      app, not the /api base"), applied to the entry point that skipped it. An
      environment ``PUBLIC_APP_URL=https://maps.example.com/api`` reached
      ``SharePanel`` through tile-config and built ``/api/api/maps/...`` card
      links and ``/api/m/...`` iframe sources, while the domain-lock gate saw a
      non-loopback origin and issued a token whose shell URL does not exist.
      One rule with two entry points, only one of them checking.

    The setting is environment-backed, so the environment path never passes
    through the persistent-setting validator; that validator now defers to this
    function for everything it does not say itself, so both entry points give
    the same answer.
    """
    if value is None:
        return False
    candidate = value.strip()
    if not candidate:
        return False
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    if not parts.hostname:
        return False
    # fix(#1548 review r9/r10): three characters/classes are refused OUTRIGHT,
    # each because the two URL parsers disagree about it — and a value the two
    # halves read differently is the whole bug class, whichever reading one
    # prefers.
    #
    # * PERCENT-ENCODING. Python's urlsplit leaves `%6Daps.example.com` literal;
    #   the browser decodes it to `maps.example.com`.
    # * BACKSLASH. `https://maps.example.com\@evil.com` parses as host
    #   `maps.example.com\` here and as host `evil.com` in a browser, which
    #   makes it an origin-confusion primitive rather than a formatting nit.
    # * NON-ASCII HOST. Refused rather than converted. Python's built-in idna
    #   codec is IDNA2003: it maps `faß.de` to `fass.de`, while browsers follow
    #   WHATWG/UTS #46 and send `xn--fa-hia.de`. Approximating that from here
    #   means deviation characters, transitional processing and registry rules,
    #   and a NEAR match is worse than none — it denies every request while
    #   looking correct. An operator with an internationalized domain supplies
    #   the punycode form, which is unambiguous and is what the browser sends.
    #
    # All three are checked on the RAW candidate rather than on the parsed host,
    # because the browser parser has already decoded and punycoded by the time
    # its equivalent could look — so the raw string is the only view the two
    # sides can compare identically.
    if "%" in candidate or "\\" in candidate:
        return False
    if not candidate.isascii():
        return False
    if canonical_host_error(parts.hostname or "") is not None:
        return False
    if is_api_base_path(parts.path):
        return False
    return not parts.query and not parts.fragment


def is_api_base_path(path: str) -> bool:
    """Does this path name the API base rather than the app?

    fix(#1555): stated once because two entry points ask it — the environment
    path through ``is_usable_public_origin`` and the persistent-setting path
    through ``validate_public_app_url``, which had it and was the only one
    checking. ``/apiary`` is not an API base; ``/geolens/api/`` is.

    fix(#1555 review): the question is asked of the path a BROWSER resolves,
    which is not the path ``urlsplit`` hands back. ``/api/.`` and
    ``/foo/../api/.`` are left untouched by Python and normalized to ``/api/``
    by every browser, so both backend doors accepted them while the frontend —
    reading ``URL.pathname``, already resolved — refused. Measured, not
    assumed: before this, ``validate_public_app_url('https://maps.example.com/
    api/.')`` returned the value and the domain-lock gate read it as a
    configured origin.
    """
    return _remove_dot_segments(path).rstrip("/").endswith("/api")


# WHATWG treats a percent-encoded dot as a dot segment, in either case, and in
# either half of a double-dot. RFC 3986 §5.2.4 knows only the literal spellings.
_SINGLE_DOT_SEGMENTS = frozenset({".", "%2e"})
_DOUBLE_DOT_SEGMENTS = frozenset({"..", ".%2e", "%2e.", "%2e%2e"})


def _remove_dot_segments(path: str) -> str:
    """Resolve ``.`` and ``..`` the way a URL parser does.

    RFC 3986 §5.2.4, with the ``%2e`` equivalences the URL Standard adds. Takes
    the path of an ABSOLUTE URL, so it is either empty or rooted.

    A trailing dot segment leaves the slash behind: ``/api/.`` is ``/api/``,
    matching ``new URL().pathname``, which is the whole point of the function.

    The ``%2e`` half cannot be reached through ``is_usable_public_origin``
    today: it refuses any candidate containing ``%`` several clauses earlier,
    because Python leaves percent-encoding literal where a browser decodes it.
    That refusal is a different rule with a different reason, though, and one
    that a later change could narrow to "decode it instead" without anyone
    noticing this depended on it. So the equivalence is implemented here rather
    than assumed, and pinned by a test that calls this classifier directly —
    an end-to-end test of a ``%2e`` value would pass on the percent clause
    alone and prove nothing about this code.
    """
    if not path:
        return path
    segments = path.split("/")
    output: list[str] = []
    for index, segment in enumerate(segments):
        lowered = segment.lower()
        is_last = index == len(segments) - 1
        if lowered in _SINGLE_DOT_SEGMENTS:
            if is_last:
                output.append("")
            continue
        if lowered in _DOUBLE_DOT_SEGMENTS:
            # Never pop the leading empty segment: it is the root, not a step.
            if len(output) > 1:
                output.pop()
            if is_last:
                output.append("")
            continue
        output.append(segment)
    return "/".join(output)


def is_loopback_host(host: str) -> bool:
    """True when a browser served from ``host`` is talking to its own machine.

    fix(#1555): the predicate this replaces was an enumerated set of three
    spellings (``localhost``, ``127.0.0.1``, ``::1``). Loopback is a RANGE:
    ``127.0.0.0/8`` is loopback in its entirety, so a deployment configured as
    ``http://127.0.0.2:8080`` was classified non-loopback, and
    ``assert_domain_lock_is_enforceable`` read that as "this deployment knows
    its public origin" and issued a domain lock every recipient resolves to
    their OWN machine. The list form fails toward permitting the lock, which is
    the direction that costs an operator a silently empty embed.

    ``*.localhost`` counts. RFC 6761 §6.3 says resolvers should treat the
    ``localhost`` zone as loopback and browsers do, so ``http://app.localhost``
    is the same misconfiguration wearing a subdomain.

    Bracketed IPv6 literals are accepted here because callers disagree about
    whether they strip: ``urlsplit(...).hostname`` does, ``URL.hostname`` in a
    browser does not.
    """
    candidate = host.strip().lower()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    if not candidate:
        return False
    if candidate == "localhost" or candidate.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def canonical_host_error(host: str) -> str | None:
    """None if ``host`` is spelled the way a browser would serialize it.

    Otherwise a sentence naming what is wrong, for an operator to act on.

    fix(#1548 review r11): the same root as the IDN refusal — Python and the
    browser disagree about a host's canonical spelling, and we store Python's.
    Measured, not assumed:

        input                          urlsplit          browser
        http://192.168.1               192.168.1         192.168.0.1
        http://010.0.0.1               010.0.0.1         8.0.0.1     (octal)
        http://0x7f.1                  0x7f.1            127.0.0.1   (hex)
        http://2130706433              2130706433        127.0.0.1
        http://[2001:0db8:0:0:0:0:0:1] 2001:0db8:0:0...  [2001:db8::1]

    In every row the shell would present the right column while
    ``_resolve_self_origins`` stored the left, so the lock was issued and then
    missed on every request.

    THE TRAP, and the reason this asserts canonical form directly rather than
    testing stability: ``192.168.1`` ROUND-TRIPS cleanly through urlsplit. It is
    perfectly stable under our own parser and still wrong. A check built on
    "parse it, re-serialize it, compare" would pass it.

    The frontend does not need this function: it has a browser URL parser, so it
    compares the host as written against the host that parser produced. Only
    this side has to state the rule. ``public-app-url-shape.cases.json`` is what
    holds the two methods to the same answers.
    """
    if not host:
        return "The host is empty."
    if host.endswith("."):
        return f"Drop the trailing dot: {host.rstrip('.')}"

    if ":" in host:  # IPv6 literal; urlsplit has already stripped the brackets.
        try:
            address = ipaddress.IPv6Address(host)
        except ValueError:
            return f"{host!r} is not a valid IPv6 address."
        # fix(#1555): an IPv4-MAPPED literal has no agreed spelling. Python
        # renders ::ffff:7f00:1 as ::ffff:127.0.0.1 and a browser renders
        # ::ffff:127.0.0.1 as ::ffff:7f00:1, so each side calls the other's
        # canonical form non-canonical and the class had no answer both halves
        # accept. Refused outright rather than translated, for the same reason
        # as a non-ASCII host: the plain IPv4 form is unambiguous and is what a
        # browser presents anyway.
        if address.ipv4_mapped is not None:
            return (
                f"{host!r} is an IPv4-mapped IPv6 literal, which browsers and "
                "this server spell differently. Write the IPv4 address: "
                f"{address.ipv4_mapped}"
            )
        compressed = str(address)
        if compressed != host:
            return f"Write the IPv6 literal in its compressed form: [{compressed}]"
        return None

    # A URL parser reads a host as IPv4 when its LAST label is numeric — which
    # covers hex and octal spellings, not just dotted decimal. Anything matching
    # that shape must already be canonical dotted-quad, and ipaddress rejects
    # short forms, leading zeros and out-of-range octets for us.
    last_label = host.rsplit(".", 1)[-1]
    if last_label.isdigit() or last_label.startswith("0x"):
        try:
            parsed_ip = ipaddress.IPv4Address(host)
        except ValueError:
            # Deliberately NOT expanding it for them: computing what a browser
            # would make of `0x7f.1` means implementing the WHATWG IPv4 parser,
            # which is the approximation this whole rule exists to avoid.
            return (
                f"{host!r} is read as an IP address by browsers, and not in the "
                "form they use. Write four decimal octets with no leading "
                "zeros, e.g. 192.168.0.1"
            )
        if str(parsed_ip) != host:
            return f"Write the IP address as: {parsed_ip}"
        return None

    # Registered name. Case is not checked: both parsers lowercase it, so an
    # uppercase spelling is not a disagreement and refusing it would cost an
    # operator a working value for nothing.
    labels = host.split(".")
    if any(not label for label in labels):
        return f"{host!r} has an empty label."
    if not all(c.isalnum() or c == "-" for label in labels for c in label):
        return f"{host!r} contains a character that is not valid in a hostname."
    # fix(#1555 review r4): an `xn--` label is accepted here as opaque LDH, and
    # three rounds of validating it were REMOVED, because "what a browser sends"
    # has no single answer for these labels. Measured with Playwright, in-page
    # `new URL('https://<host>/p').hostname`:
    #
    #     host                   chromium 151  firefox 153  webkit 26.5  node 26
    #     xn--.example           ok            THROWS       ok           THROWS
    #     xn--a-sgn.example      ok            THROWS       ok           THROWS
    #     xn--a-0hc.example      ok            THROWS       ok           ok
    #     ex-.xn--mgbh0fb        ok            THROWS       ok           ok
    #     xn--fa-hia.de          ok            ok           ok           ok
    #
    # Chromium and WebKit do not decode or validate an all-ASCII host at all;
    # Firefox implements the URL Standard including every RFC 5893 bidi rule;
    # Node's parser matches neither. So any refusal we add is stricter than the
    # two engines most viewers use, which is the direction this file exists to
    # avoid — and no rule can satisfy Firefox and Chromium at once. 13 of the 28
    # hosts measured were read differently by different engines, ALL of them
    # `xn--` cases; every other rule in this module agreed across all four.
    #
    # This also means a Node-based test cannot stand in for a browser here: run
    # `new URL('https://xn--.example')` in node, find it invalid, and you are
    # reading one engine's opinion, not the web's.
    return None


def normalize_public_url(url: str | None) -> str | None:
    if url is None:
        return None
    stripped = url.strip()
    if not stripped:
        return None
    return stripped.rstrip("/")


def append_api_suffix(app_url: str) -> str:
    parts = urlsplit(app_url)
    path = parts.path.rstrip("/")
    api_path = f"{path}/api" if path else "/api"
    return urlunsplit((parts.scheme, parts.netloc, api_path, "", ""))


def strip_api_suffix(api_url: str) -> str:
    parts = urlsplit(api_url)
    path = parts.path.rstrip("/")
    if path.endswith("/api"):
        path = path[: -len("/api")]
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _configured_api_path(
    app_url: str | None,
    api_url: str | None,
    legacy_api_url: str | None,
) -> str:
    """Return the configured API path without reusing its fleet origin."""
    configured_api = normalize_public_url(api_url) or normalize_public_url(
        legacy_api_url
    )
    if configured_api:
        return urlsplit(configured_api).path.rstrip("/")

    configured_app = normalize_public_url(app_url)
    if configured_app:
        return urlsplit(append_api_suffix(configured_app)).path.rstrip("/")
    return ""


def join_public_url(base_url: str, path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    normalized = normalize_public_url(base_url)
    if normalized is None:
        raise ValueError(
            f"Cannot join public URL: base_url={base_url!r} is not a valid URL"
        )
    return normalized + path


def _is_env_only() -> bool:
    return settings.env_only_config


def _request_origin_decision(request: Request | None) -> tuple[str | None, bool]:
    """``(origin, allowlist_rejected)`` derived from the request headers.

    SEC-05 / M-67: when ``CORS_ALLOWED_ORIGINS`` is configured (non-empty),
    the resulting origin MUST be in that allowlist. This prevents an
    attacker who controls ``X-Forwarded-Host`` (e.g., behind a permissive
    reverse proxy) from steering URL generation to attacker.com.

    When ``CORS_ALLOWED_ORIGINS`` is empty (local dev, no proxy), the
    function returns the request-derived origin unchanged — dev workflows
    (Vite proxy, localhost-only) keep working without configuration.

    fix(#1778): the second element exists because "no origin to derive" and
    "an origin was derived and the allowlist refused it" are different
    answers, and the resolvers below must not treat them alike. Collapsing
    both into ``None`` let the raw-Host fallback re-derive the very origin
    this function had just rejected.
    """
    if request is None:
        return None, False

    candidate: str | None = None

    origin = normalize_public_url(request.headers.get("origin"))
    if origin:
        candidate = origin
    else:
        referer = normalize_public_url(request.headers.get("referer"))
        if referer:
            parsed = urlsplit(referer)
            if parsed.scheme and parsed.netloc:
                candidate = f"{parsed.scheme}://{parsed.netloc}"

    if candidate is None:
        scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
        host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
        if not host:
            return None, False
        candidate = f"{scheme}://{host}"

    # SEC-05: enforce CORS allowlist when configured.
    allowlist = settings.cors_origins_list
    if allowlist:
        # normalize_public_url strips trailing slash; do the same on the
        # allowlist entries for case-insensitive byte-equality.
        normalized_allowlist = {
            (normalize_public_url(entry) or "").lower() for entry in allowlist
        }
        if (candidate or "").lower() not in normalized_allowlist:
            return None, True

    return candidate, False


def _request_origin(request: Request | None) -> str | None:
    """The allowlist-approved request origin, or None. See
    :func:`_request_origin_decision` for why callers that fall back to
    anything else need the two-value form instead."""
    origin, _rejected = _request_origin_decision(request)
    return origin


def resolve_public_api_url(
    app_url: str | None,
    api_url: str | None,
    legacy_api_url: str | None,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> str:
    """Resolve the public API URL.

    Phase 268 H-27: when ``for_external_use=True``, the request-origin
    fallback is disabled. Such a URL is handed to a third party (e.g. an
    IdP as the OAuth redirect_uri) where an attacker-controlled origin
    enables auth-code theft. Caller MUST configure ``PUBLIC_APP_URL`` /
    ``PUBLIC_API_URL`` for OAuth flows; otherwise this raises
    ``PublicUrlNotConfiguredError``.

    fix(#1778): the last-resort ``request.url.netloc`` fallback below runs only
    when the allowlist did not have an opinion. It used to run whenever
    ``_request_origin`` answered None, which included the case where the
    allowlist had just REFUSED the derived origin -- and ``request.url.netloc``
    is Starlette's read of the ``Host`` header, which nginx.conf forwards
    verbatim (``proxy_set_header Host $http_host``) with no ``server_name``
    restriction. SEC-05 therefore changed which of two code paths ran and both
    returned the attacker's host. Giving nginx a ``server_name`` so an unknown
    Host never reaches the app is still worth doing; this closes the app-side
    half.
    """
    normalized_api = normalize_public_url(api_url) or normalize_public_url(
        legacy_api_url
    )
    if normalized_api:
        return normalized_api

    normalized_app = normalize_public_url(app_url)
    if normalized_app:
        return append_api_suffix(normalized_app)

    if for_external_use:
        raise PublicUrlNotConfiguredError(
            "OAuth and other external-use flows require an explicit "
            "PUBLIC_APP_URL or PUBLIC_API_URL setting. Falling back to "
            "request-derived origin is unsafe — an attacker who controls "
            "X-Forwarded-Host can hijack the OAuth redirect_uri."
        )

    request_origin, allowlist_rejected = _request_origin_decision(request)
    if request_origin:
        assert request is not None
        root_path = request.scope.get("root_path", "").rstrip("/")
        if root_path:
            return request_origin + root_path
        return request_origin

    if request is not None and not allowlist_rejected:
        scheme = request.url.scheme
        host = request.url.netloc
        if host:
            hostname = host.split(":")[0] if ":" in host else host
            if hostname not in ("api", "backend"):
                return f"{scheme}://{host}"

    return _DEFAULT_PUBLIC_API_URL


def resolve_public_app_url(
    app_url: str | None,
    api_url: str | None,
    legacy_api_url: str | None,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> str:
    """Resolve the public app URL. See :func:`resolve_public_api_url` for
    the H-27 ``for_external_use`` semantics — same rules apply."""
    normalized_app = normalize_public_url(app_url)
    if normalized_app:
        return normalized_app

    normalized_api = normalize_public_url(api_url) or normalize_public_url(
        legacy_api_url
    )
    if normalized_api:
        stripped = strip_api_suffix(normalized_api)
        if stripped != normalized_api:
            return stripped

    if for_external_use:
        raise PublicUrlNotConfiguredError(
            "OAuth and other external-use flows require an explicit "
            "PUBLIC_APP_URL or PUBLIC_API_URL setting. Falling back to "
            "request-derived origin is unsafe — an attacker who controls "
            "X-Forwarded-Host can hijack the OAuth redirect_uri."
        )

    request_origin, allowlist_rejected = _request_origin_decision(request)
    if request_origin:
        return request_origin

    if normalized_api:
        return normalized_api

    if request is not None and not allowlist_rejected:
        scheme = request.url.scheme
        host = request.url.netloc
        if host:
            hostname = host.split(":")[0] if ":" in host else host
            if hostname not in ("api", "backend"):
                return f"{scheme}://{host}"

    return _DEFAULT_PUBLIC_APP_URL


def get_env_public_api_url(request: Request | None = None) -> str:
    return resolve_public_api_url(
        settings.public_app_url,
        settings.public_api_url,
        settings.public_base_url,
        request=request,
    )


_PUBLIC_URL_CACHE: tuple[float, dict[str, str | None]] | None = None
_PUBLIC_URL_CACHE_TTL = 60  # seconds

# BUG-025: the three keys whose AppSetting rows feed _PUBLIC_URL_CACHE. A write
# to any of them must invalidate the cache (see invalidate_public_url_cache).
PUBLIC_URL_KEYS = frozenset(
    {PUBLIC_APP_URL_KEY, PUBLIC_API_URL_KEY, LEGACY_PUBLIC_API_URL_KEY}
)


def invalidate_public_url_cache() -> None:
    """Clear the public-URL override cache.

    BUG-025: ``_PUBLIC_URL_CACHE`` is a 60s module-global memoization of the
    public_app_url / public_api_url / public_base_url AppSetting rows. The
    ``config:`` cache invalidated by ``PersistentConfig.set``/``reset`` is a
    SEPARATE layer; without clearing this one too, a settings write keeps
    returning the OLD public URL (in the PUT response, /settings/tile-config,
    OGC self-links, share links) for up to ``_PUBLIC_URL_CACHE_TTL`` per
    process. PersistentConfig.set/reset call this when one of
    ``PUBLIC_URL_KEYS`` is written.
    """
    global _PUBLIC_URL_CACHE
    _PUBLIC_URL_CACHE = None


async def _load_public_url_overrides(db: AsyncSession) -> dict[str, str | None]:
    global _PUBLIC_URL_CACHE
    now = time.monotonic()
    if _PUBLIC_URL_CACHE is not None:
        ts, cached = _PUBLIC_URL_CACHE
        if now - ts < _PUBLIC_URL_CACHE_TTL:
            return cached

    result = await db.execute(
        select(AppSetting.key, AppSetting.value).where(
            AppSetting.key.in_(
                (
                    PUBLIC_APP_URL_KEY,
                    PUBLIC_API_URL_KEY,
                    LEGACY_PUBLIC_API_URL_KEY,
                )
            )
        )
    )
    overrides: dict[str, str | None] = {}
    for key, value in result.all():
        if isinstance(value, dict) and "v" in value:
            overrides[key] = value["v"]
        else:
            overrides[key] = value
    _PUBLIC_URL_CACHE = (now, overrides)
    return overrides


async def get_public_urls(
    db: AsyncSession,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> tuple[str, str]:
    """Resolve (app_url, api_url) tuple. See :func:`resolve_public_api_url`
    for H-27 ``for_external_use`` semantics."""
    fleet_urls_only = False
    overrides: dict[str, str | None] | None = None
    if is_multi_tenant() and request is not None:
        tenant_id = getattr(request.state, "tenant_id", None)
        tenant_origin = normalize_public_url(
            getattr(request.state, "tenant_public_origin", None)
        )
        if tenant_id is not None and tenant_origin is not None:
            root_path = str(request.scope.get("root_path", "")).rstrip("/")
            if root_path:
                api_path = root_path
            else:
                # fix(#507): a proxy rewrite can clear root_path. Read the same
                # DB or environment configuration used by the fleet fallback.
                overrides = (
                    {} if _is_env_only() else await _load_public_url_overrides(db)
                )
                api_path = _configured_api_path(
                    overrides.get(PUBLIC_APP_URL_KEY, settings.public_app_url),
                    overrides.get(PUBLIC_API_URL_KEY, settings.public_api_url),
                    overrides.get(LEGACY_PUBLIC_API_URL_KEY, settings.public_base_url),
                )
            if api_path and (
                not api_path.startswith("/") or "\\" in api_path or "//" in api_path
            ):
                raise PublicUrlNotConfiguredError(
                    "The configured public API path is not a safe absolute path"
                )
            api_url = f"{tenant_origin}{api_path}" if api_path else tenant_origin
            return tenant_origin, api_url
        # fix(#507): JWT-scoped requests on a trusted service host have no
        # tenant origin. Internal response links may use the fleet URLs below,
        # but external callbacks must remain tenant-bound.
        if tenant_id is not None and for_external_use:
            raise PublicUrlNotConfiguredError(
                "Hosted tenant URLs require a middleware-validated tenant host; "
                "the fleet-wide PUBLIC_APP_URL / PUBLIC_API_URL cannot represent "
                "a tenant-specific callback or resource link."
            )
        if tenant_id is not None:
            fleet_urls_only = True
        if for_external_use:
            raise PublicUrlNotConfiguredError(
                "Hosted external-use URLs require a resolved tenant host."
            )

    if overrides is None:
        overrides = {} if _is_env_only() else await _load_public_url_overrides(db)

    app_setting = overrides.get(PUBLIC_APP_URL_KEY, settings.public_app_url)
    api_setting = overrides.get(PUBLIC_API_URL_KEY, settings.public_api_url)
    legacy_api_setting = overrides.get(
        LEGACY_PUBLIC_API_URL_KEY, settings.public_base_url
    )
    if fleet_urls_only and not any(
        normalize_public_url(value)
        for value in (app_setting, api_setting, legacy_api_setting)
    ):
        raise PublicUrlNotConfiguredError(
            "Hosted service-host response links require a fleet-wide "
            "PUBLIC_APP_URL or PUBLIC_API_URL setting."
        )
    resolver_request = None if fleet_urls_only else request

    app_url = resolve_public_app_url(
        app_setting,
        api_setting,
        legacy_api_setting,
        request=resolver_request,
        for_external_use=for_external_use,
    )
    api_url = resolve_public_api_url(
        app_setting,
        api_setting,
        legacy_api_setting,
        request=resolver_request,
        for_external_use=for_external_use,
    )
    return app_url, api_url


async def get_configured_public_app_url(db: AsyncSession) -> str | None:
    """The explicitly configured ``PUBLIC_APP_URL``, or None. No derivation.

    fix(#1548 review r9): ``get_public_app_url`` is a RESOLVER — when
    ``PUBLIC_APP_URL`` is unset it derives an app URL from ``PUBLIC_API_URL`` by
    stripping an ``/api`` suffix, and failing that from the caller's own request
    headers. Both are the right behaviour for producing a link when any link is
    better than none (OGC self-links, response bodies).

    Both are wrong for the two callers that ask "what origin does a browser
    present when it loads our embed shell", because neither derived value is
    that origin:

    * A deployment serving the API at ``https://api.example.com/api`` and the
      app at ``https://maps.example.com`` derives ``https://api.example.com``.
      That is a real, non-loopback host, so the domain-lock gate reads the
      deployment as configured and issues a lock — and then every shell request
      arrives from ``https://maps.example.com``, misses the allowlist, and the
      map is empty. The original defect of this PR wearing a different hat.
    * The request-header fallback is the vacuous-``self`` trap #1531 already
      avoided: an origin taken from the caller is one every caller satisfies.

    So domain locking and share-URL generation require the operator to say it.
    Unset is a legitimate answer here, and every consumer already knows what to
    do with it — refuse the lock, fall back for ordinary shares, suppress the
    locked preview.

    Returns the value with any trailing slash trimmed, or None when unset,
    blank, or not a usable public origin (see ``is_usable_public_origin``).
    """
    overrides = {} if _is_env_only() else await _load_public_url_overrides(db)
    configured = overrides.get(PUBLIC_APP_URL_KEY, settings.public_app_url)
    normalized = normalize_public_url(configured)
    if normalized is None or not is_usable_public_origin(normalized):
        return None
    return normalized


async def get_shareable_app_url(
    db: AsyncSession, *, request: Request | None = None
) -> str | None:
    """The origin a browser is served THIS deployment's app from, or None.

    fix(#1548 review r10): "derived" turned out to name two different things,
    and only one of them is untrustworthy.

    * An ``/api``-stripped ``PUBLIC_API_URL``, or an origin read off the
      caller's own headers, is INFERRED — nobody checked that a browser is
      served the app there, and in the header case the caller chose it. Those
      stay excluded; see ``get_configured_public_app_url``.
    * ``request.state.tenant_public_origin`` is VALIDATED INFRASTRUCTURE STATE.
      ``TenantContextMiddleware`` sets it only after the request's Host resolves
      against the tenant registry, and rejects the request outright when it
      cannot form a trusted origin. It is the one origin that is definitely
      right for a hosted tenant, and the fleet-wide ``PUBLIC_APP_URL`` cannot
      represent a tenant host at all.

    So a hosted tenant request answers with its own validated origin, and
    everything else answers with the explicit fleet setting or nothing. The
    condition mirrors the tenant branch of ``get_public_urls`` deliberately,
    rather than drawing a second line a little differently.

    Callers: share and embed URL generation, which must name a host the
    RECIPIENT can open. On a tenant host that is the tenant's own origin — a
    copied ``/card`` link on the fleet host arrives without the tenant context
    its Host would have carried, and fails closed.
    """
    if is_multi_tenant() and request is not None:
        tenant_id = getattr(request.state, "tenant_id", None)
        tenant_origin = normalize_public_url(
            getattr(request.state, "tenant_public_origin", None)
        )
        if (
            tenant_id is not None
            and tenant_origin is not None
            and is_usable_public_origin(tenant_origin)
        ):
            return tenant_origin
    return await get_configured_public_app_url(db)


async def get_public_app_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> str:
    app_url, _ = await get_public_urls(
        db, request=request, for_external_use=for_external_use
    )
    return app_url


async def get_dataset_service_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
) -> str:
    # Alias kept for future divergence (e.g. dedicated dataset service URL).
    return await get_public_app_url(db, request=request)


async def get_public_api_url(
    db: AsyncSession,
    *,
    request: Request | None = None,
    for_external_use: bool = False,
) -> str:
    _, api_url = await get_public_urls(
        db, request=request, for_external_use=for_external_use
    )
    return api_url
