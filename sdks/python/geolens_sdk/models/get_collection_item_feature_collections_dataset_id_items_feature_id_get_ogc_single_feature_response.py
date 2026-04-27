from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.geo_json_geometry import GeoJSONGeometry
    from ..models.get_collection_item_feature_collections_dataset_id_items_feature_id_get_ogc_single_feature_response_properties_type_0 import (
        GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponsePropertiesType0,
    )
    from ..models.ogc_link import OGCLink


T = TypeVar(
    "T",
    bound="GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse",
)


@_attrs_define
class GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponse:
    """Single GeoJSON Feature response.

    Attributes:
        geometry (GeoJSONGeometry | None): GeoJSON geometry of the feature, or null for geometry-less features.
        id (int): Feature identifier within the collection.
        properties (GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponsePropertiesType0
            | None): Feature attributes as a JSON object.
        links (list[OGCLink] | Unset): Self-reference and related-resource links.
        type_ (Literal['Feature'] | Unset): GeoJSON object type. Default: 'Feature'.
    """

    geometry: GeoJSONGeometry | None
    id: int
    properties: (
        GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponsePropertiesType0
        | None
    )
    links: list[OGCLink] | Unset = UNSET
    type_: Literal["Feature"] | Unset = "Feature"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.geo_json_geometry import GeoJSONGeometry
        from ..models.get_collection_item_feature_collections_dataset_id_items_feature_id_get_ogc_single_feature_response_properties_type_0 import (
            GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponsePropertiesType0,
        )

        geometry: dict[str, Any] | None
        if isinstance(self.geometry, GeoJSONGeometry):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry

        id = self.id

        properties: dict[str, Any] | None
        if isinstance(
            self.properties,
            GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponsePropertiesType0,
        ):
            properties = self.properties.to_dict()
        else:
            properties = self.properties

        links: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.links, Unset):
            links = []
            for links_item_data in self.links:
                links_item = links_item_data.to_dict()
                links.append(links_item)

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "geometry": geometry,
                "id": id,
                "properties": properties,
            }
        )
        if links is not UNSET:
            field_dict["links"] = links
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.geo_json_geometry import GeoJSONGeometry
        from ..models.get_collection_item_feature_collections_dataset_id_items_feature_id_get_ogc_single_feature_response_properties_type_0 import (
            GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponsePropertiesType0,
        )
        from ..models.ogc_link import OGCLink

        d = dict(src_dict)

        def _parse_geometry(data: object) -> GeoJSONGeometry | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_type_0 = GeoJSONGeometry.from_dict(data)

                return geometry_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GeoJSONGeometry | None, data)

        geometry = _parse_geometry(d.pop("geometry"))

        id = d.pop("id")

        def _parse_properties(
            data: object,
        ) -> (
            GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponsePropertiesType0
            | None
        ):
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                properties_type_0 = GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponsePropertiesType0.from_dict(
                    data
                )

                return properties_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                GetCollectionItemFeatureCollectionsDatasetIdItemsFeatureIdGetOGCSingleFeatureResponsePropertiesType0
                | None,
                data,
            )

        properties = _parse_properties(d.pop("properties"))

        _links = d.pop("links", UNSET)
        links: list[OGCLink] | Unset = UNSET
        if _links is not UNSET:
            links = []
            for links_item_data in _links:
                links_item = OGCLink.from_dict(links_item_data)

                links.append(links_item)

        type_ = cast(Literal["Feature"] | Unset, d.pop("type", UNSET))
        if type_ != "Feature" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'Feature', got '{type_}'")

        get_collection_item_feature_collections_dataset_id_items_feature_id_get_ogc_single_feature_response = cls(
            geometry=geometry,
            id=id,
            properties=properties,
            links=links,
            type_=type_,
        )

        get_collection_item_feature_collections_dataset_id_items_feature_id_get_ogc_single_feature_response.additional_properties = d
        return get_collection_item_feature_collections_dataset_id_items_feature_id_get_ogc_single_feature_response

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
