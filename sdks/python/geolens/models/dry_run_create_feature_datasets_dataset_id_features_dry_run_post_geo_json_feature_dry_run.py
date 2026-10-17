from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run_geo_json_geometry import (
        DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometry,
    )
    from ..models.dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run_geo_json_geometry_collection import (
        DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryCollection,
    )
    from ..models.dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run_properties import (
        DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunProperties,
    )


T = TypeVar(
    "T",
    bound="DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRun",
)


@_attrs_define
class DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRun:
    """A feature as a create would store it, from a dry run that stored nothing.

    Attributes:
        properties (DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunProperties):
        type_ (Literal['Feature'] | Unset):  Default: 'Feature'.
        geometry (DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometry |
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryCollection | None |
            Unset):
    """

    properties: DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunProperties
    type_: Literal["Feature"] | Unset = "Feature"
    geometry: (
        DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometry
        | DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryCollection
        | None
        | Unset
    ) = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run_geo_json_geometry import (
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometry,
        )
        from ..models.dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run_geo_json_geometry_collection import (
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryCollection,
        )

        properties = self.properties.to_dict()

        type_ = self.type_

        geometry: dict[str, Any] | None | Unset
        if isinstance(self.geometry, Unset):
            geometry = UNSET
        elif isinstance(
            self.geometry,
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryCollection,
        ):
            geometry = self.geometry.to_dict()
        elif isinstance(
            self.geometry,
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometry,
        ):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "properties": properties,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_
        if geometry is not UNSET:
            field_dict["geometry"] = geometry

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run_geo_json_geometry import (
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometry,
        )
        from ..models.dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run_geo_json_geometry_collection import (
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryCollection,
        )
        from ..models.dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run_properties import (
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunProperties,
        )

        d = dict(src_dict)
        properties = DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunProperties.from_dict(
            d.pop("properties")
        )

        type_ = cast(Literal["Feature"] | Unset, d.pop("type", UNSET))
        if type_ != "Feature" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'Feature', got '{type_}'")

        def _parse_geometry(
            data: object,
        ) -> (
            DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometry
            | DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryCollection
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
                geometry_geo_json_geometry_collection = DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryCollection.from_dict(
                    data
                )

                return geometry_geo_json_geometry_collection
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_geo_json_geometry = DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometry.from_dict(
                    data
                )

                return geometry_geo_json_geometry
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometry
                | DryRunCreateFeatureDatasetsDatasetIdFeaturesDryRunPostGeoJSONFeatureDryRunGeoJSONGeometryCollection
                | None
                | Unset,
                data,
            )

        geometry = _parse_geometry(d.pop("geometry", UNSET))

        dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run = cls(
            properties=properties,
            type_=type_,
            geometry=geometry,
        )

        dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run.additional_properties = d
        return dry_run_create_feature_datasets_dataset_id_features_dry_run_post_geo_json_feature_dry_run

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
