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
    from ..models.ogc_record_properties_contacts_type_0_item import (
        OGCRecordPropertiesContactsType0Item,
    )
    from ..models.ogc_record_properties_distributions_type_0_item import (
        OGCRecordPropertiesDistributionsType0Item,
    )
    from ..models.ogc_record_properties_quality_detail_type_0 import (
        OGCRecordPropertiesQualityDetailType0,
    )
    from ..models.ogc_record_properties_themes_type_0_item import (
        OGCRecordPropertiesThemesType0Item,
    )
    from ..models.ogc_record_properties_time_type_0 import OGCRecordPropertiesTimeType0


T = TypeVar("T", bound="OGCRecordProperties")


@_attrs_define
class OGCRecordProperties:
    """Properties block of an OGC API Records Feature.

    Attributes:
        title (str):
        band_count (int | None | Unset):
        column_count (int | None | Unset): Number of columns in the dataset (populated from column_info length).
        constraints (None | OGCRecordPropertiesConstraintsType0 | Unset):
        contacts (list[OGCRecordPropertiesContactsType0Item] | None | Unset):
        created (datetime.datetime | None | Unset):
        crs (None | str | Unset):
        dataset_count (int | None | Unset):
        description (None | str | Unset):
        distributions (list[OGCRecordPropertiesDistributionsType0Item] | None | Unset):
        feature_count (int | None | Unset):
        formats (list[str] | None | Unset):
        geometry_type (None | str | Unset):
        gsd (float | None | Unset):
        has_quicklook (bool | Unset):  Default: False.
        keywords (list[str] | None | Unset):
        language (None | str | Unset):
        license_ (None | str | Unset):
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
        source_organization (None | str | Unset):
        themes (list[OGCRecordPropertiesThemesType0Item] | None | Unset):
        time (None | OGCRecordPropertiesTimeType0 | Unset):
        type_ (str | Unset):  Default: 'dataset'.
        update_frequency (None | str | Unset):
        updated (datetime.datetime | None | Unset):
        updated_by_display (None | str | Unset):
        vrt_type (None | str | Unset):
    """

    title: str
    band_count: int | None | Unset = UNSET
    column_count: int | None | Unset = UNSET
    constraints: None | OGCRecordPropertiesConstraintsType0 | Unset = UNSET
    contacts: list[OGCRecordPropertiesContactsType0Item] | None | Unset = UNSET
    created: datetime.datetime | None | Unset = UNSET
    crs: None | str | Unset = UNSET
    dataset_count: int | None | Unset = UNSET
    description: None | str | Unset = UNSET
    distributions: list[OGCRecordPropertiesDistributionsType0Item] | None | Unset = (
        UNSET
    )
    feature_count: int | None | Unset = UNSET
    formats: list[str] | None | Unset = UNSET
    geometry_type: None | str | Unset = UNSET
    gsd: float | None | Unset = UNSET
    has_quicklook: bool | Unset = False
    keywords: list[str] | None | Unset = UNSET
    language: None | str | Unset = UNSET
    license_: None | str | Unset = UNSET
    lineage: None | str | Unset = UNSET
    never_edited: bool | Unset = False
    quality_detail: None | OGCRecordPropertiesQualityDetailType0 | Unset = UNSET
    quality_statement: None | str | Unset = UNSET
    record_status: None | str | Unset = UNSET
    record_type: str | Unset = "vector_dataset"
    rights: None | str | Unset = UNSET
    row_count: int | None | Unset = UNSET
    source_count: int | None | Unset = UNSET
    source_organization: None | str | Unset = UNSET
    themes: list[OGCRecordPropertiesThemesType0Item] | None | Unset = UNSET
    time: None | OGCRecordPropertiesTimeType0 | Unset = UNSET
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
        from ..models.ogc_record_properties_time_type_0 import (
            OGCRecordPropertiesTimeType0,
        )

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

        contacts: list[dict[str, Any]] | None | Unset
        if isinstance(self.contacts, Unset):
            contacts = UNSET
        elif isinstance(self.contacts, list):
            contacts = []
            for contacts_type_0_item_data in self.contacts:
                contacts_type_0_item = contacts_type_0_item_data.to_dict()
                contacts.append(contacts_type_0_item)

        else:
            contacts = self.contacts

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

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

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

        keywords: list[str] | None | Unset
        if isinstance(self.keywords, Unset):
            keywords = UNSET
        elif isinstance(self.keywords, list):
            keywords = self.keywords

        else:
            keywords = self.keywords

        language: None | str | Unset
        if isinstance(self.language, Unset):
            language = UNSET
        else:
            language = self.language

        license_: None | str | Unset
        if isinstance(self.license_, Unset):
            license_ = UNSET
        else:
            license_ = self.license_

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

        source_organization: None | str | Unset
        if isinstance(self.source_organization, Unset):
            source_organization = UNSET
        else:
            source_organization = self.source_organization

        themes: list[dict[str, Any]] | None | Unset
        if isinstance(self.themes, Unset):
            themes = UNSET
        elif isinstance(self.themes, list):
            themes = []
            for themes_type_0_item_data in self.themes:
                themes_type_0_item = themes_type_0_item_data.to_dict()
                themes.append(themes_type_0_item)

        else:
            themes = self.themes

        time: dict[str, Any] | None | Unset
        if isinstance(self.time, Unset):
            time = UNSET
        elif isinstance(self.time, OGCRecordPropertiesTimeType0):
            time = self.time.to_dict()
        else:
            time = self.time

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
                "title": title,
            }
        )
        if band_count is not UNSET:
            field_dict["band_count"] = band_count
        if column_count is not UNSET:
            field_dict["column_count"] = column_count
        if constraints is not UNSET:
            field_dict["constraints"] = constraints
        if contacts is not UNSET:
            field_dict["contacts"] = contacts
        if created is not UNSET:
            field_dict["created"] = created
        if crs is not UNSET:
            field_dict["crs"] = crs
        if dataset_count is not UNSET:
            field_dict["dataset_count"] = dataset_count
        if description is not UNSET:
            field_dict["description"] = description
        if distributions is not UNSET:
            field_dict["distributions"] = distributions
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
        if keywords is not UNSET:
            field_dict["keywords"] = keywords
        if language is not UNSET:
            field_dict["language"] = language
        if license_ is not UNSET:
            field_dict["license"] = license_
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
        if source_organization is not UNSET:
            field_dict["source_organization"] = source_organization
        if themes is not UNSET:
            field_dict["themes"] = themes
        if time is not UNSET:
            field_dict["time"] = time
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
        from ..models.ogc_record_properties_contacts_type_0_item import (
            OGCRecordPropertiesContactsType0Item,
        )
        from ..models.ogc_record_properties_distributions_type_0_item import (
            OGCRecordPropertiesDistributionsType0Item,
        )
        from ..models.ogc_record_properties_quality_detail_type_0 import (
            OGCRecordPropertiesQualityDetailType0,
        )
        from ..models.ogc_record_properties_themes_type_0_item import (
            OGCRecordPropertiesThemesType0Item,
        )
        from ..models.ogc_record_properties_time_type_0 import (
            OGCRecordPropertiesTimeType0,
        )

        d = dict(src_dict)
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

        def _parse_contacts(
            data: object,
        ) -> list[OGCRecordPropertiesContactsType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                contacts_type_0 = []
                _contacts_type_0 = data
                for contacts_type_0_item_data in _contacts_type_0:
                    contacts_type_0_item = (
                        OGCRecordPropertiesContactsType0Item.from_dict(
                            contacts_type_0_item_data
                        )
                    )

                    contacts_type_0.append(contacts_type_0_item)

                return contacts_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[OGCRecordPropertiesContactsType0Item] | None | Unset, data)

        contacts = _parse_contacts(d.pop("contacts", UNSET))

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

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

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

        def _parse_keywords(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                keywords_type_0 = cast(list[str], data)

                return keywords_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        keywords = _parse_keywords(d.pop("keywords", UNSET))

        def _parse_language(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        language = _parse_language(d.pop("language", UNSET))

        def _parse_license_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        license_ = _parse_license_(d.pop("license", UNSET))

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

        def _parse_source_organization(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_organization = _parse_source_organization(
            d.pop("source_organization", UNSET)
        )

        def _parse_themes(
            data: object,
        ) -> list[OGCRecordPropertiesThemesType0Item] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                themes_type_0 = []
                _themes_type_0 = data
                for themes_type_0_item_data in _themes_type_0:
                    themes_type_0_item = OGCRecordPropertiesThemesType0Item.from_dict(
                        themes_type_0_item_data
                    )

                    themes_type_0.append(themes_type_0_item)

                return themes_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[OGCRecordPropertiesThemesType0Item] | None | Unset, data)

        themes = _parse_themes(d.pop("themes", UNSET))

        def _parse_time(data: object) -> None | OGCRecordPropertiesTimeType0 | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                time_type_0 = OGCRecordPropertiesTimeType0.from_dict(data)

                return time_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | OGCRecordPropertiesTimeType0 | Unset, data)

        time = _parse_time(d.pop("time", UNSET))

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
            title=title,
            band_count=band_count,
            column_count=column_count,
            constraints=constraints,
            contacts=contacts,
            created=created,
            crs=crs,
            dataset_count=dataset_count,
            description=description,
            distributions=distributions,
            feature_count=feature_count,
            formats=formats,
            geometry_type=geometry_type,
            gsd=gsd,
            has_quicklook=has_quicklook,
            keywords=keywords,
            language=language,
            license_=license_,
            lineage=lineage,
            never_edited=never_edited,
            quality_detail=quality_detail,
            quality_statement=quality_statement,
            record_status=record_status,
            record_type=record_type,
            rights=rights,
            row_count=row_count,
            source_count=source_count,
            source_organization=source_organization,
            themes=themes,
            time=time,
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
