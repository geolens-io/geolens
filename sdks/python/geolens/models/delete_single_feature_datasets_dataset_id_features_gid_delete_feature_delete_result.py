from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar(
    "T",
    bound="DeleteSingleFeatureDatasetsDatasetIdFeaturesGidDeleteFeatureDeleteResult",
)


@_attrs_define
class DeleteSingleFeatureDatasetsDatasetIdFeaturesGidDeleteFeatureDeleteResult:
    """Acknowledgement for a deleted feature.

    Attributes:
        tile_cache_version (int | None | Unset): The dataset's tile_cache_version after this write committed. Send it as
            the tile routes' `_v` query parameter when reloading tiles, so a request that reaches a different API worker is
            forced to re-read the dataset instead of serving that worker's own cached snapshot.
    """

    tile_cache_version: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tile_cache_version: int | None | Unset
        if isinstance(self.tile_cache_version, Unset):
            tile_cache_version = UNSET
        else:
            tile_cache_version = self.tile_cache_version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if tile_cache_version is not UNSET:
            field_dict["tile_cache_version"] = tile_cache_version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_tile_cache_version(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        tile_cache_version = _parse_tile_cache_version(
            d.pop("tile_cache_version", UNSET)
        )

        delete_single_feature_datasets_dataset_id_features_gid_delete_feature_delete_result = cls(
            tile_cache_version=tile_cache_version,
        )

        delete_single_feature_datasets_dataset_id_features_gid_delete_feature_delete_result.additional_properties = d
        return delete_single_feature_datasets_dataset_id_features_gid_delete_feature_delete_result

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
