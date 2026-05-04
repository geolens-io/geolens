from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.manifest_metadata import ManifestMetadata
    from ..models.manifest_publication import ManifestPublication
    from ..models.manifest_source import ManifestSource


T = TypeVar("T", bound="ManifestDataset")


@_attrs_define
class ManifestDataset:
    """
    Attributes:
        key (str): Stable dataset identity key used for idempotent apply operations.
        publication (ManifestPublication):
        sources (list[ManifestSource]):
        title (str):
        description (None | str | Unset):
        metadata (ManifestMetadata | None | Unset):
    """

    key: str
    publication: ManifestPublication
    sources: list[ManifestSource]
    title: str
    description: None | str | Unset = UNSET
    metadata: ManifestMetadata | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.manifest_metadata import ManifestMetadata

        key = self.key

        publication = self.publication.to_dict()

        sources = []
        for sources_item_data in self.sources:
            sources_item = sources_item_data.to_dict()
            sources.append(sources_item)

        title = self.title

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        metadata: dict[str, Any] | None | Unset
        if isinstance(self.metadata, Unset):
            metadata = UNSET
        elif isinstance(self.metadata, ManifestMetadata):
            metadata = self.metadata.to_dict()
        else:
            metadata = self.metadata

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "key": key,
                "publication": publication,
                "sources": sources,
                "title": title,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if metadata is not UNSET:
            field_dict["metadata"] = metadata

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_metadata import ManifestMetadata
        from ..models.manifest_publication import ManifestPublication
        from ..models.manifest_source import ManifestSource

        d = dict(src_dict)
        key = d.pop("key")

        publication = ManifestPublication.from_dict(d.pop("publication"))

        sources = []
        _sources = d.pop("sources")
        for sources_item_data in _sources:
            sources_item = ManifestSource.from_dict(sources_item_data)

            sources.append(sources_item)

        title = d.pop("title")

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_metadata(data: object) -> ManifestMetadata | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                metadata_type_0 = ManifestMetadata.from_dict(data)

                return metadata_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestMetadata | None | Unset, data)

        metadata = _parse_metadata(d.pop("metadata", UNSET))

        manifest_dataset = cls(
            key=key,
            publication=publication,
            sources=sources,
            title=title,
            description=description,
            metadata=metadata,
        )

        return manifest_dataset
