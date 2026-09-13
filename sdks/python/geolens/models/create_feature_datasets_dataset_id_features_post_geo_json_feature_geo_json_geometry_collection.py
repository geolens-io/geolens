from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry_collection_geo_json_geometry import (
        CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry,
    )


T = TypeVar(
    "T",
    bound="CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryCollection",
)


@_attrs_define
class CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryCollection:
    """A GeoJSON GeometryCollection (RFC 7946 §3.1.8).

    Geometry collections carry ``geometries`` instead of ``coordinates``.
    Only generic-geometry datasets accept them on write.

    Nested collections are rejected because PostGIS cannot round-trip them
    through the GeoJSON boundary.

        Attributes:
            type_ (Literal['GeometryCollection']):
            geometries
                (list[CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry]):
    """

    type_: Literal["GeometryCollection"]
    geometries: list[
        CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry
    ]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        type_ = self.type_

        geometries = []
        for geometries_item_data in self.geometries:
            geometries_item = geometries_item_data.to_dict()
            geometries.append(geometries_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "geometries": geometries,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry_collection_geo_json_geometry import (
            CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry,
        )

        d = dict(src_dict)
        type_ = cast(Literal["GeometryCollection"], d.pop("type"))
        if type_ != "GeometryCollection":
            raise ValueError(
                f"type must match const 'GeometryCollection', got '{type_}'"
            )

        geometries = []
        _geometries = d.pop("geometries")
        for geometries_item_data in _geometries:
            geometries_item = CreateFeatureDatasetsDatasetIdFeaturesPostGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry.from_dict(
                geometries_item_data
            )

            geometries.append(geometries_item)

        create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry_collection = cls(
            type_=type_,
            geometries=geometries,
        )

        create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry_collection.additional_properties = d
        return create_feature_datasets_dataset_id_features_post_geo_json_feature_geo_json_geometry_collection

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
