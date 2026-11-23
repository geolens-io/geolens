from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast
from uuid import UUID


T = TypeVar("T", bound="ManifestRemovedLayer")


@_attrs_define
class ManifestRemovedLayer:
    """
    Attributes:
        key (str): The removed layer's key.
        dataset_id (UUID): Its dataset, which stays on the server.
        layer_id (None | Unset | UUID): The removed layer's id, which no longer names a layer.
        link (None | str | Unset): The dataset's page in the web app, to delete it there.
    """

    key: str
    dataset_id: UUID
    layer_id: None | Unset | UUID = UNSET
    link: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        key = self.key

        dataset_id = str(self.dataset_id)

        layer_id: None | str | Unset
        if isinstance(self.layer_id, Unset):
            layer_id = UNSET
        elif isinstance(self.layer_id, UUID):
            layer_id = str(self.layer_id)
        else:
            layer_id = self.layer_id

        link: None | str | Unset
        if isinstance(self.link, Unset):
            link = UNSET
        else:
            link = self.link

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "key": key,
                "dataset_id": dataset_id,
            }
        )
        if layer_id is not UNSET:
            field_dict["layer_id"] = layer_id
        if link is not UNSET:
            field_dict["link"] = link

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        key = d.pop("key")

        dataset_id = UUID(d.pop("dataset_id"))

        def _parse_layer_id(data: object) -> None | Unset | UUID:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                layer_id_type_0 = UUID(data)

                return layer_id_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(None | Unset | UUID, data)

        layer_id = _parse_layer_id(d.pop("layer_id", UNSET))

        def _parse_link(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        link = _parse_link(d.pop("link", UNSET))

        manifest_removed_layer = cls(
            key=key,
            dataset_id=dataset_id,
            layer_id=layer_id,
            link=link,
        )

        manifest_removed_layer.additional_properties = d
        return manifest_removed_layer

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
