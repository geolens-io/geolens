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
        total_records (int): Total number of records in the catalog.
        embedded_records (int): Number of records with an embedding for the ACTIVE embedding model — the only vectors
            semantic search can use.
        missing_records (int): Number of records without an active-model embedding (total_records - embedded_records).
        stale_records (int): Subset of missing_records whose only stored embeddings belong to other models. Regenerating
            all embeddings clears these; generating missing ones does not.
        coverage_percent (float): Embedding coverage as a percentage (0-100).
    """

    total_records: int
    embedded_records: int
    missing_records: int
    stale_records: int
    coverage_percent: float
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        total_records = self.total_records

        embedded_records = self.embedded_records

        missing_records = self.missing_records

        stale_records = self.stale_records

        coverage_percent = self.coverage_percent

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "total_records": total_records,
                "embedded_records": embedded_records,
                "missing_records": missing_records,
                "stale_records": stale_records,
                "coverage_percent": coverage_percent,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        total_records = d.pop("total_records")

        embedded_records = d.pop("embedded_records")

        missing_records = d.pop("missing_records")

        stale_records = d.pop("stale_records")

        coverage_percent = d.pop("coverage_percent")

        embedding_stats_response = cls(
            total_records=total_records,
            embedded_records=embedded_records,
            missing_records=missing_records,
            stale_records=stale_records,
            coverage_percent=coverage_percent,
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
