from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar("T", bound="VisibilityCheckResponse")


@_attrs_define
class VisibilityCheckResponse:
    """
    Attributes:
        has_non_public (bool): True if any layer references a non-public dataset
        non_public_datasets (list[str]): Titles of datasets not publicly visible
    """

    has_non_public: bool
    non_public_datasets: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        has_non_public = self.has_non_public

        non_public_datasets = self.non_public_datasets

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "has_non_public": has_non_public,
                "non_public_datasets": non_public_datasets,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        has_non_public = d.pop("has_non_public")

        non_public_datasets = cast(list[str], d.pop("non_public_datasets"))

        visibility_check_response = cls(
            has_non_public=has_non_public,
            non_public_datasets=non_public_datasets,
        )

        visibility_check_response.additional_properties = d
        return visibility_check_response

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
