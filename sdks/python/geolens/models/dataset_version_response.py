from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="DatasetVersionResponse")


@_attrs_define
class DatasetVersionResponse:
    """One version in a dataset's history.

    feat(#1316): ``file_hash`` and ``uploaded_by`` are null for any caller who
    is neither the dataset's owner nor an admin — the same predicate that
    gates ``origin_uri``/``origin_ref`` on the dataset itself and
    ``triggered_by`` on refresh-runs (ADR-002 Decision 4e). Unredacted, a
    public dataset's version history enumerates its editors.

        Attributes:
            id (UUID):
            dataset_id (UUID):
            version_number (int):
            source_filename (None | str):
            source_format (None | str):
            feature_count (int | None):
            srid (int | None):
            geometry_type (None | str):
            file_hash (None | str):
            uploaded_by (None | UUID):
            uploaded_at (datetime.datetime):
    """

    id: UUID
    dataset_id: UUID
    version_number: int
    source_filename: None | str
    source_format: None | str
    feature_count: int | None
    srid: int | None
    geometry_type: None | str
    file_hash: None | str
    uploaded_by: None | UUID
    uploaded_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        dataset_id = str(self.dataset_id)

        version_number = self.version_number

        source_filename: None | str
        source_filename = self.source_filename

        source_format: None | str
        source_format = self.source_format

        feature_count: int | None
        feature_count = self.feature_count

        srid: int | None
        srid = self.srid

        geometry_type: None | str
        geometry_type = self.geometry_type

        file_hash: None | str
        file_hash = self.file_hash

        uploaded_by: None | str
        if isinstance(self.uploaded_by, UUID):
            uploaded_by = str(self.uploaded_by)
        else:
            uploaded_by = self.uploaded_by

        uploaded_at = self.uploaded_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "dataset_id": dataset_id,
                "version_number": version_number,
                "source_filename": source_filename,
                "source_format": source_format,
                "feature_count": feature_count,
                "srid": srid,
                "geometry_type": geometry_type,
                "file_hash": file_hash,
                "uploaded_by": uploaded_by,
                "uploaded_at": uploaded_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = UUID(d.pop("id"))

        dataset_id = UUID(d.pop("dataset_id"))

        version_number = d.pop("version_number")

        def _parse_source_filename(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_filename = _parse_source_filename(d.pop("source_filename"))

        def _parse_source_format(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        source_format = _parse_source_format(d.pop("source_format"))

        def _parse_feature_count(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        feature_count = _parse_feature_count(d.pop("feature_count"))

        def _parse_srid(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        srid = _parse_srid(d.pop("srid"))

        def _parse_geometry_type(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        geometry_type = _parse_geometry_type(d.pop("geometry_type"))

        def _parse_file_hash(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        file_hash = _parse_file_hash(d.pop("file_hash"))

        def _parse_uploaded_by(data: object) -> None | UUID:
            if data is None:
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                uploaded_by_type_0 = UUID(data)

                return uploaded_by_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | UUID, data)

        uploaded_by = _parse_uploaded_by(d.pop("uploaded_by"))

        uploaded_at = isoparse(d.pop("uploaded_at"))

        dataset_version_response = cls(
            id=id,
            dataset_id=dataset_id,
            version_number=version_number,
            source_filename=source_filename,
            source_format=source_format,
            feature_count=feature_count,
            srid=srid,
            geometry_type=geometry_type,
            file_hash=file_hash,
            uploaded_by=uploaded_by,
            uploaded_at=uploaded_at,
        )

        dataset_version_response.additional_properties = d
        return dataset_version_response

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
