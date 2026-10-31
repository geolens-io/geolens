from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from dateutil.parser import isoparse
from uuid import UUID
import datetime


T = TypeVar("T", bound="StoryAssetResponse")


@_attrs_define
class StoryAssetResponse:
    """
    Attributes:
        id (UUID): Served at `/stories/{story_id}/assets/{id}` as WebP.
        width (int):
        height (int):
        byte_size (int): Size of the stored image in all its sizes.
        created_at (datetime.datetime):
    """

    id: UUID
    width: int
    height: int
    byte_size: int
    created_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        width = self.width

        height = self.height

        byte_size = self.byte_size

        created_at = self.created_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "width": width,
                "height": height,
                "byte_size": byte_size,
                "created_at": created_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        width = d.pop("width")

        height = d.pop("height")

        byte_size = d.pop("byte_size")

        created_at = isoparse(d.pop("created_at"))

        story_asset_response = cls(
            id=id,
            width=width,
            height=height,
            byte_size=byte_size,
            created_at=created_at,
        )

        story_asset_response.additional_properties = d
        return story_asset_response

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
