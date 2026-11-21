from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


from ..models.manifest_public_fallback_detail_reason import (
    check_manifest_public_fallback_detail_reason,
)
from ..models.manifest_public_fallback_detail_reason import (
    ManifestPublicFallbackDetailReason,
)


T = TypeVar("T", bound="ManifestPublicFallbackDetail")


@_attrs_define
class ManifestPublicFallbackDetail:
    """
    Attributes:
        reason (ManifestPublicFallbackDetailReason): key: a publish key can't make anything public. restriction: public
            visibility is restricted to admins on this server.
    """

    reason: ManifestPublicFallbackDetailReason

    def to_dict(self) -> dict[str, Any]:
        reason: str = self.reason

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "reason": reason,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        reason = check_manifest_public_fallback_detail_reason(d.pop("reason"))

        manifest_public_fallback_detail = cls(
            reason=reason,
        )

        return manifest_public_fallback_detail
