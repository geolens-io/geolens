from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.column_change import ColumnChange
    from ..models.reupload_preview_response_sample_rows_item import (
        ReuploadPreviewResponseSampleRowsItem,
    )
    from ..models.schema_diff import SchemaDiff


T = TypeVar("T", bound="ReuploadPreviewResponse")


@_attrs_define
class ReuploadPreviewResponse:
    """
    Attributes:
        columns (list[ColumnChange]):
        crs (int | None):
        feature_count (int | None):
        geometry_type (None | str):
        job_id (UUID):
        layer_name (str):
        sample_rows (list[ReuploadPreviewResponseSampleRowsItem]):
        schema_diff (SchemaDiff):
        source_filename (None | str):
    """

    columns: list[ColumnChange]
    crs: int | None
    feature_count: int | None
    geometry_type: None | str
    job_id: UUID
    layer_name: str
    sample_rows: list[ReuploadPreviewResponseSampleRowsItem]
    schema_diff: SchemaDiff
    source_filename: None | str
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        columns = []
        for columns_item_data in self.columns:
            columns_item = columns_item_data.to_dict()
            columns.append(columns_item)

        crs: int | None
        crs = self.crs

        feature_count: int | None
        feature_count = self.feature_count

        geometry_type: None | str
        geometry_type = self.geometry_type

        job_id = str(self.job_id)

        layer_name = self.layer_name

        sample_rows = []
        for sample_rows_item_data in self.sample_rows:
            sample_rows_item = sample_rows_item_data.to_dict()
            sample_rows.append(sample_rows_item)

        schema_diff = self.schema_diff.to_dict()

        source_filename: None | str
        source_filename = self.source_filename

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "columns": columns,
                "crs": crs,
                "feature_count": feature_count,
                "geometry_type": geometry_type,
                "job_id": job_id,
                "layer_name": layer_name,
                "sample_rows": sample_rows,
                "schema_diff": schema_diff,
                "source_filename": source_filename,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_change import ColumnChange
        from ..models.reupload_preview_response_sample_rows_item import (
            ReuploadPreviewResponseSampleRowsItem,
        )
        from ..models.schema_diff import SchemaDiff

        d = dict(src_dict)
        columns = []
        _columns = d.pop("columns")
        for columns_item_data in _columns:
            columns_item = ColumnChange.from_dict(columns_item_data)

            columns.append(columns_item)

        def _parse_crs(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        crs = _parse_crs(d.pop("crs"))

        def _parse_feature_count(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        feature_count = _parse_feature_count(d.pop("feature_count"))

        def _parse_geometry_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type"))

        job_id = UUID(d.pop("job_id"))

        layer_name = d.pop("layer_name")

        sample_rows = []
        _sample_rows = d.pop("sample_rows")
        for sample_rows_item_data in _sample_rows:
            sample_rows_item = ReuploadPreviewResponseSampleRowsItem.from_dict(
                sample_rows_item_data
            )

            sample_rows.append(sample_rows_item)

        schema_diff = SchemaDiff.from_dict(d.pop("schema_diff"))

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        reupload_preview_response = cls(
            columns=columns,
            crs=crs,
            feature_count=feature_count,
            geometry_type=geometry_type,
            job_id=job_id,
            layer_name=layer_name,
            sample_rows=sample_rows,
            schema_diff=schema_diff,
            source_filename=source_filename,
        )

        reupload_preview_response.additional_properties = d
        return reupload_preview_response

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
