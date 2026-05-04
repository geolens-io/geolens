from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.manifest_source_type import check_manifest_source_type
from ..models.manifest_source_type import ManifestSourceType
from typing import cast


T = TypeVar("T", bound="ManifestSource")


@_attrs_define
class ManifestSource:
    """
    Attributes:
        type_ (ManifestSourceType):
        uri (str): Relative path, HTTP(S) URL, or storage URI.
        description (None | str | Unset):
        format_ (None | str | Unset):
        layer (None | str | Unset):
        title (None | str | Unset):
    """

    type_: ManifestSourceType
    uri: str
    description: None | str | Unset = UNSET
    format_: None | str | Unset = UNSET
    layer: None | str | Unset = UNSET
    title: None | str | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        type_: str = self.type_

        uri = self.uri

        description: None | str | Unset
        if isinstance(self.description, Unset):
            description = UNSET
        else:
            description = self.description

        format_: None | str | Unset
        if isinstance(self.format_, Unset):
            format_ = UNSET
        else:
            format_ = self.format_

        layer: None | str | Unset
        if isinstance(self.layer, Unset):
            layer = UNSET
        else:
            layer = self.layer

        title: None | str | Unset
        if isinstance(self.title, Unset):
            title = UNSET
        else:
            title = self.title

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "type": type_,
                "uri": uri,
            }
        )
        if description is not UNSET:
            field_dict["description"] = description
        if format_ is not UNSET:
            field_dict["format"] = format_
        if layer is not UNSET:
            field_dict["layer"] = layer
        if title is not UNSET:
            field_dict["title"] = title

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        type_ = check_manifest_source_type(d.pop("type"))

        uri = d.pop("uri")

        def _parse_description(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        description = _parse_description(d.pop("description", UNSET))

        def _parse_format_(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        format_ = _parse_format_(d.pop("format", UNSET))

        def _parse_layer(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        layer = _parse_layer(d.pop("layer", UNSET))

        def _parse_title(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        title = _parse_title(d.pop("title", UNSET))

        manifest_source = cls(
            type_=type_,
            uri=uri,
            description=description,
            format_=format_,
            layer=layer,
            title=title,
        )

        return manifest_source
