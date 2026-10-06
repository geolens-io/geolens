from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.stac_asset_size import StacAssetSize


T = TypeVar("T", bound="StacAssetSizesResponse")


@_attrs_define
class StacAssetSizesResponse:
    """
    Attributes:
        sizes (list[StacAssetSize]): One entry per requested asset.
    """

    sizes: list[StacAssetSize]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        sizes = []
        for sizes_item_data in self.sizes:
            sizes_item = sizes_item_data.to_dict()
            sizes.append(sizes_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "sizes": sizes,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.stac_asset_size import StacAssetSize

        d = dict(src_dict)
        sizes = []
        _sizes = d.pop("sizes")
        for sizes_item_data in _sizes:
            sizes_item = StacAssetSize.from_dict(sizes_item_data)

            sizes.append(sizes_item)

        stac_asset_sizes_response = cls(
            sizes=sizes,
        )

        stac_asset_sizes_response.additional_properties = d
        return stac_asset_sizes_response

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
