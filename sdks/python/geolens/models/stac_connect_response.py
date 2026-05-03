from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="StacConnectResponse")


@_attrs_define
class StacConnectResponse:
    """
    Attributes:
        catalog_id (str): Catalog identifier from the landing page.
        description (str): Catalog description.
        stac_version (str): STAC specification version.
        title (str): Catalog title.
        url (str): Normalized STAC API URL.
    """

    catalog_id: str
    description: str
    stac_version: str
    title: str
    url: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        catalog_id = self.catalog_id

        description = self.description

        stac_version = self.stac_version

        title = self.title

        url = self.url

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "catalog_id": catalog_id,
                "description": description,
                "stac_version": stac_version,
                "title": title,
                "url": url,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        catalog_id = d.pop("catalog_id")

        description = d.pop("description")

        stac_version = d.pop("stac_version")

        title = d.pop("title")

        url = d.pop("url")

        stac_connect_response = cls(
            catalog_id=catalog_id,
            description=description,
            stac_version=stac_version,
            title=title,
            url=url,
        )

        stac_connect_response.additional_properties = d
        return stac_connect_response

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
