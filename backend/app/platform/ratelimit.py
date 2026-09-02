"""The process-wide SlowAPI limiter, in a home that is cheap to import.

Ten modules — five routers under ``modules/``, three under ``processing/``,
and ``api/main.py``, which binds it to ``app.state.limiter`` — need this
instance at module scope for their ``@limiter.limit`` decorators. It used to
live in ``app.modules.auth.router``, so importing a rate limiter registered
that router's 28 auth routes and pulled its whole transitive import graph as a
side effect. That is the API-edge coupling fix(#836) removed from the platform
ports (``test_platform_never_imports_processing_routers``), reached from the
other direction.

Nothing here may import ``app.modules.*``: the layering guard forbids it for
platform/, and an import cycle is the concrete reason — ``modules/auth`` and
four other domains import this module.

``_global_rate_limit`` is a callable rather than a literal because the global
limit is admin-editable at runtime; SlowAPI re-evaluates the default per
request, so a settings change takes effect without a restart.

fix(#1778): ``key_style="endpoint"`` keys the counter on (client IP, handler)
instead of (client IP, request path), which is slowapi's default. Under the
default every distinct URL got its own budget, so a path-parameterised route
handed one IP a fresh "Global Rate Limit (per second)" allowance per dataset
id and per z/x/y. The setting operators read as a cap on anonymous request
cost bounded nothing the caller could not multiply for free by varying a path
segment. Handlers are enumerated by the route table, so the remaining
multiplier is fixed at deploy time rather than chosen by the caller.

Two things move with it, both recorded rather than papered over. The
trailing-slash aliases of a dual-shape route now share one bucket, which is
strictly stricter and is what the guard in ``tests/test_admin_rate_limit.py``
was always asking for. Two methods on one path no longer share theirs, which
is looser by the number of methods the route table declares; that number is
fixed, unlike the number of URLs. Requests matching no route are unaffected
either way: slowapi's middleware exempts a request whose handler it cannot
resolve before key style is ever consulted
(``slowapi/middleware.py::_should_exempt``).
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.persistent_config import get_cached_global_rate_limit


def _global_rate_limit(_request: Request | None = None) -> str:
    return f"{get_cached_global_rate_limit()}/second"


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_global_rate_limit],
    key_style="endpoint",
)
