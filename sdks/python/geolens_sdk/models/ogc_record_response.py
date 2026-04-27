from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.ogc_record_link import OGCRecordLink
    from ..models.ogc_record_properties import OGCRecordProperties
    from ..models.ogc_record_response_assets_type_0 import OGCRecordResponseAssetsType0
    from ..models.ogc_record_response_geometry_type_0 import (
        OGCRecordResponseGeometryType0,
    )
    from ..models.ogc_record_response_time_type_0 import OGCRecordResponseTimeType0


T = TypeVar("T", bound="OGCRecordResponse")


@_attrs_define
class OGCRecordResponse:
    """Single OGC API Records Feature.

    Attributes:
        id (str):
        links (list[OGCRecordLink]):
        properties (OGCRecordProperties): Properties block of an OGC API Records Feature.
        assets (None | OGCRecordResponseAssetsType0 | Unset):
        bbox (list[float] | None | Unset):
        conforms_to (list[str] | None | Unset):
        geometry (None | OGCRecordResponseGeometryType0 | Unset):
        time (None | OGCRecordResponseTimeType0 | Unset):
        type_ (str | Unset):  Default: 'Feature'.
    """

    id: str
    links: list[OGCRecordLink]
    properties: OGCRecordProperties
    assets: None | OGCRecordResponseAssetsType0 | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET
    conforms_to: list[str] | None | Unset = UNSET
    geometry: None | OGCRecordResponseGeometryType0 | Unset = UNSET
    time: None | OGCRecordResponseTimeType0 | Unset = UNSET
    type_: str | Unset = "Feature"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.ogc_record_response_assets_type_0 import (
            OGCRecordResponseAssetsType0,
        )
        from ..models.ogc_record_response_geometry_type_0 import (
            OGCRecordResponseGeometryType0,
        )
        from ..models.ogc_record_response_time_type_0 import OGCRecordResponseTimeType0

        id = self.id

        links = []
        for links_item_data in self.links:
            links_item = links_item_data.to_dict()
            links.append(links_item)

        properties = self.properties.to_dict()

        assets: dict[str, Any] | None | Unset
        if isinstance(self.assets, Unset):
            assets = UNSET
        elif isinstance(self.assets, OGCRecordResponseAssetsType0):
            assets = self.assets.to_dict()
        else:
            assets = self.assets

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        conforms_to: list[str] | None | Unset
        if isinstance(self.conforms_to, Unset):
            conforms_to = UNSET
        elif isinstance(self.conforms_to, list):
            conforms_to = self.conforms_to

        else:
            conforms_to = self.conforms_to

        geometry: dict[str, Any] | None | Unset
        if isinstance(self.geometry, Unset):
            geometry = UNSET
        elif isinstance(self.geometry, OGCRecordResponseGeometryType0):
            geometry = self.geometry.to_dict()
        else:
            geometry = self.geometry

        time: dict[str, Any] | None | Unset
        if isinstance(self.time, Unset):
            time = UNSET
        elif isinstance(self.time, OGCRecordResponseTimeType0):
            time = self.time.to_dict()
        else:
            time = self.time

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "links": links,
                "properties": properties,
            }
        )
        if assets is not UNSET:
            field_dict["assets"] = assets
        if bbox is not UNSET:
            field_dict["bbox"] = bbox
        if conforms_to is not UNSET:
            field_dict["conformsTo"] = conforms_to
        if geometry is not UNSET:
            field_dict["geometry"] = geometry
        if time is not UNSET:
            field_dict["time"] = time
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ogc_record_link import OGCRecordLink
        from ..models.ogc_record_properties import OGCRecordProperties
        from ..models.ogc_record_response_assets_type_0 import (
            OGCRecordResponseAssetsType0,
        )
        from ..models.ogc_record_response_geometry_type_0 import (
            OGCRecordResponseGeometryType0,
        )
        from ..models.ogc_record_response_time_type_0 import OGCRecordResponseTimeType0

        d = dict(src_dict)
        id = d.pop("id")

        links = []
        _links = d.pop("links")
        for links_item_data in _links:
            links_item = OGCRecordLink.from_dict(links_item_data)

            links.append(links_item)

        properties = OGCRecordProperties.from_dict(d.pop("properties"))

        def _parse_assets(data: object) -> None | OGCRecordResponseAssetsType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                assets_type_0 = OGCRecordResponseAssetsType0.from_dict(data)

                return assets_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OGCRecordResponseAssetsType0 | Unset, data)

        assets = _parse_assets(d.pop("assets", UNSET))

        def _parse_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                bbox_type_0 = cast(list[float], data)

                return bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        bbox = _parse_bbox(d.pop("bbox", UNSET))

        def _parse_conforms_to(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                conforms_to_type_0 = cast(list[str], data)

                return conforms_to_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        conforms_to = _parse_conforms_to(d.pop("conformsTo", UNSET))

        def _parse_geometry(
            data: object,
        ) -> None | OGCRecordResponseGeometryType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_type_0 = OGCRecordResponseGeometryType0.from_dict(data)

                return geometry_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OGCRecordResponseGeometryType0 | Unset, data)

        geometry = _parse_geometry(d.pop("geometry", UNSET))

        def _parse_time(data: object) -> None | OGCRecordResponseTimeType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                time_type_0 = OGCRecordResponseTimeType0.from_dict(data)

                return time_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OGCRecordResponseTimeType0 | Unset, data)

        time = _parse_time(d.pop("time", UNSET))

        type_ = d.pop("type", UNSET)

        ogc_record_response = cls(
            id=id,
            links=links,
            properties=properties,
            assets=assets,
            bbox=bbox,
            conforms_to=conforms_to,
            geometry=geometry,
            time=time,
            type_=type_,
        )

        ogc_record_response.additional_properties = d
        return ogc_record_response

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
