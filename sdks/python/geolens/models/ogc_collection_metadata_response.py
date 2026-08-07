from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.ogc_collection_metadata_response_extent_type_0 import (
        OGCCollectionMetadataResponseExtentType0,
    )
    from ..models.ogc_collection_metadata_response_links_item import (
        OGCCollectionMetadataResponseLinksItem,
    )
    from ..models.ogc_collection_metadata_response_summaries_type_0 import (
        OGCCollectionMetadataResponseSummariesType0,
    )


T = TypeVar("T", bound="OGCCollectionMetadataResponse")


@_attrs_define
class OGCCollectionMetadataResponse:
    """Response for /collections/datasets single collection metadata.

    Attributes:
        id (str):
        title (str):
        description (str):
        links (list[OGCCollectionMetadataResponseLinksItem]):
        item_type (str | Unset):  Default: 'record'.
        extent (None | OGCCollectionMetadataResponseExtentType0 | Unset):
        summaries (None | OGCCollectionMetadataResponseSummariesType0 | Unset):
    """

    id: str
    title: str
    description: str
    links: list[OGCCollectionMetadataResponseLinksItem]
    item_type: str | Unset = "record"
    extent: None | OGCCollectionMetadataResponseExtentType0 | Unset = UNSET
    summaries: None | OGCCollectionMetadataResponseSummariesType0 | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.ogc_collection_metadata_response_extent_type_0 import (
            OGCCollectionMetadataResponseExtentType0,
        )
        from ..models.ogc_collection_metadata_response_summaries_type_0 import (
            OGCCollectionMetadataResponseSummariesType0,
        )

        id = self.id

        title = self.title

        description = self.description

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        item_type = self.item_type

        extent: dict[str, Any] | None | Unset
        if isinstance(self.extent, Unset):
            extent = UNSET
        elif isinstance(self.extent, OGCCollectionMetadataResponseExtentType0):
            extent = self.extent.to_dict()
        else:
            extent = self.extent

        summaries: dict[str, Any] | None | Unset
        if isinstance(self.summaries, Unset):
            summaries = UNSET
        elif isinstance(self.summaries, OGCCollectionMetadataResponseSummariesType0):
            summaries = self.summaries.to_dict()
        else:
            summaries = self.summaries

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "title": title,
                "description": description,
                "links": links,
            }
        )
        if item_type is not UNSET:
            field_dict["itemType"] = item_type
        if extent is not UNSET:
            field_dict["extent"] = extent
        if summaries is not UNSET:
            field_dict["summaries"] = summaries

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ogc_collection_metadata_response_extent_type_0 import (
            OGCCollectionMetadataResponseExtentType0,
        )
        from ..models.ogc_collection_metadata_response_links_item import (
            OGCCollectionMetadataResponseLinksItem,
        )
        from ..models.ogc_collection_metadata_response_summaries_type_0 import (
            OGCCollectionMetadataResponseSummariesType0,
        )

        d = dict(src_dict)
        id = d.pop("id")

        title = d.pop("title")

        description = d.pop("description")

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = OGCCollectionMetadataResponseLinksItem.from_dict(
                links_item_data
            )

            links.append(links_item)

        item_type = d.pop("itemType", UNSET)

        def _parse_extent(
            data: object,
        ) -> None | OGCCollectionMetadataResponseExtentType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                extent_type_0 = OGCCollectionMetadataResponseExtentType0.from_dict(data)

                return extent_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OGCCollectionMetadataResponseExtentType0 | Unset, data)

        extent = _parse_extent(d.pop("extent", UNSET))

        def _parse_summaries(
            data: object,
        ) -> None | OGCCollectionMetadataResponseSummariesType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                summaries_type_0 = (
                    OGCCollectionMetadataResponseSummariesType0.from_dict(data)
                )

                return summaries_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None | OGCCollectionMetadataResponseSummariesType0 | Unset, data
            )

        summaries = _parse_summaries(d.pop("summaries", UNSET))

        ogc_collection_metadata_response = cls(
            id=id,
            title=title,
            description=description,
            links=links,
            item_type=item_type,
            extent=extent,
            summaries=summaries,
        )

        ogc_collection_metadata_response.additional_properties = d
        return ogc_collection_metadata_response

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
