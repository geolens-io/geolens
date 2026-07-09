from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.geo_json_geometry import GeoJSONGeometry


T = TypeVar("T", bound="GeoJSONGeometryCollection")


@_attrs_define
class GeoJSONGeometryCollection:
    """A GeoJSON GeometryCollection (RFC 7946 §3.1.8).

    fix(#430 codex r9): carries ``geometries`` instead of ``coordinates``, so
    it needs its own model — only generic-GEOMETRY datasets accept it on write
    (enforced in the service), and any stored collection must serialize back
    out on read.

        Attributes:
            geometries (list[GeoJSONGeometry]):
            type_ (Literal['GeometryCollection']):
    """

    geometries: list[GeoJSONGeometry]
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
        from ..models.geo_json_geometry import GeoJSONGeometry

        d = dict(src_dict)
        geometries = []
        _geometries = d.pop("geometries")
        for geometries_item_data in _geometries:
            geometries_item = GeoJSONGeometry.from_dict(geometries_item_data)

            geometries.append(geometries_item)

        type_ = cast(Literal["GeometryCollection"], d.pop("type"))
        if type_ != "GeometryCollection":
            raise ValueError(
                f"type must match const 'GeometryCollection', got '{type_}'"
            )

        geo_json_geometry_collection = cls(
            geometries=geometries,
            type_=type_,
        )

        geo_json_geometry_collection.additional_properties = d
        return geo_json_geometry_collection

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
