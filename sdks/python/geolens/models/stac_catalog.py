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
        conforms_to (list[str]): List of conformance URIs declaring which STAC and OGC API standards the catalog
            implements.
        description (str): Human-readable catalog description.
        id (str): Stable identifier for the catalog.
        links (list[StacLink]): Catalog navigation links (self, root, search, collections, etc.).
        title (str): Catalog title.
        stac_version (str | Unset): STAC specification version implemented. Default: '1.0.0'.
        type_ (str | Unset): STAC object type. Always 'Catalog' for the landing page. Default: 'Catalog'.
    """

    conforms_to: list[str]
    description: str
    id: str
    links: list[StacLink]
    title: str
    stac_version: str | Unset = "1.0.0"
    type_: str | Unset = "Catalog"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        conforms_to = self.conforms_to

        description = self.description

        id = self.id

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        title = self.title

        stac_version = self.stac_version

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "conformsTo": conforms_to,
                "description": description,
                "id": id,
                "links": links,
                "title": title,
            }
        )
        if stac_version is not UNSET:
            field_dict["stac_version"] = stac_version
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_link import StacLink

        d = dict(src_dict)
        conforms_to = cast(list[str], d.pop("conformsTo"))

        description = d.pop("description")

        id = d.pop("id")

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = StacLink.from_dict(links_item_data)

            links.append(links_item)

        title = d.pop("title")

        stac_version = d.pop("stac_version", UNSET)

        type_ = d.pop("type", UNSET)

        stac_catalog = cls(
            conforms_to=conforms_to,
            description=description,
            id=id,
            links=links,
            title=title,
            stac_version=stac_version,
            type_=type_,
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
