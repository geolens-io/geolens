"""Deprecated: AppSettingsService replaced by PersistentConfig in app.persistent_config.

This module is kept only for backwards compatibility with any remaining imports.
All new code should import directly from app.persistent_config.
"""

# Re-export for any remaining callers that import from here
from app.persistent_config import get_cached_login_rate_limit  # noqa: F401

DEFAULT_LOGIN_RATE_LIMIT = 5  # legacy constant
