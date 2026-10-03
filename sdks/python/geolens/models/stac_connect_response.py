from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StacConnectResponse")


@_attrs_define
class StacConnectResponse:
    """
    Attributes:
        url (str): Normalized STAC API URL.
        catalog_id (str): Catalog identifier from the landing page.
        title (str): Catalog title.
        description (str): Catalog description.
        stac_version (str): STAC specification version.
        conforms_to (list[str] | Unset): Conformance classes from the landing page conformsTo, which tell a client which
            search extensions the catalog supports.
    """

    url: str
    catalog_id: str
    title: str
    description: str
    stac_version: str
    conforms_to: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        url = self.url

        catalog_id = self.catalog_id

        title = self.title

        description = self.description

        stac_version = self.stac_version

        conforms_to: list[str] | Unset = UNSET
        if not isinstance(self.conforms_to, Unset):
            conforms_to = self.conforms_to

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "url": url,
                "catalog_id": catalog_id,
                "title": title,
                "description": description,
                "stac_version": stac_version,
            }
        )
        if conforms_to is not UNSET:
            field_dict["conforms_to"] = conforms_to

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        url = d.pop("url")

        catalog_id = d.pop("catalog_id")

        title = d.pop("title")

        description = d.pop("description")

        stac_version = d.pop("stac_version")

        conforms_to = cast(list[str], d.pop("conforms_to", UNSET))

        stac_connect_response = cls(
            url=url,
            catalog_id=catalog_id,
            title=title,
            description=description,
            stac_version=stac_version,
            conforms_to=conforms_to,
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
