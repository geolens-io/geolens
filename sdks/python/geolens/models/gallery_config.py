from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


if TYPE_CHECKING:
    from ..models.gallery_image import GalleryImage


T = TypeVar("T", bound="GalleryConfig")


@_attrs_define
class GalleryConfig:
    """
    Attributes:
        images (list[GalleryImage]): Images uploaded to the host story, in reading order.
    """

    images: list[GalleryImage]

    def to_dict(self) -> dict[str, Any]:
        images = []
        for images_item_data in self.images:
            images_item = images_item_data.to_dict()
            images.append(images_item)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "images": images,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.gallery_image import GalleryImage

        d = dict(src_dict)
        images = []
        _images = d.pop("images")
        for images_item_data in _images:
            images_item = GalleryImage.from_dict(images_item_data)

            images.append(images_item)

        gallery_config = cls(
            images=images,
        )

        return gallery_config
