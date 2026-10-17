from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.feature_create import FeatureCreate


T = TypeVar("T", bound="FeatureCollectionCreate")


@_attrs_define
class FeatureCollectionCreate:
    """A GeoJSON FeatureCollection whose features are inserted together.

    Attributes:
        type_ (Literal['FeatureCollection']):
        features (list[FeatureCreate]): Features to insert in one transaction, at most 1000. If any is refused, none is
            inserted.
    """

    type_: Literal["FeatureCollection"]
    features: list[FeatureCreate]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        features = []
        for features_item_data in self.features:
            features_item = features_item_data.to_dict()
            features.append(features_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "features": features,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.feature_create import FeatureCreate

        d = dict(src_dict)
        type_ = cast(Literal["FeatureCollection"], d.pop("type"))
        if type_ != "FeatureCollection":
            raise ValueError(
                f"type must match const 'FeatureCollection', got '{type_}'"
            )

        features = []
        _features = d.pop("features")
        for features_item_data in _features:
            features_item = FeatureCreate.from_dict(features_item_data)

            features.append(features_item)

        feature_collection_create = cls(
            type_=type_,
            features=features,
        )

        feature_collection_create.additional_properties = d
        return feature_collection_create

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
