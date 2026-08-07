from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.service_preview_response_columns_item import (
        ServicePreviewResponseColumnsItem,
    )
    from ..models.service_preview_response_sample_rows_item import (
        ServicePreviewResponseSampleRowsItem,
    )


T = TypeVar("T", bound="ServicePreviewResponse")


@_attrs_define
class ServicePreviewResponse:
    """
    Attributes:
        job_id (UUID): IngestJob ID for the preview. Use this to commit the import.
        source_filename (None | str): Layer name acting as a source filename for downstream ingestion logic.
        columns (list[ServicePreviewResponseColumnsItem]): Detected attribute columns: [{'name': str, 'type': str},
            ...].
        crs (int | None): Detected EPSG code for the layer's CRS.
        geometry_type (None | str): Detected geometry type.
        feature_count (int | None): Total feature count if reported by the source service.
        sample_rows (list[ServicePreviewResponseSampleRowsItem]): Up to 5 sample rows for preview display.
        layer_name (str): Layer name as it appears in the remote service.
    """

    job_id: UUID
    source_filename: None | str
    columns: list[ServicePreviewResponseColumnsItem]
    crs: int | None
    geometry_type: None | str
    feature_count: int | None
    sample_rows: list[ServicePreviewResponseSampleRowsItem]
    layer_name: str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        job_id = str(self.job_id)

        source_filename: None | str
        source_filename = self.source_filename

        columns = []
        for columns_item_data in self.columns:
            columns_item = columns_item_data.to_dict()
            columns.append(columns_item)

        crs: int | None
        crs = self.crs

        geometry_type: None | str
        geometry_type = self.geometry_type

        feature_count: int | None
        feature_count = self.feature_count

        sample_rows = []
        for sample_rows_item_data in self.sample_rows:
            sample_rows_item = sample_rows_item_data.to_dict()
            sample_rows.append(sample_rows_item)

        layer_name = self.layer_name

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "job_id": job_id,
                "source_filename": source_filename,
                "columns": columns,
                "crs": crs,
                "geometry_type": geometry_type,
                "feature_count": feature_count,
                "sample_rows": sample_rows,
                "layer_name": layer_name,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.service_preview_response_columns_item import (
            ServicePreviewResponseColumnsItem,
        )
        from ..models.service_preview_response_sample_rows_item import (
            ServicePreviewResponseSampleRowsItem,
        )

        d = dict(src_dict)
        job_id = UUID(d.pop("job_id"))

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        columns = []
        _columns = d.pop("columns")
        for columns_item_data in _columns:
            columns_item = ServicePreviewResponseColumnsItem.from_dict(
                columns_item_data
            )

            columns.append(columns_item)

        def _parse_crs(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        crs = _parse_crs(d.pop("crs"))

        def _parse_geometry_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type"))

        def _parse_feature_count(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        feature_count = _parse_feature_count(d.pop("feature_count"))

        sample_rows = []
        _sample_rows = d.pop("sample_rows")
        for sample_rows_item_data in _sample_rows:
            sample_rows_item = ServicePreviewResponseSampleRowsItem.from_dict(
                sample_rows_item_data
            )

            sample_rows.append(sample_rows_item)

        layer_name = d.pop("layer_name")

        service_preview_response = cls(
            job_id=job_id,
            source_filename=source_filename,
            columns=columns,
            crs=crs,
            geometry_type=geometry_type,
            feature_count=feature_count,
            sample_rows=sample_rows,
            layer_name=layer_name,
        )

        service_preview_response.additional_properties = d
        return service_preview_response

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
