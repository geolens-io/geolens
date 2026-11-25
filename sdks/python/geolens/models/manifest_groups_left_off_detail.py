from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


from ..models.manifest_groups_left_off_detail_reason import (
    check_manifest_groups_left_off_detail_reason,
)
from ..models.manifest_groups_left_off_detail_reason import (
    ManifestGroupsLeftOffDetailReason,
)
from typing import cast


T = TypeVar("T", bound="ManifestGroupsLeftOffDetail")


@_attrs_define
class ManifestGroupsLeftOffDetail:
    """
    Attributes:
        group_ids (list[str]): The groups the dataset wasn't shared with.
        reason (ManifestGroupsLeftOffDetailReason): left_off: the groups no longer exist, or the submitter may not share
            with them. held_back: sharing with them would let more people read the dataset than before this publish, by a
            publish key or after the dataset was narrowed since the apply, so it kept the groups it had. refused: the share
            was refused or held up, and the dataset kept the groups it had.
    """

    group_ids: list[str]
    reason: ManifestGroupsLeftOffDetailReason

    def to_dict(self) -> dict[str, Any]:
        group_ids = self.group_ids

        reason: str = self.reason

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "group_ids": group_ids,
                "reason": reason,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        group_ids = cast(list[str], d.pop("group_ids"))

        reason = check_manifest_groups_left_off_detail_reason(d.pop("reason"))

        manifest_groups_left_off_detail = cls(
            group_ids=group_ids,
            reason=reason,
        )

        return manifest_groups_left_off_detail
