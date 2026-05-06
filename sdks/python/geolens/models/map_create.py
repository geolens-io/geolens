from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.terrain_config import TerrainConfig


T = TypeVar("T", bound="MapCreate")


@_attrs_define
class MapCreate:
    """
    Attributes:
        name (str): Map display name Example: NYC Infrastructure.
        description (None | str | Unset): Short description for sharing Example: Buildings, parks, and transit routes in
            Manhattan.
        notes (None | str | Unset): Private notes (not shown publicly)
        terrain_config (None | TerrainConfig | Unset): Map-level terrain source and exaggeration preferences
    """

    name: str
    description: None | str | Unset = UNSET
    notes: None | str | Unset = UNSET
    terrain_config: None | TerrainConfig | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.terrain_config import TerrainConfig

        name = self.name

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        notes: None | str | Unset
        if isinstance(self.notes, Unset):
            notes = UNSET
        else:
            notes = self.notes

        terrain_config: dict[str, Any] | None | Unset
        if isinstance(self.terrain_config, Unset):
            terrain_config = UNSET
        elif isinstance(self.terrain_config, TerrainConfig):
            terrain_config = self.terrain_config.to_dict()
        else:
            terrain_config = self.terrain_config

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if notes is not UNSET:
            field_dict["notes"] = notes
        if terrain_config is not UNSET:
            field_dict["terrain_config"] = terrain_config

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.terrain_config import TerrainConfig

        d = dict(src_dict)
        name = d.pop("name")

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_notes(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        notes = _parse_notes(d.pop("notes", UNSET))

        def _parse_terrain_config(data: object) -> None | TerrainConfig | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                terrain_config_type_0 = TerrainConfig.from_dict(data)

                return terrain_config_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | TerrainConfig | Unset, data)

        terrain_config = _parse_terrain_config(d.pop("terrain_config", UNSET))

        map_create = cls(
            name=name,
            description=description,
            notes=notes,
            terrain_config=terrain_config,
        )

        map_create.additional_properties = d
        return map_create

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
