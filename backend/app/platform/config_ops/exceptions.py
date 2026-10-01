"""Domain exceptions for the config_ops service layer."""


class ConfigValidationError(Exception):
    """Raised when config import validation fails."""

    pass


class ConfigBusyError(Exception):
    """Raised when another embedding width change is still running."""

    pass


class ConfigLockedError(Exception):
    """Raised when configuration is locked to environment variables."""

    pass


class ConfigApplyError(Exception):
    """Raised when part of a committed import could not take effect and was reverted."""

    pass


class ConfigPreviewError(Exception):
    """Raised when an overwrite is not backed by a current, matching preview."""

    pass
