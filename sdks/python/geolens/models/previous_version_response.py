from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
import datetime


T = TypeVar("T", bound="PreviousVersionResponse")


@_attrs_define
class PreviousVersionResponse:
    """The data a replacement or restore replaced, kept until the next one.

    Attributes:
        version_number (int): The version whose data is kept
        retained_at (datetime.datetime | None | Unset):
        size_bytes (int | None | Unset): Its table's size; not counted toward quota
        feature_count (int | None | Unset): As recorded on that version
    """

    version_number: int
    retained_at: datetime.datetime | None | Unset = UNSET
    size_bytes: int | None | Unset = UNSET
    feature_count: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        version_number = self.version_number

        retained_at: None | str | Unset
        if isinstance(self.retained_at, Unset):
            retained_at = UNSET
        elif isinstance(self.retained_at, datetime.datetime):
            retained_at = self.retained_at.isoformat()
        else:
            retained_at = self.retained_at

        size_bytes: int | None | Unset
        if isinstance(self.size_bytes, Unset):
            size_bytes = UNSET
        else:
            size_bytes = self.size_bytes

        feature_count: int | None | Unset
        if isinstance(self.feature_count, Unset):
            feature_count = UNSET
        else:
            feature_count = self.feature_count

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "version_number": version_number,
            }
        )
        if retained_at is not UNSET:
            field_dict["retained_at"] = retained_at
        if size_bytes is not UNSET:
            field_dict["size_bytes"] = size_bytes
        if feature_count is not UNSET:
            field_dict["feature_count"] = feature_count

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        version_number = d.pop("version_number")

        def _parse_retained_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                retained_at_type_0 = isoparse(data)

                return retained_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        retained_at = _parse_retained_at(d.pop("retained_at", UNSET))

        def _parse_size_bytes(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        size_bytes = _parse_size_bytes(d.pop("size_bytes", UNSET))

        def _parse_feature_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count = _parse_feature_count(d.pop("feature_count", UNSET))

        previous_version_response = cls(
            version_number=version_number,
            retained_at=retained_at,
            size_bytes=size_bytes,
            feature_count=feature_count,
        )

        previous_version_response.additional_properties = d
        return previous_version_response

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
