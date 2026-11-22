from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.manifest_attribute_unmatched_detail import (
        ManifestAttributeUnmatchedDetail,
    )


T = TypeVar("T", bound="ManifestAttributeUnmatchedWarning")


@_attrs_define
class ManifestAttributeUnmatchedWarning:
    """Publish manifest code A092: these attribute names matched no column.

    Attributes:
        kind (Literal['manifest_attribute_unmatched']):
        details (ManifestAttributeUnmatchedDetail):
    """

    kind: Literal["manifest_attribute_unmatched"]
    details: ManifestAttributeUnmatchedDetail

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
        from ..models.manifest_attribute_unmatched_detail import (
            ManifestAttributeUnmatchedDetail,
        )

        d = dict(src_dict)
        kind = cast(Literal["manifest_attribute_unmatched"], d.pop("kind"))
        if kind != "manifest_attribute_unmatched":
            raise ValueError(
                f"kind must match const 'manifest_attribute_unmatched', got '{kind}'"
            )

        details = ManifestAttributeUnmatchedDetail.from_dict(d.pop("details"))

        manifest_attribute_unmatched_warning = cls(
            kind=kind,
            details=details,
        )

        return manifest_attribute_unmatched_warning
