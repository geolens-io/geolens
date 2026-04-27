from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.validation_issue import ValidationIssue
    from ..models.validation_result_response_quality_score_type_0 import (
        ValidationResultResponseQualityScoreType0,
    )


T = TypeVar("T", bound="ValidationResultResponse")


@_attrs_define
class ValidationResultResponse:
    """
    Attributes:
        errors (list[ValidationIssue]):
        is_valid (bool):
        warnings (list[ValidationIssue]):
        quality_score (None | Unset | ValidationResultResponseQualityScoreType0):
    """

    errors: list[ValidationIssue]
    is_valid: bool
    warnings: list[ValidationIssue]
    quality_score: None | Unset | ValidationResultResponseQualityScoreType0 = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.validation_result_response_quality_score_type_0 import (
            ValidationResultResponseQualityScoreType0,
        )

        errors = []
        for errors_item_data in self.errors:
            errors_item = errors_item_data.to_dict()
            errors.append(errors_item)

        is_valid = self.is_valid

        warnings = []
        for warnings_item_data in self.warnings:
            warnings_item = warnings_item_data.to_dict()
            warnings.append(warnings_item)

        quality_score: dict[str, Any] | None | Unset
        if isinstance(self.quality_score, Unset):
            quality_score = UNSET
        elif isinstance(self.quality_score, ValidationResultResponseQualityScoreType0):
            quality_score = self.quality_score.to_dict()
        else:
            quality_score = self.quality_score

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "errors": errors,
                "is_valid": is_valid,
                "warnings": warnings,
            }
        )
        if quality_score is not UNSET:
            field_dict["quality_score"] = quality_score

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.validation_issue import ValidationIssue
        from ..models.validation_result_response_quality_score_type_0 import (
            ValidationResultResponseQualityScoreType0,
        )

        d = dict(src_dict)
        errors = []
        _errors = d.pop("errors")
        for errors_item_data in _errors:
            errors_item = ValidationIssue.from_dict(errors_item_data)

            errors.append(errors_item)

        is_valid = d.pop("is_valid")

        warnings = []
        _warnings = d.pop("warnings")
        for warnings_item_data in _warnings:
            warnings_item = ValidationIssue.from_dict(warnings_item_data)

            warnings.append(warnings_item)

        def _parse_quality_score(
            data: object,
        ) -> None | Unset | ValidationResultResponseQualityScoreType0:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                quality_score_type_0 = (
                    ValidationResultResponseQualityScoreType0.from_dict(data)
                )

                return quality_score_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | ValidationResultResponseQualityScoreType0, data)

        quality_score = _parse_quality_score(d.pop("quality_score", UNSET))

        validation_result_response = cls(
            errors=errors,
            is_valid=is_valid,
            warnings=warnings,
            quality_score=quality_score,
        )

        validation_result_response.additional_properties = d
        return validation_result_response

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
