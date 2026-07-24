from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.analysis_preview_request_operation import AnalysisPreviewRequestOperation
from ..models.analysis_preview_request_operation import (
    check_analysis_preview_request_operation,
)
from typing import cast

if TYPE_CHECKING:
    from ..models.analysis_preview_request_mask_type_0 import (
        AnalysisPreviewRequestMaskType0,
    )


T = TypeVar("T", bound="AnalysisPreviewRequest")


@_attrs_define
class AnalysisPreviewRequest:
    """Parameters for a synchronous analysis preview.

    Deliberately flat (no discriminated union) so SDK generators keep the
    endpoint; per-operation requiredness is enforced by the validator.

        Attributes:
            operation (AnalysisPreviewRequestOperation):
            distance_meters (float | None | Unset): Buffer distance in meters (buffer only)
            mask (AnalysisPreviewRequestMaskType0 | None | Unset): GeoJSON Polygon or MultiPolygon geometry in EPSG:4326
                (clip only)
    """

    operation: AnalysisPreviewRequestOperation
    distance_meters: float | None | Unset = UNSET
    mask: AnalysisPreviewRequestMaskType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.analysis_preview_request_mask_type_0 import (
            AnalysisPreviewRequestMaskType0,
        )

        operation: str = self.operation

        distance_meters: float | None | Unset
        if isinstance(self.distance_meters, Unset):
            distance_meters = UNSET
        else:
            distance_meters = self.distance_meters

        mask: dict[str, Any] | None | Unset
        if isinstance(self.mask, Unset):
            mask = UNSET
        elif isinstance(self.mask, AnalysisPreviewRequestMaskType0):
            mask = self.mask.to_dict()
        else:
            mask = self.mask

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "operation": operation,
            }
        )
        if distance_meters is not UNSET:
            field_dict["distance_meters"] = distance_meters
        if mask is not UNSET:
            field_dict["mask"] = mask

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.analysis_preview_request_mask_type_0 import (
            AnalysisPreviewRequestMaskType0,
        )

        d = dict(src_dict)
        operation = check_analysis_preview_request_operation(d.pop("operation"))

        def _parse_distance_meters(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        distance_meters = _parse_distance_meters(d.pop("distance_meters", UNSET))

        def _parse_mask(data: object) -> AnalysisPreviewRequestMaskType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                mask_type_0 = AnalysisPreviewRequestMaskType0.from_dict(data)

                return mask_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AnalysisPreviewRequestMaskType0 | None | Unset, data)

        mask = _parse_mask(d.pop("mask", UNSET))

        analysis_preview_request = cls(
            operation=operation,
            distance_meters=distance_meters,
            mask=mask,
        )

        analysis_preview_request.additional_properties = d
        return analysis_preview_request

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
