from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="MapIconResponse")


@_attrs_define
class MapIconResponse:
    """
    Attributes:
        id (str):
        media_type (str):
        name (str):
        slug (str):
        sprite_id (str):
        url (str):
        builtin (bool | Unset):  Default: False.
        size_bytes (int | None | Unset):
    """

    id: str
    media_type: str
    name: str
    slug: str
    sprite_id: str
    url: str
    builtin: bool | Unset = False
    size_bytes: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        media_type = self.media_type

        name = self.name

        slug = self.slug

        sprite_id = self.sprite_id

        url = self.url

        builtin = self.builtin

        size_bytes: int | None | Unset
        if isinstance(self.size_bytes, Unset):
            size_bytes = UNSET
        else:
            size_bytes = self.size_bytes

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "media_type": media_type,
                "name": name,
                "slug": slug,
                "sprite_id": sprite_id,
                "url": url,
            }
        )
        if builtin is not UNSET:
            field_dict["builtin"] = builtin
        if size_bytes is not UNSET:
            field_dict["size_bytes"] = size_bytes

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        media_type = d.pop("media_type")

        name = d.pop("name")

        slug = d.pop("slug")

        sprite_id = d.pop("sprite_id")

        url = d.pop("url")

        builtin = d.pop("builtin", UNSET)

        def _parse_size_bytes(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        size_bytes = _parse_size_bytes(d.pop("size_bytes", UNSET))

        map_icon_response = cls(
            id=id,
            media_type=media_type,
            name=name,
            slug=slug,
            sprite_id=sprite_id,
            url=url,
            builtin=builtin,
            size_bytes=size_bytes,
        )

        map_icon_response.additional_properties = d
        return map_icon_response

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
