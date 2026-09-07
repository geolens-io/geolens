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
