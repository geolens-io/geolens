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
    from ..models.inline_def_geo_json_feature_afaebacb_properties import (
        InlineDefGeoJSONFeatureAfaebacbProperties,
    )


T = TypeVar("T", bound="InlineDefGeoJSONFeatureAfaebacb")


@_attrs_define
class InlineDefGeoJSONFeatureAfaebacb:
    """A single GeoJSON Feature.

    Attributes:
        id (int):
        properties (InlineDefGeoJSONFeatureAfaebacbProperties):
        geometry (GeoJSONGeometry | None | Unset):
        type_ (Literal['Feature'] | Unset):  Default: 'Feature'.
    """

    id: int
    properties: InlineDefGeoJSONFeatureAfaebacbProperties
    geometry: GeoJSONGeometry | None | Unset = UNSET
    type_: Literal["Feature"] | Unset = "Feature"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.geo_json_geometry import GeoJSONGeometry

        id = self.id

        properties = self.properties.to_dict()

        geometry: dict[str, Any] | None | Unset
        if isinstance(self.geometry, Unset):
            geometry = UNSET
        elif isinstance(self.geometry, GeoJSONGeometry):
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
        from ..models.geo_json_geometry import GeoJSONGeometry
        from ..models.inline_def_geo_json_feature_afaebacb_properties import (
            InlineDefGeoJSONFeatureAfaebacbProperties,
        )

        d = dict(src_dict)
        id = d.pop("id")

        properties = InlineDefGeoJSONFeatureAfaebacbProperties.from_dict(
            d.pop("properties")
        )

        def _parse_geometry(data: object) -> GeoJSONGeometry | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                geometry_type_0 = GeoJSONGeometry.from_dict(data)

                return geometry_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(GeoJSONGeometry | None | Unset, data)

        geometry = _parse_geometry(d.pop("geometry", UNSET))

        type_ = cast(Literal["Feature"] | Unset, d.pop("type", UNSET))
        if type_ != "Feature" and not isinstance(type_, Unset):
            raise ValueError(f"type must match const 'Feature', got '{type_}'")

        inline_def_geo_json_feature_afaebacb = cls(
            id=id,
            properties=properties,
            geometry=geometry,
            type_=type_,
        )

        inline_def_geo_json_feature_afaebacb.additional_properties = d
        return inline_def_geo_json_feature_afaebacb

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
