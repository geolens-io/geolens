from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
import datetime


T = TypeVar("T", bound="QualityDetail")


@_attrs_define
class QualityDetail:
    """Automated quality assessment results.

    Attributes:
        overall (float):
        metadata_completeness (float):
        attribute_completeness (float):
        geometry_validity (float | None | Unset):
        crs_defined (float | None | Unset):
        computed_at (datetime.datetime | None | Unset):
    """

    overall: float
    metadata_completeness: float
    attribute_completeness: float
    geometry_validity: float | None | Unset = UNSET
    crs_defined: float | None | Unset = UNSET
    computed_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        overall = self.overall

        metadata_completeness = self.metadata_completeness

        attribute_completeness = self.attribute_completeness

        geometry_validity: float | None | Unset
        if isinstance(self.geometry_validity, Unset):
            geometry_validity = UNSET
        else:
            geometry_validity = self.geometry_validity

        crs_defined: float | None | Unset
        if isinstance(self.crs_defined, Unset):
            crs_defined = UNSET
        else:
            crs_defined = self.crs_defined

        computed_at: None | str | Unset
        if isinstance(self.computed_at, Unset):
            computed_at = UNSET
        elif isinstance(self.computed_at, datetime.datetime):
            computed_at = self.computed_at.isoformat()
        else:
            computed_at = self.computed_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "overall": overall,
                "metadata_completeness": metadata_completeness,
                "attribute_completeness": attribute_completeness,
            }
        )
        if geometry_validity is not UNSET:
            field_dict["geometry_validity"] = geometry_validity
        if crs_defined is not UNSET:
            field_dict["crs_defined"] = crs_defined
        if computed_at is not UNSET:
            field_dict["computed_at"] = computed_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        overall = d.pop("overall")

        metadata_completeness = d.pop("metadata_completeness")

        attribute_completeness = d.pop("attribute_completeness")

        def _parse_geometry_validity(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        geometry_validity = _parse_geometry_validity(d.pop("geometry_validity", UNSET))

        def _parse_crs_defined(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        crs_defined = _parse_crs_defined(d.pop("crs_defined", UNSET))

        def _parse_computed_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                computed_at_type_0 = isoparse(data)

                return computed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        computed_at = _parse_computed_at(d.pop("computed_at", UNSET))

        quality_detail = cls(
            overall=overall,
            metadata_completeness=metadata_completeness,
            attribute_completeness=attribute_completeness,
            geometry_validity=geometry_validity,
            crs_defined=crs_defined,
            computed_at=computed_at,
        )

        quality_detail.additional_properties = d
        return quality_detail

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
