from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="JobRefreshRunSummary")


@_attrs_define
class JobRefreshRunSummary:
    """
    Attributes:
        id (UUID):
        status (str): Refresh run status. `blocked` means the run is held for review.
        review_reasons (list[str] | Unset): Why a blocked run needs review.
    """

    id: UUID
    status: str
    review_reasons: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        status = self.status

        review_reasons: list[str] | Unset = UNSET
        if not isinstance(self.review_reasons, Unset):
            review_reasons = self.review_reasons

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "status": status,
            }
        )
        if review_reasons is not UNSET:
            field_dict["review_reasons"] = review_reasons

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        status = d.pop("status")

        review_reasons = cast(list[str], d.pop("review_reasons", UNSET))

        job_refresh_run_summary = cls(
            id=id,
            status=status,
            review_reasons=review_reasons,
        )

        job_refresh_run_summary.additional_properties = d
        return job_refresh_run_summary

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
