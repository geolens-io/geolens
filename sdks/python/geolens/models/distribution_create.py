from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="DistributionCreate")


@_attrs_define
class DistributionCreate:
    """
    Attributes:
        distribution_type (str): e.g. download, api, ogc_wms, ogc_wfs
        format_ (str): File or service format, e.g. GeoJSON, SHP, WMS
        url (str): Access URL for this distribution
        description (None | str | Unset):
        is_primary (bool | Unset): Mark as the preferred distribution Default: False.
        media_type (None | str | Unset): IANA media type, e.g. application/geo+json
        protocol (None | str | Unset): Transfer protocol, e.g. HTTPS, OGC:WFS
        title (None | str | Unset):
    """

    distribution_type: str
    format_: str
    url: str
    description: None | str | Unset = UNSET
    is_primary: bool | Unset = False
    media_type: None | str | Unset = UNSET
    protocol: None | str | Unset = UNSET
    title: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        distribution_type = self.distribution_type

        format_ = self.format_

        url = self.url

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        is_primary = self.is_primary

        media_type: None | str | Unset
        if isinstance(self.media_type, Unset):
            media_type = UNSET
        else:
            media_type = self.media_type

        protocol: None | str | Unset
        if isinstance(self.protocol, Unset):
            protocol = UNSET
        else:
            protocol = self.protocol

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "distribution_type": distribution_type,
                "format": format_,
                "url": url,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if is_primary is not UNSET:
            field_dict["is_primary"] = is_primary
        if media_type is not UNSET:
            field_dict["media_type"] = media_type
        if protocol is not UNSET:
            field_dict["protocol"] = protocol
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        distribution_type = d.pop("distribution_type")

        format_ = d.pop("format")

        url = d.pop("url")

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        is_primary = d.pop("is_primary", UNSET)

        def _parse_media_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        media_type = _parse_media_type(d.pop("media_type", UNSET))

        def _parse_protocol(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        protocol = _parse_protocol(d.pop("protocol", UNSET))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        distribution_create = cls(
            distribution_type=distribution_type,
            format_=format_,
            url=url,
            description=description,
            is_primary=is_primary,
            media_type=media_type,
            protocol=protocol,
            title=title,
        )

        distribution_create.additional_properties = d
        return distribution_create

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
