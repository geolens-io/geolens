from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


T = TypeVar("T", bound="ProblemDetail")


@_attrs_define
class ProblemDetail:
    """
    Attributes:
        detail (str):
        status (int):
        title (str):
        type_ (str | Unset):  Default: 'about:blank'.
    """

    detail: str
    status: int
    title: str
    type_: str | Unset = "about:blank"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        detail = self.detail

        status = self.status

        title = self.title

        type_ = self.type_

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "detail": detail,
                "status": status,
                "title": title,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        detail = d.pop("detail")

        status = d.pop("status")

        title = d.pop("title")

        type_ = d.pop("type", UNSET)

        problem_detail = cls(
            detail=detail,
            status=status,
            title=title,
            type_=type_,
        )

        problem_detail.additional_properties = d
        return problem_detail

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
