from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="StaleCleanupResponse")


@_attrs_define
class StaleCleanupResponse:
    """
    Attributes:
        pending_failed (int):
        running_failed (int):
        total_cleaned (int):
    """

    pending_failed: int
    running_failed: int
    total_cleaned: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        pending_failed = self.pending_failed

        running_failed = self.running_failed

        total_cleaned = self.total_cleaned

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "pending_failed": pending_failed,
                "running_failed": running_failed,
                "total_cleaned": total_cleaned,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        pending_failed = d.pop("pending_failed")

        running_failed = d.pop("running_failed")

        total_cleaned = d.pop("total_cleaned")

        stale_cleanup_response = cls(
            pending_failed=pending_failed,
            running_failed=running_failed,
            total_cleaned=total_cleaned,
        )

        stale_cleanup_response.additional_properties = d
        return stale_cleanup_response

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
