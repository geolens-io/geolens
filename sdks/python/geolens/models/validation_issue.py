from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from ..models.validation_issue_severity import check_validation_issue_severity
from ..models.validation_issue_severity import ValidationIssueSeverity


T = TypeVar("T", bound="ValidationIssue")


@_attrs_define
class ValidationIssue:
    """
    Attributes:
        field (str):
        message (str):
        severity (ValidationIssueSeverity):
    """

    field: str
    message: str
    severity: ValidationIssueSeverity
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        field = self.field

        message = self.message

        severity: str = self.severity

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "field": field,
                "message": message,
                "severity": severity,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        field = d.pop("field")

        message = d.pop("message")

        severity = check_validation_issue_severity(d.pop("severity"))

        validation_issue = cls(
            field=field,
            message=message,
            severity=severity,
        )

        validation_issue.additional_properties = d
        return validation_issue

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
