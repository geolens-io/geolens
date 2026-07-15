from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry import (
        ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometry,
    )
    from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry_collection import (
        ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection,
    )
    from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_properties import (
        ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureProperties,
    )


T = TypeVar(
    "T",
    bound="ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeature",
)


@_attrs_define
class ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeature:
    """A single GeoJSON Feature.

    Attributes:
        id (int):
        properties (ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureProperties):
        geometry (ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometry |
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection | None |
            Unset):
        type_ (Literal['Feature'] | Unset):  Default: 'Feature'.
    """

    id: int
    properties: ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureProperties
    geometry: (
        ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometry
        | ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection
        | None
        | Unset
    ) = UNSET
    type_: Literal["Feature"] | Unset = "Feature"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry import (
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometry,
        )
        from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry_collection import (
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection,
        )

        id = self.id

        properties = self.properties.to_dict()

        geometry: dict[str, Any] | None | Unset
        if isinstance(self.geometry, Unset):
            geometry = UNSET
        elif isinstance(
            self.geometry,
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection,
        ):
            geometry = self.geometry.to_dict()
        elif isinstance(
            self.geometry,
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometry,
        ):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "properties": properties,
            }
        )
        if geometry is not UNSET:
            field_dict["geometry"] = geometry
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry import (
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometry,
        )
        from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_geo_json_geometry_collection import (
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection,
        )
        from ..models.list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature_properties import (
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureProperties,
        )

        d = dict(src_dict)
        id = d.pop("id")

        properties = ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureProperties.from_dict(
            d.pop("properties")
        )

        def _parse_geometry(
            data: object,
        ) -> (
            ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometry
            | ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection
            | None
            | Unset
        ):
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_geo_json_geometry_collection = ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection.from_dict(
                    data
                )

                return geometry_geo_json_geometry_collection
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_geo_json_geometry = ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometry.from_dict(
                    data
                )

                return geometry_geo_json_geometry
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometry
                | ListFeaturesDatasetsDatasetIdFeaturesGetGeoJSONFeatureCollectionGeoJSONFeatureGeoJSONGeometryCollection
                | None
                | Unset,
                data,
            )

        geometry = _parse_geometry(d.pop("geometry", UNSET))

        type_ = cast(Literal["Feature"] | Unset, d.pop("type", UNSET))
        if type_ != "Feature" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'Feature', got '{type_}'")

        list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature = cls(
            id=id,
            properties=properties,
            geometry=geometry,
            type_=type_,
        )

        list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature.additional_properties = d
        return list_features_datasets_dataset_id_features_get_geo_json_feature_collection_geo_json_feature

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
