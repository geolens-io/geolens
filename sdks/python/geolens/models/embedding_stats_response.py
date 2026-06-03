from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="EmbeddingStatsResponse")


@_attrs_define
class EmbeddingStatsResponse:
    """
    Attributes:
        coverage_percent (float): Embedding coverage as a percentage (0-100).
        embedded_records (int): Number of records that have an embedding stored.
        missing_records (int): Number of records still missing embeddings.
        total_records (int): Total number of records in the catalog.
    """

    coverage_percent: float
    embedded_records: int
    missing_records: int
    total_records: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        coverage_percent = self.coverage_percent

        embedded_records = self.embedded_records

        missing_records = self.missing_records

        total_records = self.total_records

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "coverage_percent": coverage_percent,
                "embedded_records": embedded_records,
                "missing_records": missing_records,
                "total_records": total_records,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        coverage_percent = d.pop("coverage_percent")

        embedded_records = d.pop("embedded_records")

        missing_records = d.pop("missing_records")

        total_records = d.pop("total_records")

        embedding_stats_response = cls(
            coverage_percent=coverage_percent,
            embedded_records=embedded_records,
            missing_records=missing_records,
            total_records=total_records,
        )

        embedding_stats_response.additional_properties = d
        return embedding_stats_response

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
