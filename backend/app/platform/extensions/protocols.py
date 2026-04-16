"""Protocol interfaces for GeoLens extension points.

Uses only stdlib types to avoid circular imports with domain models.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class BrandingExtension(Protocol):
    """Extension point for branding customization."""

    def get_branding_defaults(self) -> dict[str, object]: ...


@runtime_checkable
class AuditExtension(Protocol):
    """Extension point for audit export formats."""

    def get_export_formats(self) -> list[str]: ...


@runtime_checkable
class AuthExtension(Protocol):
    """Extension point for additional auth methods."""

    def get_auth_methods(self) -> list[str]: ...
