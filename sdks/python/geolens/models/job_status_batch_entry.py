from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.job_status_batch_entry_current_step_type_0 import (
    check_job_status_batch_entry_current_step_type_0,
)
from ..models.job_status_batch_entry_current_step_type_0 import (
    JobStatusBatchEntryCurrentStepType0,
)
from ..models.job_status_batch_entry_status_type_0 import (
    check_job_status_batch_entry_status_type_0,
)
from ..models.job_status_batch_entry_status_type_0 import JobStatusBatchEntryStatusType0
from typing import cast
from typing import Literal
from uuid import UUID

if TYPE_CHECKING:
    from ..models.dbf_truncation_collision_warning import DbfTruncationCollisionWarning
    from ..models.job_refresh_run_summary import JobRefreshRunSummary
    from ..models.mercator_clip_warning import MercatorClipWarning
    from ..models.reserved_rename_warning import ReservedRenameWarning


T = TypeVar("T", bound="JobStatusBatchEntry")


@_attrs_define
class JobStatusBatchEntry:
    """
    Attributes:
        id (UUID):
        status (JobStatusBatchEntryStatusType0 | Literal['not_found']): Job status. `not_found` covers an unknown id and
            a job the caller may not read alike.
        dataset_id (None | Unset | UUID):
        progress (float | None | Unset):
        current_step (JobStatusBatchEntryCurrentStepType0 | None | Unset):
        error_code (None | str | Unset):
        warnings (list[DbfTruncationCollisionWarning | MercatorClipWarning | ReservedRenameWarning] | Unset):
        can_retry (bool | Unset):  Default: False.
        refresh_run (JobRefreshRunSummary | None | Unset): The refresh run bound to a reupload or manifest update job.
    """

    id: UUID
    status: JobStatusBatchEntryStatusType0 | Literal["not_found"]
    dataset_id: None | Unset | UUID = UNSET
    progress: float | None | Unset = UNSET
    current_step: JobStatusBatchEntryCurrentStepType0 | None | Unset = UNSET
    error_code: None | str | Unset = UNSET
    warnings: (
        list[
            DbfTruncationCollisionWarning | MercatorClipWarning | ReservedRenameWarning
        ]
        | Unset
    ) = UNSET
    can_retry: bool | Unset = False
    refresh_run: JobRefreshRunSummary | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.dbf_truncation_collision_warning import (
            DbfTruncationCollisionWarning,
        )
        from ..models.job_refresh_run_summary import JobRefreshRunSummary
        from ..models.reserved_rename_warning import ReservedRenameWarning

        id = str(self.id)

        status: Literal["not_found"] | str
        if isinstance(self.status, str):
            status = self.status
        else:
            status = self.status

        dataset_id: None | str | Unset
        if isinstance(self.dataset_id, Unset):
            dataset_id = UNSET
        elif isinstance(self.dataset_id, UUID):
            dataset_id = str(self.dataset_id)
        else:
            dataset_id = self.dataset_id

        progress: float | None | Unset
        if isinstance(self.progress, Unset):
            progress = UNSET
        else:
            progress = self.progress

        current_step: None | str | Unset
        if isinstance(self.current_step, Unset):
            current_step = UNSET
        elif isinstance(self.current_step, str):
            current_step = self.current_step
        else:
            current_step = self.current_step

        error_code: None | str | Unset
        if isinstance(self.error_code, Unset):
            error_code = UNSET
        else:
            error_code = self.error_code

        warnings: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.warnings, Unset):
            warnings = []
            for warnings_item_data in self.warnings:
                warnings_item: dict[str, Any]
                if isinstance(warnings_item_data, ReservedRenameWarning):
                    warnings_item = warnings_item_data.to_dict()
                elif isinstance(warnings_item_data, DbfTruncationCollisionWarning):
                    warnings_item = warnings_item_data.to_dict()
                else:
                    warnings_item = warnings_item_data.to_dict()

                warnings.append(warnings_item)

        can_retry = self.can_retry

        refresh_run: dict[str, Any] | None | Unset
        if isinstance(self.refresh_run, Unset):
            refresh_run = UNSET
        elif isinstance(self.refresh_run, JobRefreshRunSummary):
            refresh_run = self.refresh_run.to_dict()
        else:
            refresh_run = self.refresh_run

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "status": status,
            }
        )
        if dataset_id is not UNSET:
            field_dict["dataset_id"] = dataset_id
        if progress is not UNSET:
            field_dict["progress"] = progress
        if current_step is not UNSET:
            field_dict["current_step"] = current_step
        if error_code is not UNSET:
            field_dict["error_code"] = error_code
        if warnings is not UNSET:
            field_dict["warnings"] = warnings
        if can_retry is not UNSET:
            field_dict["can_retry"] = can_retry
        if refresh_run is not UNSET:
            field_dict["refresh_run"] = refresh_run

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dbf_truncation_collision_warning import (
            DbfTruncationCollisionWarning,
        )
        from ..models.job_refresh_run_summary import JobRefreshRunSummary
        from ..models.mercator_clip_warning import MercatorClipWarning
        from ..models.reserved_rename_warning import ReservedRenameWarning

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        def _parse_status(
            data: object,
        ) -> JobStatusBatchEntryStatusType0 | Literal["not_found"]:
            try:
                if not isinstance(data, str):
                    raise TypeError()
                status_type_0 = check_job_status_batch_entry_status_type_0(data)

                return status_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            status_type_1 = cast(Literal["not_found"], data)
            if status_type_1 != "not_found":
                raise ValueError(
                    f"status_type_1 must match const 'not_found', got '{status_type_1}'"
                )
            return status_type_1

        status = _parse_status(d.pop("status"))

        def _parse_dataset_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                dataset_id_type_0 = UUID(data)

                return dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        dataset_id = _parse_dataset_id(d.pop("dataset_id", UNSET))

        def _parse_progress(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        progress = _parse_progress(d.pop("progress", UNSET))

        def _parse_current_step(
            data: object,
        ) -> JobStatusBatchEntryCurrentStepType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                current_step_type_0 = check_job_status_batch_entry_current_step_type_0(
                    data
                )

                return current_step_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(JobStatusBatchEntryCurrentStepType0 | None | Unset, data)

        current_step = _parse_current_step(d.pop("current_step", UNSET))

        def _parse_error_code(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error_code = _parse_error_code(d.pop("error_code", UNSET))

        _warnings = d.pop("warnings", UNSET)
        warnings: (
            list[
                DbfTruncationCollisionWarning
                | MercatorClipWarning
                | ReservedRenameWarning
            ]
            | Unset
        ) = UNSET
        if _warnings is not UNSET:
            warnings = []
            for warnings_item_data in _warnings:

                def _parse_warnings_item(
                    data: object,
                ) -> (
                    DbfTruncationCollisionWarning
                    | MercatorClipWarning
                    | ReservedRenameWarning
                ):
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        warnings_item_type_0 = ReservedRenameWarning.from_dict(data)

                        return warnings_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        warnings_item_type_1 = DbfTruncationCollisionWarning.from_dict(
                            data
                        )

                        return warnings_item_type_1
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    warnings_item_type_2 = MercatorClipWarning.from_dict(data)

                    return warnings_item_type_2

                warnings_item = _parse_warnings_item(warnings_item_data)

                warnings.append(warnings_item)

        can_retry = d.pop("can_retry", UNSET)

        def _parse_refresh_run(data: object) -> JobRefreshRunSummary | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                refresh_run_type_0 = JobRefreshRunSummary.from_dict(data)

                return refresh_run_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(JobRefreshRunSummary | None | Unset, data)

        refresh_run = _parse_refresh_run(d.pop("refresh_run", UNSET))

        job_status_batch_entry = cls(
            id=id,
            status=status,
            dataset_id=dataset_id,
            progress=progress,
            current_step=current_step,
            error_code=error_code,
            warnings=warnings,
            can_retry=can_retry,
            refresh_run=refresh_run,
        )

        job_status_batch_entry.additional_properties = d
        return job_status_batch_entry

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
