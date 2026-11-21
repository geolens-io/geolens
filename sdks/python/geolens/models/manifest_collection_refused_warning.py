from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define


from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.manifest_collection_refused_detail import (
        ManifestCollectionRefusedDetail,
    )


T = TypeVar("T", bound="ManifestCollectionRefusedWarning")


@_attrs_define
class ManifestCollectionRefusedWarning:
    """Publish manifest code A033: the dataset was published without its collection.

    Attributes:
        kind (Literal['manifest_collection_refused']):
        details (ManifestCollectionRefusedDetail): The collection a manifest asked for and the submitter could not add
            to.
    """

    kind: Literal["manifest_collection_refused"]
    details: ManifestCollectionRefusedDetail

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
        from ..models.manifest_collection_refused_detail import (
            ManifestCollectionRefusedDetail,
        )

        d = dict(src_dict)
        kind = cast(Literal["manifest_collection_refused"], d.pop("kind"))
        if kind != "manifest_collection_refused":
            raise ValueError(
                f"kind must match const 'manifest_collection_refused', got '{kind}'"
            )

        details = ManifestCollectionRefusedDetail.from_dict(d.pop("details"))

        manifest_collection_refused_warning = cls(
            kind=kind,
            details=details,
        )

        return manifest_collection_refused_warning
