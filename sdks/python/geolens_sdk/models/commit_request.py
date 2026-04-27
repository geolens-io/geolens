from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.commit_request_visibility import check_commit_request_visibility
from ..models.commit_request_visibility import CommitRequestVisibility
from dateutil.parser import isoparse
from typing import cast
import datetime


T = TypeVar("T", bound="CommitRequest")


@_attrs_define
class CommitRequest:
    """Wire-level schema for ``POST /ingest/commit/{job_id}``.

    Preserved as a flat union of all possible commit fields so that the
    FastAPI route signature renders correctly in OpenAPI and so that the
    frontend's ``CommitImportRequest`` TypeScript type stays unchanged.

    The route handler re-validates the body against a subclass chosen by
    ``_pick_commit_subclass(job)`` (see ``app.ingest.router``):

      - ``VectorCommitRequest`` — default for file uploads
      - ``RasterCommitRequest`` — when ``job.user_metadata['file_type'] == 'raster'``
      - ``ServiceCommitRequest`` — when ``job.source_url`` is set and ``job.file_path`` is None

    For new internal code that constructs a commit view, prefer importing
    the appropriate subclass directly. This flat class is the wire contract,
    not an implementation detail.

        Attributes:
            title (str): Human-readable dataset title.
            compression (None | str | Unset): Raster only: target compression for COG output (e.g. 'LZW', 'DEFLATE').
            geom_column (None | str | Unset): CSV/Excel only: name of the WKT geometry column (alternative to
                x_column/y_column).
            layer_name (None | str | Unset): Multi-layer source only: name of the specific layer to ingest.
            nodata_override (float | None | str | Unset): Raster only: nodata value to use when source has none defined.
            resampling (None | str | Unset): Raster only: resampling method for COG conversion (e.g. 'nearest', 'bilinear',
                'cubic').
            srid_override (int | None | Unset): EPSG code to use when source CRS is missing or incorrect. Forces
                reprojection during ingestion.
            summary (None | str | Unset): Optional dataset description shown in the catalog.
            temporal_end (datetime.datetime | None | Unset): ISO 8601 end of the dataset's temporal extent.
            temporal_start (datetime.datetime | None | Unset): ISO 8601 start of the dataset's temporal extent.
            token (None | str | Unset): Optional confirmation token returned by the preview step. Required for some
                workflows.
            visibility (CommitRequestVisibility | Unset): Dataset visibility level: 'private' (owner-only), 'restricted'
                (RBAC-controlled), 'internal' (all users), 'public' (anonymous access). Default: 'private'.
            x_column (None | str | Unset): CSV/Excel only: name of the longitude/X coordinate column.
            y_column (None | str | Unset): CSV/Excel only: name of the latitude/Y coordinate column.
    """

    title: str
    compression: None | str | Unset = UNSET
    geom_column: None | str | Unset = UNSET
    layer_name: None | str | Unset = UNSET
    nodata_override: float | None | str | Unset = UNSET
    resampling: None | str | Unset = UNSET
    srid_override: int | None | Unset = UNSET
    summary: None | str | Unset = UNSET
    temporal_end: datetime.datetime | None | Unset = UNSET
    temporal_start: datetime.datetime | None | Unset = UNSET
    token: None | str | Unset = UNSET
    visibility: CommitRequestVisibility | Unset = "private"
    x_column: None | str | Unset = UNSET
    y_column: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        title = self.title

        compression: None | str | Unset
        if isinstance(self.compression, Unset):
            compression = UNSET
        else:
            compression = self.compression

        geom_column: None | str | Unset
        if isinstance(self.geom_column, Unset):
            geom_column = UNSET
        else:
            geom_column = self.geom_column

        layer_name: None | str | Unset
        if isinstance(self.layer_name, Unset):
            layer_name = UNSET
        else:
            layer_name = self.layer_name

        nodata_override: float | None | str | Unset
        if isinstance(self.nodata_override, Unset):
            nodata_override = UNSET
        else:
            nodata_override = self.nodata_override

        resampling: None | str | Unset
        if isinstance(self.resampling, Unset):
            resampling = UNSET
        else:
            resampling = self.resampling

        srid_override: int | None | Unset
        if isinstance(self.srid_override, Unset):
            srid_override = UNSET
        else:
            srid_override = self.srid_override

        summary: None | str | Unset
        if isinstance(self.summary, Unset):
            summary = UNSET
        else:
            summary = self.summary

        temporal_end: None | str | Unset
        if isinstance(self.temporal_end, Unset):
            temporal_end = UNSET
        elif isinstance(self.temporal_end, datetime.datetime):
            temporal_end = self.temporal_end.isoformat()
        else:
            temporal_end = self.temporal_end

        temporal_start: None | str | Unset
        if isinstance(self.temporal_start, Unset):
            temporal_start = UNSET
        elif isinstance(self.temporal_start, datetime.datetime):
            temporal_start = self.temporal_start.isoformat()
        else:
            temporal_start = self.temporal_start

        token: None | str | Unset
        if isinstance(self.token, Unset):
            token = UNSET
        else:
            token = self.token

        visibility: str | Unset = UNSET
        if not isinstance(self.visibility, Unset):
            visibility = self.visibility

        x_column: None | str | Unset
        if isinstance(self.x_column, Unset):
            x_column = UNSET
        else:
            x_column = self.x_column

        y_column: None | str | Unset
        if isinstance(self.y_column, Unset):
            y_column = UNSET
        else:
            y_column = self.y_column

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "title": title,
            }
        )
        if compression is not UNSET:
            field_dict["compression"] = compression
        if geom_column is not UNSET:
            field_dict["geom_column"] = geom_column
        if layer_name is not UNSET:
            field_dict["layer_name"] = layer_name
        if nodata_override is not UNSET:
            field_dict["nodata_override"] = nodata_override
        if resampling is not UNSET:
            field_dict["resampling"] = resampling
        if srid_override is not UNSET:
            field_dict["srid_override"] = srid_override
        if summary is not UNSET:
            field_dict["summary"] = summary
        if temporal_end is not UNSET:
            field_dict["temporal_end"] = temporal_end
        if temporal_start is not UNSET:
            field_dict["temporal_start"] = temporal_start
        if token is not UNSET:
            field_dict["token"] = token
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if x_column is not UNSET:
            field_dict["x_column"] = x_column
        if y_column is not UNSET:
            field_dict["y_column"] = y_column

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        title = d.pop("title")

        def _parse_compression(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        compression = _parse_compression(d.pop("compression", UNSET))

        def _parse_geom_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        geom_column = _parse_geom_column(d.pop("geom_column", UNSET))

        def _parse_layer_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        layer_name = _parse_layer_name(d.pop("layer_name", UNSET))

        def _parse_nodata_override(data: object) -> float | None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(float | None | str | Unset, data)

        nodata_override = _parse_nodata_override(d.pop("nodata_override", UNSET))

        def _parse_resampling(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        resampling = _parse_resampling(d.pop("resampling", UNSET))

        def _parse_srid_override(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        srid_override = _parse_srid_override(d.pop("srid_override", UNSET))

        def _parse_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        summary = _parse_summary(d.pop("summary", UNSET))

        def _parse_temporal_end(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                temporal_end_type_0 = isoparse(data)

                return temporal_end_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        temporal_end = _parse_temporal_end(d.pop("temporal_end", UNSET))

        def _parse_temporal_start(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                temporal_start_type_0 = isoparse(data)

                return temporal_start_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        temporal_start = _parse_temporal_start(d.pop("temporal_start", UNSET))

        def _parse_token(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        token = _parse_token(d.pop("token", UNSET))

        _visibility = d.pop("visibility", UNSET)
        visibility: CommitRequestVisibility | Unset
        if isinstance(_visibility, Unset):
            visibility = UNSET
        else:
            visibility = check_commit_request_visibility(_visibility)

        def _parse_x_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        x_column = _parse_x_column(d.pop("x_column", UNSET))

        def _parse_y_column(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        y_column = _parse_y_column(d.pop("y_column", UNSET))

        commit_request = cls(
            title=title,
            compression=compression,
            geom_column=geom_column,
            layer_name=layer_name,
            nodata_override=nodata_override,
            resampling=resampling,
            srid_override=srid_override,
            summary=summary,
            temporal_end=temporal_end,
            temporal_start=temporal_start,
            token=token,
            visibility=visibility,
            x_column=x_column,
            y_column=y_column,
        )

        commit_request.additional_properties = d
        return commit_request

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
