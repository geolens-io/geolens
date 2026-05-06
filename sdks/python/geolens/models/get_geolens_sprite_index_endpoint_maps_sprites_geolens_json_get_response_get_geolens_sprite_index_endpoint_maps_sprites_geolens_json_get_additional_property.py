from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar(
    "T",
    bound="GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetAdditionalProperty",
)


@_attrs_define
class GetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetResponseGetGeolensSpriteIndexEndpointMapsSpritesGeolensJsonGetAdditionalProperty:
    """ """

    additional_properties: dict[str, float | int] = _attrs_field(
        init=False, factory=dict
    )

    def to_dict(self) -> dict[str, Any]:

        field_dict: dict[str, Any] = {}
        for prop_name, prop in self.additional_properties.items():
            field_dict[prop_name] = prop

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        get_geolens_sprite_index_endpoint_maps_sprites_geolens_json_get_response_get_geolens_sprite_index_endpoint_maps_sprites_geolens_json_get_additional_property = cls()

        additional_properties = {}
        for prop_name, prop_dict in d.items():

            def _parse_additional_property(data: object) -> float | int:
                return cast(float | int, data)

            additional_property = _parse_additional_property(prop_dict)

            additional_properties[prop_name] = additional_property

        get_geolens_sprite_index_endpoint_maps_sprites_geolens_json_get_response_get_geolens_sprite_index_endpoint_maps_sprites_geolens_json_get_additional_property.additional_properties = additional_properties
        return get_geolens_sprite_index_endpoint_maps_sprites_geolens_json_get_response_get_geolens_sprite_index_endpoint_maps_sprites_geolens_json_get_additional_property

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> float | int:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: float | int) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
