from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="TerrainConfig")


@_attrs_define
class TerrainConfig:
    """
    Attributes:
        enabled (bool | Unset):  Default: False.
        exaggeration (float | Unset):  Default: 1.0.
        source_dataset_id (None | Unset | UUID):
    """

    enabled: bool | Unset = False
    exaggeration: float | Unset = 1.0
    source_dataset_id: None | Unset | UUID = UNSET

    def to_dict(self) -> dict[str, Any]:
        enabled = self.enabled

        exaggeration = self.exaggeration

        source_dataset_id: None | str | Unset
        if isinstance(self.source_dataset_id, Unset):
            source_dataset_id = UNSET
        elif isinstance(self.source_dataset_id, UUID):
            source_dataset_id = str(self.source_dataset_id)
        else:
            source_dataset_id = self.source_dataset_id

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if enabled is not UNSET:
            field_dict["enabled"] = enabled
        if exaggeration is not UNSET:
            field_dict["exaggeration"] = exaggeration
        if source_dataset_id is not UNSET:
            field_dict["source_dataset_id"] = source_dataset_id

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        enabled = d.pop("enabled", UNSET)

        exaggeration = d.pop("exaggeration", UNSET)

        def _parse_source_dataset_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                source_dataset_id_type_0 = UUID(data)

                return source_dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        source_dataset_id = _parse_source_dataset_id(d.pop("source_dataset_id", UNSET))

        terrain_config = cls(
            enabled=enabled,
            exaggeration=exaggeration,
            source_dataset_id=source_dataset_id,
        )

        return terrain_config
