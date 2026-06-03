from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from dateutil.parser import isoparse
from uuid import UUID
import datetime


T = TypeVar("T", bound="VrtActiveGeneration")


@_attrs_define
class VrtActiveGeneration:
    """
    Attributes:
        elapsed_seconds (float):
        generation_id (UUID):
        started_at (datetime.datetime):
    """

    elapsed_seconds: float
    generation_id: UUID
    started_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        elapsed_seconds = self.elapsed_seconds

        generation_id = str(self.generation_id)

        started_at = self.started_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "elapsed_seconds": elapsed_seconds,
                "generation_id": generation_id,
                "started_at": started_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        elapsed_seconds = d.pop("elapsed_seconds")

        generation_id = UUID(d.pop("generation_id"))

        started_at = isoparse(d.pop("started_at"))

        vrt_active_generation = cls(
            elapsed_seconds=elapsed_seconds,
            generation_id=generation_id,
            started_at=started_at,
        )

        vrt_active_generation.additional_properties = d
        return vrt_active_generation

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
