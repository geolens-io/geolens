from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


from ..models.manifest_publication_intent import check_manifest_publication_intent
from ..models.manifest_publication_intent import ManifestPublicationIntent


T = TypeVar("T", bound="ManifestPublication")


@_attrs_define
class ManifestPublication:
    """
    Attributes:
        intent (ManifestPublicationIntent):
    """

    intent: ManifestPublicationIntent

    def to_dict(self) -> dict[str, Any]:
        intent: str = self.intent

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "intent": intent,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        intent = check_manifest_publication_intent(d.pop("intent"))

        manifest_publication = cls(
            intent=intent,
        )

        return manifest_publication
