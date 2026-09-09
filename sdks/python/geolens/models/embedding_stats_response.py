from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.backfill_estimate import BackfillEstimate
    from ..models.backfill_run_progress import BackfillRunProgress
    from ..models.backfill_run_summary import BackfillRunSummary


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
        current_run (BackfillRunProgress | None | Unset): The backfill run in flight, or null when none is running.
        recent_runs (list[BackfillRunSummary] | Unset): The most recent finished backfill runs, newest first.
        estimate (BackfillEstimate | None | Unset): Expected duration of each backfill action, or null until one run has
            completed and measured this deployment's throughput.
    """

    total_records: int
    embedded_records: int
    missing_records: int
    stale_records: int
    coverage_percent: float
    current_run: BackfillRunProgress | None | Unset = UNSET
    recent_runs: list[BackfillRunSummary] | Unset = UNSET
    estimate: BackfillEstimate | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.backfill_estimate import BackfillEstimate
        from ..models.backfill_run_progress import BackfillRunProgress

        total_records = self.total_records

        embedded_records = self.embedded_records

        missing_records = self.missing_records

        stale_records = self.stale_records

        coverage_percent = self.coverage_percent

        current_run: dict[str, Any] | None | Unset
        if isinstance(self.current_run, Unset):
            current_run = UNSET
        elif isinstance(self.current_run, BackfillRunProgress):
            current_run = self.current_run.to_dict()
        else:
            current_run = self.current_run

        recent_runs: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.recent_runs, Unset):
            recent_runs = []
            for recent_runs_item_data in self.recent_runs:
                recent_runs_item = recent_runs_item_data.to_dict()
                recent_runs.append(recent_runs_item)

        estimate: dict[str, Any] | None | Unset
        if isinstance(self.estimate, Unset):
            estimate = UNSET
        elif isinstance(self.estimate, BackfillEstimate):
            estimate = self.estimate.to_dict()
        else:
            estimate = self.estimate

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
        if current_run is not UNSET:
            field_dict["current_run"] = current_run
        if recent_runs is not UNSET:
            field_dict["recent_runs"] = recent_runs
        if estimate is not UNSET:
            field_dict["estimate"] = estimate

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.backfill_estimate import BackfillEstimate
        from ..models.backfill_run_progress import BackfillRunProgress
        from ..models.backfill_run_summary import BackfillRunSummary

        d = dict(src_dict)
        total_records = d.pop("total_records")

        embedded_records = d.pop("embedded_records")

        missing_records = d.pop("missing_records")

        stale_records = d.pop("stale_records")

        coverage_percent = d.pop("coverage_percent")

        def _parse_current_run(data: object) -> BackfillRunProgress | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                current_run_type_0 = BackfillRunProgress.from_dict(data)

                return current_run_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(BackfillRunProgress | None | Unset, data)

        current_run = _parse_current_run(d.pop("current_run", UNSET))

        _recent_runs = d.pop("recent_runs", UNSET)
        recent_runs: list[BackfillRunSummary] | Unset = UNSET
        if _recent_runs is not UNSET:
            recent_runs = []
            for recent_runs_item_data in _recent_runs:
                recent_runs_item = BackfillRunSummary.from_dict(recent_runs_item_data)

                recent_runs.append(recent_runs_item)

        def _parse_estimate(data: object) -> BackfillEstimate | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                estimate_type_0 = BackfillEstimate.from_dict(data)

                return estimate_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(BackfillEstimate | None | Unset, data)

        estimate = _parse_estimate(d.pop("estimate", UNSET))

        embedding_stats_response = cls(
            total_records=total_records,
            embedded_records=embedded_records,
            missing_records=missing_records,
            stale_records=stale_records,
            coverage_percent=coverage_percent,
            current_run=current_run,
            recent_runs=recent_runs,
            estimate=estimate,
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
