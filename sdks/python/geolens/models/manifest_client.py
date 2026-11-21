from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ManifestClient")


@_attrs_define
class ManifestClient:
    """The publishing client that built the manifest.

    Attributes:
        id (str):
        version (str):
        app (None | str | Unset):
        project (None | str | Unset):
    """

    id: str
    version: str
    app: None | str | Unset = UNSET
    project: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        id = self.id

        version = self.version

        app: None | str | Unset
        if isinstance(self.app, Unset):
            app = UNSET
        else:
            app = self.app

        project: None | str | Unset
        if isinstance(self.project, Unset):
            project = UNSET
        else:
            project = self.project

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "id": id,
                "version": version,
            }
        )
        if app is not UNSET:
            field_dict["app"] = app
        if project is not UNSET:
            field_dict["project"] = project

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        id = d.pop("id")

        version = d.pop("version")

        def _parse_app(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        app = _parse_app(d.pop("app", UNSET))

        def _parse_project(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        project = _parse_project(d.pop("project", UNSET))

        manifest_client = cls(
            id=id,
            version=version,
            app=app,
            project=project,
        )

        return manifest_client
