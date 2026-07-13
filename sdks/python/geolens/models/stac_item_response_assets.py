from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.stac_item_asset import StacItemAsset


T = TypeVar("T", bound="StacItemResponseAssets")


@_attrs_define
class StacItemResponseAssets:
    """ """

    additional_properties: dict[str, StacItemAsset] = _attrs_field(
        init=False, factory=dict
    )

    def to_dict(self) -> dict[str, Any]:

        field_dict: dict[str, Any] = {}
        for prop_name, prop in self.additional_properties.items():
            field_dict[prop_name] = prop.to_dict()

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_item_asset import StacItemAsset

        d = dict(src_dict)
        stac_item_response_assets = cls()

        additional_properties = {}
        for prop_name, prop_dict in d.items():
            additional_property = StacItemAsset.from_dict(prop_dict)

            additional_properties[prop_name] = additional_property

        stac_item_response_assets.additional_properties = additional_properties
        return stac_item_response_assets

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> StacItemAsset:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: StacItemAsset) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
