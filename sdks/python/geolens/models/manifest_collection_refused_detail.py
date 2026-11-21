from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


T = TypeVar("T", bound="ManifestCollectionRefusedDetail")


@_attrs_define
class ManifestCollectionRefusedDetail:
    """The collection a manifest asked for and the submitter could not add to.

    Attributes:
        collection_id (str):
    """

    collection_id: str

    def to_dict(self) -> dict[str, Any]:
        collection_id = self.collection_id

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "collection_id": collection_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        collection_id = d.pop("collection_id")

        manifest_collection_refused_detail = cls(
            collection_id=collection_id,
        )

        return manifest_collection_refused_detail
