from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from uuid import UUID


T = TypeVar("T", bound="BulkRevokeRequest")


@_attrs_define
class BulkRevokeRequest:
    """
    Attributes:
        token_ids (list[UUID]):
    """

    token_ids: list[UUID]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        token_ids = []
        for token_ids_item_data in self.token_ids:
            token_ids_item = str(token_ids_item_data)
            token_ids.append(token_ids_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "token_ids": token_ids,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        token_ids = []
        _token_ids = d.pop("token_ids")
        for token_ids_item_data in _token_ids:
            token_ids_item = UUID(token_ids_item_data)

            token_ids.append(token_ids_item)

        bulk_revoke_request = cls(
            token_ids=token_ids,
        )

        bulk_revoke_request.additional_properties = d
        return bulk_revoke_request

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
