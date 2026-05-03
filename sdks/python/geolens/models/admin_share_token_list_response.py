from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.admin_share_token_response import AdminShareTokenResponse


T = TypeVar("T", bound="AdminShareTokenListResponse")


@_attrs_define
class AdminShareTokenListResponse:
    """
    Attributes:
        tokens (list[AdminShareTokenResponse]):
        total (int):
    """

    tokens: list[AdminShareTokenResponse]
    total: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        tokens = []
        for tokens_item_data in self.tokens:
            tokens_item = tokens_item_data.to_dict()
            tokens.append(tokens_item)

        total = self.total

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "tokens": tokens,
                "total": total,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.admin_share_token_response import AdminShareTokenResponse

        d = dict(src_dict)
        tokens = []
        _tokens = d.pop("tokens")
        for tokens_item_data in _tokens:
            tokens_item = AdminShareTokenResponse.from_dict(tokens_item_data)

            tokens.append(tokens_item)

        total = d.pop("total")

        admin_share_token_list_response = cls(
            tokens=tokens,
            total=total,
        )

        admin_share_token_list_response.additional_properties = d
        return admin_share_token_list_response

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
