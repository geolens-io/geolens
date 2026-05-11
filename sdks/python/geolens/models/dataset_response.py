from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.collection_ref import CollectionRef
    from ..models.column_info import ColumnInfo
    from ..models.dataset_response_stac_assets_type_0 import (
        DatasetResponseStacAssetsType0,
    )
    from ..models.quality_detail import QualityDetail
    from ..models.raster_metadata import RasterMetadata


T = TypeVar("T", bound="DatasetResponse")


@_attrs_define
class DatasetResponse:
    """
    Attributes:
        created_at (datetime.datetime):
        created_by (None | UUID):
        created_by_display (str):
        feature_count (int | None):
        id (UUID):
        record_id (UUID): Parent catalog record UUID
        source_filename (None | str):
        summary (None | str):
        table_name (str): Internal PostGIS table name
        title (str):
        updated_at (datetime.datetime):
        visibility (str): Access level: private, restricted, internal, public
        access_constraints (None | str | Unset):
        collections (list[CollectionRef] | None | Unset):
        column_info (list[ColumnInfo] | None | Unset): Column names, types, and stats
        current_version (int | Unset): Monotonic version counter Default: 1.
        data_vintage_end (datetime.date | None | Unset): End of temporal coverage
        data_vintage_start (datetime.date | None | Unset): Start of temporal coverage
        extent_bbox (list[float] | None | Unset): Bounding box [minx, miny, maxx, maxy]
        geometry_type (None | str | Unset): OGC geometry type, e.g. MultiPolygon
        is_3d (bool | None | Unset): True if geometry has Z dimension
        language (None | str | Unset): ISO 639-1 language code, e.g. en, fr
        last_edited_at (datetime.datetime | None | Unset):
        last_edited_by_display (None | str | Unset):
        license_ (None | str | Unset):
        lineage_summary (None | str | Unset): Free-text provenance / lineage statement
        n_dims (int | None | Unset): Number of coordinate dimensions (2, 3, or 4)
        original_srid (int | None | Unset): EPSG SRID of the uploaded source file
        owner_org (None | str | Unset): Owning organization name
        published_at (datetime.datetime | None | Unset):
        quality_detail (None | QualityDetail | Unset): Automated quality assessment results
        quality_statement (None | str | Unset):
        raster (None | RasterMetadata | Unset): Raster-specific metadata (null for vectors)
        record_status (str | Unset): Lifecycle status: draft, ready, published Default: 'draft'.
        record_type (str | Unset): Record type: 'vector_dataset' (spatial features), 'raster_dataset' (single COG),
            'vrt_dataset' (VRT mosaic), 'table' (non-spatial tabular), 'map' (saved map), 'service' (catalogued remote
            service), 'collection' (flat dataset group). Default: 'vector_dataset'.
        sensitivity_classification (None | str | Unset): e.g. public, confidential, restricted
        source_format (None | str | Unset): Original file format, e.g. GPKG, SHP
        source_organization (None | str | Unset):
        source_url (None | str | Unset): URL the data was originally fetched from
        srid (int | None | Unset): Current EPSG SRID of stored geometry
        stac_assets (DatasetResponseStacAssetsType0 | None | Unset): STAC-style asset dictionary
        stac_extensions (list[str] | None | Unset):
        theme_category (list[str] | None | Unset): ISO topic category codes
        tile_columns (list[str] | None | Unset): Ordered vector-tile property allowlist; null uses zoom defaults, []
            emits geometry-only tiles, list emits those properties at any zoom.
        update_frequency (None | str | Unset): ISO maintenance frequency code
        updated_by (None | Unset | UUID):
        usage_constraints (None | str | Unset):
        z_max (float | None | Unset): Maximum Z value across all features
        z_min (float | None | Unset): Minimum Z value across all features
    """

    created_at: datetime.datetime
    created_by: None | UUID
    created_by_display: str
    feature_count: int | None
    id: UUID
    record_id: UUID
    source_filename: None | str
    summary: None | str
    table_name: str
    title: str
    updated_at: datetime.datetime
    visibility: str
    access_constraints: None | str | Unset = UNSET
    collections: list[CollectionRef] | None | Unset = UNSET
    column_info: list[ColumnInfo] | None | Unset = UNSET
    current_version: int | Unset = 1
    data_vintage_end: datetime.date | None | Unset = UNSET
    data_vintage_start: datetime.date | None | Unset = UNSET
    extent_bbox: list[float] | None | Unset = UNSET
    geometry_type: None | str | Unset = UNSET
    is_3d: bool | None | Unset = UNSET
    language: None | str | Unset = UNSET
    last_edited_at: datetime.datetime | None | Unset = UNSET
    last_edited_by_display: None | str | Unset = UNSET
    license_: None | str | Unset = UNSET
    lineage_summary: None | str | Unset = UNSET
    n_dims: int | None | Unset = UNSET
    original_srid: int | None | Unset = UNSET
    owner_org: None | str | Unset = UNSET
    published_at: datetime.datetime | None | Unset = UNSET
    quality_detail: None | QualityDetail | Unset = UNSET
    quality_statement: None | str | Unset = UNSET
    raster: None | RasterMetadata | Unset = UNSET
    record_status: str | Unset = "draft"
    record_type: str | Unset = "vector_dataset"
    sensitivity_classification: None | str | Unset = UNSET
    source_format: None | str | Unset = UNSET
    source_organization: None | str | Unset = UNSET
    source_url: None | str | Unset = UNSET
    srid: int | None | Unset = UNSET
    stac_assets: DatasetResponseStacAssetsType0 | None | Unset = UNSET
    stac_extensions: list[str] | None | Unset = UNSET
    theme_category: list[str] | None | Unset = UNSET
    tile_columns: list[str] | None | Unset = UNSET
    update_frequency: None | str | Unset = UNSET
    updated_by: None | Unset | UUID = UNSET
    usage_constraints: None | str | Unset = UNSET
    z_max: float | None | Unset = UNSET
    z_min: float | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.dataset_response_stac_assets_type_0 import (
            DatasetResponseStacAssetsType0,
        )
        from ..models.quality_detail import QualityDetail
        from ..models.raster_metadata import RasterMetadata

        created_at = self.created_at.isoformat()

        created_by: None | str
        if isinstance(self.created_by, UUID):
            created_by = str(self.created_by)
        else:
            created_by = self.created_by

        created_by_display = self.created_by_display

        feature_count: int | None
        feature_count = self.feature_count

        id = str(self.id)

        record_id = str(self.record_id)

        source_filename: None | str
        source_filename = self.source_filename

        summary: None | str
        summary = self.summary

        table_name = self.table_name

        title = self.title

        updated_at = self.updated_at.isoformat()

        visibility = self.visibility

        access_constraints: None | str | Unset
        if isinstance(self.access_constraints, Unset):
            access_constraints = UNSET
        else:
            access_constraints = self.access_constraints

        collections: list[dict[str, Any]] | None | Unset
        if isinstance(self.collections, Unset):
            collections = UNSET
        elif isinstance(self.collections, list):
            collections = []
            for collections_type_0_item_data in self.collections:
                collections_type_0_item = collections_type_0_item_data.to_dict()
                collections.append(collections_type_0_item)

        else:
            collections = self.collections

        column_info: list[dict[str, Any]] | None | Unset
        if isinstance(self.column_info, Unset):
            column_info = UNSET
        elif isinstance(self.column_info, list):
            column_info = []
            for column_info_type_0_item_data in self.column_info:
                column_info_type_0_item = column_info_type_0_item_data.to_dict()
                column_info.append(column_info_type_0_item)

        else:
            column_info = self.column_info

        current_version = self.current_version

        data_vintage_end: None | str | Unset
        if isinstance(self.data_vintage_end, Unset):
            data_vintage_end = UNSET
        elif isinstance(self.data_vintage_end, datetime.date):
            data_vintage_end = self.data_vintage_end.isoformat()
        else:
            data_vintage_end = self.data_vintage_end

        data_vintage_start: None | str | Unset
        if isinstance(self.data_vintage_start, Unset):
            data_vintage_start = UNSET
        elif isinstance(self.data_vintage_start, datetime.date):
            data_vintage_start = self.data_vintage_start.isoformat()
        else:
            data_vintage_start = self.data_vintage_start

        extent_bbox: list[float] | None | Unset
        if isinstance(self.extent_bbox, Unset):
            extent_bbox = UNSET
        elif isinstance(self.extent_bbox, list):
            extent_bbox = self.extent_bbox

        else:
            extent_bbox = self.extent_bbox

        geometry_type: None | str | Unset
        if isinstance(self.geometry_type, Unset):
            geometry_type = UNSET
        else:
            geometry_type = self.geometry_type

        is_3d: bool | None | Unset
        if isinstance(self.is_3d, Unset):
            is_3d = UNSET
        else:
            is_3d = self.is_3d

        language: None | str | Unset
        if isinstance(self.language, Unset):
            language = UNSET
        else:
            language = self.language

        last_edited_at: None | str | Unset
        if isinstance(self.last_edited_at, Unset):
            last_edited_at = UNSET
        elif isinstance(self.last_edited_at, datetime.datetime):
            last_edited_at = self.last_edited_at.isoformat()
        else:
            last_edited_at = self.last_edited_at

        last_edited_by_display: None | str | Unset
        if isinstance(self.last_edited_by_display, Unset):
            last_edited_by_display = UNSET
        else:
            last_edited_by_display = self.last_edited_by_display

        license_: None | str | Unset
        if isinstance(self.license_, Unset):
            license_ = UNSET
        else:
            license_ = self.license_

        lineage_summary: None | str | Unset
        if isinstance(self.lineage_summary, Unset):
            lineage_summary = UNSET
        else:
            lineage_summary = self.lineage_summary

        n_dims: int | None | Unset
        if isinstance(self.n_dims, Unset):
            n_dims = UNSET
        else:
            n_dims = self.n_dims

        original_srid: int | None | Unset
        if isinstance(self.original_srid, Unset):
            original_srid = UNSET
        else:
            original_srid = self.original_srid

        owner_org: None | str | Unset
        if isinstance(self.owner_org, Unset):
            owner_org = UNSET
        else:
            owner_org = self.owner_org

        published_at: None | str | Unset
        if isinstance(self.published_at, Unset):
            published_at = UNSET
        elif isinstance(self.published_at, datetime.datetime):
            published_at = self.published_at.isoformat()
        else:
            published_at = self.published_at

        quality_detail: dict[str, Any] | None | Unset
        if isinstance(self.quality_detail, Unset):
            quality_detail = UNSET
        elif isinstance(self.quality_detail, QualityDetail):
            quality_detail = self.quality_detail.to_dict()
        else:
            quality_detail = self.quality_detail

        quality_statement: None | str | Unset
        if isinstance(self.quality_statement, Unset):
            quality_statement = UNSET
        else:
            quality_statement = self.quality_statement

        raster: dict[str, Any] | None | Unset
        if isinstance(self.raster, Unset):
            raster = UNSET
        elif isinstance(self.raster, RasterMetadata):
            raster = self.raster.to_dict()
        else:
            raster = self.raster

        record_status = self.record_status

        record_type = self.record_type

        sensitivity_classification: None | str | Unset
        if isinstance(self.sensitivity_classification, Unset):
            sensitivity_classification = UNSET
        else:
            sensitivity_classification = self.sensitivity_classification

        source_format: None | str | Unset
        if isinstance(self.source_format, Unset):
            source_format = UNSET
        else:
            source_format = self.source_format

        source_organization: None | str | Unset
        if isinstance(self.source_organization, Unset):
            source_organization = UNSET
        else:
            source_organization = self.source_organization

        source_url: None | str | Unset
        if isinstance(self.source_url, Unset):
            source_url = UNSET
        else:
            source_url = self.source_url

        srid: int | None | Unset
        if isinstance(self.srid, Unset):
            srid = UNSET
        else:
            srid = self.srid

        stac_assets: dict[str, Any] | None | Unset
        if isinstance(self.stac_assets, Unset):
            stac_assets = UNSET
        elif isinstance(self.stac_assets, DatasetResponseStacAssetsType0):
            stac_assets = self.stac_assets.to_dict()
        else:
            stac_assets = self.stac_assets

        stac_extensions: list[str] | None | Unset
        if isinstance(self.stac_extensions, Unset):
            stac_extensions = UNSET
        elif isinstance(self.stac_extensions, list):
            stac_extensions = self.stac_extensions

        else:
            stac_extensions = self.stac_extensions

        theme_category: list[str] | None | Unset
        if isinstance(self.theme_category, Unset):
            theme_category = UNSET
        elif isinstance(self.theme_category, list):
            theme_category = self.theme_category

        else:
            theme_category = self.theme_category

        tile_columns: list[str] | None | Unset
        if isinstance(self.tile_columns, Unset):
            tile_columns = UNSET
        elif isinstance(self.tile_columns, list):
            tile_columns = self.tile_columns

        else:
            tile_columns = self.tile_columns

        update_frequency: None | str | Unset
        if isinstance(self.update_frequency, Unset):
            update_frequency = UNSET
        else:
            update_frequency = self.update_frequency

        updated_by: None | str | Unset
        if isinstance(self.updated_by, Unset):
            updated_by = UNSET
        elif isinstance(self.updated_by, UUID):
            updated_by = str(self.updated_by)
        else:
            updated_by = self.updated_by

        usage_constraints: None | str | Unset
        if isinstance(self.usage_constraints, Unset):
            usage_constraints = UNSET
        else:
            usage_constraints = self.usage_constraints

        z_max: float | None | Unset
        if isinstance(self.z_max, Unset):
            z_max = UNSET
        else:
            z_max = self.z_max

        z_min: float | None | Unset
        if isinstance(self.z_min, Unset):
            z_min = UNSET
        else:
            z_min = self.z_min

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "created_at": created_at,
                "created_by": created_by,
                "created_by_display": created_by_display,
                "feature_count": feature_count,
                "id": id,
                "record_id": record_id,
                "source_filename": source_filename,
                "summary": summary,
                "table_name": table_name,
                "title": title,
                "updated_at": updated_at,
                "visibility": visibility,
            }
        )
        if access_constraints is not UNSET:
            field_dict["access_constraints"] = access_constraints
        if collections is not UNSET:
            field_dict["collections"] = collections
        if column_info is not UNSET:
            field_dict["column_info"] = column_info
        if current_version is not UNSET:
            field_dict["current_version"] = current_version
        if data_vintage_end is not UNSET:
            field_dict["data_vintage_end"] = data_vintage_end
        if data_vintage_start is not UNSET:
            field_dict["data_vintage_start"] = data_vintage_start
        if extent_bbox is not UNSET:
            field_dict["extent_bbox"] = extent_bbox
        if geometry_type is not UNSET:
            field_dict["geometry_type"] = geometry_type
        if is_3d is not UNSET:
            field_dict["is_3d"] = is_3d
        if language is not UNSET:
            field_dict["language"] = language
        if last_edited_at is not UNSET:
            field_dict["last_edited_at"] = last_edited_at
        if last_edited_by_display is not UNSET:
            field_dict["last_edited_by_display"] = last_edited_by_display
        if license_ is not UNSET:
            field_dict["license"] = license_
        if lineage_summary is not UNSET:
            field_dict["lineage_summary"] = lineage_summary
        if n_dims is not UNSET:
            field_dict["n_dims"] = n_dims
        if original_srid is not UNSET:
            field_dict["original_srid"] = original_srid
        if owner_org is not UNSET:
            field_dict["owner_org"] = owner_org
        if published_at is not UNSET:
            field_dict["published_at"] = published_at
        if quality_detail is not UNSET:
            field_dict["quality_detail"] = quality_detail
        if quality_statement is not UNSET:
            field_dict["quality_statement"] = quality_statement
        if raster is not UNSET:
            field_dict["raster"] = raster
        if record_status is not UNSET:
            field_dict["record_status"] = record_status
        if record_type is not UNSET:
            field_dict["record_type"] = record_type
        if sensitivity_classification is not UNSET:
            field_dict["sensitivity_classification"] = sensitivity_classification
        if source_format is not UNSET:
            field_dict["source_format"] = source_format
        if source_organization is not UNSET:
            field_dict["source_organization"] = source_organization
        if source_url is not UNSET:
            field_dict["source_url"] = source_url
        if srid is not UNSET:
            field_dict["srid"] = srid
        if stac_assets is not UNSET:
            field_dict["stac_assets"] = stac_assets
        if stac_extensions is not UNSET:
            field_dict["stac_extensions"] = stac_extensions
        if theme_category is not UNSET:
            field_dict["theme_category"] = theme_category
        if tile_columns is not UNSET:
            field_dict["tile_columns"] = tile_columns
        if update_frequency is not UNSET:
            field_dict["update_frequency"] = update_frequency
        if updated_by is not UNSET:
            field_dict["updated_by"] = updated_by
        if usage_constraints is not UNSET:
            field_dict["usage_constraints"] = usage_constraints
        if z_max is not UNSET:
            field_dict["z_max"] = z_max
        if z_min is not UNSET:
            field_dict["z_min"] = z_min

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.collection_ref import CollectionRef
        from ..models.column_info import ColumnInfo
        from ..models.dataset_response_stac_assets_type_0 import (
            DatasetResponseStacAssetsType0,
        )
        from ..models.quality_detail import QualityDetail
        from ..models.raster_metadata import RasterMetadata

        d = dict(src_dict)
        created_at = isoparse(d.pop("created_at"))

        def _parse_created_by(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_by_type_0 = UUID(data)

                return created_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        created_by = _parse_created_by(d.pop("created_by"))

        created_by_display = d.pop("created_by_display")

        def _parse_feature_count(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        feature_count = _parse_feature_count(d.pop("feature_count"))

        id = UUID(d.pop("id"))

        record_id = UUID(d.pop("record_id"))

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        def _parse_summary(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        summary = _parse_summary(d.pop("summary"))

        table_name = d.pop("table_name")

        title = d.pop("title")

        updated_at = isoparse(d.pop("updated_at"))

        visibility = d.pop("visibility")

        def _parse_access_constraints(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        access_constraints = _parse_access_constraints(
            d.pop("access_constraints", UNSET)
        )

        def _parse_collections(data: object) -> list[CollectionRef] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                collections_type_0 = []
                _collections_type_0 = data
                for collections_type_0_item_data in _collections_type_0:
                    collections_type_0_item = CollectionRef.from_dict(
                        collections_type_0_item_data
                    )

                    collections_type_0.append(collections_type_0_item)

                return collections_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[CollectionRef] | None | Unset, data)

        collections = _parse_collections(d.pop("collections", UNSET))

        def _parse_column_info(data: object) -> list[ColumnInfo] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                column_info_type_0 = []
                _column_info_type_0 = data
                for column_info_type_0_item_data in _column_info_type_0:
                    column_info_type_0_item = ColumnInfo.from_dict(
                        column_info_type_0_item_data
                    )

                    column_info_type_0.append(column_info_type_0_item)

                return column_info_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ColumnInfo] | None | Unset, data)

        column_info = _parse_column_info(d.pop("column_info", UNSET))

        current_version = d.pop("current_version", UNSET)

        def _parse_data_vintage_end(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                data_vintage_end_type_0 = isoparse(data).date()

                return data_vintage_end_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        data_vintage_end = _parse_data_vintage_end(d.pop("data_vintage_end", UNSET))

        def _parse_data_vintage_start(data: object) -> datetime.date | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                data_vintage_start_type_0 = isoparse(data).date()

                return data_vintage_start_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.date | None | Unset, data)

        data_vintage_start = _parse_data_vintage_start(
            d.pop("data_vintage_start", UNSET)
        )

        def _parse_extent_bbox(data: object) -> list[float] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                extent_bbox_type_0 = cast(list[float], data)

                return extent_bbox_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[float] | None | Unset, data)

        extent_bbox = _parse_extent_bbox(d.pop("extent_bbox", UNSET))

        def _parse_geometry_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type", UNSET))

        def _parse_is_3d(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_3d = _parse_is_3d(d.pop("is_3d", UNSET))

        def _parse_language(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        language = _parse_language(d.pop("language", UNSET))

        def _parse_last_edited_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_edited_at_type_0 = isoparse(data)

                return last_edited_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_edited_at = _parse_last_edited_at(d.pop("last_edited_at", UNSET))

        def _parse_last_edited_by_display(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        last_edited_by_display = _parse_last_edited_by_display(
            d.pop("last_edited_by_display", UNSET)
        )

        def _parse_license_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        license_ = _parse_license_(d.pop("license", UNSET))

        def _parse_lineage_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lineage_summary = _parse_lineage_summary(d.pop("lineage_summary", UNSET))

        def _parse_n_dims(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        n_dims = _parse_n_dims(d.pop("n_dims", UNSET))

        def _parse_original_srid(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        original_srid = _parse_original_srid(d.pop("original_srid", UNSET))

        def _parse_owner_org(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        owner_org = _parse_owner_org(d.pop("owner_org", UNSET))

        def _parse_published_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                published_at_type_0 = isoparse(data)

                return published_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        published_at = _parse_published_at(d.pop("published_at", UNSET))

        def _parse_quality_detail(data: object) -> None | QualityDetail | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                quality_detail_type_0 = QualityDetail.from_dict(data)

                return quality_detail_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | QualityDetail | Unset, data)

        quality_detail = _parse_quality_detail(d.pop("quality_detail", UNSET))

        def _parse_quality_statement(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        quality_statement = _parse_quality_statement(d.pop("quality_statement", UNSET))

        def _parse_raster(data: object) -> None | RasterMetadata | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                raster_type_0 = RasterMetadata.from_dict(data)

                return raster_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | RasterMetadata | Unset, data)

        raster = _parse_raster(d.pop("raster", UNSET))

        record_status = d.pop("record_status", UNSET)

        record_type = d.pop("record_type", UNSET)

        def _parse_sensitivity_classification(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sensitivity_classification = _parse_sensitivity_classification(
            d.pop("sensitivity_classification", UNSET)
        )

        def _parse_source_format(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_format = _parse_source_format(d.pop("source_format", UNSET))

        def _parse_source_organization(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_organization = _parse_source_organization(
            d.pop("source_organization", UNSET)
        )

        def _parse_source_url(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_url = _parse_source_url(d.pop("source_url", UNSET))

        def _parse_srid(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        srid = _parse_srid(d.pop("srid", UNSET))

        def _parse_stac_assets(
            data: object,
        ) -> DatasetResponseStacAssetsType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                stac_assets_type_0 = DatasetResponseStacAssetsType0.from_dict(data)

                return stac_assets_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DatasetResponseStacAssetsType0 | None | Unset, data)

        stac_assets = _parse_stac_assets(d.pop("stac_assets", UNSET))

        def _parse_stac_extensions(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                stac_extensions_type_0 = cast(list[str], data)

                return stac_extensions_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        stac_extensions = _parse_stac_extensions(d.pop("stac_extensions", UNSET))

        def _parse_theme_category(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                theme_category_type_0 = cast(list[str], data)

                return theme_category_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        theme_category = _parse_theme_category(d.pop("theme_category", UNSET))

        def _parse_tile_columns(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                tile_columns_type_0 = cast(list[str], data)

                return tile_columns_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        tile_columns = _parse_tile_columns(d.pop("tile_columns", UNSET))

        def _parse_update_frequency(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        update_frequency = _parse_update_frequency(d.pop("update_frequency", UNSET))

        def _parse_updated_by(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                updated_by_type_0 = UUID(data)

                return updated_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        updated_by = _parse_updated_by(d.pop("updated_by", UNSET))

        def _parse_usage_constraints(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        usage_constraints = _parse_usage_constraints(d.pop("usage_constraints", UNSET))

        def _parse_z_max(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        z_max = _parse_z_max(d.pop("z_max", UNSET))

        def _parse_z_min(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        z_min = _parse_z_min(d.pop("z_min", UNSET))

        dataset_response = cls(
            created_at=created_at,
            created_by=created_by,
            created_by_display=created_by_display,
            feature_count=feature_count,
            id=id,
            record_id=record_id,
            source_filename=source_filename,
            summary=summary,
            table_name=table_name,
            title=title,
            updated_at=updated_at,
            visibility=visibility,
            access_constraints=access_constraints,
            collections=collections,
            column_info=column_info,
            current_version=current_version,
            data_vintage_end=data_vintage_end,
            data_vintage_start=data_vintage_start,
            extent_bbox=extent_bbox,
            geometry_type=geometry_type,
            is_3d=is_3d,
            language=language,
            last_edited_at=last_edited_at,
            last_edited_by_display=last_edited_by_display,
            license_=license_,
            lineage_summary=lineage_summary,
            n_dims=n_dims,
            original_srid=original_srid,
            owner_org=owner_org,
            published_at=published_at,
            quality_detail=quality_detail,
            quality_statement=quality_statement,
            raster=raster,
            record_status=record_status,
            record_type=record_type,
            sensitivity_classification=sensitivity_classification,
            source_format=source_format,
            source_organization=source_organization,
            source_url=source_url,
            srid=srid,
            stac_assets=stac_assets,
            stac_extensions=stac_extensions,
            theme_category=theme_category,
            tile_columns=tile_columns,
            update_frequency=update_frequency,
            updated_by=updated_by,
            usage_constraints=usage_constraints,
            z_max=z_max,
            z_min=z_min,
        )

        dataset_response.additional_properties = d
        return dataset_response

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
