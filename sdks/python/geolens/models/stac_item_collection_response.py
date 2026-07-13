from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.stac_context import StacContext
    from ..models.stac_item_response import StacItemResponse
    from ..models.stac_link import StacLink


T = TypeVar("T", bound="StacItemCollectionResponse")


@_attrs_define
class StacItemCollectionResponse:
    """Typed OpenAPI representation of a STAC ItemCollection.

    Attributes:
        context (StacContext): Paging metadata emitted with STAC ItemCollections.
        features (list[StacItemResponse]):
        links (list[StacLink]):
        number_matched (int):
        number_returned (int):
        type_ (Literal['FeatureCollection'] | Unset):  Default: 'FeatureCollection'.
    """

    context: StacContext
    features: list[StacItemResponse]
    links: list[StacLink]
    number_matched: int
    number_returned: int
    type_: Literal["FeatureCollection"] | Unset = "FeatureCollection"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        context = self.context.to_dict()

        features = []
        for features_item_data in self.features:
            features_item = features_item_data.to_dict()
            features.append(features_item)

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        number_matched = self.number_matched

        number_returned = self.number_returned

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "context": context,
                "features": features,
                "links": links,
                "numberMatched": number_matched,
                "numberReturned": number_returned,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_context import StacContext
        from ..models.stac_item_response import StacItemResponse
        from ..models.stac_link import StacLink

        d = dict(src_dict)
        context = StacContext.from_dict(d.pop("context"))

        features = []
        _features = d.pop("features")
        for features_item_data in _features:
            features_item = StacItemResponse.from_dict(features_item_data)

            features.append(features_item)

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = StacLink.from_dict(links_item_data)

            links.append(links_item)

        number_matched = d.pop("numberMatched")

        number_returned = d.pop("numberReturned")

        type_ = cast(Literal["FeatureCollection"] | Unset, d.pop("type", UNSET))
        if type_ != "FeatureCollection" and not isinstance(type_, Unset):
            raise ValueError(
                f"type must match const 'FeatureCollection', got '{type_}'"
            )

        stac_item_collection_response = cls(
            context=context,
            features=features,
            links=links,
            number_matched=number_matched,
            number_returned=number_returned,
            type_=type_,
        )

        stac_item_collection_response.additional_properties = d
        return stac_item_collection_response

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
