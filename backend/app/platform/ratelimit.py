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

from functools import cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import structlog
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings
from app.core.persistent_config import get_cached_global_rate_limit

logger = structlog.stdlib.get_logger(__name__)

# fix(#2018): the schemes BOTH limits' sync storage and redis-py accept.
# `redis_url` reaches redis-py directly in `platform/cache`, so a scheme
# outside this set cannot be a working deployment's value anyway.
_SHARED_STORAGE_SCHEMES = frozenset({"redis", "rediss"})

# fix(#2018): limits' sync storage blocks the event loop for its round trip,
# so a hung store has to fail into the in-memory fallback fast.
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
    logger.warning(
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
        logger.warning(
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
    logger.warning(
        "rate_limit_storage_scheme_unsupported",
        scheme=scheme or "none",
        consequence="rate-limit buckets stay per uvicorn worker",
        remediation="set REDIS_URL to a redis:// or rediss:// URL",
    )
    return None


def _global_rate_limit(_request: Request | None = None) -> str:
    return f"{get_cached_global_rate_limit()}/second"


class _FallbackAnnouncingLimiter(Limiter):
    """A Limiter that announces losing and regaining its shared store."""

    _storage_dead_state = False

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


limiter = _FallbackAnnouncingLimiter(
    key_func=get_remote_address,
    default_limits=[_global_rate_limit],
    key_style="endpoint",
    storage_uri=shared_storage_uri(),
    storage_options={
        "socket_timeout": STORAGE_SOCKET_TIMEOUT_SECONDS,
        "socket_connect_timeout": STORAGE_SOCKET_TIMEOUT_SECONDS,
    },
    in_memory_fallback_enabled=True,
)
