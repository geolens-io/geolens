from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.attribute_metadata_update_domain_type_type_0 import (
    AttributeMetadataUpdateDomainTypeType0,
)
from ..models.attribute_metadata_update_domain_type_type_0 import (
    check_attribute_metadata_update_domain_type_type_0,
)
from ..models.attribute_metadata_update_semantic_role_type_0 import (
    AttributeMetadataUpdateSemanticRoleType0,
)
from ..models.attribute_metadata_update_semantic_role_type_0 import (
    check_attribute_metadata_update_semantic_role_type_0,
)
from typing import cast


T = TypeVar("T", bound="AttributeMetadataUpdate")


@_attrs_define
class AttributeMetadataUpdate:
    """
    Attributes:
        description (None | str | Unset):
        domain_type (AttributeMetadataUpdateDomainTypeType0 | None | Unset): Value domain: continuous, categorical,
            coded, etc.
        semantic_role (AttributeMetadataUpdateSemanticRoleType0 | None | Unset): Column role: geometry, identifier,
            measure, etc.
        title (None | str | Unset): Human-friendly column display name
        units (None | str | Unset): Measurement units, e.g. meters, kg
    """

    description: None | str | Unset = UNSET
    domain_type: AttributeMetadataUpdateDomainTypeType0 | None | Unset = UNSET
    semantic_role: AttributeMetadataUpdateSemanticRoleType0 | None | Unset = UNSET
    title: None | str | Unset = UNSET
    units: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        domain_type: None | str | Unset
        if isinstance(self.domain_type, Unset):
            domain_type = UNSET
        elif isinstance(self.domain_type, str):
            domain_type = self.domain_type
        else:
            domain_type = self.domain_type

        semantic_role: None | str | Unset
        if isinstance(self.semantic_role, Unset):
            semantic_role = UNSET
        elif isinstance(self.semantic_role, str):
            semantic_role = self.semantic_role
        else:
            semantic_role = self.semantic_role

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        units: None | str | Unset
        if isinstance(self.units, Unset):
            units = UNSET
        else:
            units = self.units

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if description is not UNSET:
            field_dict["description"] = description
        if domain_type is not UNSET:
            field_dict["domain_type"] = domain_type
        if semantic_role is not UNSET:
            field_dict["semantic_role"] = semantic_role
        if title is not UNSET:
            field_dict["title"] = title
        if units is not UNSET:
            field_dict["units"] = units

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_domain_type(
            data: object,
        ) -> AttributeMetadataUpdateDomainTypeType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                domain_type_type_0 = check_attribute_metadata_update_domain_type_type_0(
                    data
                )

                return domain_type_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AttributeMetadataUpdateDomainTypeType0 | None | Unset, data)

        domain_type = _parse_domain_type(d.pop("domain_type", UNSET))

        def _parse_semantic_role(
            data: object,
        ) -> AttributeMetadataUpdateSemanticRoleType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                semantic_role_type_0 = (
                    check_attribute_metadata_update_semantic_role_type_0(data)
                )

                return semantic_role_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AttributeMetadataUpdateSemanticRoleType0 | None | Unset, data)

        semantic_role = _parse_semantic_role(d.pop("semantic_role", UNSET))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        def _parse_units(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        units = _parse_units(d.pop("units", UNSET))

        attribute_metadata_update = cls(
            description=description,
            domain_type=domain_type,
            semantic_role=semantic_role,
            title=title,
            units=units,
        )

        attribute_metadata_update.additional_properties = d
        return attribute_metadata_update

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
