"""Domain exceptions for the config_ops service layer."""


class ConfigValidationError(Exception):
    """Raised when config import validation fails."""

    pass


class ConfigLockedError(Exception):
    """Raised when configuration is locked to environment variables."""

    pass
