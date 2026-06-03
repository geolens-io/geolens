from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.stac_collection_extent import StacCollectionExtent
    from ..models.stac_link import StacLink


T = TypeVar("T", bound="StacCollection")


@_attrs_define
class StacCollection:
    """A single STAC Collection response (permissive — allows extra STAC fields).

    Attributes:
        extent (StacCollectionExtent): Spatial and temporal extent of items in the collection.
        id (str): Stable collection identifier.
        links (list[StacLink]): Collection navigation links.
        description (str | Unset): Collection description. Default: ''.
        license_ (str | Unset): SPDX license identifier or 'proprietary'. Default: 'proprietary'.
        stac_version (str | Unset): STAC specification version. Default: '1.0.0'.
        title (None | str | Unset): Human-readable collection title.
        type_ (str | Unset): STAC object type. Default: 'Collection'.
    """

    extent: StacCollectionExtent
    id: str
    links: list[StacLink]
    description: str | Unset = ""
    license_: str | Unset = "proprietary"
    stac_version: str | Unset = "1.0.0"
    title: None | str | Unset = UNSET
    type_: str | Unset = "Collection"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        extent = self.extent.to_dict()

        id = self.id

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        description = self.description

        license_ = self.license_

        stac_version = self.stac_version

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "extent": extent,
                "id": id,
                "links": links,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if license_ is not UNSET:
            field_dict["license"] = license_
        if stac_version is not UNSET:
            field_dict["stac_version"] = stac_version
        if title is not UNSET:
            field_dict["title"] = title
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_collection_extent import StacCollectionExtent
        from ..models.stac_link import StacLink

        d = dict(src_dict)
        extent = StacCollectionExtent.from_dict(d.pop("extent"))

        id = d.pop("id")

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = StacLink.from_dict(links_item_data)

            links.append(links_item)

        description = d.pop("description", UNSET)

        license_ = d.pop("license", UNSET)

        stac_version = d.pop("stac_version", UNSET)

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        type_ = d.pop("type", UNSET)

        stac_collection = cls(
            extent=extent,
            id=id,
            links=links,
            description=description,
            license_=license_,
            stac_version=stac_version,
            title=title,
            type_=type_,
        )

        stac_collection.additional_properties = d
        return stac_collection

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
