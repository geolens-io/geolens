from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.database_import_request_visibility import (
    check_database_import_request_visibility,
)
from ..models.database_import_request_visibility import DatabaseImportRequestVisibility
from typing import cast


T = TypeVar("T", bound="DatabaseImportRequest")


@_attrs_define
class DatabaseImportRequest:
    """
    Attributes:
        schema_name (str): Schema of the table, as listed.
        table_name (str): Table or view name, as listed.
        title (None | str | Unset): Dataset title. Defaults to the table name.
        summary (None | str | Unset): Optional dataset description shown in the catalog.
        visibility (DatabaseImportRequestVisibility | Unset): Dataset visibility: private, restricted, internal or
            public. Default: 'private'.
        srid_override (int | None | Unset): EPSG code the table's coordinates are read under when the table has no SRID
            of its own: its geometries have SRID 0 or it has no rows. A table with an SRID is always read under that SRID.
    """

    schema_name: str
    table_name: str
    title: None | str | Unset = UNSET
    summary: None | str | Unset = UNSET
    visibility: DatabaseImportRequestVisibility | Unset = "private"
    srid_override: int | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        schema_name = self.schema_name

        table_name = self.table_name

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        summary: None | str | Unset
        if isinstance(self.summary, Unset):
            summary = UNSET
        else:
            summary = self.summary

        visibility: str | Unset = UNSET
        if not isinstance(self.visibility, Unset):
            visibility = self.visibility

        srid_override: int | None | Unset
        if isinstance(self.srid_override, Unset):
            srid_override = UNSET
        else:
            srid_override = self.srid_override

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "schema_name": schema_name,
                "table_name": table_name,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title
        if summary is not UNSET:
            field_dict["summary"] = summary
        if visibility is not UNSET:
            field_dict["visibility"] = visibility
        if srid_override is not UNSET:
            field_dict["srid_override"] = srid_override

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        schema_name = d.pop("schema_name")

        table_name = d.pop("table_name")

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        def _parse_summary(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        summary = _parse_summary(d.pop("summary", UNSET))

        _visibility = d.pop("visibility", UNSET)
        visibility: DatabaseImportRequestVisibility | Unset
        if isinstance(_visibility, Unset):
            visibility = UNSET
        else:
            visibility = check_database_import_request_visibility(_visibility)

        def _parse_srid_override(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        srid_override = _parse_srid_override(d.pop("srid_override", UNSET))

        database_import_request = cls(
            schema_name=schema_name,
            table_name=table_name,
            title=title,
            summary=summary,
            visibility=visibility,
            srid_override=srid_override,
        )

        return database_import_request
