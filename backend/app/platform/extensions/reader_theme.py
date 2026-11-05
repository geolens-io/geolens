"""The reader theme a branding extension may set on story and dashboard pages."""

from __future__ import annotations

from urllib.parse import urlsplit

import structlog
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import validate_privacy_url_shape

logger = structlog.stdlib.get_logger(__name__)

_warned = False


_FONT_SEGMENT = (
    r"""(?:"[A-Za-z0-9 -]+"|'[A-Za-z0-9 -]+'|[A-Za-z0-9-]+(?: [A-Za-z0-9-]+)*)"""
)
_FONT_LIST = rf"^ ?{_FONT_SEGMENT} ?(?:, ?{_FONT_SEGMENT} ?)*$"


class ReaderTheme(BaseModel):
    """An accent colour, a logo and a font family for reader-facing pages.

    The frontend applies these as theme tokens only. A font is named, never
    fetched: the operator ships the font file, since the CSP allows no remote
    fonts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    accent: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
        description="The accent colour as `#rrggbb`.",
    )
    logo_url: str | None = Field(
        default=None,
        max_length=2000,
        description="An https URL of the logo shown in the page header.",
    )
    font_family: str | None = Field(
        default=None,
        max_length=100,
        # A comma-separated list of family names, each quoted or bare and
        # never empty, so the page can append its own fallback after it.
        pattern=_FONT_LIST,
        description="A CSS font family list the page's text uses first.",
    )

    @field_validator("logo_url")
    @classmethod
    def _https_logo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = validate_privacy_url_shape(value)
        if urlsplit(value).scheme != "https":
            raise ValueError("must be an https URL")
        return value


def current_reader_theme() -> ReaderTheme | None:
    """Return the registered branding extension's reader theme, or None.

    A theme that fails validation, or an extension that raises, gives None
    and one warning per process, so a bad overlay never breaks a page.
    """
    global _warned
    from app.platform.extensions import get_branding_extension

    try:
        theme = get_branding_extension().get_reader_theme()
        if theme is None:
            return None
        raw = theme.model_dump() if isinstance(theme, BaseModel) else theme
        return ReaderTheme.model_validate(raw)
    except Exception:  # broad: an overlay's theme must never fail the page it decorates
        if not _warned:
            _warned = True
            logger.warning("extensions.reader_theme.invalid", exc_info=True)
        return None
