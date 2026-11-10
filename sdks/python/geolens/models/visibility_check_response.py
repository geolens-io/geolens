from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.map_layer_access_gap import MapLayerAccessGap


T = TypeVar("T", bound="VisibilityCheckResponse")


@_attrs_define
class VisibilityCheckResponse:
    """
    Attributes:
        non_public_datasets (list[str]): Titles of datasets not publicly visible
        has_non_public (bool): True if any layer references a non-public dataset
        hidden_from_groups (list[MapLayerAccessGap] | Unset): On a restricted map, the layers some of its groups can't
            read, among those the caller reads. Empty on other maps, and when the permission authority can't say who reads a
            dataset.
    """

    non_public_datasets: list[str]
    has_non_public: bool
    hidden_from_groups: list[MapLayerAccessGap] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        non_public_datasets = self.non_public_datasets

        has_non_public = self.has_non_public

        hidden_from_groups: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.hidden_from_groups, Unset):
            hidden_from_groups = []
            for hidden_from_groups_item_data in self.hidden_from_groups:
                hidden_from_groups_item = hidden_from_groups_item_data.to_dict()
                hidden_from_groups.append(hidden_from_groups_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "non_public_datasets": non_public_datasets,
                "has_non_public": has_non_public,
            }
        )
        if hidden_from_groups is not UNSET:
            field_dict["hidden_from_groups"] = hidden_from_groups

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.map_layer_access_gap import MapLayerAccessGap

        d = dict(src_dict)
        non_public_datasets = cast(list[str], d.pop("non_public_datasets"))

        has_non_public = d.pop("has_non_public")

        _hidden_from_groups = d.pop("hidden_from_groups", UNSET)
        hidden_from_groups: list[MapLayerAccessGap] | Unset = UNSET
        if _hidden_from_groups is not UNSET:
            hidden_from_groups = []
            for hidden_from_groups_item_data in _hidden_from_groups:
                hidden_from_groups_item = MapLayerAccessGap.from_dict(
                    hidden_from_groups_item_data
                )

                hidden_from_groups.append(hidden_from_groups_item)

        visibility_check_response = cls(
            non_public_datasets=non_public_datasets,
            has_non_public=has_non_public,
            hidden_from_groups=hidden_from_groups,
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
