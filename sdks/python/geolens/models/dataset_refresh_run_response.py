from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.schema_diff import SchemaDiff


T = TypeVar("T", bound="DatasetRefreshRunResponse")


@_attrs_define
class DatasetRefreshRunResponse:
    """One refresh attempt, success or failure (ADR-002 Decision 4).

    Five fields are redacted for callers who are neither the dataset owner nor
    an admin: ``triggered_by``, ``triggered_by_username``, ``error_code``,
    ``error_message`` and ``schema_diff``. A public dataset's refresh history
    otherwise enumerates who edits it, and failure text leaks internal origin
    detail. The redaction is enumerated against NAMED third-party readers as
    well as anonymous ones — a signed-in stranger is the case that gets
    missed.

        Attributes:
            dataset_id (UUID):
            id (UUID):
            origin_kind (str): upload, postgis, service, stac, or raster
            started_at (datetime.datetime): Dispatch time, not claim time — queue wait is visible
            status (str): pending, running, succeeded, failed, or cancelled
            trigger (str): manual, api, or cli
            claimed_at (datetime.datetime | None | Unset): When a worker began executing the run. Queue wait is this minus
                started_at; null while the run is still queued.
            dataset_version_id (None | Unset | UUID): The version this run produced. Null for a run that never committed a
                swap.
            error_code (None | str | Unset):
            error_message (None | str | Unset): Short redacted failure reason
            feature_count_after (int | None | Unset):
            feature_count_before (int | None | Unset):
            finished_at (datetime.datetime | None | Unset):
            ingest_job_id (None | Unset | UUID): The ingest job that carried out the work. Nulls out when the job row is
                purged by retention; the run itself survives.
            schema_diff (None | SchemaDiff | Unset): Schema drift measured against the incoming data at swap time. Null for
                a run that never reached the swap.
            triggered_by (None | Unset | UUID):
            triggered_by_username (None | str | Unset):
    """

    dataset_id: UUID
    id: UUID
    origin_kind: str
    started_at: datetime.datetime
    status: str
    trigger: str
    claimed_at: datetime.datetime | None | Unset = UNSET
    dataset_version_id: None | Unset | UUID = UNSET
    error_code: None | str | Unset = UNSET
    error_message: None | str | Unset = UNSET
    feature_count_after: int | None | Unset = UNSET
    feature_count_before: int | None | Unset = UNSET
    finished_at: datetime.datetime | None | Unset = UNSET
    ingest_job_id: None | Unset | UUID = UNSET
    schema_diff: None | SchemaDiff | Unset = UNSET
    triggered_by: None | Unset | UUID = UNSET
    triggered_by_username: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.schema_diff import SchemaDiff

        dataset_id = str(self.dataset_id)

        id = str(self.id)

        origin_kind = self.origin_kind

        started_at = self.started_at.isoformat()

        status = self.status

        trigger = self.trigger

        claimed_at: None | str | Unset
        if isinstance(self.claimed_at, Unset):
            claimed_at = UNSET
        elif isinstance(self.claimed_at, datetime.datetime):
            claimed_at = self.claimed_at.isoformat()
        else:
            claimed_at = self.claimed_at

        dataset_version_id: None | str | Unset
        if isinstance(self.dataset_version_id, Unset):
            dataset_version_id = UNSET
        elif isinstance(self.dataset_version_id, UUID):
            dataset_version_id = str(self.dataset_version_id)
        else:
            dataset_version_id = self.dataset_version_id

        error_code: None | str | Unset
        if isinstance(self.error_code, Unset):
            error_code = UNSET
        else:
            error_code = self.error_code

        error_message: None | str | Unset
        if isinstance(self.error_message, Unset):
            error_message = UNSET
        else:
            error_message = self.error_message

        feature_count_after: int | None | Unset
        if isinstance(self.feature_count_after, Unset):
            feature_count_after = UNSET
        else:
            feature_count_after = self.feature_count_after

        feature_count_before: int | None | Unset
        if isinstance(self.feature_count_before, Unset):
            feature_count_before = UNSET
        else:
            feature_count_before = self.feature_count_before

        finished_at: None | str | Unset
        if isinstance(self.finished_at, Unset):
            finished_at = UNSET
        elif isinstance(self.finished_at, datetime.datetime):
            finished_at = self.finished_at.isoformat()
        else:
            finished_at = self.finished_at

        ingest_job_id: None | str | Unset
        if isinstance(self.ingest_job_id, Unset):
            ingest_job_id = UNSET
        elif isinstance(self.ingest_job_id, UUID):
            ingest_job_id = str(self.ingest_job_id)
        else:
            ingest_job_id = self.ingest_job_id

        schema_diff: dict[str, Any] | None | Unset
        if isinstance(self.schema_diff, Unset):
            schema_diff = UNSET
        elif isinstance(self.schema_diff, SchemaDiff):
            schema_diff = self.schema_diff.to_dict()
        else:
            schema_diff = self.schema_diff

        triggered_by: None | str | Unset
        if isinstance(self.triggered_by, Unset):
            triggered_by = UNSET
        elif isinstance(self.triggered_by, UUID):
            triggered_by = str(self.triggered_by)
        else:
            triggered_by = self.triggered_by

        triggered_by_username: None | str | Unset
        if isinstance(self.triggered_by_username, Unset):
            triggered_by_username = UNSET
        else:
            triggered_by_username = self.triggered_by_username

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_id": dataset_id,
                "id": id,
                "origin_kind": origin_kind,
                "started_at": started_at,
                "status": status,
                "trigger": trigger,
            }
        )
        if claimed_at is not UNSET:
            field_dict["claimed_at"] = claimed_at
        if dataset_version_id is not UNSET:
            field_dict["dataset_version_id"] = dataset_version_id
        if error_code is not UNSET:
            field_dict["error_code"] = error_code
        if error_message is not UNSET:
            field_dict["error_message"] = error_message
        if feature_count_after is not UNSET:
            field_dict["feature_count_after"] = feature_count_after
        if feature_count_before is not UNSET:
            field_dict["feature_count_before"] = feature_count_before
        if finished_at is not UNSET:
            field_dict["finished_at"] = finished_at
        if ingest_job_id is not UNSET:
            field_dict["ingest_job_id"] = ingest_job_id
        if schema_diff is not UNSET:
            field_dict["schema_diff"] = schema_diff
        if triggered_by is not UNSET:
            field_dict["triggered_by"] = triggered_by
        if triggered_by_username is not UNSET:
            field_dict["triggered_by_username"] = triggered_by_username

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.schema_diff import SchemaDiff

        d = dict(src_dict)
        dataset_id = UUID(d.pop("dataset_id"))

        id = UUID(d.pop("id"))

        origin_kind = d.pop("origin_kind")

        started_at = isoparse(d.pop("started_at"))

        status = d.pop("status")

        trigger = d.pop("trigger")

        def _parse_claimed_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                claimed_at_type_0 = isoparse(data)

                return claimed_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        claimed_at = _parse_claimed_at(d.pop("claimed_at", UNSET))

        def _parse_dataset_version_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                dataset_version_id_type_0 = UUID(data)

                return dataset_version_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        dataset_version_id = _parse_dataset_version_id(
            d.pop("dataset_version_id", UNSET)
        )

        def _parse_error_code(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error_code = _parse_error_code(d.pop("error_code", UNSET))

        def _parse_error_message(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error_message = _parse_error_message(d.pop("error_message", UNSET))

        def _parse_feature_count_after(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count_after = _parse_feature_count_after(
            d.pop("feature_count_after", UNSET)
        )

        def _parse_feature_count_before(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        feature_count_before = _parse_feature_count_before(
            d.pop("feature_count_before", UNSET)
        )

        def _parse_finished_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                finished_at_type_0 = isoparse(data)

                return finished_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        finished_at = _parse_finished_at(d.pop("finished_at", UNSET))

        def _parse_ingest_job_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                ingest_job_id_type_0 = UUID(data)

                return ingest_job_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        ingest_job_id = _parse_ingest_job_id(d.pop("ingest_job_id", UNSET))

        def _parse_schema_diff(data: object) -> None | SchemaDiff | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                schema_diff_type_0 = SchemaDiff.from_dict(data)

                return schema_diff_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | SchemaDiff | Unset, data)

        schema_diff = _parse_schema_diff(d.pop("schema_diff", UNSET))

        def _parse_triggered_by(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                triggered_by_type_0 = UUID(data)

                return triggered_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        triggered_by = _parse_triggered_by(d.pop("triggered_by", UNSET))

        def _parse_triggered_by_username(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        triggered_by_username = _parse_triggered_by_username(
            d.pop("triggered_by_username", UNSET)
        )

        dataset_refresh_run_response = cls(
            dataset_id=dataset_id,
            id=id,
            origin_kind=origin_kind,
            started_at=started_at,
            status=status,
            trigger=trigger,
            claimed_at=claimed_at,
            dataset_version_id=dataset_version_id,
            error_code=error_code,
            error_message=error_message,
            feature_count_after=feature_count_after,
            feature_count_before=feature_count_before,
            finished_at=finished_at,
            ingest_job_id=ingest_job_id,
            schema_diff=schema_diff,
            triggered_by=triggered_by,
            triggered_by_username=triggered_by_username,
        )

        dataset_refresh_run_response.additional_properties = d
        return dataset_refresh_run_response

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
