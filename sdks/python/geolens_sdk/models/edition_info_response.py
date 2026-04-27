from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast


T = TypeVar("T", bound="EditionInfoResponse")


@_attrs_define
class EditionInfoResponse:
    """Response for GET /settings/edition/.

    Attributes:
        edition (str): Active edition: 'community' or 'enterprise'.
        features (list[str]): List of feature flags enabled for this edition.
    """

    edition: str
    features: list[str]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        edition = self.edition

        features = self.features

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "edition": edition,
                "features": features,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        edition = d.pop("edition")

        features = cast(list[str], d.pop("features"))

        edition_info_response = cls(
            edition=edition,
            features=features,
        )

        edition_info_response.additional_properties = d
        return edition_info_response

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
