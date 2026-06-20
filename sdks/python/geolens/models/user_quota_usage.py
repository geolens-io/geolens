from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="UserQuotaUsage")


@_attrs_define
class UserQuotaUsage:
    """Per-user quota usage: current consumption vs configured caps.

    Attributes:
        bytes_used (int):
        count_cap (int):
        dataset_count (int):
        storage_cap (int):
    """

    bytes_used: int
    count_cap: int
    dataset_count: int
    storage_cap: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        bytes_used = self.bytes_used

        count_cap = self.count_cap

        dataset_count = self.dataset_count

        storage_cap = self.storage_cap

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "bytes_used": bytes_used,
                "count_cap": count_cap,
                "dataset_count": dataset_count,
                "storage_cap": storage_cap,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        bytes_used = d.pop("bytes_used")

        count_cap = d.pop("count_cap")

        dataset_count = d.pop("dataset_count")

        storage_cap = d.pop("storage_cap")

        user_quota_usage = cls(
            bytes_used=bytes_used,
            count_cap=count_cap,
            dataset_count=dataset_count,
            storage_cap=storage_cap,
        )

        user_quota_usage.additional_properties = d
        return user_quota_usage

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
