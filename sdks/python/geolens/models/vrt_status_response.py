from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.vrt_status_response_status import check_vrt_status_response_status
from ..models.vrt_status_response_status import VrtStatusResponseStatus
from dateutil.parser import isoparse
from typing import cast
import datetime

if TYPE_CHECKING:
    from ..models.vrt_active_generation import VrtActiveGeneration
    from ..models.vrt_source_health import VrtSourceHealth


T = TypeVar("T", bound="VrtStatusResponse")


@_attrs_define
class VrtStatusResponse:
    """
    Attributes:
        source_count (int):
        source_health (list[VrtSourceHealth]):
        status (VrtStatusResponseStatus):
        active_generation (None | Unset | VrtActiveGeneration):
        last_generation_at (datetime.datetime | None | Unset):
    """

    source_count: int
    source_health: list[VrtSourceHealth]
    status: VrtStatusResponseStatus
    active_generation: None | Unset | VrtActiveGeneration = UNSET
    last_generation_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.vrt_active_generation import VrtActiveGeneration

        source_count = self.source_count

        source_health = []
        for source_health_item_data in self.source_health:
            source_health_item = source_health_item_data.to_dict()
            source_health.append(source_health_item)

        status: str = self.status

        active_generation: dict[str, Any] | None | Unset
        if isinstance(self.active_generation, Unset):
            active_generation = UNSET
        elif isinstance(self.active_generation, VrtActiveGeneration):
            active_generation = self.active_generation.to_dict()
        else:
            active_generation = self.active_generation

        last_generation_at: None | str | Unset
        if isinstance(self.last_generation_at, Unset):
            last_generation_at = UNSET
        elif isinstance(self.last_generation_at, datetime.datetime):
            last_generation_at = self.last_generation_at.isoformat()
        else:
            last_generation_at = self.last_generation_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "source_count": source_count,
                "source_health": source_health,
                "status": status,
            }
        )
        if active_generation is not UNSET:
            field_dict["active_generation"] = active_generation
        if last_generation_at is not UNSET:
            field_dict["last_generation_at"] = last_generation_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.vrt_active_generation import VrtActiveGeneration
        from ..models.vrt_source_health import VrtSourceHealth

        d = dict(src_dict)
        source_count = d.pop("source_count")

        source_health = []
        _source_health = d.pop("source_health")
        for source_health_item_data in _source_health:
            source_health_item = VrtSourceHealth.from_dict(source_health_item_data)

            source_health.append(source_health_item)

        status = check_vrt_status_response_status(d.pop("status"))

        def _parse_active_generation(
            data: object,
        ) -> None | Unset | VrtActiveGeneration:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                active_generation_type_0 = VrtActiveGeneration.from_dict(data)

                return active_generation_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | VrtActiveGeneration, data)

        active_generation = _parse_active_generation(d.pop("active_generation", UNSET))

        def _parse_last_generation_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_generation_at_type_0 = isoparse(data)

                return last_generation_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_generation_at = _parse_last_generation_at(
            d.pop("last_generation_at", UNSET)
        )

        vrt_status_response = cls(
            source_count=source_count,
            source_health=source_health,
            status=status,
            active_generation=active_generation,
            last_generation_at=last_generation_at,
        )

        vrt_status_response.additional_properties = d
        return vrt_status_response

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
