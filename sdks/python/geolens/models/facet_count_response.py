from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.collection_facet_item import CollectionFacetItem
    from ..models.facet_count_response_record_type import FacetCountResponseRecordType
    from ..models.facet_value_count import FacetValueCount


T = TypeVar("T", bound="FacetCountResponse")


@_attrs_define
class FacetCountResponse:
    """Multi-group facet counts for the search sidebar.

    Attributes:
        record_type (FacetCountResponseRecordType): Hit counts keyed by record type
        collections (list[CollectionFacetItem] | Unset): Collections containing matched records
        keywords (list[FacetValueCount] | Unset): Top keyword tags with counts
        source_organization (list[FacetValueCount] | Unset): Top organizations with counts
        srid (list[FacetValueCount] | Unset): Top SRIDs with counts
    """

    record_type: FacetCountResponseRecordType
    collections: list[CollectionFacetItem] | Unset = UNSET
    keywords: list[FacetValueCount] | Unset = UNSET
    source_organization: list[FacetValueCount] | Unset = UNSET
    srid: list[FacetValueCount] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        record_type = self.record_type.to_dict()

        collections: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.collections, Unset):
            collections = []
            for collections_item_data in self.collections:
                collections_item = collections_item_data.to_dict()
                collections.append(collections_item)

        keywords: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.keywords, Unset):
            keywords = []
            for keywords_item_data in self.keywords:
                keywords_item = keywords_item_data.to_dict()
                keywords.append(keywords_item)

        source_organization: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.source_organization, Unset):
            source_organization = []
            for source_organization_item_data in self.source_organization:
                source_organization_item = source_organization_item_data.to_dict()
                source_organization.append(source_organization_item)

        srid: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.srid, Unset):
            srid = []
            for srid_item_data in self.srid:
                srid_item = srid_item_data.to_dict()
                srid.append(srid_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "record_type": record_type,
            }
        )
        if collections is not UNSET:
            field_dict["collections"] = collections
        if keywords is not UNSET:
            field_dict["keywords"] = keywords
        if source_organization is not UNSET:
            field_dict["source_organization"] = source_organization
        if srid is not UNSET:
            field_dict["srid"] = srid

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.collection_facet_item import CollectionFacetItem
        from ..models.facet_count_response_record_type import (
            FacetCountResponseRecordType,
        )
        from ..models.facet_value_count import FacetValueCount

        d = dict(src_dict)
        record_type = FacetCountResponseRecordType.from_dict(d.pop("record_type"))

        _collections = d.pop("collections", UNSET)
        collections: list[CollectionFacetItem] | Unset = UNSET
        if _collections is not UNSET:
            collections = []
            for collections_item_data in _collections:
                collections_item = CollectionFacetItem.from_dict(collections_item_data)

                collections.append(collections_item)

        _keywords = d.pop("keywords", UNSET)
        keywords: list[FacetValueCount] | Unset = UNSET
        if _keywords is not UNSET:
            keywords = []
            for keywords_item_data in _keywords:
                keywords_item = FacetValueCount.from_dict(keywords_item_data)

                keywords.append(keywords_item)

        _source_organization = d.pop("source_organization", UNSET)
        source_organization: list[FacetValueCount] | Unset = UNSET
        if _source_organization is not UNSET:
            source_organization = []
            for source_organization_item_data in _source_organization:
                source_organization_item = FacetValueCount.from_dict(
                    source_organization_item_data
                )

                source_organization.append(source_organization_item)

        _srid = d.pop("srid", UNSET)
        srid: list[FacetValueCount] | Unset = UNSET
        if _srid is not UNSET:
            srid = []
            for srid_item_data in _srid:
                srid_item = FacetValueCount.from_dict(srid_item_data)

                srid.append(srid_item)

        facet_count_response = cls(
            record_type=record_type,
            collections=collections,
            keywords=keywords,
            source_organization=source_organization,
            srid=srid,
        )

        facet_count_response.additional_properties = d
        return facet_count_response

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
