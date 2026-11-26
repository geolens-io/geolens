from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.manifest_groups_left_off_detail import ManifestGroupsLeftOffDetail


T = TypeVar("T", bound="ManifestGroupsLeftOffWarning")


@_attrs_define
class ManifestGroupsLeftOffWarning:
    """Publish manifest code A058: the dataset wasn't shared with some groups.

    Attributes:
        kind (Literal['manifest_groups_left_off']):
        details (ManifestGroupsLeftOffDetail):
    """

    kind: Literal["manifest_groups_left_off"]
    details: ManifestGroupsLeftOffDetail

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
        from ..models.manifest_groups_left_off_detail import ManifestGroupsLeftOffDetail

        d = dict(src_dict)
        kind = cast(Literal["manifest_groups_left_off"], d.pop("kind"))
        if kind != "manifest_groups_left_off":
            raise ValueError(
                f"kind must match const 'manifest_groups_left_off', got '{kind}'"
            )

        details = ManifestGroupsLeftOffDetail.from_dict(d.pop("details"))

        manifest_groups_left_off_warning = cls(
            kind=kind,
            details=details,
        )

        return manifest_groups_left_off_warning
