from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.manifest_apply_entry_result import ManifestApplyEntryResult


T = TypeVar("T", bound="ManifestApplyResponse")


@_attrs_define
class ManifestApplyResponse:
    """
    Attributes:
        accepted (bool):
        dry_run (bool):
        results (list[ManifestApplyEntryResult]):
    """

    accepted: bool
    dry_run: bool
    results: list[ManifestApplyEntryResult]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        accepted = self.accepted

        dry_run = self.dry_run

        results = []
        for results_item_data in self.results:
            results_item = results_item_data.to_dict()
            results.append(results_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "accepted": accepted,
                "dry_run": dry_run,
                "results": results,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_apply_entry_result import ManifestApplyEntryResult

        d = dict(src_dict)
        accepted = d.pop("accepted")

        dry_run = d.pop("dry_run")

        results = []
        _results = d.pop("results")
        for results_item_data in _results:
            results_item = ManifestApplyEntryResult.from_dict(results_item_data)

            results.append(results_item)

        manifest_apply_response = cls(
            accepted=accepted,
            dry_run=dry_run,
            results=results,
        )

        manifest_apply_response.additional_properties = d
        return manifest_apply_response

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
