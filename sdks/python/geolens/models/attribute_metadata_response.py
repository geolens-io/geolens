from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="AttributeMetadataResponse")


@_attrs_define
class AttributeMetadataResponse:
    """
    Attributes:
        data_type (None | str):
        dataset_id (UUID):
        description (None | str):
        domain_type (None | str):
        field_name (str):
        id (UUID):
        is_current (bool): False if column was removed in a later version
        title (None | str):
        units (None | str):
        user_modified_fields (list[str]): Field names manually edited by a user
        example_values (list[Any] | None | Unset): Sample values from the column
        is_nullable (bool | None | Unset):
        ordinal_position (int | None | Unset): Column position in the table (1-based)
        semantic_role (None | str | Unset): Inferred role: geometry, identifier, measure, etc.
    """

    data_type: None | str
    dataset_id: UUID
    description: None | str
    domain_type: None | str
    field_name: str
    id: UUID
    is_current: bool
    title: None | str
    units: None | str
    user_modified_fields: list[str]
    example_values: list[Any] | None | Unset = UNSET
    is_nullable: bool | None | Unset = UNSET
    ordinal_position: int | None | Unset = UNSET
    semantic_role: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data_type: None | str
        data_type = self.data_type

        dataset_id = str(self.dataset_id)

        description: None | str
        description = self.description

        domain_type: None | str
        domain_type = self.domain_type

        field_name = self.field_name

        id = str(self.id)

        is_current = self.is_current

        title: None | str
        title = self.title

        units: None | str
        units = self.units

        user_modified_fields = self.user_modified_fields

        example_values: list[Any] | None | Unset
        if isinstance(self.example_values, Unset):
            example_values = UNSET
        elif isinstance(self.example_values, list):
            example_values = self.example_values

        else:
            example_values = self.example_values

        is_nullable: bool | None | Unset
        if isinstance(self.is_nullable, Unset):
            is_nullable = UNSET
        else:
            is_nullable = self.is_nullable

        ordinal_position: int | None | Unset
        if isinstance(self.ordinal_position, Unset):
            ordinal_position = UNSET
        else:
            ordinal_position = self.ordinal_position

        semantic_role: None | str | Unset
        if isinstance(self.semantic_role, Unset):
            semantic_role = UNSET
        else:
            semantic_role = self.semantic_role

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "data_type": data_type,
                "dataset_id": dataset_id,
                "description": description,
                "domain_type": domain_type,
                "field_name": field_name,
                "id": id,
                "is_current": is_current,
                "title": title,
                "units": units,
                "user_modified_fields": user_modified_fields,
            }
        )
        if example_values is not UNSET:
            field_dict["example_values"] = example_values
        if is_nullable is not UNSET:
            field_dict["is_nullable"] = is_nullable
        if ordinal_position is not UNSET:
            field_dict["ordinal_position"] = ordinal_position
        if semantic_role is not UNSET:
            field_dict["semantic_role"] = semantic_role

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_data_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        data_type = _parse_data_type(d.pop("data_type"))

        dataset_id = UUID(d.pop("dataset_id"))

        def _parse_description(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        description = _parse_description(d.pop("description"))

        def _parse_domain_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        domain_type = _parse_domain_type(d.pop("domain_type"))

        field_name = d.pop("field_name")

        id = UUID(d.pop("id"))

        is_current = d.pop("is_current")

        def _parse_title(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        title = _parse_title(d.pop("title"))

        def _parse_units(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        units = _parse_units(d.pop("units"))

        user_modified_fields = cast(list[str], d.pop("user_modified_fields"))

        def _parse_example_values(data: object) -> list[Any] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                example_values_type_0 = cast(list[Any], data)

                return example_values_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[Any] | None | Unset, data)

        example_values = _parse_example_values(d.pop("example_values", UNSET))

        def _parse_is_nullable(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_nullable = _parse_is_nullable(d.pop("is_nullable", UNSET))

        def _parse_ordinal_position(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        ordinal_position = _parse_ordinal_position(d.pop("ordinal_position", UNSET))

        def _parse_semantic_role(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        semantic_role = _parse_semantic_role(d.pop("semantic_role", UNSET))

        attribute_metadata_response = cls(
            data_type=data_type,
            dataset_id=dataset_id,
            description=description,
            domain_type=domain_type,
            field_name=field_name,
            id=id,
            is_current=is_current,
            title=title,
            units=units,
            user_modified_fields=user_modified_fields,
            example_values=example_values,
            is_nullable=is_nullable,
            ordinal_position=ordinal_position,
            semantic_role=semantic_role,
        )

        attribute_metadata_response.additional_properties = d
        return attribute_metadata_response

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
