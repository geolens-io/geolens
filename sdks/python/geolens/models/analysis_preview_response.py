from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.analysis_preview_response_geojson import (
        AnalysisPreviewResponseGeojson,
    )


T = TypeVar("T", bound="AnalysisPreviewResponse")


@_attrs_define
class AnalysisPreviewResponse:
    """GeoJSON FeatureCollection preview of an analysis operation.

    Attributes:
        feature_count (int):
        geojson (AnalysisPreviewResponseGeojson):
        truncated (bool):
        bbox (list[float] | None | Unset):
    """

    feature_count: int
    geojson: AnalysisPreviewResponseGeojson
    truncated: bool
    bbox: list[float] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        feature_count = self.feature_count

        geojson = self.geojson.to_dict()

        truncated = self.truncated

        bbox: list[float] | None | Unset
        if isinstance(self.bbox, Unset):
            bbox = UNSET
        elif isinstance(self.bbox, list):
            bbox = self.bbox

        else:
            bbox = self.bbox

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "feature_count": feature_count,
                "geojson": geojson,
                "truncated": truncated,
            }
        )
        if bbox is not UNSET:
            field_dict["bbox"] = bbox

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.analysis_preview_response_geojson import (
            AnalysisPreviewResponseGeojson,
        )

        d = dict(src_dict)
        feature_count = d.pop("feature_count")

        geojson = AnalysisPreviewResponseGeojson.from_dict(d.pop("geojson"))

        truncated = d.pop("truncated")

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

        analysis_preview_response = cls(
            feature_count=feature_count,
            geojson=geojson,
            truncated=truncated,
            bbox=bbox,
        )

        analysis_preview_response.additional_properties = d
        return analysis_preview_response

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
