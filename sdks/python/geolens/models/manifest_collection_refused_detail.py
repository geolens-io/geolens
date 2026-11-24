from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.manifest_collection_refused_detail_reason import (
    check_manifest_collection_refused_detail_reason,
)
from ..models.manifest_collection_refused_detail_reason import (
    ManifestCollectionRefusedDetailReason,
)


T = TypeVar("T", bound="ManifestCollectionRefusedDetail")


@_attrs_define
class ManifestCollectionRefusedDetail:
    """The collection a manifest asked for that the dataset was not added to.

    Attributes:
        collection_id (str):
        reason (ManifestCollectionRefusedDetailReason | Unset): refused: the submitter can't add datasets to the
            collection. busy: another change held the collection too long; publishing again may add the dataset. Default:
            'refused'.
    """

    collection_id: str
    reason: ManifestCollectionRefusedDetailReason | Unset = "refused"

    def to_dict(self) -> dict[str, Any]:
        collection_id = self.collection_id

        reason: str | Unset = UNSET
        if not isinstance(self.reason, Unset):
            reason = self.reason

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "collection_id": collection_id,
            }
        )
        if reason is not UNSET:
            field_dict["reason"] = reason

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        collection_id = d.pop("collection_id")

        _reason = d.pop("reason", UNSET)
        reason: ManifestCollectionRefusedDetailReason | Unset
        if isinstance(_reason, Unset):
            reason = UNSET
        else:
            reason = check_manifest_collection_refused_detail_reason(_reason)

        manifest_collection_refused_detail = cls(
            collection_id=collection_id,
            reason=reason,
        )

        return manifest_collection_refused_detail
