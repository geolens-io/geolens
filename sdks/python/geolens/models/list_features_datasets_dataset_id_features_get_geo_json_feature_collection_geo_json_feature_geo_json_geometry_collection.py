from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry_collection_geo_json_geometry import (
        ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry,
    )


T = TypeVar(
    "T",
    bound="ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection",
)


@_attrs_define
class ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection:
    """A GeoJSON GeometryCollection (RFC 7946 §3.1.8).

    fix(#430 codex r9): carries ``geometries`` instead of ``coordinates``, so
    it needs its own model — only generic-GEOMETRY datasets accept it on write
    (enforced in the service), and any stored collection must serialize back
    out on read.

    Deliberately NON-recursive (codex r13, refuted): PostGIS cannot round-trip
    nested collections through the GeoJSON boundary in either direction —
    ST_GeomFromGeoJSON rejects them on write and ST_AsGeoJSON raises
    'GeoJson: geometry not supported' on read — so a recursive model could
    never receive one and would only convert the write-side 422 into a raw
    database 500. The write schemas add a raw-payload guard for a clear 422.

        Attributes:
            geometries (list[ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCo
                llectionGeoJSONGeometry]):
            type_ (Literal['GeometryCollection']):
    """

    geometries: list[
        ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry
    ]
    type_: Literal["GeometryCollection"]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        geometries = []
        for geometries_item_data in self.geometries:
            geometries_item = geometries_item_data.to_dict()
            geometries.append(geometries_item)

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "geometries": geometries,
                "type": type_,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry_collection_geo_json_geometry import (
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry,
        )

        d = dict(src_dict)
        geometries = []
        _geometries = d.pop("geometries")
        for geometries_item_data in _geometries:
            geometries_item = ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollectionGeoJSONGeometry.from_dict(
                geometries_item_data
            )

            geometries.append(geometries_item)

        type_ = cast(Literal["GeometryCollection"], d.pop("type"))
        if type_ != "GeometryCollection":
            raise ValueError(
                f"type must match const 'GeometryCollection', got '{type_}'"
            )

        list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry_collection = cls(
            geometries=geometries,
            type_=type_,
        )

        list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry_collection.additional_properties = d
        return list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry_collection

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
