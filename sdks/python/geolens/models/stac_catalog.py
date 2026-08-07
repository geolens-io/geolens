from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.stac_link import StacLink


T = TypeVar("T", bound="StacCatalog")


@_attrs_define
class StacCatalog:
    """STAC Catalog / landing page response.

    Attributes:
        id (str): Stable identifier for the catalog.
        title (str): Catalog title.
        description (str): Human-readable catalog description.
        conforms_to (list[str]): List of conformance URIs declaring which STAC and OGC API standards the catalog
            implements.
        links (list[StacLink]): Catalog navigation links (self, root, search, collections, etc.).
        type_ (str | Unset): STAC object type. Always 'Catalog' for the landing page. Default: 'Catalog'.
        stac_version (str | Unset): STAC specification version implemented. Default: '1.0.0'.
    """

    id: str
    title: str
    description: str
    conforms_to: list[str]
    links: list[StacLink]
    type_: str | Unset = "Catalog"
    stac_version: str | Unset = "1.0.0"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        title = self.title

        description = self.description

        conforms_to = self.conforms_to

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        type_ = self.type_

        stac_version = self.stac_version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "title": title,
                "description": description,
                "conformsTo": conforms_to,
                "links": links,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_
        if stac_version is not UNSET:
            field_dict["stac_version"] = stac_version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_link import StacLink

        d = dict(src_dict)
        id = d.pop("id")

        title = d.pop("title")

        description = d.pop("description")

        conforms_to = cast(list[str], d.pop("conformsTo"))

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = StacLink.from_dict(links_item_data)

            links.append(links_item)

        type_ = d.pop("type", UNSET)

        stac_version = d.pop("stac_version", UNSET)

        stac_catalog = cls(
            id=id,
            title=title,
            description=description,
            conforms_to=conforms_to,
            links=links,
            type_=type_,
            stac_version=stac_version,
        )

        stac_catalog.additional_properties = d
        return stac_catalog

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
