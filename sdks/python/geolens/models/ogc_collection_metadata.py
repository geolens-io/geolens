from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.ogc_collection_metadata_extent_type_0 import (
        OGCCollectionMetadataExtentType0,
    )
    from ..models.ogc_link import OGCLink


T = TypeVar("T", bound="OGCCollectionMetadata")


@_attrs_define
class OGCCollectionMetadata:
    """Per-dataset collection metadata per OGC API Features.

    Attributes:
        id (str): Stable collection identifier (typically the dataset ID).
        links (list[OGCLink]): Collection navigation links (self, items, queryables, etc.).
        title (str): Human-readable collection title.
        crs (list[str] | Unset): Coordinate reference systems supported for items in this collection.
        description (None | str | Unset): Collection description.
        extent (None | OGCCollectionMetadataExtentType0 | Unset): Spatial and temporal extent (OGC API Features extent
            object).
        item_type (str | Unset): Type of items in the collection. Always 'feature' for OGC API Features. Default:
            'feature'.
    """

    id: str
    links: list[OGCLink]
    title: str
    crs: list[str] | Unset = UNSET
    description: None | str | Unset = UNSET
    extent: None | OGCCollectionMetadataExtentType0 | Unset = UNSET
    item_type: str | Unset = "feature"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.ogc_collection_metadata_extent_type_0 import (
            OGCCollectionMetadataExtentType0,
        )

        id = self.id

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        title = self.title

        crs: list[str] | Unset = UNSET
        if not isinstance(self.crs, Unset):
            crs = self.crs

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        extent: dict[str, Any] | None | Unset
        if isinstance(self.extent, Unset):
            extent = UNSET
        elif isinstance(self.extent, OGCCollectionMetadataExtentType0):
            extent = self.extent.to_dict()
        else:
            extent = self.extent

        item_type = self.item_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "links": links,
                "title": title,
            }
        )
        if crs is not UNSET:
            field_dict["crs"] = crs
        if description is not UNSET:
            field_dict["description"] = description
        if extent is not UNSET:
            field_dict["extent"] = extent
        if item_type is not UNSET:
            field_dict["itemType"] = item_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ogc_collection_metadata_extent_type_0 import (
            OGCCollectionMetadataExtentType0,
        )
        from ..models.ogc_link import OGCLink

        d = dict(src_dict)
        id = d.pop("id")

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = OGCLink.from_dict(links_item_data)

            links.append(links_item)

        title = d.pop("title")

        crs = cast(list[str], d.pop("crs", UNSET))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_extent(
            data: object,
        ) -> None | OGCCollectionMetadataExtentType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                extent_type_0 = OGCCollectionMetadataExtentType0.from_dict(data)

                return extent_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OGCCollectionMetadataExtentType0 | Unset, data)

        extent = _parse_extent(d.pop("extent", UNSET))

        item_type = d.pop("itemType", UNSET)

        ogc_collection_metadata = cls(
            id=id,
            links=links,
            title=title,
            crs=crs,
            description=description,
            extent=extent,
            item_type=item_type,
        )

        ogc_collection_metadata.additional_properties = d
        return ogc_collection_metadata

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
