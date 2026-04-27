from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="ApiKeyStatusResponse")


@_attrs_define
class ApiKeyStatusResponse:
    """Response for GET /settings/api-key-status/.

    Attributes:
        anthropic_configured (bool): Whether ANTHROPIC_API_KEY is set in the environment.
        openai_configured (bool): Whether OPENAI_API_KEY is set in the environment.
    """

    anthropic_configured: bool
    openai_configured: bool
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        anthropic_configured = self.anthropic_configured

        openai_configured = self.openai_configured

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "anthropic_configured": anthropic_configured,
                "openai_configured": openai_configured,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        anthropic_configured = d.pop("anthropic_configured")

        openai_configured = d.pop("openai_configured")

        api_key_status_response = cls(
            anthropic_configured=anthropic_configured,
            openai_configured=openai_configured,
        )

        api_key_status_response.additional_properties = d
        return api_key_status_response

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
