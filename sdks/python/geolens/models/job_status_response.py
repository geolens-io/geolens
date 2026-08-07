from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.job_status_response_current_step_type_0 import (
    check_job_status_response_current_step_type_0,
)
from ..models.job_status_response_current_step_type_0 import (
    JobStatusResponseCurrentStepType0,
)
from ..models.job_status_response_status import check_job_status_response_status
from ..models.job_status_response_status import JobStatusResponseStatus
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.dbf_truncation_collision_warning import DbfTruncationCollisionWarning
    from ..models.job_status_response_temporal_parse_errors import (
        JobStatusResponseTemporalParseErrors,
    )
    from ..models.mercator_clip_warning import MercatorClipWarning
    from ..models.reserved_rename_warning import ReservedRenameWarning


T = TypeVar("T", bound="JobStatusResponse")


@_attrs_define
class JobStatusResponse:
    """
    Attributes:
        id (UUID):
        status (JobStatusResponseStatus):
        dataset_id (None | UUID):
        source_filename (None | str):
        error_message (None | str):
        can_retry (bool):
        retry_reason (None | str):
        started_at (datetime.datetime | None):
        completed_at (datetime.datetime | None):
        created_at (datetime.datetime):
        warning_message (None | str | Unset):
        warnings (list[DbfTruncationCollisionWarning | MercatorClipWarning | ReservedRenameWarning] | Unset):
        progress (float | None | Unset):
        current_step (JobStatusResponseCurrentStepType0 | None | Unset):
        rows_processed (int | None | Unset):
        archive_failed (bool | Unset):  Default: False.
        temporal_parse_errors (JobStatusResponseTemporalParseErrors | Unset):
    """

    id: UUID
    status: JobStatusResponseStatus
    dataset_id: None | UUID
    source_filename: None | str
    error_message: None | str
    can_retry: bool
    retry_reason: None | str
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    created_at: datetime.datetime
    warning_message: None | str | Unset = UNSET
    warnings: (
        list[
            DbfTruncationCollisionWarning | MercatorClipWarning | ReservedRenameWarning
        ]
        | Unset
    ) = UNSET
    progress: float | None | Unset = UNSET
    current_step: JobStatusResponseCurrentStepType0 | None | Unset = UNSET
    rows_processed: int | None | Unset = UNSET
    archive_failed: bool | Unset = False
    temporal_parse_errors: JobStatusResponseTemporalParseErrors | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.dbf_truncation_collision_warning import (
            DbfTruncationCollisionWarning,
        )
        from ..models.reserved_rename_warning import ReservedRenameWarning

        id = str(self.id)

        status: str = self.status

        dataset_id: None | str
        if isinstance(self.dataset_id, UUID):
            dataset_id = str(self.dataset_id)
        else:
            dataset_id = self.dataset_id

        source_filename: None | str
        source_filename = self.source_filename

        error_message: None | str
        error_message = self.error_message

        can_retry = self.can_retry

        retry_reason: None | str
        retry_reason = self.retry_reason

        started_at: None | str
        if isinstance(self.started_at, datetime.datetime):
            started_at = self.started_at.isoformat()
        else:
            started_at = self.started_at

        completed_at: None | str
        if isinstance(self.completed_at, datetime.datetime):
            completed_at = self.completed_at.isoformat()
        else:
            completed_at = self.completed_at

        created_at = self.created_at.isoformat()

        warning_message: None | str | Unset
        if isinstance(self.warning_message, Unset):
            warning_message = UNSET
        else:
            warning_message = self.warning_message

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

        rows_processed: int | None | Unset
        if isinstance(self.rows_processed, Unset):
            rows_processed = UNSET
        else:
            rows_processed = self.rows_processed

        archive_failed = self.archive_failed

        temporal_parse_errors: dict[str, Any] | Unset = UNSET
        if not isinstance(self.temporal_parse_errors, Unset):
            temporal_parse_errors = self.temporal_parse_errors.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "status": status,
                "dataset_id": dataset_id,
                "source_filename": source_filename,
                "error_message": error_message,
                "can_retry": can_retry,
                "retry_reason": retry_reason,
                "started_at": started_at,
                "completed_at": completed_at,
                "created_at": created_at,
            }
        )
        if warning_message is not UNSET:
            field_dict["warning_message"] = warning_message
        if warnings is not UNSET:
            field_dict["warnings"] = warnings
        if progress is not UNSET:
            field_dict["progress"] = progress
        if current_step is not UNSET:
            field_dict["current_step"] = current_step
        if rows_processed is not UNSET:
            field_dict["rows_processed"] = rows_processed
        if archive_failed is not UNSET:
            field_dict["archive_failed"] = archive_failed
        if temporal_parse_errors is not UNSET:
            field_dict["temporal_parse_errors"] = temporal_parse_errors

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.dbf_truncation_collision_warning import (
            DbfTruncationCollisionWarning,
        )
        from ..models.job_status_response_temporal_parse_errors import (
            JobStatusResponseTemporalParseErrors,
        )
        from ..models.mercator_clip_warning import MercatorClipWarning
        from ..models.reserved_rename_warning import ReservedRenameWarning

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        status = check_job_status_response_status(d.pop("status"))

        def _parse_dataset_id(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                dataset_id_type_0 = UUID(data)

                return dataset_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        dataset_id = _parse_dataset_id(d.pop("dataset_id"))

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        def _parse_error_message(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        error_message = _parse_error_message(d.pop("error_message"))

        can_retry = d.pop("can_retry")

        def _parse_retry_reason(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        retry_reason = _parse_retry_reason(d.pop("retry_reason"))

        def _parse_started_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                started_at_type_0 = isoparse(data)

                return started_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        started_at = _parse_started_at(d.pop("started_at"))

        def _parse_completed_at(data: object) -> datetime.datetime | None:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                completed_at_type_0 = isoparse(data)

                return completed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None, data)

        completed_at = _parse_completed_at(d.pop("completed_at"))

        created_at = isoparse(d.pop("created_at"))

        def _parse_warning_message(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        warning_message = _parse_warning_message(d.pop("warning_message", UNSET))

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

        def _parse_progress(data: object) -> float | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | Unset, data)

        progress = _parse_progress(d.pop("progress", UNSET))

        def _parse_current_step(
            data: object,
        ) -> JobStatusResponseCurrentStepType0 | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                current_step_type_0 = check_job_status_response_current_step_type_0(
                    data
                )

                return current_step_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(JobStatusResponseCurrentStepType0 | None | Unset, data)

        current_step = _parse_current_step(d.pop("current_step", UNSET))

        def _parse_rows_processed(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        rows_processed = _parse_rows_processed(d.pop("rows_processed", UNSET))

        archive_failed = d.pop("archive_failed", UNSET)

        _temporal_parse_errors = d.pop("temporal_parse_errors", UNSET)
        temporal_parse_errors: JobStatusResponseTemporalParseErrors | Unset
        if isinstance(_temporal_parse_errors, Unset):
            temporal_parse_errors = UNSET
        else:
            temporal_parse_errors = JobStatusResponseTemporalParseErrors.from_dict(
                _temporal_parse_errors
            )

        job_status_response = cls(
            id=id,
            status=status,
            dataset_id=dataset_id,
            source_filename=source_filename,
            error_message=error_message,
            can_retry=can_retry,
            retry_reason=retry_reason,
            started_at=started_at,
            completed_at=completed_at,
            created_at=created_at,
            warning_message=warning_message,
            warnings=warnings,
            progress=progress,
            current_step=current_step,
            rows_processed=rows_processed,
            archive_failed=archive_failed,
            temporal_parse_errors=temporal_parse_errors,
        )

        job_status_response.additional_properties = d
        return job_status_response

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
