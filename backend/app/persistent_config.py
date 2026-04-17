"""Compatibility shim — real code moved to app.core.persistent_config."""

from app.core.persistent_config import *  # noqa: F403
from app.core.persistent_config import _is_env_only, _registry  # noqa: F401
