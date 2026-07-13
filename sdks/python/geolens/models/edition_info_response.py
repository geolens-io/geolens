from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="EditionInfoResponse")


@_attrs_define
class EditionInfoResponse:
    """Response for runtime capability metadata.

    Attributes:
        edition (str): Runtime capability channel.
        features (list[str]): List of enabled runtime feature flags.
        tenancy_mode (str | Unset): Deployment tenancy mode. Default: 'single_tenant'.
    """

    edition: str
    features: list[str]
    tenancy_mode: str | Unset = "single_tenant"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        edition = self.edition

        features = self.features

        tenancy_mode = self.tenancy_mode

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "edition": edition,
                "features": features,
            }
        )
        if tenancy_mode is not UNSET:
            field_dict["tenancy_mode"] = tenancy_mode

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        edition = d.pop("edition")

        features = cast(list[str], d.pop("features"))

        tenancy_mode = d.pop("tenancy_mode", UNSET)

        edition_info_response = cls(
            edition=edition,
            features=features,
            tenancy_mode=tenancy_mode,
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
