from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.ogc_record_link import OGCRecordLink
    from ..models.ogc_record_response import OGCRecordResponse


T = TypeVar("T", bound="OGCFeatureCollectionResponse")


@_attrs_define
class OGCFeatureCollectionResponse:
    """OGC API Records FeatureCollection with match counts.

    Attributes:
        features (list[OGCRecordResponse]):
        number_matched (int): Total records matching the query
        number_returned (int): Number of records in this response page
        links (list[OGCRecordLink] | None | Unset): Pagination and self links
        time_stamp (None | str | Unset):
        type_ (str | Unset):  Default: 'FeatureCollection'.
    """

    features: list[OGCRecordResponse]
    number_matched: int
    number_returned: int
    links: list[OGCRecordLink] | None | Unset = UNSET
    time_stamp: None | str | Unset = UNSET
    type_: str | Unset = "FeatureCollection"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        features = []
        for features_item_data in self.features:
            features_item = features_item_data.to_dict()
            features.append(features_item)

        number_matched = self.number_matched

        number_returned = self.number_returned

        links: list[dict[str, Any]] | None | Unset
        if isinstance(self.links, Unset):
            links = UNSET
        elif isinstance(self.links, list):
            links = []
            for links_type_0_item_data in self.links:
                links_type_0_item = links_type_0_item_data.to_dict()
                links.append(links_type_0_item)

        else:
            links = self.links

        time_stamp: None | str | Unset
        if isinstance(self.time_stamp, Unset):
            time_stamp = UNSET
        else:
            time_stamp = self.time_stamp

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "features": features,
                "numberMatched": number_matched,
                "numberReturned": number_returned,
            }
        )
        if links is not UNSET:
            field_dict["links"] = links
        if time_stamp is not UNSET:
            field_dict["timeStamp"] = time_stamp
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ogc_record_link import OGCRecordLink
        from ..models.ogc_record_response import OGCRecordResponse

        d = dict(src_dict)
        features = []
        _features = d.pop("features")
        for features_item_data in _features:
            features_item = OGCRecordResponse.from_dict(features_item_data)

            features.append(features_item)

        number_matched = d.pop("numberMatched")

        number_returned = d.pop("numberReturned")

        def _parse_links(data: object) -> list[OGCRecordLink] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                links_type_0 = []
                _links_type_0 = data
                for links_type_0_item_data in _links_type_0:
                    links_type_0_item = OGCRecordLink.from_dict(links_type_0_item_data)

                    links_type_0.append(links_type_0_item)

                return links_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[OGCRecordLink] | None | Unset, data)

        links = _parse_links(d.pop("links", UNSET))

        def _parse_time_stamp(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        time_stamp = _parse_time_stamp(d.pop("timeStamp", UNSET))

        type_ = d.pop("type", UNSET)

        ogc_feature_collection_response = cls(
            features=features,
            number_matched=number_matched,
            number_returned=number_returned,
            links=links,
            time_stamp=time_stamp,
            type_=type_,
        )

        ogc_feature_collection_response.additional_properties = d
        return ogc_feature_collection_response

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
