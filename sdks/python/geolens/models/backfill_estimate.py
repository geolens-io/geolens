from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="BackfillEstimate")


@_attrs_define
class BackfillEstimate:
    """How long each backfill action should take, before starting one.

    Both figures come from the throughput of the most recent completed run, so
    they describe this deployment's own provider rather than a generic rate.

        Attributes:
            missing_seconds (float): Estimated seconds to embed the records that lack a usable vector.
            all_seconds (float): Estimated seconds to regenerate every record in the catalog.
    """

    missing_seconds: float
    all_seconds: float
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        missing_seconds = self.missing_seconds

        all_seconds = self.all_seconds

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "missing_seconds": missing_seconds,
                "all_seconds": all_seconds,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        missing_seconds = d.pop("missing_seconds")

        all_seconds = d.pop("all_seconds")

        backfill_estimate = cls(
            missing_seconds=missing_seconds,
            all_seconds=all_seconds,
        )

        backfill_estimate.additional_properties = d
        return backfill_estimate

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
