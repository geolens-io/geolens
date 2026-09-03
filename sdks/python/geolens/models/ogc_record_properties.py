from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
import datetime

if TYPE_CHECKING:
    from ..models.ogc_raster_band import OGCRasterBand
    from ..models.ogc_record_properties_constraints_type_0 import (
        OGCRecordPropertiesConstraintsType0,
    )
    from ..models.ogc_record_properties_contacts_item import (
        OGCRecordPropertiesContactsItem,
    )
    from ..models.ogc_record_properties_distributions_type_0_item import (
        OGCRecordPropertiesDistributionsType0Item,
    )
    from ..models.ogc_record_properties_quality_detail_type_0 import (
        OGCRecordPropertiesQualityDetailType0,
    )
    from ..models.ogc_record_properties_themes_item import OGCRecordPropertiesThemesItem
    from ..models.ogc_record_properties_time import OGCRecordPropertiesTime


T = TypeVar("T", bound="OGCRecordProperties")


@_attrs_define
class OGCRecordProperties:
    """Properties block of an OGC API Records Feature.

    Attributes:
        title (str):
        description (str):
        keywords (list[str]):
        license_ (str):
        themes (list[OGCRecordPropertiesThemesItem]):
        contacts (list[OGCRecordPropertiesContactsItem]):
        time (OGCRecordPropertiesTime):
        type_ (str | Unset):  Default: 'dataset'.
        created (datetime.datetime | None | Unset):
        updated (datetime.datetime | None | Unset):
        updated_by_display (None | str | Unset):
        never_edited (bool | Unset):  Default: False.
        crs (None | str | Unset):
        record_type (str | Unset):  Default: 'vector_dataset'.
        band_count (int | None | Unset):
        geometry_type (None | str | Unset):
        feature_count (int | None | Unset):
        row_count (int | None | Unset): Row count for tabular records (alias for feature_count when
            record_type='table').
        column_count (int | None | Unset): Number of columns in the dataset (populated from column_info length).
        source_organization (None | str | Unset):
        source_format (None | str | Unset): Ingest source format ('geojson', 'shapefile', 'geotiff', 'wfs', 'stac',
            'created', ...). Null for datasets registered from existing PostGIS tables and for composed VRT datasets.
        quality_detail (None | OGCRecordPropertiesQualityDetailType0 | Unset):
        quality_statement (None | str | Unset):
        formats (list[str] | None | Unset):
        language (None | str | Unset):
        external_ids (list[str] | Unset): Identifiers assigned by the described resource's source system.
        rights (None | str | Unset):
        lineage (None | str | Unset):
        update_frequency (None | str | Unset):
        source_freshness (str | Unset): fresh, due, overdue, or unknown — how the dataset's last refresh compares to its
            declared update_frequency. 'unknown' for origins nothing can refresh. Advisory only, and distinct from the
            quality score's own freshness. Default: 'unknown'.
        source_health (str | Unset): healthy, missing, inaccessible, or unknown. 'unknown' means never probed, or an
            origin kind with nothing to probe. Default: 'unknown'.
        last_checked_at (datetime.datetime | None | Unset): Last time GeoLens contacted the origin, whether the attempt
            succeeded or failed.
        last_refreshed_at (datetime.datetime | None | Unset): Last committed successful refresh — not the last attempt.
        constraints (None | OGCRecordPropertiesConstraintsType0 | Unset):
        distributions (list[OGCRecordPropertiesDistributionsType0Item] | None | Unset):
        record_status (None | str | Unset):
        has_quicklook (bool | Unset):  Default: False.
        gsd (float | None | Unset):
        crs_is_geographic (bool | None | Unset): True when the raster CRS is geographic (gsd/res are degrees, not
            meters); None when the CRS class is unknown.
        vrt_type (None | str | Unset):
        source_count (int | None | Unset):
        dataset_count (int | None | Unset):
        projcode (None | str | Unset):
        projshape (list[int] | None | Unset): [height, width] in pixels.
        rasterbands (list[OGCRasterBand] | None | Unset):
    """

    title: str
    description: str
    keywords: list[str]
    license_: str
    themes: list[OGCRecordPropertiesThemesItem]
    contacts: list[OGCRecordPropertiesContactsItem]
    time: OGCRecordPropertiesTime
    type_: str | Unset = "dataset"
    created: datetime.datetime | None | Unset = UNSET
    updated: datetime.datetime | None | Unset = UNSET
    updated_by_display: None | str | Unset = UNSET
    never_edited: bool | Unset = False
    crs: None | str | Unset = UNSET
    record_type: str | Unset = "vector_dataset"
    band_count: int | None | Unset = UNSET
    geometry_type: None | str | Unset = UNSET
    feature_count: int | None | Unset = UNSET
    row_count: int | None | Unset = UNSET
    column_count: int | None | Unset = UNSET
    source_organization: None | str | Unset = UNSET
    source_format: None | str | Unset = UNSET
    quality_detail: None | OGCRecordPropertiesQualityDetailType0 | Unset = UNSET
    quality_statement: None | str | Unset = UNSET
    formats: list[str] | None | Unset = UNSET
    language: None | str | Unset = UNSET
    external_ids: list[str] | Unset = UNSET
    rights: None | str | Unset = UNSET
    lineage: None | str | Unset = UNSET
    update_frequency: None | str | Unset = UNSET
    source_freshness: str | Unset = "unknown"
    source_health: str | Unset = "unknown"
    last_checked_at: datetime.datetime | None | Unset = UNSET
    last_refreshed_at: datetime.datetime | None | Unset = UNSET
    constraints: None | OGCRecordPropertiesConstraintsType0 | Unset = UNSET
    distributions: list[OGCRecordPropertiesDistributionsType0Item] | None | Unset = (
        UNSET
    )
    record_status: None | str | Unset = UNSET
    has_quicklook: bool | Unset = False
    gsd: float | None | Unset = UNSET
    crs_is_geographic: bool | None | Unset = UNSET
    vrt_type: None | str | Unset = UNSET
    source_count: int | None | Unset = UNSET
    dataset_count: int | None | Unset = UNSET
    projcode: None | str | Unset = UNSET
    projshape: list[int] | None | Unset = UNSET
    rasterbands: list[OGCRasterBand] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.ogc_record_properties_constraints_type_0 import (
            OGCRecordPropertiesConstraintsType0,
        )
        from ..models.ogc_record_properties_quality_detail_type_0 import (
            OGCRecordPropertiesQualityDetailType0,
        )

        title = self.title

        description = self.description

        keywords = self.keywords

        license_ = self.license_

        themes = []
        for themes_item_data in self.themes:
            themes_item = themes_item_data.to_dict()
            themes.append(themes_item)

        contacts = []
        for contacts_item_data in self.contacts:
            contacts_item = contacts_item_data.to_dict()
            contacts.append(contacts_item)

        time = self.time.to_dict()

        type_ = self.type_

        created: None | str | Unset
        if isinstance(self.created, Unset):
            created = UNSET
        elif isinstance(self.created, datetime.datetime):
            created = self.created.isoformat()
        else:
            created = self.created

        updated: None | str | Unset
        if isinstance(self.updated, Unset):
            updated = UNSET
        elif isinstance(self.updated, datetime.datetime):
            updated = self.updated.isoformat()
        else:
            updated = self.updated

        updated_by_display: None | str | Unset
        if isinstance(self.updated_by_display, Unset):
            updated_by_display = UNSET
        else:
            updated_by_display = self.updated_by_display

        never_edited = self.never_edited

        crs: None | str | Unset
        if isinstance(self.crs, Unset):
            crs = UNSET
        else:
            crs = self.crs

        record_type = self.record_type

        band_count: int | None | Unset
        if isinstance(self.band_count, Unset):
            band_count = UNSET
        else:
            band_count = self.band_count

        geometry_type: None | str | Unset
        if isinstance(self.geometry_type, Unset):
            geometry_type = UNSET
        else:
            geometry_type = self.geometry_type

        feature_count: int | None | Unset
        if isinstance(self.feature_count, Unset):
            feature_count = UNSET
        else:
            feature_count = self.feature_count

        row_count: int | None | Unset
        if isinstance(self.row_count, Unset):
            row_count = UNSET
        else:
            row_count = self.row_count

        column_count: int | None | Unset
        if isinstance(self.column_count, Unset):
            column_count = UNSET
        else:
            column_count = self.column_count

        source_organization: None | str | Unset
        if isinstance(self.source_organization, Unset):
            source_organization = UNSET
        else:
            source_organization = self.source_organization

        source_format: None | str | Unset
        if isinstance(self.source_format, Unset):
            source_format = UNSET
        else:
            source_format = self.source_format

        quality_detail: dict[str, Any] | None | Unset
        if isinstance(self.quality_detail, Unset):
            quality_detail = UNSET
        elif isinstance(self.quality_detail, OGCRecordPropertiesQualityDetailType0):
            quality_detail = self.quality_detail.to_dict()
        else:
            quality_detail = self.quality_detail

        quality_statement: None | str | Unset
        if isinstance(self.quality_statement, Unset):
            quality_statement = UNSET
        else:
            quality_statement = self.quality_statement

        formats: list[str] | None | Unset
        if isinstance(self.formats, Unset):
            formats = UNSET
        elif isinstance(self.formats, list):
            formats = self.formats

        else:
            formats = self.formats

        language: None | str | Unset
        if isinstance(self.language, Unset):
            language = UNSET
        else:
            language = self.language

        external_ids: list[str] | Unset = UNSET
        if not isinstance(self.external_ids, Unset):
            external_ids = self.external_ids

        rights: None | str | Unset
        if isinstance(self.rights, Unset):
            rights = UNSET
        else:
            rights = self.rights

        lineage: None | str | Unset
        if isinstance(self.lineage, Unset):
            lineage = UNSET
        else:
            lineage = self.lineage

        update_frequency: None | str | Unset
        if isinstance(self.update_frequency, Unset):
            update_frequency = UNSET
        else:
            update_frequency = self.update_frequency

        source_freshness = self.source_freshness

        source_health = self.source_health

        last_checked_at: None | str | Unset
        if isinstance(self.last_checked_at, Unset):
            last_checked_at = UNSET
        elif isinstance(self.last_checked_at, datetime.datetime):
            last_checked_at = self.last_checked_at.isoformat()
        else:
            last_checked_at = self.last_checked_at

        last_refreshed_at: None | str | Unset
        if isinstance(self.last_refreshed_at, Unset):
            last_refreshed_at = UNSET
        elif isinstance(self.last_refreshed_at, datetime.datetime):
            last_refreshed_at = self.last_refreshed_at.isoformat()
        else:
            last_refreshed_at = self.last_refreshed_at

        constraints: dict[str, Any] | None | Unset
        if isinstance(self.constraints, Unset):
            constraints = UNSET
        elif isinstance(self.constraints, OGCRecordPropertiesConstraintsType0):
            constraints = self.constraints.to_dict()
        else:
            constraints = self.constraints

        distributions: list[dict[str, Any]] | None | Unset
        if isinstance(self.distributions, Unset):
            distributions = UNSET
        elif isinstance(self.distributions, list):
            distributions = []
            for distributions_type_0_item_data in self.distributions:
                distributions_type_0_item = distributions_type_0_item_data.to_dict()
                distributions.append(distributions_type_0_item)

        else:
            distributions = self.distributions

        record_status: None | str | Unset
        if isinstance(self.record_status, Unset):
            record_status = UNSET
        else:
            record_status = self.record_status

        has_quicklook = self.has_quicklook

        gsd: float | None | Unset
        if isinstance(self.gsd, Unset):
            gsd = UNSET
        else:
            gsd = self.gsd

        crs_is_geographic: bool | None | Unset
        if isinstance(self.crs_is_geographic, Unset):
            crs_is_geographic = UNSET
        else:
            crs_is_geographic = self.crs_is_geographic

        vrt_type: None | str | Unset
        if isinstance(self.vrt_type, Unset):
            vrt_type = UNSET
        else:
            vrt_type = self.vrt_type

        source_count: int | None | Unset
        if isinstance(self.source_count, Unset):
            source_count = UNSET
        else:
            source_count = self.source_count

        dataset_count: int | None | Unset
        if isinstance(self.dataset_count, Unset):
            dataset_count = UNSET
        else:
            dataset_count = self.dataset_count

        projcode: None | str | Unset
        if isinstance(self.projcode, Unset):
            projcode = UNSET
        else:
            projcode = self.projcode

        projshape: list[int] | None | Unset
        if isinstance(self.projshape, Unset):
            projshape = UNSET
        elif isinstance(self.projshape, list):
            projshape = []
            for projshape_type_0_item_data in self.projshape:
                projshape_type_0_item: int
                projshape_type_0_item = projshape_type_0_item_data
                projshape.append(projshape_type_0_item)

        else:
            projshape = self.projshape

        rasterbands: list[dict[str, Any]] | None | Unset
        if isinstance(self.rasterbands, Unset):
            rasterbands = UNSET
        elif isinstance(self.rasterbands, list):
            rasterbands = []
            for rasterbands_type_0_item_data in self.rasterbands:
                rasterbands_type_0_item = rasterbands_type_0_item_data.to_dict()
                rasterbands.append(rasterbands_type_0_item)

        else:
            rasterbands = self.rasterbands

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "title": title,
                "description": description,
                "keywords": keywords,
                "license": license_,
                "themes": themes,
                "contacts": contacts,
                "time": time,
            }
        )
        if type_ is not UNSET:
            field_dict["type"] = type_
        if created is not UNSET:
            field_dict["created"] = created
        if updated is not UNSET:
            field_dict["updated"] = updated
        if updated_by_display is not UNSET:
            field_dict["updated_by_display"] = updated_by_display
        if never_edited is not UNSET:
            field_dict["never_edited"] = never_edited
        if crs is not UNSET:
            field_dict["crs"] = crs
        if record_type is not UNSET:
            field_dict["record_type"] = record_type
        if band_count is not UNSET:
            field_dict["band_count"] = band_count
        if geometry_type is not UNSET:
            field_dict["geometry_type"] = geometry_type
        if feature_count is not UNSET:
            field_dict["feature_count"] = feature_count
        if row_count is not UNSET:
            field_dict["row_count"] = row_count
        if column_count is not UNSET:
            field_dict["column_count"] = column_count
        if source_organization is not UNSET:
            field_dict["source_organization"] = source_organization
        if source_format is not UNSET:
            field_dict["source_format"] = source_format
        if quality_detail is not UNSET:
            field_dict["quality_detail"] = quality_detail
        if quality_statement is not UNSET:
            field_dict["quality_statement"] = quality_statement
        if formats is not UNSET:
            field_dict["formats"] = formats
        if language is not UNSET:
            field_dict["language"] = language
        if external_ids is not UNSET:
            field_dict["externalIds"] = external_ids
        if rights is not UNSET:
            field_dict["rights"] = rights
        if lineage is not UNSET:
            field_dict["lineage"] = lineage
        if update_frequency is not UNSET:
            field_dict["update_frequency"] = update_frequency
        if source_freshness is not UNSET:
            field_dict["source_freshness"] = source_freshness
        if source_health is not UNSET:
            field_dict["source_health"] = source_health
        if last_checked_at is not UNSET:
            field_dict["last_checked_at"] = last_checked_at
        if last_refreshed_at is not UNSET:
            field_dict["last_refreshed_at"] = last_refreshed_at
        if constraints is not UNSET:
            field_dict["constraints"] = constraints
        if distributions is not UNSET:
            field_dict["distributions"] = distributions
        if record_status is not UNSET:
            field_dict["record_status"] = record_status
        if has_quicklook is not UNSET:
            field_dict["has_quicklook"] = has_quicklook
        if gsd is not UNSET:
            field_dict["gsd"] = gsd
        if crs_is_geographic is not UNSET:
            field_dict["crs_is_geographic"] = crs_is_geographic
        if vrt_type is not UNSET:
            field_dict["vrt_type"] = vrt_type
        if source_count is not UNSET:
            field_dict["source_count"] = source_count
        if dataset_count is not UNSET:
            field_dict["dataset_count"] = dataset_count
        if projcode is not UNSET:
            field_dict["proj:code"] = projcode
        if projshape is not UNSET:
            field_dict["proj:shape"] = projshape
        if rasterbands is not UNSET:
            field_dict["raster:bands"] = rasterbands

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ogc_raster_band import OGCRasterBand
        from ..models.ogc_record_properties_constraints_type_0 import (
            OGCRecordPropertiesConstraintsType0,
        )
        from ..models.ogc_record_properties_contacts_item import (
            OGCRecordPropertiesContactsItem,
        )
        from ..models.ogc_record_properties_distributions_type_0_item import (
            OGCRecordPropertiesDistributionsType0Item,
        )
        from ..models.ogc_record_properties_quality_detail_type_0 import (
            OGCRecordPropertiesQualityDetailType0,
        )
        from ..models.ogc_record_properties_themes_item import (
            OGCRecordPropertiesThemesItem,
        )
        from ..models.ogc_record_properties_time import OGCRecordPropertiesTime

        d = dict(src_dict)
        title = d.pop("title")

        description = d.pop("description")

        keywords = cast(list[str], d.pop("keywords"))

        license_ = d.pop("license")

        themes = []
        _themes = d.pop("themes")
        for themes_item_data in _themes:
            themes_item = OGCRecordPropertiesThemesItem.from_dict(themes_item_data)

            themes.append(themes_item)

        contacts = []
        _contacts = d.pop("contacts")
        for contacts_item_data in _contacts:
            contacts_item = OGCRecordPropertiesContactsItem.from_dict(
                contacts_item_data
            )

            contacts.append(contacts_item)

        time = OGCRecordPropertiesTime.from_dict(d.pop("time"))

        type_ = d.pop("type", UNSET)

        def _parse_created(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                created_type_0 = isoparse(data)

                return created_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        created = _parse_created(d.pop("created", UNSET))

        def _parse_updated(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                updated_type_0 = isoparse(data)

                return updated_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        updated = _parse_updated(d.pop("updated", UNSET))

        def _parse_updated_by_display(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        updated_by_display = _parse_updated_by_display(
            d.pop("updated_by_display", UNSET)
        )

        never_edited = d.pop("never_edited", UNSET)

        def _parse_crs(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        crs = _parse_crs(d.pop("crs", UNSET))

        record_type = d.pop("record_type", UNSET)

        def _parse_band_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        band_count = _parse_band_count(d.pop("band_count", UNSET))

        def _parse_geometry_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type", UNSET))

        def _parse_feature_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count = _parse_feature_count(d.pop("feature_count", UNSET))

        def _parse_row_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        row_count = _parse_row_count(d.pop("row_count", UNSET))

        def _parse_column_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        column_count = _parse_column_count(d.pop("column_count", UNSET))

        def _parse_source_organization(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_organization = _parse_source_organization(
            d.pop("source_organization", UNSET)
        )

        def _parse_source_format(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_format = _parse_source_format(d.pop("source_format", UNSET))

        def _parse_quality_detail(
            data: object,
        ) -> None | OGCRecordPropertiesQualityDetailType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                quality_detail_type_0 = OGCRecordPropertiesQualityDetailType0.from_dict(
                    data
                )

                return quality_detail_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OGCRecordPropertiesQualityDetailType0 | Unset, data)

        quality_detail = _parse_quality_detail(d.pop("quality_detail", UNSET))

        def _parse_quality_statement(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        quality_statement = _parse_quality_statement(d.pop("quality_statement", UNSET))

        def _parse_formats(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                formats_type_0 = cast(list[str], data)

                return formats_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        formats = _parse_formats(d.pop("formats", UNSET))

        def _parse_language(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        language = _parse_language(d.pop("language", UNSET))

        external_ids = cast(list[str], d.pop("externalIds", UNSET))

        def _parse_rights(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        rights = _parse_rights(d.pop("rights", UNSET))

        def _parse_lineage(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lineage = _parse_lineage(d.pop("lineage", UNSET))

        def _parse_update_frequency(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        update_frequency = _parse_update_frequency(d.pop("update_frequency", UNSET))

        source_freshness = d.pop("source_freshness", UNSET)

        source_health = d.pop("source_health", UNSET)

        def _parse_last_checked_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_checked_at_type_0 = isoparse(data)

                return last_checked_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_checked_at = _parse_last_checked_at(d.pop("last_checked_at", UNSET))

        def _parse_last_refreshed_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_refreshed_at_type_0 = isoparse(data)

                return last_refreshed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_refreshed_at = _parse_last_refreshed_at(d.pop("last_refreshed_at", UNSET))

        def _parse_constraints(
            data: object,
        ) -> None | OGCRecordPropertiesConstraintsType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                constraints_type_0 = OGCRecordPropertiesConstraintsType0.from_dict(data)

                return constraints_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OGCRecordPropertiesConstraintsType0 | Unset, data)

        constraints = _parse_constraints(d.pop("constraints", UNSET))

        def _parse_distributions(
            data: object,
        ) -> list[OGCRecordPropertiesDistributionsType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                distributions_type_0 = []
                _distributions_type_0 = data
                for distributions_type_0_item_data in _distributions_type_0:
                    distributions_type_0_item = (
                        OGCRecordPropertiesDistributionsType0Item.from_dict(
                            distributions_type_0_item_data
                        )
                    )

                    distributions_type_0.append(distributions_type_0_item)

                return distributions_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(
                list[OGCRecordPropertiesDistributionsType0Item] | None | Unset, data
            )

        distributions = _parse_distributions(d.pop("distributions", UNSET))

        def _parse_record_status(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        record_status = _parse_record_status(d.pop("record_status", UNSET))

        has_quicklook = d.pop("has_quicklook", UNSET)

        def _parse_gsd(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        gsd = _parse_gsd(d.pop("gsd", UNSET))

        def _parse_crs_is_geographic(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        crs_is_geographic = _parse_crs_is_geographic(d.pop("crs_is_geographic", UNSET))

        def _parse_vrt_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        vrt_type = _parse_vrt_type(d.pop("vrt_type", UNSET))

        def _parse_source_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        source_count = _parse_source_count(d.pop("source_count", UNSET))

        def _parse_dataset_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        dataset_count = _parse_dataset_count(d.pop("dataset_count", UNSET))

        def _parse_projcode(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        projcode = _parse_projcode(d.pop("proj:code", UNSET))

        def _parse_projshape(data: object) -> list[int] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                projshape_type_0 = []
                _projshape_type_0 = data
                for projshape_type_0_item_data in _projshape_type_0:

                    def _parse_projshape_type_0_item(data: object) -> int:
                        return cast(int, data)

                    projshape_type_0_item = _parse_projshape_type_0_item(
                        projshape_type_0_item_data
                    )

                    projshape_type_0.append(projshape_type_0_item)

                return projshape_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[int] | None | Unset, data)

        projshape = _parse_projshape(d.pop("proj:shape", UNSET))

        def _parse_rasterbands(data: object) -> list[OGCRasterBand] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                rasterbands_type_0 = []
                _rasterbands_type_0 = data
                for rasterbands_type_0_item_data in _rasterbands_type_0:
                    rasterbands_type_0_item = OGCRasterBand.from_dict(
                        rasterbands_type_0_item_data
                    )

                    rasterbands_type_0.append(rasterbands_type_0_item)

                return rasterbands_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[OGCRasterBand] | None | Unset, data)

        rasterbands = _parse_rasterbands(d.pop("raster:bands", UNSET))

        ogc_record_properties = cls(
            title=title,
            description=description,
            keywords=keywords,
            license_=license_,
            themes=themes,
            contacts=contacts,
            time=time,
            type_=type_,
            created=created,
            updated=updated,
            updated_by_display=updated_by_display,
            never_edited=never_edited,
            crs=crs,
            record_type=record_type,
            band_count=band_count,
            geometry_type=geometry_type,
            feature_count=feature_count,
            row_count=row_count,
            column_count=column_count,
            source_organization=source_organization,
            source_format=source_format,
            quality_detail=quality_detail,
            quality_statement=quality_statement,
            formats=formats,
            language=language,
            external_ids=external_ids,
            rights=rights,
            lineage=lineage,
            update_frequency=update_frequency,
            source_freshness=source_freshness,
            source_health=source_health,
            last_checked_at=last_checked_at,
            last_refreshed_at=last_refreshed_at,
            constraints=constraints,
            distributions=distributions,
            record_status=record_status,
            has_quicklook=has_quicklook,
            gsd=gsd,
            crs_is_geographic=crs_is_geographic,
            vrt_type=vrt_type,
            source_count=source_count,
            dataset_count=dataset_count,
            projcode=projcode,
            projshape=projshape,
            rasterbands=rasterbands,
        )

        ogc_record_properties.additional_properties = d
        return ogc_record_properties

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
