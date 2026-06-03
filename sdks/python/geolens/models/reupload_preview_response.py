from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID

if TYPE_CHECKING:
    from ..models.column_change import ColumnChange
    from ..models.reupload_preview_response_all_layers_type_0_item import (
        ReuploadPreviewResponseAllLayersType0Item,
    )
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
        all_layers (list[ReuploadPreviewResponseAllLayersType0Item] | None | Unset):
        previous_source_layer (None | str | Unset):
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
    all_layers: list[ReuploadPreviewResponseAllLayersType0Item] | None | Unset = UNSET
    previous_source_layer: None | str | Unset = UNSET
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

        all_layers: list[dict[str, Any]] | None | Unset
        if isinstance(self.all_layers, Unset):
            all_layers = UNSET
        elif isinstance(self.all_layers, list):
            all_layers = []
            for all_layers_type_0_item_data in self.all_layers:
                all_layers_type_0_item = all_layers_type_0_item_data.to_dict()
                all_layers.append(all_layers_type_0_item)

        else:
            all_layers = self.all_layers

        previous_source_layer: None | str | Unset
        if isinstance(self.previous_source_layer, Unset):
            previous_source_layer = UNSET
        else:
            previous_source_layer = self.previous_source_layer

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
        if all_layers is not UNSET:
            field_dict["all_layers"] = all_layers
        if previous_source_layer is not UNSET:
            field_dict["previous_source_layer"] = previous_source_layer

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.column_change import ColumnChange
        from ..models.reupload_preview_response_all_layers_type_0_item import (
            ReuploadPreviewResponseAllLayersType0Item,
        )
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

        def _parse_all_layers(
            data: object,
        ) -> list[ReuploadPreviewResponseAllLayersType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                all_layers_type_0 = []
                _all_layers_type_0 = data
                for all_layers_type_0_item_data in _all_layers_type_0:
                    all_layers_type_0_item = (
                        ReuploadPreviewResponseAllLayersType0Item.from_dict(
                            all_layers_type_0_item_data
                        )
                    )

                    all_layers_type_0.append(all_layers_type_0_item)

                return all_layers_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                list[ReuploadPreviewResponseAllLayersType0Item] | None | Unset, data
            )

        all_layers = _parse_all_layers(d.pop("all_layers", UNSET))

        def _parse_previous_source_layer(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        previous_source_layer = _parse_previous_source_layer(
            d.pop("previous_source_layer", UNSET)
        )

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
            all_layers=all_layers,
            previous_source_layer=previous_source_layer,
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
