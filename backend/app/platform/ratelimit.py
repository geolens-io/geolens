"""Process-wide SlowAPI limiter; lives in platform/ to stay cheap to import.

fix(#836): moved out of ``app.modules.auth.router`` so importing the limiter
no longer drags in that router's whole transitive graph. Nothing here may
import ``app.modules.*`` — several domains import this module, so that would
be a cycle.

``_global_rate_limit`` is a callable, not a literal: the limit is
admin-editable at runtime and SlowAPI re-evaluates the default per request.

fix(#1778): ``key_style="endpoint"`` keys the counter on (client IP, handler)
rather than (client IP, path), slowapi's default. Otherwise a
path-parameterised route hands one IP a fresh budget per dataset id or per
z/x/y, multiplying the configured cap for free. See
``tests/test_admin_rate_limit.py``.

fix(#2018): with ``REDIS_URL`` set every bucket is one counter the whole
cluster shares, instead of one per uvicorn worker (the bundled prod compose
runs two, so each configured cap was really twice that). ``in_memory_
fallback_enabled`` keeps an outage degrading to per-worker counting, the
pre-#2018 behaviour, rather than to no limit or a 500 per request.
"""

from __future__ import annotations

import inspect
import itertools
from collections.abc import Callable
from functools import cache
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import structlog
from fastapi import Request
from limits.aio.strategies import STRATEGIES as ASYNC_STRATEGIES
from limits.storage import storage_from_string
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from slowapi.wrappers import Limit

from app.core.config import settings
from app.core.persistent_config import get_cached_global_rate_limit
from app.platform.redis_protocol import REDIS_PROTOCOL

logger = structlog.stdlib.get_logger(__name__)

# fix(#2018): the storage decision is made while this module is imported,
# which `app/api/main.py` does before it calls `setup_logging`. Logging there
# renders console-formatted lines outside the JSON stream an operator greps,
# so the notices queue here and the app flushes them once logging is up.
_startup_notices: list[tuple[str, dict[str, Any]]] = []


def _notice(event: str, **fields: Any) -> None:
    _startup_notices.append((event, fields))


def emit_startup_notices() -> None:
    """Log every queued storage notice. Call once, after logging is set up."""
    while _startup_notices:
        event, fields = _startup_notices.pop(0)
        logger.warning(event, **fields)


# fix(#2018): the schemes BOTH limits' sync storage and redis-py accept.
# `redis_url` reaches redis-py directly in `platform/cache`, so a scheme
# outside this set cannot be a working deployment's value anyway.
_SHARED_STORAGE_SCHEMES = frozenset({"redis", "rediss"})

# The per-route decorators reach the store through limits' sync storage, which
# blocks the event loop for the round trip, and the global check holds each
# request until the async client answers. Either way a hung store has to fail
# into the in-memory fallback fast.
STORAGE_SOCKET_TIMEOUT_SECONDS = 0.25

# fix(#2018): every URL parameter that can widen how long ONE call holds the
# event loop. redis-py parses each from the URL and lets the querystring win
# over the keyword arguments; either retry flag also lifts retries 0 -> 1,
# doubling the bound. That bound is not the operator's to widen.
_PINNED_CLIENT_PARAMS = frozenset(
    {"socket_timeout", "socket_connect_timeout", "retry_on_timeout", "retry_on_error"}
)


