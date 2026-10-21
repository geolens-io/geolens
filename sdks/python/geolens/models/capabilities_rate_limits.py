from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="CapabilitiesRateLimits")


@_attrs_define
class CapabilitiesRateLimits:
    """
    Attributes:
        global_per_second (int): Requests per second per client IP.
        login_per_minute (int): Login attempts per minute.
    """

    global_per_second: int
    login_per_minute: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        global_per_second = self.global_per_second

        login_per_minute = self.login_per_minute

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "global_per_second": global_per_second,
                "login_per_minute": login_per_minute,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        global_per_second = d.pop("global_per_second")

        login_per_minute = d.pop("login_per_minute")

        capabilities_rate_limits = cls(
            global_per_second=global_per_second,
            login_per_minute=login_per_minute,
        )

        capabilities_rate_limits.additional_properties = d
        return capabilities_rate_limits

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
