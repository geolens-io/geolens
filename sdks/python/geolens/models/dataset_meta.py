from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.dataset_meta_visibility_type_0 import check_dataset_meta_visibility_type_0
from ..models.dataset_meta_visibility_type_0 import DatasetMetaVisibilityType0
from dateutil.parser import isoparse
from typing import cast
import datetime


T = TypeVar("T", bound="DatasetMeta")


@_attrs_define
class DatasetMeta:
    """
    Attributes:
        access_constraints (None | str | Unset):
        data_vintage_end (datetime.date | None | Unset): End of temporal coverage
        data_vintage_start (datetime.date | None | Unset): Start of temporal coverage
        is_dem (bool | None | Unset): Flag raster as a Digital Elevation Model for terrain rendering
        language (None | str | Unset): ISO 639-1 language code, e.g. en, fr
        license_ (None | str | Unset):
        lineage_summary (None | str | Unset): Free-text provenance / lineage statement
        owner_org (None | str | Unset): Owning organization name
        quality_statement (None | str | Unset):
        record_status (None | str | Unset): Lifecycle status: draft, ready, published
        sensitivity_classification (None | str | Unset): e.g. public, confidential, restricted
        source_organization (None | str | Unset):
        source_url (None | str | Unset): URL the data was originally fetched from
        summary (None | str | Unset):
        theme_category (list[str] | None | Unset): ISO topic category codes
        title (None | str | Unset):
        update_frequency (None | str | Unset): ISO maintenance frequency code
        usage_constraints (None | str | Unset):
        visibility (DatasetMetaVisibilityType0 | None | Unset): Access level: private, restricted, internal, or public
    """

    access_constraints: None | str | Unset = UNSET
    data_vintage_end: datetime.date | None | Unset = UNSET
    data_vintage_start: datetime.date | None | Unset = UNSET
    is_dem: bool | None | Unset = UNSET
    language: None | str | Unset = UNSET
    license_: None | str | Unset = UNSET
    lineage_summary: None | str | Unset = UNSET
    owner_org: None | str | Unset = UNSET
    quality_statement: None | str | Unset = UNSET
    record_status: None | str | Unset = UNSET
    sensitivity_classification: None | str | Unset = UNSET
    source_organization: None | str | Unset = UNSET
    source_url: None | str | Unset = UNSET
    summary: None | str | Unset = UNSET
    theme_category: list[str] | None | Unset = UNSET
    title: None | str | Unset = UNSET
    update_frequency: None | str | Unset = UNSET
    usage_constraints: None | str | Unset = UNSET
    visibility: DatasetMetaVisibilityType0 | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        access_constraints: None | str | Unset
        if isinstance(self.access_constraints, Unset):
            access_constraints = UNSET
        else:
            access_constraints = self.access_constraints

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

        is_dem: bool | None | Unset
        if isinstance(self.is_dem, Unset):
            is_dem = UNSET
        else:
            is_dem = self.is_dem

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

        lineage_summary: None | str | Unset
        if isinstance(self.lineage_summary, Unset):
            lineage_summary = UNSET
        else:
            lineage_summary = self.lineage_summary

        owner_org: None | str | Unset
        if isinstance(self.owner_org, Unset):
            owner_org = UNSET
        else:
            owner_org = self.owner_org

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

        sensitivity_classification: None | str | Unset
        if isinstance(self.sensitivity_classification, Unset):
            sensitivity_classification = UNSET
        else:
            sensitivity_classification = self.sensitivity_classification

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

        summary: None | str | Unset
        if isinstance(self.summary, Unset):
            summary = UNSET
        else:
            summary = self.summary

        theme_category: list[str] | None | Unset
        if isinstance(self.theme_category, Unset):
            theme_category = UNSET
        elif isinstance(self.theme_category, list):
            theme_category = self.theme_category

        else:
            theme_category = self.theme_category

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        update_frequency: None | str | Unset
        if isinstance(self.update_frequency, Unset):
            update_frequency = UNSET
        else:
            update_frequency = self.update_frequency

        usage_constraints: None | str | Unset
        if isinstance(self.usage_constraints, Unset):
            usage_constraints = UNSET
        else:
            usage_constraints = self.usage_constraints

        visibility: None | str | Unset
        if isinstance(self.visibility, Unset):
            visibility = UNSET
        elif isinstance(self.visibility, str):
            visibility = self.visibility
        else:
            visibility = self.visibility

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if access_constraints is not UNSET:
            field_dict["access_constraints"] = access_constraints
        if data_vintage_end is not UNSET:
            field_dict["data_vintage_end"] = data_vintage_end
        if data_vintage_start is not UNSET:
            field_dict["data_vintage_start"] = data_vintage_start
        if is_dem is not UNSET:
            field_dict["is_dem"] = is_dem
        if language is not UNSET:
            field_dict["language"] = language
        if license_ is not UNSET:
            field_dict["license"] = license_
        if lineage_summary is not UNSET:
            field_dict["lineage_summary"] = lineage_summary
        if owner_org is not UNSET:
            field_dict["owner_org"] = owner_org
        if quality_statement is not UNSET:
            field_dict["quality_statement"] = quality_statement
        if record_status is not UNSET:
            field_dict["record_status"] = record_status
        if sensitivity_classification is not UNSET:
            field_dict["sensitivity_classification"] = sensitivity_classification
        if source_organization is not UNSET:
            field_dict["source_organization"] = source_organization
        if source_url is not UNSET:
            field_dict["source_url"] = source_url
        if summary is not UNSET:
            field_dict["summary"] = summary
        if theme_category is not UNSET:
            field_dict["theme_category"] = theme_category
        if title is not UNSET:
            field_dict["title"] = title
        if update_frequency is not UNSET:
            field_dict["update_frequency"] = update_frequency
        if usage_constraints is not UNSET:
            field_dict["usage_constraints"] = usage_constraints
        if visibility is not UNSET:
            field_dict["visibility"] = visibility

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_access_constraints(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        access_constraints = _parse_access_constraints(
            d.pop("access_constraints", UNSET)
        )

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

        def _parse_is_dem(data: object) -> bool | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(bool | None | Unset, data)

        is_dem = _parse_is_dem(d.pop("is_dem", UNSET))

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

        def _parse_lineage_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        lineage_summary = _parse_lineage_summary(d.pop("lineage_summary", UNSET))

        def _parse_owner_org(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        owner_org = _parse_owner_org(d.pop("owner_org", UNSET))

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

        def _parse_sensitivity_classification(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        sensitivity_classification = _parse_sensitivity_classification(
            d.pop("sensitivity_classification", UNSET)
        )

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

        def _parse_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        summary = _parse_summary(d.pop("summary", UNSET))

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

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        def _parse_update_frequency(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        update_frequency = _parse_update_frequency(d.pop("update_frequency", UNSET))

        def _parse_usage_constraints(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        usage_constraints = _parse_usage_constraints(d.pop("usage_constraints", UNSET))

        def _parse_visibility(
            data: object,
        ) -> DatasetMetaVisibilityType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                visibility_type_0 = check_dataset_meta_visibility_type_0(data)

                return visibility_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(DatasetMetaVisibilityType0 | None | Unset, data)

        visibility = _parse_visibility(d.pop("visibility", UNSET))

        dataset_meta = cls(
            access_constraints=access_constraints,
            data_vintage_end=data_vintage_end,
            data_vintage_start=data_vintage_start,
            is_dem=is_dem,
            language=language,
            license_=license_,
            lineage_summary=lineage_summary,
            owner_org=owner_org,
            quality_statement=quality_statement,
            record_status=record_status,
            sensitivity_classification=sensitivity_classification,
            source_organization=source_organization,
            source_url=source_url,
            summary=summary,
            theme_category=theme_category,
            title=title,
            update_frequency=update_frequency,
            usage_constraints=usage_constraints,
            visibility=visibility,
        )

        dataset_meta.additional_properties = d
        return dataset_meta

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
