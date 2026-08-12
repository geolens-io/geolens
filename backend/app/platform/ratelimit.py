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
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.persistent_config import get_cached_global_rate_limit


def _global_rate_limit(_request: Request | None = None) -> str:
    return f"{get_cached_global_rate_limit()}/second"


limiter = Limiter(key_func=get_remote_address, default_limits=[_global_rate_limit])
