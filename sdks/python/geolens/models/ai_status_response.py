from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="AIStatusResponse")


@_attrs_define
class AIStatusResponse:
    """
    Attributes:
        configured (bool): Whether an API key is configured. AI features require both 'enabled' and 'configured'.
        enabled (bool): Whether AI features are enabled for this instance.
        model (None | str): Active model name (e.g. 'claude-sonnet-4-20250514').
        provider (None | str): Active AI provider name (e.g. 'anthropic', 'openai').
        has_embeddings (bool | Unset): Whether at least one record has embeddings stored. Default: False.
        semantic_search_enabled (bool | Unset): Whether pgvector-backed semantic search is enabled. Default: False.
    """

    configured: bool
    enabled: bool
    model: None | str
    provider: None | str
    has_embeddings: bool | Unset = False
    semantic_search_enabled: bool | Unset = False
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        configured = self.configured

        enabled = self.enabled

        model: None | str
        model = self.model

        provider: None | str
        provider = self.provider

        has_embeddings = self.has_embeddings

        semantic_search_enabled = self.semantic_search_enabled

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "configured": configured,
                "enabled": enabled,
                "model": model,
                "provider": provider,
            }
        )
        if has_embeddings is not UNSET:
            field_dict["has_embeddings"] = has_embeddings
        if semantic_search_enabled is not UNSET:
            field_dict["semantic_search_enabled"] = semantic_search_enabled

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        configured = d.pop("configured")

        enabled = d.pop("enabled")

        def _parse_model(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        model = _parse_model(d.pop("model"))

        def _parse_provider(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        provider = _parse_provider(d.pop("provider"))

        has_embeddings = d.pop("has_embeddings", UNSET)

        semantic_search_enabled = d.pop("semantic_search_enabled", UNSET)

        ai_status_response = cls(
            configured=configured,
            enabled=enabled,
            model=model,
            provider=provider,
            has_embeddings=has_embeddings,
            semantic_search_enabled=semantic_search_enabled,
        )

        ai_status_response.additional_properties = d
        return ai_status_response

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
