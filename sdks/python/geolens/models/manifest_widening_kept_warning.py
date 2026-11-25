from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.manifest_widening_kept_detail import ManifestWideningKeptDetail


T = TypeVar("T", bound="ManifestWideningKeptWarning")


@_attrs_define
class ManifestWideningKeptWarning:
    """Publish manifest code A056: a publish key can't widen the dataset, so
    it kept its level.

        Attributes:
            kind (Literal['manifest_widening_kept']):
            details (ManifestWideningKeptDetail):
    """

    kind: Literal["manifest_widening_kept"]
    details: ManifestWideningKeptDetail

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
        from ..models.manifest_widening_kept_detail import ManifestWideningKeptDetail

        d = dict(src_dict)
        kind = cast(Literal["manifest_widening_kept"], d.pop("kind"))
        if kind != "manifest_widening_kept":
            raise ValueError(
                f"kind must match const 'manifest_widening_kept', got '{kind}'"
            )

        details = ManifestWideningKeptDetail.from_dict(d.pop("details"))

        manifest_widening_kept_warning = cls(
            kind=kind,
            details=details,
        )

        return manifest_widening_kept_warning
