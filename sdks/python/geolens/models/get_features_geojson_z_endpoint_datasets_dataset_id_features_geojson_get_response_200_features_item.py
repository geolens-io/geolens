from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_type import (
    check_get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_type,
)
from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_type import (
    GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemType,
)
from typing import cast

if TYPE_CHECKING:
    from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_geometry_type_0 import (
        GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemGeometryType0,
    )
    from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_properties import (
        GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemProperties,
    )


T = TypeVar(
    "T",
    bound="GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItem",
)


@_attrs_define
class GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItem:
    """
    Attributes:
        type_ (GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemType):
        id (int):
        geometry (GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemGeometryType0 |
            None):
        properties (GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemProperties):
    """

    type_: GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemType
    id: int
    geometry: (
        GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemGeometryType0
        | None
    )
    properties: GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemProperties
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_geometry_type_0 import (
            GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemGeometryType0,
        )

        type_: str = self.type_

        id = self.id

        geometry: dict[str, Any] | None
        if isinstance(
            self.geometry,
            GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemGeometryType0,
        ):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry

        properties = self.properties.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "type": type_,
                "id": id,
                "geometry": geometry,
                "properties": properties,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_geometry_type_0 import (
            GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemGeometryType0,
        )
        from ..models.get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_properties import (
            GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemProperties,
        )

        d = dict(src_dict)
        type_ = check_get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item_type(
            d.pop("type")
        )

        id = d.pop("id")

        def _parse_geometry(
            data: object,
        ) -> (
            GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemGeometryType0
            | None
        ):
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_type_0 = GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemGeometryType0.from_dict(
                    data
                )

                return geometry_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemGeometryType0
                | None,
                data,
            )

        geometry = _parse_geometry(d.pop("geometry"))

        properties = GetFeaturesGeojsonZEndpointDatasetsDatasetIdFeaturesGeojsonGetResponse200FeaturesItemProperties.from_dict(
            d.pop("properties")
        )

        get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item = cls(
            type_=type_,
            id=id,
            geometry=geometry,
            properties=properties,
        )

        get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item.additional_properties = d
        return get_features_geojson_z_endpoint_datasets_dataset_id_features_geojson_get_response_200_features_item

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
