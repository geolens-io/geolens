from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from uuid import UUID


T = TypeVar("T", bound="DistributionResponse")


@_attrs_define
class DistributionResponse:
    """
    Attributes:
        id (UUID):
        record_id (UUID):
        distribution_type (str):
        format_ (None | str):
        url (str):
        title (None | str):
        description (None | str):
        protocol (None | str):
        media_type (None | str):
        is_primary (bool):
        auto_generated (bool): True if created automatically by the system
    """

    id: UUID
    record_id: UUID
    distribution_type: str
    format_: None | str
    url: str
    title: None | str
    description: None | str
    protocol: None | str
    media_type: None | str
    is_primary: bool
    auto_generated: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        record_id = str(self.record_id)

        distribution_type = self.distribution_type

        format_: None | str
        format_ = self.format_

        url = self.url

        title: None | str
        title = self.title

        description: None | str
        description = self.description

        protocol: None | str
        protocol = self.protocol

        media_type: None | str
        media_type = self.media_type

        is_primary = self.is_primary

        auto_generated = self.auto_generated

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "record_id": record_id,
                "distribution_type": distribution_type,
                "format": format_,
                "url": url,
                "title": title,
                "description": description,
                "protocol": protocol,
                "media_type": media_type,
                "is_primary": is_primary,
                "auto_generated": auto_generated,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        record_id = UUID(d.pop("record_id"))

        distribution_type = d.pop("distribution_type")

        def _parse_format_(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        format_ = _parse_format_(d.pop("format"))

        url = d.pop("url")

        def _parse_title(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        title = _parse_title(d.pop("title"))

        def _parse_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        description = _parse_description(d.pop("description"))

        def _parse_protocol(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        protocol = _parse_protocol(d.pop("protocol"))

        def _parse_media_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        media_type = _parse_media_type(d.pop("media_type"))

        is_primary = d.pop("is_primary")

        auto_generated = d.pop("auto_generated")

        distribution_response = cls(
            id=id,
            record_id=record_id,
            distribution_type=distribution_type,
            format_=format_,
            url=url,
            title=title,
            description=description,
            protocol=protocol,
            media_type=media_type,
            is_primary=is_primary,
            auto_generated=auto_generated,
        )

        distribution_response.additional_properties = d
        return distribution_response

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
