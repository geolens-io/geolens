from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get_response_get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get_additional_property import (
        GetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetResponseGetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetAdditionalProperty,
    )


T = TypeVar(
    "T",
    bound="GetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetResponseGetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGet",
)


@_attrs_define
class GetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetResponseGetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGet:
    """ """

    additional_properties: dict[
        str,
        GetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetResponseGetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetAdditionalProperty,
    ] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:

        field_dict: dict[str, Any] = {}
        for prop_name, prop in self.additional_properties.items():
            field_dict[prop_name] = prop.to_dict()

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get_response_get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get_additional_property import (
            GetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetResponseGetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetAdditionalProperty,
        )

        d = dict(src_dict)
        get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get_response_get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get = cls()

        additional_properties = {}
        for prop_name, prop_dict in d.items():
            additional_property = GetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetResponseGetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetAdditionalProperty.from_dict(
                prop_dict
            )

            additional_properties[prop_name] = additional_property

        get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get_response_get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get.additional_properties = additional_properties
        return get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get_response_get_prefixed_sprite_index_endpoint_maps_sprites_geolens_prefixed_json_get

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(
        self, key: str
    ) -> GetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetResponseGetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetAdditionalProperty:
        return self.additional_properties[key]

    def __setitem__(
        self,
        key: str,
        value: GetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetResponseGetPrefixedSpriteIndexEndpointMapsSpritesGeolensPrefixedJsonGetAdditionalProperty,
    ) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
