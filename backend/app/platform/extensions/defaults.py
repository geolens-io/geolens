"""Community-edition default implementations of extension protocols."""

from __future__ import annotations


class DefaultBrandingExtension:
    """Default branding: shows community badge."""

    def get_branding_defaults(self) -> dict[str, object]:
        return {"show_badge": True}


class DefaultAuditExtension:
    """Default audit: no additional export formats."""

    def get_export_formats(self) -> list[str]:
        return []


class DefaultAuthExtension:
    """Default auth: no additional auth methods."""

    def get_auth_methods(self) -> list[str]:
        return []
