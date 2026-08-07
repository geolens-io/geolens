from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.vrt_create_request_resolution_strategy import (
    check_vrt_create_request_resolution_strategy,
)
from ..models.vrt_create_request_resolution_strategy import (
    VrtCreateRequestResolutionStrategy,
)
from ..models.vrt_create_request_visibility import check_vrt_create_request_visibility
from ..models.vrt_create_request_visibility import VrtCreateRequestVisibility
from ..models.vrt_create_request_vrt_type import check_vrt_create_request_vrt_type
from ..models.vrt_create_request_vrt_type import VrtCreateRequestVrtType
from typing import cast
from uuid import UUID


T = TypeVar("T", bound="VrtCreateRequest")


@_attrs_define
class VrtCreateRequest:
    """
    Attributes:
        source_dataset_ids (list[UUID]): Source raster dataset IDs to include in the VRT mosaic or band stack (1-500).
        vrt_type (VrtCreateRequestVrtType): Type of VRT to create. 'mosaic' tiles sources spatially; 'band_stack' aligns
            same-extent sources as multi-band output.
        resolution_strategy (VrtCreateRequestResolutionStrategy): How to resolve mismatched source resolutions: 'finest'
            uses the highest, 'coarsest' uses the lowest, 'average' computes the mean.
        title (str): Human-readable title for the resulting VRT dataset.
        summary (None | str | Unset): Optional description for the VRT dataset.
        visibility (VrtCreateRequestVisibility | Unset): Visibility level for the resulting VRT dataset. Default:
            'private'.
    """

    source_dataset_ids: list[UUID]
    vrt_type: VrtCreateRequestVrtType
    resolution_strategy: VrtCreateRequestResolutionStrategy
    title: str
    summary: None | str | Unset = UNSET
    visibility: VrtCreateRequestVisibility | Unset = "private"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        source_dataset_ids = []
        for source_dataset_ids_item_data in self.source_dataset_ids:
            source_dataset_ids_item = str(source_dataset_ids_item_data)
            source_dataset_ids.append(source_dataset_ids_item)

        vrt_type: str = self.vrt_type

        resolution_strategy: str = self.resolution_strategy

        title = self.title

        summary: None | str | Unset
        if isinstance(self.summary, Unset):
            summary = UNSET
        else:
            summary = self.summary

        visibility: str | Unset = UNSET
        if not isinstance(self.visibility, Unset):
            visibility = self.visibility

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "source_dataset_ids": source_dataset_ids,
                "vrt_type": vrt_type,
                "resolution_strategy": resolution_strategy,
                "title": title,
            }
        )
        if summary is not UNSET:
            field_dict["summary"] = summary
        if visibility is not UNSET:
            field_dict["visibility"] = visibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        source_dataset_ids = []
        _source_dataset_ids = d.pop("source_dataset_ids")
        for source_dataset_ids_item_data in _source_dataset_ids:
            source_dataset_ids_item = UUID(source_dataset_ids_item_data)

            source_dataset_ids.append(source_dataset_ids_item)

        vrt_type = check_vrt_create_request_vrt_type(d.pop("vrt_type"))

        resolution_strategy = check_vrt_create_request_resolution_strategy(
            d.pop("resolution_strategy")
        )

        title = d.pop("title")

        def _parse_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        summary = _parse_summary(d.pop("summary", UNSET))

        _visibility = d.pop("visibility", UNSET)
        visibility: VrtCreateRequestVisibility | Unset
        if isinstance(_visibility, Unset):
            visibility = UNSET
        else:
            visibility = check_vrt_create_request_visibility(_visibility)

        vrt_create_request = cls(
            source_dataset_ids=source_dataset_ids,
            vrt_type=vrt_type,
            resolution_strategy=resolution_strategy,
            title=title,
            summary=summary,
            visibility=visibility,
        )

        vrt_create_request.additional_properties = d
        return vrt_create_request

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
