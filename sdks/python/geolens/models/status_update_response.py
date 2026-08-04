from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="StatusUpdateResponse")


@_attrs_define
class StatusUpdateResponse:
    """
    Attributes:
        id (str):
        record_status (str):
        metadata_warnings (list[str] | None | Unset): Advisory warnings from the status change — the same inherited-
            keyword disclosure check the metadata PATCH runs (feat #1070, fix #1178 review). The transition has already
            applied.
    """

    id: str
    record_status: str
    metadata_warnings: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        record_status = self.record_status

        metadata_warnings: list[str] | None | Unset
        if isinstance(self.metadata_warnings, Unset):
            metadata_warnings = UNSET
        elif isinstance(self.metadata_warnings, list):
            metadata_warnings = self.metadata_warnings

        else:
            metadata_warnings = self.metadata_warnings

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "record_status": record_status,
            }
        )
        if metadata_warnings is not UNSET:
            field_dict["metadata_warnings"] = metadata_warnings

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        record_status = d.pop("record_status")

        def _parse_metadata_warnings(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                metadata_warnings_type_0 = cast(list[str], data)

                return metadata_warnings_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        metadata_warnings = _parse_metadata_warnings(d.pop("metadata_warnings", UNSET))

        status_update_response = cls(
            id=id,
            record_status=record_status,
            metadata_warnings=metadata_warnings,
        )

        status_update_response.additional_properties = d
        return status_update_response

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
