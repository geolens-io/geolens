from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="GalleryImage")


@_attrs_define
class GalleryImage:
    """
    Attributes:
        asset_id (UUID): An image uploaded to the host story.
        alt (None | str | Unset): Text that stands in for the image; required unless it is decorative.
        decorative (bool | None | Unset): True when the image adds nothing a reader needs: readers get an empty alt, and
            `alt` may be left out.
        caption (None | str | Unset):
    """

    asset_id: UUID
    alt: None | str | Unset = UNSET
    decorative: bool | None | Unset = UNSET
    caption: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        asset_id = str(self.asset_id)

        alt: None | str | Unset
        if isinstance(self.alt, Unset):
            alt = UNSET
        else:
            alt = self.alt

        decorative: bool | None | Unset
        if isinstance(self.decorative, Unset):
            decorative = UNSET
        else:
            decorative = self.decorative

        caption: None | str | Unset
        if isinstance(self.caption, Unset):
            caption = UNSET
        else:
            caption = self.caption

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "asset_id": asset_id,
            }
        )
        if alt is not UNSET:
            field_dict["alt"] = alt
        if decorative is not UNSET:
            field_dict["decorative"] = decorative
        if caption is not UNSET:
            field_dict["caption"] = caption

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        asset_id = UUID(d.pop("asset_id"))

        def _parse_alt(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        alt = _parse_alt(d.pop("alt", UNSET))

        def _parse_decorative(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        decorative = _parse_decorative(d.pop("decorative", UNSET))

        def _parse_caption(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        caption = _parse_caption(d.pop("caption", UNSET))

        gallery_image = cls(
            asset_id=asset_id,
            alt=alt,
            decorative=decorative,
            caption=caption,
        )

        return gallery_image