def _pin_call_duration(url: str) -> str:
    """Return *url* without any query parameter that lengthens one call."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    # fix(#2018): REDIS_URL is an operator-supplied boot-time value parsed
    # once at import, the same class as config.py's DATABASE_URL_OVERRIDE
    # sites; a raise here would fail boot rather than refuse a request.
    pairs = parse_qsl(parts.query, keep_blank_values=True)  # parse_qs: unbounded
    kept = [(k, v) for k, v in pairs if k.lower() not in _PINNED_CLIENT_PARAMS]
    if len(kept) == len(pairs):
        return url
    _notice(
        "rate_limit_storage_call_duration_override_ignored",
        parameters=sorted({k.lower() for k, _ in pairs} & _PINNED_CLIENT_PARAMS),
        consequence="the store is held to the built-in socket timeout",
    )
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment)
    )


@cache
def shared_storage_uri() -> str | None:
    """The cluster-wide rate-limit store URL, or None to count per process.

    Cached so both readers (this limiter and the claim store) resolve one
    answer and a refused scheme is reported once per process.
    """
    url = settings.redis_url
    if not url:
        _notice(
            "rate_limit_storage_not_configured",
            consequence="rate-limit buckets count per uvicorn worker",
            remediation="set REDIS_URL when running more than one uvicorn worker",
        )
        return None
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        scheme = ""
    if scheme in _SHARED_STORAGE_SCHEMES:
        return _pin_call_duration(url)
    # fix(#2018): the scheme, never the URL -- REDIS_URL commonly carries a
    # password in its userinfo, and redact_url_credentials only rewrites
    # http(s), so it would hand a credential straight to the log.
    _notice(
        "rate_limit_storage_scheme_unsupported",
        scheme=scheme or "none",
        consequence="rate-limit buckets stay per uvicorn worker",
        remediation="set REDIS_URL to a redis:// or rediss:// URL",
    )
    return None


def _global_rate_limit(_request: Request | None = None) -> str:
    return f"{get_cached_global_rate_limit()}/second"


def _async_shared_limiter(
    uri: str, strategy: str | None, options: dict[str, Any]
) -> Any:
    """The async twin of the sync shared store, on the same parsed config.

    redis-py parses *uri* into the async pool exactly as it does for the sync
    client (host and port defaults, auth, db, query options, TLS), and limits
    gets the pool rather than the URL, whose stricter parser refuses some
    spellings redis-py accepts. Raises RuntimeError naming only the scheme,
    since the URL can carry a password.
    """
    import redis.asyncio

    try:
        pool = redis.asyncio.ConnectionPool.from_url(uri, **options)
        storage = storage_from_string(
            "async+redis://", implementation="redispy", connection_pool=pool
        )
    except Exception as exc:  # broad: refuse boot with a message that names no secret
        scheme = urlsplit(uri).scheme
        raise RuntimeError(
            f"REDIS_URL ({scheme}://...) works for the sync rate-limit store but "
            f"could not configure its async client: {type(exc).__name__}"
        ) from None
    return ASYNC_STRATEGIES[strategy or "fixed-window"](storage)


def _endpoint_name(endpoint: Callable[..., Any]) -> str:
    return f"{endpoint.__module__}.{endpoint.__name__}"


class _FallbackAnnouncingLimiter(Limiter):
    """A Limiter that announces losing and regaining its shared store, and
    checks the default limits without blocking the event loop.

    slowapi's own middleware checks the default limits through limits' sync
    storage, a blocking Redis round trip on the event loop for every request.
    ``check_default_limits`` applies the same limits, keys and fallback
    through limits' asyncio storage on the same store; the per-route
    decorators keep slowapi's sync path.
    """

    _storage_dead_state = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Only a shared store does I/O. Without one the default limits count in
        # the sync in-memory storage the decorators share, which never blocks.
        self._async_limiter = None
        uri = self._storage_uri
        if uri and urlsplit(uri).scheme.lower() in _SHARED_STORAGE_SCHEMES:
            self._async_limiter = _async_shared_limiter(
                uri, self._strategy, self._storage_options
            )

    @property
    def _storage_dead(self) -> bool:
        return self._storage_dead_state

    @_storage_dead.setter
    def _storage_dead(self, dead: bool) -> None:
        # fix(#2018): slowapi flips this once per outage, on the first failed
        # check and again on recovery, so hooking the transition logs once
        # rather than once per rejected request.
        if dead == self._storage_dead_state:
            return
        self._storage_dead_state = dead
        if dead:
            logger.warning(
                "rate_limit_storage_unreachable",
                consequence="buckets count per uvicorn worker until it recovers",
            )
        else:
            logger.info("rate_limit_storage_recovered")

    def is_exempt_from_default_limits(
        self, endpoint: Callable[..., Any] | None
    ) -> bool:
        """Whether SlowAPIMiddleware would skip *endpoint* outright."""
        if not self.enabled or not self._auto_check or endpoint is None:
            return True
        name = _endpoint_name(endpoint)
        return name in self._exempt_routes or name in self._route_limits

    async def check_default_limits(
        self, request: Request, endpoint: Callable[..., Any]
    ) -> None:
        """Hit the default limits for *endpoint*; raise RateLimitExceeded.

        Mirrors slowapi's ``_check_request_limit`` for its middleware: the
        same limit list, keys, fallback to the in-memory store on a store
        error, and recovery probe on slowapi's own backoff.
        """
        name = _endpoint_name(endpoint)
        if (
            not self.enabled
            or name in self._exempt_routes
            or any(fn() for fn in self._request_filters)
        ):
            return
        # A route with a callable @limiter.limit still reaches here and pays
        # the default limits too; slowapi leaves the store probe to its
        # decorator.
        if (
            self._storage_dead
            and self._fallback_limiter is not None
            and name not in self._dynamic_route_limits
            and self._Limiter__should_check_backend()
            and await self._store_alive()
        ):
            self._storage_dead = False
            self._Limiter__check_backend_count = 0
        limits = list(itertools.chain(*self._application_limits, *self._default_limits))
        endpoint_key = (request["path"] or "") if self._key_style == "url" else name
        try:
            await self._evaluate_default_limits(request, endpoint_key, limits)
        except RateLimitExceeded:
            raise
        except Exception:  # broad: any store failure degrades to per-process counting
            if self._in_memory_fallback_enabled:
                # Concurrent checks fail together; each one counts in the
                # fallback, while the setter announces the outage only once.
                self._storage_dead = True
                await self._evaluate_default_limits(
                    request, endpoint_key, limits, fallback=True
                )
            elif self._swallow_errors:
                self.logger.exception("Failed to rate limit. Swallowing error")
            else:
                raise

    async def _store_alive(self) -> bool:
        if self._async_limiter is None:
            return self._storage.check()
        return await self._async_limiter.storage.check()

    async def _hit(
        self, limit: Limit, *identifiers: str, cost: int, fallback: bool
    ) -> bool:
        if fallback or (self._storage_dead and self._in_memory_fallback_enabled):
            return self._fallback_limiter.hit(limit.limit, *identifiers, cost=cost)
        if self._async_limiter is None:
            return self.limiter.hit(limit.limit, *identifiers, cost=cost)
        return await self._async_limiter.hit(limit.limit, *identifiers, cost=cost)

    async def _evaluate_default_limits(
        self,
        request: Request,
        endpoint_key: str,
        limits: list[Limit],
        *,
        fallback: bool = False,
    ) -> None:
        """slowapi's ``__evaluate_limits``, with the storage hit awaited."""
        failed_limit = None
        limit_for_header = None
        for lim in limits:
            if lim.is_exempt(request if lim._exempt_when_takes_request else None):
                continue
            if lim.methods is not None and request.method.lower() not in lim.methods:
                continue
            limit_scope = lim.scope or endpoint_key
            if lim.per_method:
                limit_scope += f":{request.method}"
            if "request" in inspect.signature(lim.key_func).parameters:
                limit_key = lim.key_func(request)
            else:
                limit_key = lim.key_func()
            args = [limit_key, limit_scope]
            if not all(args):
                self.logger.error(
                    "Skipping limit: %s. Empty value found in parameters.", lim.limit
                )
                continue
            if self._key_prefix:
                args = [self._key_prefix, *args]
            if not limit_for_header or lim.limit < limit_for_header[0]:
                limit_for_header = (lim.limit, args)
            cost = lim.cost(request) if callable(lim.cost) else lim.cost
            if not await self._hit(lim, *args, cost=cost, fallback=fallback):
                self.logger.warning(
                    "ratelimit %s (%s) exceeded at endpoint: %s",
                    lim.limit,
                    limit_key,
                    limit_scope,
                )
                failed_limit = lim
                limit_for_header = (lim.limit, args)
                break
        request.state.view_rate_limit = limit_for_header
        if failed_limit is not None:
            raise RateLimitExceeded(failed_limit)


limiter = _FallbackAnnouncingLimiter(
    key_func=get_remote_address,
    default_limits=[_global_rate_limit],
    key_style="endpoint",
    storage_uri=shared_storage_uri(),
    storage_options={
        "protocol": REDIS_PROTOCOL,
        "socket_timeout": STORAGE_SOCKET_TIMEOUT_SECONDS,
        "socket_connect_timeout": STORAGE_SOCKET_TIMEOUT_SECONDS,
    },
    in_memory_fallback_enabled=True,
)
