from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


T = TypeVar("T", bound="FeatureFlagsResponse")


@_attrs_define
class FeatureFlagsResponse:
    """Public feature flags readable by any authenticated user.

    Attributes:
        enable_dataset_editing (bool | Unset):  Default: False.
        require_metadata_for_publish (bool | Unset):  Default: False.
    """

    enable_dataset_editing: bool | Unset = False
    require_metadata_for_publish: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        enable_dataset_editing = self.enable_dataset_editing

        require_metadata_for_publish = self.require_metadata_for_publish

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if enable_dataset_editing is not UNSET:
            field_dict["enable_dataset_editing"] = enable_dataset_editing
        if require_metadata_for_publish is not UNSET:
            field_dict["require_metadata_for_publish"] = require_metadata_for_publish

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        enable_dataset_editing = d.pop("enable_dataset_editing", UNSET)

        require_metadata_for_publish = d.pop("require_metadata_for_publish", UNSET)

        feature_flags_response = cls(
            enable_dataset_editing=enable_dataset_editing,
            require_metadata_for_publish=require_metadata_for_publish,
        )

        feature_flags_response.additional_properties = d
        return feature_flags_response

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
