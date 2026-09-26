from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write_geo_json_geometry import (
        PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometry,
    )
    from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write_geo_json_geometry_collection import (
        PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometryCollection,
    )
    from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write_properties import (
        PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteProperties,
    )


T = TypeVar(
    "T", bound="PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWrite"
)


@_attrs_define
class PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWrite:
    """A written GeoJSON Feature, plus the dataset's committed tile version.

    Attributes:
        id (int):
        properties (PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteProperties):
        type_ (Literal['Feature'] | Unset):  Default: 'Feature'.
        geometry (None | PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometry |
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometryCollection | Unset):
        tile_cache_version (int | None | Unset): The dataset's tile_cache_version after this write committed. Send it as
            the tile routes' `_v` query parameter when reloading tiles, so a request that reaches a different API worker is
            forced to re-read the dataset instead of serving that worker's own cached snapshot.
    """

    id: int
    properties: (
        PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteProperties
    )
    type_: Literal["Feature"] | Unset = "Feature"
    geometry: (
        None
        | PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometry
        | PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometryCollection
        | Unset
    ) = UNSET
    tile_cache_version: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write_geo_json_geometry import (
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometry,
        )
        from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write_geo_json_geometry_collection import (
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometryCollection,
        )

        id = self.id

        properties = self.properties.to_dict()

        type_ = self.type_

        geometry: dict[str, Any] | None | Unset
        if isinstance(self.geometry, Unset):
            geometry = UNSET
        elif isinstance(
            self.geometry,
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometryCollection,
        ):
            geometry = self.geometry.to_dict()
        elif isinstance(
            self.geometry,
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometry,
        ):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry

        tile_cache_version: int | None | Unset
        if isinstance(self.tile_cache_version, Unset):
            tile_cache_version = UNSET
        else:
            tile_cache_version = self.tile_cache_version

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "properties": properties,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_
        if geometry is not UNSET:
            field_dict["geometry"] = geometry
        if tile_cache_version is not UNSET:
            field_dict["tile_cache_version"] = tile_cache_version

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write_geo_json_geometry import (
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometry,
        )
        from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write_geo_json_geometry_collection import (
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometryCollection,
        )
        from ..models.patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write_properties import (
            PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteProperties,
        )

        d = dict(src_dict)
        id = d.pop("id")

        properties = PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteProperties.from_dict(
            d.pop("properties")
        )

        type_ = cast(Literal["Feature"] | Unset, d.pop("type", UNSET))
        if type_ != "Feature" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'Feature', got '{type_}'")

        def _parse_geometry(
            data: object,
        ) -> (
            None
            | PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometry
            | PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometryCollection
            | Unset
        ):
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_geo_json_geometry_collection = PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometryCollection.from_dict(
                    data
                )

                return geometry_geo_json_geometry_collection
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_geo_json_geometry = PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometry.from_dict(
                    data
                )

                return geometry_geo_json_geometry
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None
                | PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometry
                | PatchSingleFeatureDatasetsDatasetIdFeaturesGidPatchGeoJSONFeatureWriteGeoJSONGeometryCollection
                | Unset,
                data,
            )

        geometry = _parse_geometry(d.pop("geometry", UNSET))

        def _parse_tile_cache_version(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        tile_cache_version = _parse_tile_cache_version(
            d.pop("tile_cache_version", UNSET)
        )

        patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write = cls(
            id=id,
            properties=properties,
            type_=type_,
            geometry=geometry,
            tile_cache_version=tile_cache_version,
        )

        patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write.additional_properties = d
        return patch_single_feature_datasets_dataset_id_features_gid_patch_geo_json_feature_write

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
