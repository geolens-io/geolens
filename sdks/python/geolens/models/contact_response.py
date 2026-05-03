from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.contact_response_extra_json_type_0 import (
        ContactResponseExtraJsonType0,
    )


T = TypeVar("T", bound="ContactResponse")


@_attrs_define
class ContactResponse:
    """
    Attributes:
        email (None | str):
        extra_json (ContactResponseExtraJsonType0 | None):
        id (UUID):
        name (None | str):
        organization (None | str):
        phone (None | str):
        record_id (UUID):
        role (str):
        sort_order (int):
    """

    email: None | str
    extra_json: ContactResponseExtraJsonType0 | None
    id: UUID
    name: None | str
    organization: None | str
    phone: None | str
    record_id: UUID
    role: str
    sort_order: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.contact_response_extra_json_type_0 import (
            ContactResponseExtraJsonType0,
        )

        email: None | str
        email = self.email

        extra_json: dict[str, Any] | None
        if isinstance(self.extra_json, ContactResponseExtraJsonType0):
            extra_json = self.extra_json.to_dict()
        else:
            extra_json = self.extra_json

        id = str(self.id)

        name: None | str
        name = self.name

        organization: None | str
        organization = self.organization

        phone: None | str
        phone = self.phone

        record_id = str(self.record_id)

        role = self.role

        sort_order = self.sort_order

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "email": email,
                "extra_json": extra_json,
                "id": id,
                "name": name,
                "organization": organization,
                "phone": phone,
                "record_id": record_id,
                "role": role,
                "sort_order": sort_order,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.contact_response_extra_json_type_0 import (
            ContactResponseExtraJsonType0,
        )

        d = dict(src_dict)

        def _parse_email(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        email = _parse_email(d.pop("email"))

        def _parse_extra_json(data: object) -> ContactResponseExtraJsonType0 | None:
            if data is None:
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                extra_json_type_0 = ContactResponseExtraJsonType0.from_dict(data)

                return extra_json_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ContactResponseExtraJsonType0 | None, data)

        extra_json = _parse_extra_json(d.pop("extra_json"))

        id = UUID(d.pop("id"))

        def _parse_name(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        name = _parse_name(d.pop("name"))

        def _parse_organization(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        organization = _parse_organization(d.pop("organization"))

        def _parse_phone(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        phone = _parse_phone(d.pop("phone"))

        record_id = UUID(d.pop("record_id"))

        role = d.pop("role")

        sort_order = d.pop("sort_order")

        contact_response = cls(
            email=email,
            extra_json=extra_json,
            id=id,
            name=name,
            organization=organization,
            phone=phone,
            record_id=record_id,
            role=role,
            sort_order=sort_order,
        )

        contact_response.additional_properties = d
        return contact_response

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
