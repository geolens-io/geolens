from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.contact_create_extra_json_type_0 import ContactCreateExtraJsonType0


T = TypeVar("T", bound="ContactCreate")


@_attrs_define
class ContactCreate:
    """
    Attributes:
        role (str): ISO CI_RoleCode, e.g. pointOfContact, author
        email (None | str | Unset):
        extra_json (ContactCreateExtraJsonType0 | None | Unset): Arbitrary extra fields stored as JSON
        name (None | str | Unset):
        organization (None | str | Unset):
        phone (None | str | Unset):
        sort_order (int | Unset): Display ordering (lower first) Default: 0.
    """

    role: str
    email: None | str | Unset = UNSET
    extra_json: ContactCreateExtraJsonType0 | None | Unset = UNSET
    name: None | str | Unset = UNSET
    organization: None | str | Unset = UNSET
    phone: None | str | Unset = UNSET
    sort_order: int | Unset = 0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.contact_create_extra_json_type_0 import (
            ContactCreateExtraJsonType0,
        )

        role = self.role

        email: None | str | Unset
        if isinstance(self.email, Unset):
            email = UNSET
        else:
            email = self.email

        extra_json: dict[str, Any] | None | Unset
        if isinstance(self.extra_json, Unset):
            extra_json = UNSET
        elif isinstance(self.extra_json, ContactCreateExtraJsonType0):
            extra_json = self.extra_json.to_dict()
        else:
            extra_json = self.extra_json

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        organization: None | str | Unset
        if isinstance(self.organization, Unset):
            organization = UNSET
        else:
            organization = self.organization

        phone: None | str | Unset
        if isinstance(self.phone, Unset):
            phone = UNSET
        else:
            phone = self.phone

        sort_order = self.sort_order

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "role": role,
            }
        )
        if email is not UNSET:
            field_dict["email"] = email
        if extra_json is not UNSET:
            field_dict["extra_json"] = extra_json
        if name is not UNSET:
            field_dict["name"] = name
        if organization is not UNSET:
            field_dict["organization"] = organization
        if phone is not UNSET:
            field_dict["phone"] = phone
        if sort_order is not UNSET:
            field_dict["sort_order"] = sort_order

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.contact_create_extra_json_type_0 import (
            ContactCreateExtraJsonType0,
        )

        d = dict(src_dict)
        role = d.pop("role")

        def _parse_email(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        email = _parse_email(d.pop("email", UNSET))

        def _parse_extra_json(
            data: object,
        ) -> ContactCreateExtraJsonType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                extra_json_type_0 = ContactCreateExtraJsonType0.from_dict(data)

                return extra_json_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ContactCreateExtraJsonType0 | None | Unset, data)

        extra_json = _parse_extra_json(d.pop("extra_json", UNSET))

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        def _parse_organization(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        organization = _parse_organization(d.pop("organization", UNSET))

        def _parse_phone(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        phone = _parse_phone(d.pop("phone", UNSET))

        sort_order = d.pop("sort_order", UNSET)

        contact_create = cls(
            role=role,
            email=email,
            extra_json=extra_json,
            name=name,
            organization=organization,
            phone=phone,
            sort_order=sort_order,
        )

        contact_create.additional_properties = d
        return contact_create

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
