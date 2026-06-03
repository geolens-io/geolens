from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.contact_update_extra_json_type_0 import ContactUpdateExtraJsonType0


T = TypeVar("T", bound="ContactUpdate")


@_attrs_define
class ContactUpdate:
    """
    Attributes:
        email (None | str | Unset):
        extra_json (ContactUpdateExtraJsonType0 | None | Unset):
        name (None | str | Unset):
        organization (None | str | Unset):
        phone (None | str | Unset):
        role (None | str | Unset):
        sort_order (int | None | Unset):
    """

    email: None | str | Unset = UNSET
    extra_json: ContactUpdateExtraJsonType0 | None | Unset = UNSET
    name: None | str | Unset = UNSET
    organization: None | str | Unset = UNSET
    phone: None | str | Unset = UNSET
    role: None | str | Unset = UNSET
    sort_order: int | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.contact_update_extra_json_type_0 import (
            ContactUpdateExtraJsonType0,
        )

        email: None | str | Unset
        if isinstance(self.email, Unset):
            email = UNSET
        else:
            email = self.email

        extra_json: dict[str, Any] | None | Unset
        if isinstance(self.extra_json, Unset):
            extra_json = UNSET
        elif isinstance(self.extra_json, ContactUpdateExtraJsonType0):
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

        role: None | str | Unset
        if isinstance(self.role, Unset):
            role = UNSET
        else:
            role = self.role

        sort_order: int | None | Unset
        if isinstance(self.sort_order, Unset):
            sort_order = UNSET
        else:
            sort_order = self.sort_order

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
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
        if role is not UNSET:
            field_dict["role"] = role
        if sort_order is not UNSET:
            field_dict["sort_order"] = sort_order

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.contact_update_extra_json_type_0 import (
            ContactUpdateExtraJsonType0,
        )

        d = dict(src_dict)

        def _parse_email(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        email = _parse_email(d.pop("email", UNSET))

        def _parse_extra_json(
            data: object,
        ) -> ContactUpdateExtraJsonType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                extra_json_type_0 = ContactUpdateExtraJsonType0.from_dict(data)

                return extra_json_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ContactUpdateExtraJsonType0 | None | Unset, data)

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

        def _parse_role(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        role = _parse_role(d.pop("role", UNSET))

        def _parse_sort_order(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        sort_order = _parse_sort_order(d.pop("sort_order", UNSET))

        contact_update = cls(
            email=email,
            extra_json=extra_json,
            name=name,
            organization=organization,
            phone=phone,
            role=role,
            sort_order=sort_order,
        )

        contact_update.additional_properties = d
        return contact_update

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
