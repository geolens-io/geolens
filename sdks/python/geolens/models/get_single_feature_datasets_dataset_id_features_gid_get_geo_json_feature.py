from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_geo_json_geometry import (
        GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometry,
    )
    from ..models.get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_geo_json_geometry_collection import (
        GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollection,
    )
    from ..models.get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_properties import (
        GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureProperties,
    )


T = TypeVar("T", bound="GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature")


@_attrs_define
class GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeature:
    """A GeoJSON Feature, plus the id of the table it was read from.

    Attributes:
        id (int):
        properties (GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureProperties):
        type_ (Literal['Feature'] | Unset):  Default: 'Feature'.
        geometry (GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometry |
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollection | None | Unset):
        table_id (None | str | Unset): Opaque id of the data table this feature was read from or written to. A reupload
            or an overwrite of the dataset's data replaces the table, and the replacement can reuse feature ids. Send it
            back as the `table_id` query parameter of a PUT, PATCH or DELETE of this feature to have the write refused if
            the table was replaced since.
    """

    id: int
    properties: GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureProperties
    type_: Literal["Feature"] | Unset = "Feature"
    geometry: (
        GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometry
        | GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollection
        | None
        | Unset
    ) = UNSET
    table_id: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_geo_json_geometry import (
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometry,
        )
        from ..models.get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_geo_json_geometry_collection import (
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollection,
        )

        id = self.id

        properties = self.properties.to_dict()

        type_ = self.type_

        geometry: dict[str, Any] | None | Unset
        if isinstance(self.geometry, Unset):
            geometry = UNSET
        elif isinstance(
            self.geometry,
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollection,
        ):
            geometry = self.geometry.to_dict()
        elif isinstance(
            self.geometry,
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometry,
        ):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry

        table_id: None | str | Unset
        if isinstance(self.table_id, Unset):
            table_id = UNSET
        else:
            table_id = self.table_id

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
        if table_id is not UNSET:
            field_dict["table_id"] = table_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_geo_json_geometry import (
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometry,
        )
        from ..models.get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_geo_json_geometry_collection import (
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollection,
        )
        from ..models.get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature_properties import (
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureProperties,
        )

        d = dict(src_dict)
        id = d.pop("id")

        properties = GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureProperties.from_dict(
            d.pop("properties")
        )

        type_ = cast(Literal["Feature"] | Unset, d.pop("type", UNSET))
        if type_ != "Feature" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'Feature', got '{type_}'")

        def _parse_geometry(
            data: object,
        ) -> (
            GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometry
            | GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollection
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
                geometry_geo_json_geometry_collection = GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollection.from_dict(
                    data
                )

                return geometry_geo_json_geometry_collection
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_geo_json_geometry = GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometry.from_dict(
                    data
                )

                return geometry_geo_json_geometry
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometry
                | GetSingleFeatureDatasetsDatasetIdFeaturesGidGetGeoJSONFeatureGeoJSONGeometryCollection
                | None
                | Unset,
                data,
            )

        geometry = _parse_geometry(d.pop("geometry", UNSET))

        def _parse_table_id(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        table_id = _parse_table_id(d.pop("table_id", UNSET))

        get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature = cls(
            id=id,
            properties=properties,
            type_=type_,
            geometry=geometry,
            table_id=table_id,
        )

        get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature.additional_properties = d
        return get_single_feature_datasets_dataset_id_features_gid_get_geo_json_feature

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
