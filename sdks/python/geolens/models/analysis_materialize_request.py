from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.analysis_materialize_request_operation import (
    AnalysisMaterializeRequestOperation,
)
from ..models.analysis_materialize_request_operation import (
    check_analysis_materialize_request_operation,
)
from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.analysis_materialize_request_mask_type_0 import (
        AnalysisMaterializeRequestMaskType0,
    )


T = TypeVar("T", bound="AnalysisMaterializeRequest")


@_attrs_define
class AnalysisMaterializeRequest:
    """Parameters for materializing an analysis result as a new dataset.

    Attributes:
        operation (AnalysisMaterializeRequestOperation):
        title (str):
        distance_meters (float | None | Unset): Buffer distance in meters (buffer only)
        mask (AnalysisMaterializeRequestMaskType0 | None | Unset): GeoJSON Polygon or MultiPolygon geometry in EPSG:4326
            (clip and select_by_location)
        mask_dataset_id (None | Unset | UUID): Polygon dataset supplying the second layer: the area clipped to, selected
            against, or overlaid with. For clip and select_by_location it is the alternative to `mask`; for intersect it is
            REQUIRED and `mask` is rejected, because an overlay carries the second layer's attributes onto its output and a
            drawn polygon has none.
        by_field (None | str | Unset): Optional group-by column for dissolve
        join_dataset_id (None | Unset | UUID): Dataset to join against; each source feature gains a count of the
            features from it that intersect (spatial_join only)
        join_fields (list[str] | None | Unset): Columns to copy from the intersecting join feature, prefixed 'join_' in
            the output. Ties break on the lowest join-layer gid (spatial_join only)
    """

    operation: AnalysisMaterializeRequestOperation
    title: str
    distance_meters: float | None | Unset = UNSET
    mask: AnalysisMaterializeRequestMaskType0 | None | Unset = UNSET
    mask_dataset_id: None | Unset | UUID = UNSET
    by_field: None | str | Unset = UNSET
    join_dataset_id: None | Unset | UUID = UNSET
    join_fields: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.analysis_materialize_request_mask_type_0 import (
            AnalysisMaterializeRequestMaskType0,
        )

        operation: str = self.operation

        title = self.title

        distance_meters: float | None | Unset
        if isinstance(self.distance_meters, Unset):
            distance_meters = UNSET
        else:
            distance_meters = self.distance_meters

        mask: dict[str, Any] | None | Unset
        if isinstance(self.mask, Unset):
            mask = UNSET
        elif isinstance(self.mask, AnalysisMaterializeRequestMaskType0):
            mask = self.mask.to_dict()
        else:
            mask = self.mask

        mask_dataset_id: None | str | Unset
        if isinstance(self.mask_dataset_id, Unset):
            mask_dataset_id = UNSET
        elif isinstance(self.mask_dataset_id, UUID):
            mask_dataset_id = str(self.mask_dataset_id)
        else:
            mask_dataset_id = self.mask_dataset_id

        by_field: None | str | Unset
        if isinstance(self.by_field, Unset):
            by_field = UNSET
        else:
            by_field = self.by_field

        join_dataset_id: None | str | Unset
        if isinstance(self.join_dataset_id, Unset):
            join_dataset_id = UNSET
        elif isinstance(self.join_dataset_id, UUID):
            join_dataset_id = str(self.join_dataset_id)
        else:
            join_dataset_id = self.join_dataset_id

        join_fields: list[str] | None | Unset
        if isinstance(self.join_fields, Unset):
            join_fields = UNSET
        elif isinstance(self.join_fields, list):
            join_fields = self.join_fields

        else:
            join_fields = self.join_fields

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "operation": operation,
                "title": title,
            }
        )
        if distance_meters is not UNSET:
            field_dict["distance_meters"] = distance_meters
        if mask is not UNSET:
            field_dict["mask"] = mask
        if mask_dataset_id is not UNSET:
            field_dict["mask_dataset_id"] = mask_dataset_id
        if by_field is not UNSET:
            field_dict["by_field"] = by_field
        if join_dataset_id is not UNSET:
            field_dict["join_dataset_id"] = join_dataset_id
        if join_fields is not UNSET:
            field_dict["join_fields"] = join_fields

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.analysis_materialize_request_mask_type_0 import (
            AnalysisMaterializeRequestMaskType0,
        )

        d = dict(src_dict)
        operation = check_analysis_materialize_request_operation(d.pop("operation"))

        title = d.pop("title")

        def _parse_distance_meters(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        distance_meters = _parse_distance_meters(d.pop("distance_meters", UNSET))

        def _parse_mask(
            data: object,
        ) -> AnalysisMaterializeRequestMaskType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                mask_type_0 = AnalysisMaterializeRequestMaskType0.from_dict(data)

                return mask_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(AnalysisMaterializeRequestMaskType0 | None | Unset, data)

        mask = _parse_mask(d.pop("mask", UNSET))

        def _parse_mask_dataset_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                mask_dataset_id_type_0 = UUID(data)

                return mask_dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        mask_dataset_id = _parse_mask_dataset_id(d.pop("mask_dataset_id", UNSET))

        def _parse_by_field(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        by_field = _parse_by_field(d.pop("by_field", UNSET))

        def _parse_join_dataset_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                join_dataset_id_type_0 = UUID(data)

                return join_dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        join_dataset_id = _parse_join_dataset_id(d.pop("join_dataset_id", UNSET))

        def _parse_join_fields(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                join_fields_type_0 = cast(list[str], data)

                return join_fields_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        join_fields = _parse_join_fields(d.pop("join_fields", UNSET))

        analysis_materialize_request = cls(
            operation=operation,
            title=title,
            distance_meters=distance_meters,
            mask=mask,
            mask_dataset_id=mask_dataset_id,
            by_field=by_field,
            join_dataset_id=join_dataset_id,
            join_fields=join_fields,
        )

        analysis_materialize_request.additional_properties = d
        return analysis_materialize_request

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
