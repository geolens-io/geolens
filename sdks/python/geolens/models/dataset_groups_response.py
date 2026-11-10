from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.group_ref import GroupRef


T = TypeVar("T", bound="DatasetGroupsResponse")


@_attrs_define
class DatasetGroupsResponse:
    """
    Attributes:
        visibility (str): The dataset's visibility after the change: a private dataset shared with a group becomes
            restricted, and a restricted one left with no group or role grant becomes private.
        groups (list[GroupRef]): The sharing groups the dataset is shared with, by name.
        metadata_warnings (list[str] | None | Unset): Advisory warnings, as on the metadata PATCH. The change has
            already applied.
    """

    visibility: str
    groups: list[GroupRef]
    metadata_warnings: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        visibility = self.visibility

        groups = []
        for groups_item_data in self.groups:
            groups_item = groups_item_data.to_dict()
            groups.append(groups_item)

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
                "visibility": visibility,
                "groups": groups,
            }
        )
        if metadata_warnings is not UNSET:
            field_dict["metadata_warnings"] = metadata_warnings

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.group_ref import GroupRef

        d = dict(src_dict)
        visibility = d.pop("visibility")

        groups = []
        _groups = d.pop("groups")
        for groups_item_data in _groups:
            groups_item = GroupRef.from_dict(groups_item_data)

            groups.append(groups_item)

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

        dataset_groups_response = cls(
            visibility=visibility,
            groups=groups,
            metadata_warnings=metadata_warnings,
        )

        dataset_groups_response.additional_properties = d
        return dataset_groups_response

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
