from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="AIAvailabilityResponse")


@_attrs_define
class AIAvailabilityResponse:
    """Public-safe AI readiness signal (builder-audit P1-11).

    Carries a single boolean and intentionally exposes NO provider name, model,
    or key detail — it is readable by any non-admin editor holding
    ``use_ai_chat`` so the builder can enable/disable chat without the
    admin-only ``/admin/ai-status`` endpoint (which leaks provider/key info).

        Attributes:
            available (bool):
    """

    available: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        available = self.available

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "available": available,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        available = d.pop("available")

        ai_availability_response = cls(
            available=available,
        )

        ai_availability_response.additional_properties = d
        return ai_availability_response

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
