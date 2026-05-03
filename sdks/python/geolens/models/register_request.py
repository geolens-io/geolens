from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.register_request_visibility import check_register_request_visibility
from ..models.register_request_visibility import RegisterRequestVisibility
from typing import cast


T = TypeVar("T", bound="RegisterRequest")


@_attrs_define
class RegisterRequest:
    """
    Attributes:
        table_name (str): PostgreSQL table name in the `data` schema (max 63 chars per PostgreSQL identifier limit).
        title (str): Human-readable dataset title shown in the catalog.
        summary (None | str | Unset): Optional dataset description.
        visibility (RegisterRequestVisibility | Unset): Dataset visibility level. Default: 'private'.
    """

    table_name: str
    title: str
    summary: None | str | Unset = UNSET
    visibility: RegisterRequestVisibility | Unset = "private"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        table_name = self.table_name

        title = self.title

        summary: None | str | Unset
        if isinstance(self.summary, Unset):
            summary = UNSET
        else:
            summary = self.summary

        visibility: str | Unset = UNSET
        if not isinstance(self.visibility, Unset):
            visibility = self.visibility

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "table_name": table_name,
                "title": title,
            }
        )
        if summary is not UNSET:
            field_dict["summary"] = summary
        if visibility is not UNSET:
            field_dict["visibility"] = visibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        table_name = d.pop("table_name")

        title = d.pop("title")

        def _parse_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        summary = _parse_summary(d.pop("summary", UNSET))

        _visibility = d.pop("visibility", UNSET)
        visibility: RegisterRequestVisibility | Unset
        if isinstance(_visibility, Unset):
            visibility = UNSET
        else:
            visibility = check_register_request_visibility(_visibility)

        register_request = cls(
            table_name=table_name,
            title=title,
            summary=summary,
            visibility=visibility,
        )

        register_request.additional_properties = d
        return register_request

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
