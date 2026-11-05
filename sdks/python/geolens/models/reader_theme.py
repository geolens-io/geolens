from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ReaderTheme")


@_attrs_define
class ReaderTheme:
    """An accent colour, a logo and a font family for reader-facing pages.

    The frontend applies these as theme tokens only. A font is named, never
    fetched: the operator ships the font file, since the CSP allows no remote
    fonts.

        Attributes:
            accent (None | str | Unset): The accent colour as `#rrggbb`.
            logo_url (None | str | Unset): An https URL of the logo shown in the page header.
            font_family (None | str | Unset): A CSS font family list the page's text uses first.
    """

    accent: None | str | Unset = UNSET
    logo_url: None | str | Unset = UNSET
    font_family: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        accent: None | str | Unset
        if isinstance(self.accent, Unset):
            accent = UNSET
        else:
            accent = self.accent

        logo_url: None | str | Unset
        if isinstance(self.logo_url, Unset):
            logo_url = UNSET
        else:
            logo_url = self.logo_url

        font_family: None | str | Unset
        if isinstance(self.font_family, Unset):
            font_family = UNSET
        else:
            font_family = self.font_family

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if accent is not UNSET:
            field_dict["accent"] = accent
        if logo_url is not UNSET:
            field_dict["logo_url"] = logo_url
        if font_family is not UNSET:
            field_dict["font_family"] = font_family

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_accent(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        accent = _parse_accent(d.pop("accent", UNSET))

        def _parse_logo_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        logo_url = _parse_logo_url(d.pop("logo_url", UNSET))

        def _parse_font_family(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        font_family = _parse_font_family(d.pop("font_family", UNSET))

        reader_theme = cls(
            accent=accent,
            logo_url=logo_url,
            font_family=font_family,
        )

        return reader_theme
