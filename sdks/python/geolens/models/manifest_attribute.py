from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="ManifestAttribute")


@_attrs_define
class ManifestAttribute:
    """Per-column text for the column named ``source_name`` in the uploaded file.

    Attributes:
        source_name (str):
        title (None | str | Unset):
        description (None | str | Unset):
        units (None | str | Unset):
    """

    source_name: str
    title: None | str | Unset = UNSET
    description: None | str | Unset = UNSET
    units: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        source_name = self.source_name

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        units: None | str | Unset
        if isinstance(self.units, Unset):
            units = UNSET
        else:
            units = self.units

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "source_name": source_name,
            }
        )
        if title is not UNSET:
            field_dict["title"] = title
        if description is not UNSET:
            field_dict["description"] = description
        if units is not UNSET:
            field_dict["units"] = units

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        source_name = d.pop("source_name")

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_units(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        units = _parse_units(d.pop("units", UNSET))

        manifest_attribute = cls(
            source_name=source_name,
            title=title,
            description=description,
            units=units,
        )

        return manifest_attribute
