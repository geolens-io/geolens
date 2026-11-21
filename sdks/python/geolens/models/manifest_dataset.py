from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.manifest_dataset_visibility_type_0 import (
    check_manifest_dataset_visibility_type_0,
)
from ..models.manifest_dataset_visibility_type_0 import ManifestDatasetVisibilityType0
from typing import cast

if TYPE_CHECKING:
    from ..models.manifest_attribute import ManifestAttribute
    from ..models.manifest_collection_ref import ManifestCollectionRef
    from ..models.manifest_metadata import ManifestMetadata
    from ..models.manifest_publication import ManifestPublication
    from ..models.manifest_source import ManifestSource


T = TypeVar("T", bound="ManifestDataset")


@_attrs_define
class ManifestDataset:
    """
    Attributes:
        key (str): Stable dataset identity key used for idempotent apply operations.
        title (str):
        sources (list[ManifestSource]):
        publication (ManifestPublication):
        description (None | str | Unset):
        metadata (ManifestMetadata | None | Unset):
        visibility (ManifestDatasetVisibilityType0 | None | Unset): Who can see the dataset. Version 2 only. Omitted on
            create the dataset is private; omitted on update the current level is kept.
        collection (ManifestCollectionRef | None | Unset): Collection to add the dataset to. Version 2 only. Adding
            needs the manage_collections permission and ownership of the collection; otherwise the entry carries warning
            A033.
        attributes (list[ManifestAttribute] | None | Unset): Per-column title, description and units, by column name in
            the uploaded file. Version 2 only. A null field keeps the stored text; a name matching no column is warning
            A092.
    """

    key: str
    title: str
    sources: list[ManifestSource]
    publication: ManifestPublication
    description: None | str | Unset = UNSET
    metadata: ManifestMetadata | None | Unset = UNSET
    visibility: ManifestDatasetVisibilityType0 | None | Unset = UNSET
    collection: ManifestCollectionRef | None | Unset = UNSET
    attributes: list[ManifestAttribute] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.manifest_collection_ref import ManifestCollectionRef
        from ..models.manifest_metadata import ManifestMetadata

        key = self.key

        title = self.title

        sources = []
        for sources_item_data in self.sources:
            sources_item = sources_item_data.to_dict()
            sources.append(sources_item)

        publication = self.publication.to_dict()

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

        visibility: None | str | Unset
        if isinstance(self.visibility, Unset):
            visibility = UNSET
        elif isinstance(self.visibility, str):
            visibility = self.visibility
        else:
            visibility = self.visibility

        collection: dict[str, Any] | None | Unset
        if isinstance(self.collection, Unset):
            collection = UNSET
        elif isinstance(self.collection, ManifestCollectionRef):
            collection = self.collection.to_dict()
        else:
            collection = self.collection

        attributes: list[dict[str, Any]] | None | Unset
        if isinstance(self.attributes, Unset):
            attributes = UNSET
        elif isinstance(self.attributes, list):
            attributes = []
            for attributes_type_0_item_data in self.attributes:
                attributes_type_0_item = attributes_type_0_item_data.to_dict()
                attributes.append(attributes_type_0_item)

        else:
            attributes = self.attributes

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "key": key,
                "title": title,
                "sources": sources,
                "publication": publication,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if metadata is not UNSET:
            field_dict["metadata"] = metadata
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if collection is not UNSET:
            field_dict["collection"] = collection
        if attributes is not UNSET:
            field_dict["attributes"] = attributes

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_attribute import ManifestAttribute
        from ..models.manifest_collection_ref import ManifestCollectionRef
        from ..models.manifest_metadata import ManifestMetadata
        from ..models.manifest_publication import ManifestPublication
        from ..models.manifest_source import ManifestSource

        d = dict(src_dict)
        key = d.pop("key")

        title = d.pop("title")

        sources = []
        _sources = d.pop("sources")
        for sources_item_data in _sources:
            sources_item = ManifestSource.from_dict(sources_item_data)

            sources.append(sources_item)

        publication = ManifestPublication.from_dict(d.pop("publication"))

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

        def _parse_visibility(
            data: object,
        ) -> ManifestDatasetVisibilityType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                visibility_type_0 = check_manifest_dataset_visibility_type_0(data)

                return visibility_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestDatasetVisibilityType0 | None | Unset, data)

        visibility = _parse_visibility(d.pop("visibility", UNSET))

        def _parse_collection(data: object) -> ManifestCollectionRef | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                collection_type_0 = ManifestCollectionRef.from_dict(data)

                return collection_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestCollectionRef | None | Unset, data)

        collection = _parse_collection(d.pop("collection", UNSET))

        def _parse_attributes(data: object) -> list[ManifestAttribute] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                attributes_type_0 = []
                _attributes_type_0 = data
                for attributes_type_0_item_data in _attributes_type_0:
                    attributes_type_0_item = ManifestAttribute.from_dict(
                        attributes_type_0_item_data
                    )

                    attributes_type_0.append(attributes_type_0_item)

                return attributes_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ManifestAttribute] | None | Unset, data)

        attributes = _parse_attributes(d.pop("attributes", UNSET))

        manifest_dataset = cls(
            key=key,
            title=title,
            sources=sources,
            publication=publication,
            description=description,
            metadata=metadata,
            visibility=visibility,
            collection=collection,
            attributes=attributes,
        )

        return manifest_dataset
