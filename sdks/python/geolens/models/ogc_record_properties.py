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
        contacts (list[OGCRecordPropertiesContactsItem]):
        description (str):
        keywords (list[str]):
        license_ (str):
        themes (list[OGCRecordPropertiesThemesItem]):
        time (OGCRecordPropertiesTime):
        title (str):
        band_count (int | None | Unset):
        column_count (int | None | Unset): Number of columns in the dataset (populated from column_info length).
        constraints (None | OGCRecordPropertiesConstraintsType0 | Unset):
        created (datetime.datetime | None | Unset):
        crs (None | str | Unset):
        dataset_count (int | None | Unset):
        distributions (list[OGCRecordPropertiesDistributionsType0Item] | None | Unset):
        external_ids (list[str] | Unset): Identifiers assigned by the described resource's source system.
        feature_count (int | None | Unset):
        formats (list[str] | None | Unset):
        geometry_type (None | str | Unset):
        gsd (float | None | Unset):
        has_quicklook (bool | Unset):  Default: False.
        language (None | str | Unset):
        lineage (None | str | Unset):
        never_edited (bool | Unset):  Default: False.
        quality_detail (None | OGCRecordPropertiesQualityDetailType0 | Unset):
        quality_statement (None | str | Unset):
        record_status (None | str | Unset):
        record_type (str | Unset):  Default: 'vector_dataset'.
        rights (None | str | Unset):
        row_count (int | None | Unset): Row count for tabular records (alias for feature_count when
            record_type='table').
        source_count (int | None | Unset):
        source_format (None | str | Unset): Ingest source format ('geojson', 'shapefile', 'geotiff', 'wfs', 'stac',
            'created', ...). Null for datasets registered from existing PostGIS tables and for composed VRT datasets.
        source_organization (None | str | Unset):
        type_ (str | Unset):  Default: 'dataset'.
        update_frequency (None | str | Unset):
        updated (datetime.datetime | None | Unset):
        updated_by_display (None | str | Unset):
        vrt_type (None | str | Unset):
    """

    contacts: list[OGCRecordPropertiesContactsItem]
    description: str
    keywords: list[str]
    license_: str
    themes: list[OGCRecordPropertiesThemesItem]
    time: OGCRecordPropertiesTime
    title: str
    band_count: int | None | Unset = UNSET
    column_count: int | None | Unset = UNSET
    constraints: None | OGCRecordPropertiesConstraintsType0 | Unset = UNSET
    created: datetime.datetime | None | Unset = UNSET
    crs: None | str | Unset = UNSET
    dataset_count: int | None | Unset = UNSET
    distributions: list[OGCRecordPropertiesDistributionsType0Item] | None | Unset = (
        UNSET
    )
    external_ids: list[str] | Unset = UNSET
    feature_count: int | None | Unset = UNSET
    formats: list[str] | None | Unset = UNSET
    geometry_type: None | str | Unset = UNSET
    gsd: float | None | Unset = UNSET
    has_quicklook: bool | Unset = False
    language: None | str | Unset = UNSET
    lineage: None | str | Unset = UNSET
    never_edited: bool | Unset = False
    quality_detail: None | OGCRecordPropertiesQualityDetailType0 | Unset = UNSET
    quality_statement: None | str | Unset = UNSET
    record_status: None | str | Unset = UNSET
    record_type: str | Unset = "vector_dataset"
    rights: None | str | Unset = UNSET
    row_count: int | None | Unset = UNSET
    source_count: int | None | Unset = UNSET
    source_format: None | str | Unset = UNSET
    source_organization: None | str | Unset = UNSET
    type_: str | Unset = "dataset"
    update_frequency: None | str | Unset = UNSET
    updated: datetime.datetime | None | Unset = UNSET
    updated_by_display: None | str | Unset = UNSET
    vrt_type: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.ogc_record_properties_constraints_type_0 import (
            OGCRecordPropertiesConstraintsType0,
        )
        from ..models.ogc_record_properties_quality_detail_type_0 import (
            OGCRecordPropertiesQualityDetailType0,
        )

        contacts = []
        for contacts_item_data in self.contacts:
            contacts_item = contacts_item_data.to_dict()
            contacts.append(contacts_item)

        description = self.description

        keywords = self.keywords

        license_ = self.license_

        themes = []
        for themes_item_data in self.themes:
            themes_item = themes_item_data.to_dict()
            themes.append(themes_item)

        time = self.time.to_dict()

        title = self.title

        band_count: int | None | Unset
        if isinstance(self.band_count, Unset):
            band_count = UNSET
        else:
            band_count = self.band_count

        column_count: int | None | Unset
        if isinstance(self.column_count, Unset):
            column_count = UNSET
        else:
            column_count = self.column_count

        constraints: dict[str, Any] | None | Unset
        if isinstance(self.constraints, Unset):
            constraints = UNSET
        elif isinstance(self.constraints, OGCRecordPropertiesConstraintsType0):
            constraints = self.constraints.to_dict()
        else:
            constraints = self.constraints

        created: None | str | Unset
        if isinstance(self.created, Unset):
            created = UNSET
        elif isinstance(self.created, datetime.datetime):
            created = self.created.isoformat()
        else:
            created = self.created

        crs: None | str | Unset
        if isinstance(self.crs, Unset):
            crs = UNSET
        else:
            crs = self.crs

        dataset_count: int | None | Unset
        if isinstance(self.dataset_count, Unset):
            dataset_count = UNSET
        else:
            dataset_count = self.dataset_count

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

        external_ids: list[str] | Unset = UNSET
        if not isinstance(self.external_ids, Unset):
            external_ids = self.external_ids

        feature_count: int | None | Unset
        if isinstance(self.feature_count, Unset):
            feature_count = UNSET
        else:
            feature_count = self.feature_count

        formats: list[str] | None | Unset
        if isinstance(self.formats, Unset):
            formats = UNSET
        elif isinstance(self.formats, list):
            formats = self.formats

        else:
            formats = self.formats

        geometry_type: None | str | Unset
        if isinstance(self.geometry_type, Unset):
            geometry_type = UNSET
        else:
            geometry_type = self.geometry_type

        gsd: float | None | Unset
        if isinstance(self.gsd, Unset):
            gsd = UNSET
        else:
            gsd = self.gsd

        has_quicklook = self.has_quicklook

        language: None | str | Unset
        if isinstance(self.language, Unset):
            language = UNSET
        else:
            language = self.language

        lineage: None | str | Unset
        if isinstance(self.lineage, Unset):
            lineage = UNSET
        else:
            lineage = self.lineage

        never_edited = self.never_edited

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

        record_status: None | str | Unset
        if isinstance(self.record_status, Unset):
            record_status = UNSET
        else:
            record_status = self.record_status

        record_type = self.record_type

        rights: None | str | Unset
        if isinstance(self.rights, Unset):
            rights = UNSET
        else:
            rights = self.rights

        row_count: int | None | Unset
        if isinstance(self.row_count, Unset):
            row_count = UNSET
        else:
            row_count = self.row_count

        source_count: int | None | Unset
        if isinstance(self.source_count, Unset):
            source_count = UNSET
        else:
            source_count = self.source_count

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

        type_ = self.type_

        update_frequency: None | str | Unset
        if isinstance(self.update_frequency, Unset):
            update_frequency = UNSET
        else:
            update_frequency = self.update_frequency

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

        vrt_type: None | str | Unset
        if isinstance(self.vrt_type, Unset):
            vrt_type = UNSET
        else:
            vrt_type = self.vrt_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "contacts": contacts,
                "description": description,
                "keywords": keywords,
                "license": license_,
                "themes": themes,
                "time": time,
                "title": title,
            }
        )
        if band_count is not UNSET:
            field_dict["band_count"] = band_count
        if column_count is not UNSET:
            field_dict["column_count"] = column_count
        if constraints is not UNSET:
            field_dict["constraints"] = constraints
        if created is not UNSET:
            field_dict["created"] = created
        if crs is not UNSET:
            field_dict["crs"] = crs
        if dataset_count is not UNSET:
            field_dict["dataset_count"] = dataset_count
        if distributions is not UNSET:
            field_dict["distributions"] = distributions
        if external_ids is not UNSET:
            field_dict["externalIds"] = external_ids
        if feature_count is not UNSET:
            field_dict["feature_count"] = feature_count
        if formats is not UNSET:
            field_dict["formats"] = formats
        if geometry_type is not UNSET:
            field_dict["geometry_type"] = geometry_type
        if gsd is not UNSET:
            field_dict["gsd"] = gsd
        if has_quicklook is not UNSET:
            field_dict["has_quicklook"] = has_quicklook
        if language is not UNSET:
            field_dict["language"] = language
        if lineage is not UNSET:
            field_dict["lineage"] = lineage
        if never_edited is not UNSET:
            field_dict["never_edited"] = never_edited
        if quality_detail is not UNSET:
            field_dict["quality_detail"] = quality_detail
        if quality_statement is not UNSET:
            field_dict["quality_statement"] = quality_statement
        if record_status is not UNSET:
            field_dict["record_status"] = record_status
        if record_type is not UNSET:
            field_dict["record_type"] = record_type
        if rights is not UNSET:
            field_dict["rights"] = rights
        if row_count is not UNSET:
            field_dict["row_count"] = row_count
        if source_count is not UNSET:
            field_dict["source_count"] = source_count
        if source_format is not UNSET:
            field_dict["source_format"] = source_format
        if source_organization is not UNSET:
            field_dict["source_organization"] = source_organization
        if type_ is not UNSET:
            field_dict["type"] = type_
        if update_frequency is not UNSET:
            field_dict["update_frequency"] = update_frequency
        if updated is not UNSET:
            field_dict["updated"] = updated
        if updated_by_display is not UNSET:
            field_dict["updated_by_display"] = updated_by_display
        if vrt_type is not UNSET:
            field_dict["vrt_type"] = vrt_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
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
        contacts = []
        _contacts = d.pop("contacts")
        for contacts_item_data in _contacts:
            contacts_item = OGCRecordPropertiesContactsItem.from_dict(
                contacts_item_data
            )

            contacts.append(contacts_item)

        description = d.pop("description")

        keywords = cast(list[str], d.pop("keywords"))

        license_ = d.pop("license")

        themes = []
        _themes = d.pop("themes")
        for themes_item_data in _themes:
            themes_item = OGCRecordPropertiesThemesItem.from_dict(themes_item_data)

            themes.append(themes_item)

        time = OGCRecordPropertiesTime.from_dict(d.pop("time"))

        title = d.pop("title")

        def _parse_band_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        band_count = _parse_band_count(d.pop("band_count", UNSET))

        def _parse_column_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        column_count = _parse_column_count(d.pop("column_count", UNSET))

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

        def _parse_crs(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        crs = _parse_crs(d.pop("crs", UNSET))

        def _parse_dataset_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        dataset_count = _parse_dataset_count(d.pop("dataset_count", UNSET))

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

        external_ids = cast(list[str], d.pop("externalIds", UNSET))

        def _parse_feature_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count = _parse_feature_count(d.pop("feature_count", UNSET))

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

        def _parse_geometry_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type", UNSET))

        def _parse_gsd(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        gsd = _parse_gsd(d.pop("gsd", UNSET))

        has_quicklook = d.pop("has_quicklook", UNSET)

        def _parse_language(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        language = _parse_language(d.pop("language", UNSET))

        def _parse_lineage(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lineage = _parse_lineage(d.pop("lineage", UNSET))

        never_edited = d.pop("never_edited", UNSET)

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

        def _parse_record_status(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        record_status = _parse_record_status(d.pop("record_status", UNSET))

        record_type = d.pop("record_type", UNSET)

        def _parse_rights(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        rights = _parse_rights(d.pop("rights", UNSET))

        def _parse_row_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        row_count = _parse_row_count(d.pop("row_count", UNSET))

        def _parse_source_count(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        source_count = _parse_source_count(d.pop("source_count", UNSET))

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

        type_ = d.pop("type", UNSET)

        def _parse_update_frequency(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        update_frequency = _parse_update_frequency(d.pop("update_frequency", UNSET))

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

        def _parse_vrt_type(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        vrt_type = _parse_vrt_type(d.pop("vrt_type", UNSET))

        ogc_record_properties = cls(
            contacts=contacts,
            description=description,
            keywords=keywords,
            license_=license_,
            themes=themes,
            time=time,
            title=title,
            band_count=band_count,
            column_count=column_count,
            constraints=constraints,
            created=created,
            crs=crs,
            dataset_count=dataset_count,
            distributions=distributions,
            external_ids=external_ids,
            feature_count=feature_count,
            formats=formats,
            geometry_type=geometry_type,
            gsd=gsd,
            has_quicklook=has_quicklook,
            language=language,
            lineage=lineage,
            never_edited=never_edited,
            quality_detail=quality_detail,
            quality_statement=quality_statement,
            record_status=record_status,
            record_type=record_type,
            rights=rights,
            row_count=row_count,
            source_count=source_count,
            source_format=source_format,
            source_organization=source_organization,
            type_=type_,
            update_frequency=update_frequency,
            updated=updated,
            updated_by_display=updated_by_display,
            vrt_type=vrt_type,
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
