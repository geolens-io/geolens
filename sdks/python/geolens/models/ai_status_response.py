from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.ai_probe_report import AIProbeReport


T = TypeVar("T", bound="AIStatusResponse")


@_attrs_define
class AIStatusResponse:
    """
    Attributes:
        provider (None | str): Active AI provider name (e.g. 'anthropic', 'openai').
        model (None | str): Active model name (e.g. 'claude-sonnet-4-20250514').
        enabled (bool): Whether AI features are enabled for this instance.
        configured (bool): Whether an API key is configured. AI features require both 'enabled' and 'configured'.
        semantic_search_enabled (bool | Unset): Whether pgvector-backed semantic search is enabled. Default: False.
        has_embeddings (bool | Unset): Whether at least one record has embeddings stored. Default: False.
        probe (AIProbeReport | None | Unset): Live provider probe results. Only present when the request opted in via
            ?probe=true.
    """

    provider: None | str
    model: None | str
    enabled: bool
    configured: bool
    semantic_search_enabled: bool | Unset = False
    has_embeddings: bool | Unset = False
    probe: AIProbeReport | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.ai_probe_report import AIProbeReport

        provider: None | str
        provider = self.provider

        model: None | str
        model = self.model

        enabled = self.enabled

        configured = self.configured

        semantic_search_enabled = self.semantic_search_enabled

        has_embeddings = self.has_embeddings

        probe: dict[str, Any] | None | Unset
        if isinstance(self.probe, Unset):
            probe = UNSET
        elif isinstance(self.probe, AIProbeReport):
            probe = self.probe.to_dict()
        else:
            probe = self.probe

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "provider": provider,
                "model": model,
                "enabled": enabled,
                "configured": configured,
            }
        )
        if semantic_search_enabled is not UNSET:
            field_dict["semantic_search_enabled"] = semantic_search_enabled
        if has_embeddings is not UNSET:
            field_dict["has_embeddings"] = has_embeddings
        if probe is not UNSET:
            field_dict["probe"] = probe

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ai_probe_report import AIProbeReport

        d = dict(src_dict)

        def _parse_provider(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        provider = _parse_provider(d.pop("provider"))

        def _parse_model(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        model = _parse_model(d.pop("model"))

        enabled = d.pop("enabled")

        configured = d.pop("configured")

        semantic_search_enabled = d.pop("semantic_search_enabled", UNSET)

        has_embeddings = d.pop("has_embeddings", UNSET)

        def _parse_probe(data: object) -> AIProbeReport | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                probe_type_0 = AIProbeReport.from_dict(data)

                return probe_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AIProbeReport | None | Unset, data)

        probe = _parse_probe(d.pop("probe", UNSET))

        ai_status_response = cls(
            provider=provider,
            model=model,
            enabled=enabled,
            configured=configured,
            semantic_search_enabled=semantic_search_enabled,
            has_embeddings=has_embeddings,
            probe=probe,
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
