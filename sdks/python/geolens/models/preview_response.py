from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.column_preview import ColumnPreview
    from ..models.layer_preview import LayerPreview
    from ..models.preview_response_detected_geometry_columns_type_0 import (
        PreviewResponseDetectedGeometryColumnsType0,
    )
    from ..models.preview_response_sample_rows_item import PreviewResponseSampleRowsItem


T = TypeVar("T", bound="PreviewResponse")


@_attrs_define
class PreviewResponse:
    """
    Attributes:
        columns (list[ColumnPreview]): Detected attribute columns. Each entry includes name, type, and nullability.
        crs (int | None): Detected coordinate reference system EPSG code, or null if undetermined.
        feature_count (int | None): Total number of features in the source file, if known.
        geometry_type (None | str): Detected geometry type (Point, LineString, Polygon, MultiPolygon, etc.), or null for
            non-spatial data.
        job_id (UUID): Identifier of the ingestion job being previewed.
        layer_name (str): Name of the layer being previewed. Defaults to the source filename for single-layer files.
        sample_rows (list[PreviewResponseSampleRowsItem]): Up to 5 sample rows from the source file for preview
            purposes.
        source_filename (None | str): Original filename of the uploaded file, if known.
        detected_geometry_columns (None | PreviewResponseDetectedGeometryColumnsType0 | Unset): Auto-detected lat/lon or
            geometry columns for CSV/Excel sources. Null for native geospatial formats.
        layers (list[LayerPreview] | None | Unset): List of all layers in multi-layer sources (e.g. GeoPackage). Null
            for single-layer files.
    """

    columns: list[ColumnPreview]
    crs: int | None
    feature_count: int | None
    geometry_type: None | str
    job_id: UUID
    layer_name: str
    sample_rows: list[PreviewResponseSampleRowsItem]
    source_filename: None | str
    detected_geometry_columns: (
        None | PreviewResponseDetectedGeometryColumnsType0 | Unset
    ) = UNSET
    layers: list[LayerPreview] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.preview_response_detected_geometry_columns_type_0 import (
            PreviewResponseDetectedGeometryColumnsType0,
        )

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

        source_filename: None | str
        source_filename = self.source_filename

        detected_geometry_columns: dict[str, Any] | None | Unset
        if isinstance(self.detected_geometry_columns, Unset):
            detected_geometry_columns = UNSET
        elif isinstance(
            self.detected_geometry_columns, PreviewResponseDetectedGeometryColumnsType0
        ):
            detected_geometry_columns = self.detected_geometry_columns.to_dict()
        else:
            detected_geometry_columns = self.detected_geometry_columns

        layers: list[dict[str, Any]] | None | Unset
        if isinstance(self.layers, Unset):
            layers = UNSET
        elif isinstance(self.layers, list):
            layers = []
            for layers_type_0_item_data in self.layers:
                layers_type_0_item = layers_type_0_item_data.to_dict()
                layers.append(layers_type_0_item)

        else:
            layers = self.layers

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
                "source_filename": source_filename,
            }
        )
        if detected_geometry_columns is not UNSET:
            field_dict["detected_geometry_columns"] = detected_geometry_columns
        if layers is not UNSET:
            field_dict["layers"] = layers

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_preview import ColumnPreview
        from ..models.layer_preview import LayerPreview
        from ..models.preview_response_detected_geometry_columns_type_0 import (
            PreviewResponseDetectedGeometryColumnsType0,
        )
        from ..models.preview_response_sample_rows_item import (
            PreviewResponseSampleRowsItem,
        )

        d = dict(src_dict)
        columns = []
        _columns = d.pop("columns")
        for columns_item_data in _columns:
            columns_item = ColumnPreview.from_dict(columns_item_data)

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
            sample_rows_item = PreviewResponseSampleRowsItem.from_dict(
                sample_rows_item_data
            )

            sample_rows.append(sample_rows_item)

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        def _parse_detected_geometry_columns(
            data: object,
        ) -> None | PreviewResponseDetectedGeometryColumnsType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                detected_geometry_columns_type_0 = (
                    PreviewResponseDetectedGeometryColumnsType0.from_dict(data)
                )

                return detected_geometry_columns_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                None | PreviewResponseDetectedGeometryColumnsType0 | Unset, data
            )

        detected_geometry_columns = _parse_detected_geometry_columns(
            d.pop("detected_geometry_columns", UNSET)
        )

        def _parse_layers(data: object) -> list[LayerPreview] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                layers_type_0 = []
                _layers_type_0 = data
                for layers_type_0_item_data in _layers_type_0:
                    layers_type_0_item = LayerPreview.from_dict(layers_type_0_item_data)

                    layers_type_0.append(layers_type_0_item)

                return layers_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[LayerPreview] | None | Unset, data)

        layers = _parse_layers(d.pop("layers", UNSET))

        preview_response = cls(
            columns=columns,
            crs=crs,
            feature_count=feature_count,
            geometry_type=geometry_type,
            job_id=job_id,
            layer_name=layer_name,
            sample_rows=sample_rows,
            source_filename=source_filename,
            detected_geometry_columns=detected_geometry_columns,
            layers=layers,
        )

        preview_response.additional_properties = d
        return preview_response

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
