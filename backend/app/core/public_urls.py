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
    """Phase 268 H-27: raised when a caller needs an external-use URL (e.g.
    OAuth redirect_uri) but neither PUBLIC_APP_URL nor PUBLIC_API_URL is
    configured. The request-origin fallback is unsafe here: an attacker
    controls ``X-Forwarded-Host``/``Origin``/``Referer``, enabling
    auth-code theft against IdPs with permissive redirect-URI policies."""


def is_usable_public_origin(value: str | None) -> bool:
    """Is this a value a browser could actually be sent to?

    fix(#1548): the shape rule for ``PUBLIC_APP_URL``, mirrored by
    ``parseUsablePublicUrl`` in ``frontend/src/lib/public-urls.ts`` — an
    absolute HTTP(S) URL, with a host, no query/fragment, and no ``/api``
    path (fix(#1555), the same clause ``validate_public_app_url`` already
    had). Everything else is untrusted; each consumer refuses or falls
    back accordingly rather than issuing a domain lock it can't satisfy.
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
    # fix(#1548): percent-encoding, backslashes, and non-ASCII hosts
    # are refused outright on the RAW candidate — urlsplit and a browser
    # parser read each differently (e.g. IDNA2003 vs WHATWG/UTS #46 for
    # non-ASCII), which is origin confusion, not a formatting nit.
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

    fix(#1555): checked once, on the path a BROWSER resolves rather than the
    one ``urlsplit`` hands back — ``/api/.`` and ``/foo/../api/.`` are left
    untouched by Python but normalized to ``/api/`` by every browser, so a
    raw-path check would miss both. ``/apiary`` is not an API base;
    ``/geolens/api/`` is.
    """
    return _remove_dot_segments(path).rstrip("/").endswith("/api")


# WHATWG treats a percent-encoded dot as a dot segment, in either case, and in
# either half of a double-dot. RFC 3986 §5.2.4 knows only the literal spellings.
_SINGLE_DOT_SEGMENTS = frozenset({".", "%2e"})
_DOUBLE_DOT_SEGMENTS = frozenset({"..", ".%2e", "%2e.", "%2e%2e"})


