from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="DatasetRelationshipResponse")


@_attrs_define
class DatasetRelationshipResponse:
    """
    Attributes:
        id (UUID):
        label (None | str):
        relationship_type (str):
        source_column (str):
        source_dataset_id (UUID):
        target_column (str):
        target_dataset_id (UUID):
        target_dataset_title (None | str | Unset):
    """

    id: UUID
    label: None | str
    relationship_type: str
    source_column: str
    source_dataset_id: UUID
    target_column: str
    target_dataset_id: UUID
    target_dataset_title: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        label: None | str
        label = self.label

        relationship_type = self.relationship_type

        source_column = self.source_column

        source_dataset_id = str(self.source_dataset_id)

        target_column = self.target_column

        target_dataset_id = str(self.target_dataset_id)

        target_dataset_title: None | str | Unset
        if isinstance(self.target_dataset_title, Unset):
            target_dataset_title = UNSET
        else:
            target_dataset_title = self.target_dataset_title

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "label": label,
                "relationship_type": relationship_type,
                "source_column": source_column,
                "source_dataset_id": source_dataset_id,
                "target_column": target_column,
                "target_dataset_id": target_dataset_id,
            }
        )
        if target_dataset_title is not UNSET:
            field_dict["target_dataset_title"] = target_dataset_title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        def _parse_label(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        label = _parse_label(d.pop("label"))

        relationship_type = d.pop("relationship_type")

        source_column = d.pop("source_column")

        source_dataset_id = UUID(d.pop("source_dataset_id"))

        target_column = d.pop("target_column")

        target_dataset_id = UUID(d.pop("target_dataset_id"))

        def _parse_target_dataset_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        target_dataset_title = _parse_target_dataset_title(
            d.pop("target_dataset_title", UNSET)
        )

        dataset_relationship_response = cls(
            id=id,
            label=label,
            relationship_type=relationship_type,
            source_column=source_column,
            source_dataset_id=source_dataset_id,
            target_column=target_column,
            target_dataset_id=target_dataset_id,
            target_dataset_title=target_dataset_title,
        )

        dataset_relationship_response.additional_properties = d
        return dataset_relationship_response

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
