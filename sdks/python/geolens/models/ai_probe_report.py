from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.ai_probe_check import AIProbeCheck


T = TypeVar("T", bound="AIProbeReport")


@_attrs_define
class AIProbeReport:
    """Per-purpose live provider probe results (admin ai-status ?probe=true).

    Attributes:
        chat (AIProbeCheck): Result of one live provider check (chat or embeddings).
        embeddings (AIProbeCheck): Result of one live provider check (chat or embeddings).
    """

    chat: AIProbeCheck
    embeddings: AIProbeCheck
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        chat = self.chat.to_dict()

        embeddings = self.embeddings.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "chat": chat,
                "embeddings": embeddings,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ai_probe_check import AIProbeCheck

        d = dict(src_dict)
        chat = AIProbeCheck.from_dict(d.pop("chat"))

        embeddings = AIProbeCheck.from_dict(d.pop("embeddings"))

        ai_probe_report = cls(
            chat=chat,
            embeddings=embeddings,
        )

        ai_probe_report.additional_properties = d
        return ai_probe_report

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
