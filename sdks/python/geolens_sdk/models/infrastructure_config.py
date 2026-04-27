from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="InfrastructureConfig")


@_attrs_define
class InfrastructureConfig:
    """
    Attributes:
        cache_provider (str): Active cache backend ('memory' or 'redis').
        cdn_configured (bool): Whether a CDN base URL is configured for tile delivery.
        database_pooler (str): Active connection pooler mode ('sqlalchemy' or 'external').
        database_type (str): Database flavor (e.g. 'postgres', 'managed-postgres').
        storage_provider (str): Active storage backend ('local' or 's3').
        tile_cache (str): Tile caching backend in use.
        tile_cache_ttl (int): Tile cache TTL in seconds.
    """

    cache_provider: str
    cdn_configured: bool
    database_pooler: str
    database_type: str
    storage_provider: str
    tile_cache: str
    tile_cache_ttl: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        cache_provider = self.cache_provider

        cdn_configured = self.cdn_configured

        database_pooler = self.database_pooler

        database_type = self.database_type

        storage_provider = self.storage_provider

        tile_cache = self.tile_cache

        tile_cache_ttl = self.tile_cache_ttl

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "cache_provider": cache_provider,
                "cdn_configured": cdn_configured,
                "database_pooler": database_pooler,
                "database_type": database_type,
                "storage_provider": storage_provider,
                "tile_cache": tile_cache,
                "tile_cache_ttl": tile_cache_ttl,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        cache_provider = d.pop("cache_provider")

        cdn_configured = d.pop("cdn_configured")

        database_pooler = d.pop("database_pooler")

        database_type = d.pop("database_type")

        storage_provider = d.pop("storage_provider")

        tile_cache = d.pop("tile_cache")

        tile_cache_ttl = d.pop("tile_cache_ttl")

        infrastructure_config = cls(
            cache_provider=cache_provider,
            cdn_configured=cdn_configured,
            database_pooler=database_pooler,
            database_type=database_type,
            storage_provider=storage_provider,
            tile_cache=tile_cache,
            tile_cache_ttl=tile_cache_ttl,
        )

        infrastructure_config.additional_properties = d
        return infrastructure_config

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
