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
    from ..models.geo_json_geometry_collection import GeoJSONGeometryCollection
    from ..models.stac_item_properties import StacItemProperties
    from ..models.stac_item_response_assets import StacItemResponseAssets
    from ..models.stac_link import StacLink


T = TypeVar("T", bound="StacItemResponse")


@_attrs_define
class StacItemResponse:
    """A GeoJSON Feature conforming to the STAC Item specification.

    Attributes:
        assets (StacItemResponseAssets):
        geometry (GeoJSONGeometry | GeoJSONGeometryCollection | None): Item footprint as GeoJSON, or null when
            unavailable.
        id (str): Stable item identifier.
        links (list[StacLink]):
        properties (StacItemProperties): Core STAC Item properties plus extension-defined fields.
        stac_version (str): STAC specification version.
        bbox (list[float] | None | Unset): Item bounding box with exactly four 2D or six 3D coordinates.
        collection (None | str | Unset): Identifier of the containing STAC Collection.
        stac_extensions (list[str] | Unset): STAC extension schema URIs in use.
        type_ (Literal['Feature'] | Unset):  Default: 'Feature'.
    """

    assets: StacItemResponseAssets
    geometry: GeoJSONGeometry | GeoJSONGeometryCollection | None
    id: str
    links: list[StacLink]
    properties: StacItemProperties
    stac_version: str
    bbox: list[float] | None | Unset = UNSET
    collection: None | str | Unset = UNSET
    stac_extensions: list[str] | Unset = UNSET
    type_: Literal["Feature"] | Unset = "Feature"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.geo_json_geometry import GeoJSONGeometry
        from ..models.geo_json_geometry_collection import GeoJSONGeometryCollection

        assets = self.assets.to_dict()

        geometry: dict[str, Any] | None
        if isinstance(self.geometry, GeoJSONGeometryCollection):
            geometry = self.geometry.to_dict()
        elif isinstance(self.geometry, GeoJSONGeometry):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry

        id = self.id

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        properties = self.properties.to_dict()

        stac_version = self.stac_version

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = []
            for bbox_type_0_item_data in self.bbox:
                bbox_type_0_item: float
                bbox_type_0_item = bbox_type_0_item_data
                bbox.append(bbox_type_0_item)

        else:
            bbox = self.bbox

        collection: None | str | Unset
        if isinstance(self.collection, Unset):
            collection = UNSET
        else:
            collection = self.collection

        stac_extensions: list[str] | Unset = UNSET
        if not isinstance(self.stac_extensions, Unset):
            stac_extensions = self.stac_extensions

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "assets": assets,
                "geometry": geometry,
                "id": id,
                "links": links,
                "properties": properties,
                "stac_version": stac_version,
            }
        )
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if collection is not UNSET:
            field_dict["collection"] = collection
        if stac_extensions is not UNSET:
            field_dict["stac_extensions"] = stac_extensions
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.geo_json_geometry import GeoJSONGeometry
        from ..models.geo_json_geometry_collection import GeoJSONGeometryCollection
        from ..models.stac_item_properties import StacItemProperties
        from ..models.stac_item_response_assets import StacItemResponseAssets
        from ..models.stac_link import StacLink

        d = dict(src_dict)
        assets = StacItemResponseAssets.from_dict(d.pop("assets"))

        def _parse_geometry(
            data: object,
        ) -> GeoJSONGeometry | GeoJSONGeometryCollection | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_type_0 = GeoJSONGeometryCollection.from_dict(data)

                return geometry_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_type_1 = GeoJSONGeometry.from_dict(data)

                return geometry_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GeoJSONGeometry | GeoJSONGeometryCollection | None, data)

        geometry = _parse_geometry(d.pop("geometry"))

        id = d.pop("id")

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = StacLink.from_dict(links_item_data)

            links.append(links_item)

        properties = StacItemProperties.from_dict(d.pop("properties"))

        stac_version = d.pop("stac_version")

        def _parse_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                bbox_type_0 = []
                _bbox_type_0 = data
                for bbox_type_0_item_data in _bbox_type_0:

                    def _parse_bbox_type_0_item(data: object) -> float:
                        return cast(float, data)

                    bbox_type_0_item = _parse_bbox_type_0_item(bbox_type_0_item_data)

                    bbox_type_0.append(bbox_type_0_item)

                return bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        bbox = _parse_bbox(d.pop("bbox", UNSET))

        def _parse_collection(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        collection = _parse_collection(d.pop("collection", UNSET))

        stac_extensions = cast(list[str], d.pop("stac_extensions", UNSET))

        type_ = cast(Literal["Feature"] | Unset, d.pop("type", UNSET))
        if type_ != "Feature" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'Feature', got '{type_}'")

        stac_item_response = cls(
            assets=assets,
            geometry=geometry,
            id=id,
            links=links,
            properties=properties,
            stac_version=stac_version,
            bbox=bbox,
            collection=collection,
            stac_extensions=stac_extensions,
            type_=type_,
        )

        stac_item_response.additional_properties = d
        return stac_item_response

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
