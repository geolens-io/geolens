from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ManifestMetadata")


@_attrs_define
class ManifestMetadata:
    """
    Attributes:
        tags (list[str] | None | Unset):
        organization (None | str | Unset):
        crs (None | str | Unset):
        license_ (None | str | Unset):
        attribution (None | str | Unset):
        bbox (list[float] | None | Unset):
    """

    tags: list[str] | None | Unset = UNSET
    organization: None | str | Unset = UNSET
    crs: None | str | Unset = UNSET
    license_: None | str | Unset = UNSET
    attribution: None | str | Unset = UNSET
    bbox: list[float] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        tags: list[str] | None | Unset
        if isinstance(self.tags, Unset):
            tags = UNSET
        elif isinstance(self.tags, list):
            tags = self.tags

        else:
            tags = self.tags

        organization: None | str | Unset
        if isinstance(self.organization, Unset):
            organization = UNSET
        else:
            organization = self.organization

        crs: None | str | Unset
        if isinstance(self.crs, Unset):
            crs = UNSET
        else:
            crs = self.crs

        license_: None | str | Unset
        if isinstance(self.license_, Unset):
            license_ = UNSET
        else:
            license_ = self.license_

        attribution: None | str | Unset
        if isinstance(self.attribution, Unset):
            attribution = UNSET
        else:
            attribution = self.attribution

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        field_dict: dict[str, Any] = {}

        field_dict.update({})
        if tags is not UNSET:
            field_dict["tags"] = tags
        if organization is not UNSET:
            field_dict["organization"] = organization
        if crs is not UNSET:
            field_dict["crs"] = crs
        if license_ is not UNSET:
            field_dict["license"] = license_
        if attribution is not UNSET:
            field_dict["attribution"] = attribution
        if bbox is not UNSET:
            field_dict["bbox"] = bbox

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_tags(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                tags_type_0 = cast(list[str], data)

                return tags_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        tags = _parse_tags(d.pop("tags", UNSET))

        def _parse_organization(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        organization = _parse_organization(d.pop("organization", UNSET))

        def _parse_crs(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        crs = _parse_crs(d.pop("crs", UNSET))

        def _parse_license_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        license_ = _parse_license_(d.pop("license", UNSET))

        def _parse_attribution(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        attribution = _parse_attribution(d.pop("attribution", UNSET))

        def _parse_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                bbox_type_0 = cast(list[float], data)

                return bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        bbox = _parse_bbox(d.pop("bbox", UNSET))

        manifest_metadata = cls(
            tags=tags,
            organization=organization,
            crs=crs,
            license_=license_,
            attribution=attribution,
            bbox=bbox,
        )

        return manifest_metadata