def _remove_dot_segments(path: str) -> str:
    """Resolve ``.`` and ``..`` in an absolute URL's path the way a browser
    does (RFC 3986 §5.2.4 plus the WHATWG ``%2e`` equivalences).

    A trailing dot segment leaves the slash behind: ``/api/.`` is ``/api/``,
    matching ``new URL().pathname``. The ``%2e`` handling is implemented
    here rather than relied on via the caller's separate percent-encoding
    refusal, since that refusal could change independently of this.
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
    ``127.0.0.0/8`` in its entirety, so e.g. ``127.0.0.2`` was previously
    read as non-loopback and could get a domain lock issued that every
    recipient resolves to their own machine. ``*.localhost`` counts too
    (RFC 6761 §6.3). Bracketed IPv6 literals are accepted since
    ``urlsplit(...).hostname`` strips brackets but a browser's
    ``URL.hostname`` does not.
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

    fix(#1548): Python and the browser disagree on canonical host
    spelling (e.g. ``192.168.1`` → ``192.168.0.1``; also octal/hex IPv4 and
    IPv6 non-compressed forms) — the shell presents the browser's reading
    while the lock stored Python's, so it was issued and then missed on
    every request. The trap: ``192.168.1`` ROUND-TRIPS cleanly through
    urlsplit, so a "parse it, re-serialize it, compare" check would pass
    it; only asserting canonical form directly catches it. The frontend
    needs no equivalent — it has a browser parser to compare against.
    ``public-app-url-shape.cases.json`` holds both sides to the same
    answers.
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
        # fix(#1555): an IPv4-mapped literal has no canonical spelling both
        # Python and a browser agree on, so it's refused outright rather
        # than translated.
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

    # A URL parser reads a host as IPv4 when its last label is numeric
    # (covers hex/octal too); ipaddress rejects non-canonical forms for us.
    last_label = host.rsplit(".", 1)[-1]
    if last_label.isdigit() or last_label.startswith("0x"):
        try:
            parsed_ip = ipaddress.IPv4Address(host)
        except ValueError:
            # Not expanded for them: that needs the WHATWG IPv4 parser, the
            # approximation this whole rule exists to avoid.
            return (
                f"{host!r} is read as an IP address by browsers, and not in the "
                "form they use. Write four decimal octets with no leading "
                "zeros, e.g. 192.168.0.1"
            )
        if str(parsed_ip) != host:
            return f"Write the IP address as: {parsed_ip}"
        return None

    # Registered name. Case isn't checked: both parsers lowercase it already.
    labels = host.split(".")
    if any(not label for label in labels):
        return f"{host!r} has an empty label."
    if not all(c.isalnum() or c == "-" for label in labels for c in label):
        return f"{host!r} contains a character that is not valid in a hostname."
    # fix(#1555): `xn--` labels are accepted as opaque LDH — Chromium/WebKit
    # don't validate them at all, Firefox enforces full RFC 5893 bidi rules,
    # and node matches neither; measured across 28 hosts they disagreed on
    # 13, all `xn--` cases. Any refusal we add is stricter than the engines
    # most viewers use, and no rule satisfies both; a node-based test can't
    # stand in for a browser here.
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

    SEC-05/M-67: when ``CORS_ALLOWED_ORIGINS`` is set, the derived origin
    must be in that allowlist, or an attacker controlling
    ``X-Forwarded-Host`` behind a permissive proxy could steer URL
    generation to their own host. Empty allowlist (local dev) returns the
    request-derived origin unchanged.

    fix(#1778): the second element distinguishes "no origin to derive" from
    "an origin was derived and the allowlist refused it" — resolvers must
    not treat those alike, or a raw-Host fallback re-derives the origin
    just rejected.
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

    Phase 268 H-27: when ``for_external_use=True`` the request-origin
    fallback is disabled and this raises ``PublicUrlNotConfiguredError`` if
    neither PUBLIC_APP_URL nor PUBLIC_API_URL is set — such a URL can reach
    a third party (e.g. an OAuth IdP) where an attacker-controlled origin
    enables auth-code theft.

    fix(#1778): the last-resort ``request.url.netloc`` fallback only runs
    when the allowlist had no opinion, not when it just rejected a derived
    origin — that fallback reads the raw ``Host`` header, which nginx
    forwards verbatim.
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

    BUG-025: ``_PUBLIC_URL_CACHE`` is a 60s memo of the public_app_url/
    public_api_url/public_base_url AppSetting rows, separate from the
    ``config:`` cache ``PersistentConfig`` manages — without clearing this
    too, a settings write keeps returning the old public URL for up to
    ``_PUBLIC_URL_CACHE_TTL``. ``PersistentConfig.set``/``reset`` call this
    when a ``PUBLIC_URL_KEYS`` entry is written.
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

    fix(#1548): unlike ``get_public_app_url``, this never derives from
    PUBLIC_API_URL or request headers. Domain locking and share-URL
    generation need the operator's own origin: a derived API origin can be
    a real, non-loopback host that still isn't where the embed shell is
    served (the original bug), and a request-derived origin is the
    vacuous-``self`` trap #1531 already ruled out. Unset is a legitimate
    answer here.

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

    fix(#1548): only ``request.state.tenant_public_origin`` counts as
    trustworthy here — ``TenantContextMiddleware`` sets it after validating
    the request Host against the tenant registry. An ``/api``-stripped
    PUBLIC_API_URL or a header-derived origin is inferred, not verified,
    and stays excluded (see ``get_configured_public_app_url``).

    Callers: share/embed URL generation, which must name a host the
    recipient can open — a tenant's own origin on a hosted tenant, since a
    copied link on the fleet host arrives without the tenant context its
    Host would carry.
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
