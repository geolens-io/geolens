from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.manifest_public_fallback_detail import ManifestPublicFallbackDetail


T = TypeVar("T", bound="ManifestPublicFallbackWarning")


@_attrs_define
class ManifestPublicFallbackWarning:
    """Publish manifest code A020: public was refused when the job ran, so
    the dataset was shared with the organization instead.

        Attributes:
            kind (Literal['manifest_public_fallback']):
            details (ManifestPublicFallbackDetail):
    """

    kind: Literal["manifest_public_fallback"]
    details: ManifestPublicFallbackDetail

    def to_dict(self) -> dict[str, Any]:
        kind = self.kind

        details = self.details.to_dict()

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "kind": kind,
                "details": details,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_public_fallback_detail import (
            ManifestPublicFallbackDetail,
        )

        d = dict(src_dict)
        kind = cast(Literal["manifest_public_fallback"], d.pop("kind"))
        if kind != "manifest_public_fallback":
            raise ValueError(
                f"kind must match const 'manifest_public_fallback', got '{kind}'"
            )

        details = ManifestPublicFallbackDetail.from_dict(d.pop("details"))

        manifest_public_fallback_warning = cls(
            kind=kind,
            details=details,
        )

        return manifest_public_fallback_warning
