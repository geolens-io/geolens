from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="DatasetRelationshipCreate")


@_attrs_define
class DatasetRelationshipCreate:
    """
    Attributes:
        source_column (str): Join column in the source dataset
        target_dataset_id (UUID): UUID of the dataset to link to
        label (None | str | Unset): Optional display label for this relationship
        target_column (str | Unset): Join column in the target dataset Default: 'gid'.
    """

    source_column: str
    target_dataset_id: UUID
    label: None | str | Unset = UNSET
    target_column: str | Unset = "gid"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        source_column = self.source_column

        target_dataset_id = str(self.target_dataset_id)

        label: None | str | Unset
        if isinstance(self.label, Unset):
            label = UNSET
        else:
            label = self.label

        target_column = self.target_column

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "source_column": source_column,
                "target_dataset_id": target_dataset_id,
            }
        )
        if label is not UNSET:
            field_dict["label"] = label
        if target_column is not UNSET:
            field_dict["target_column"] = target_column

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        source_column = d.pop("source_column")

        target_dataset_id = UUID(d.pop("target_dataset_id"))

        def _parse_label(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        label = _parse_label(d.pop("label", UNSET))

        target_column = d.pop("target_column", UNSET)

        dataset_relationship_create = cls(
            source_column=source_column,
            target_dataset_id=target_dataset_id,
            label=label,
            target_column=target_column,
        )

        dataset_relationship_create.additional_properties = d
        return dataset_relationship_create

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
