from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ImageConfig")


@_attrs_define
class ImageConfig:
    """
    Attributes:
        alt (str | Unset): Empty for decorative. Default: ''.
        caption (None | str | Unset):
    """

    alt: str | Unset = ""
    caption: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        alt = self.alt

        caption: None | str | Unset
        if isinstance(self.caption, Unset):
            caption = UNSET
        else:
            caption = self.caption

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if alt is not UNSET:
            field_dict["alt"] = alt
        if caption is not UNSET:
            field_dict["caption"] = caption

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        alt = d.pop("alt", UNSET)

        def _parse_caption(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        caption = _parse_caption(d.pop("caption", UNSET))

        image_config = cls(
            alt=alt,
            caption=caption,
        )

        return image_config
