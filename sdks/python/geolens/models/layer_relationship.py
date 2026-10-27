from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast


T = TypeVar("T", bound="LayerRelationship")


@_attrs_define
class LayerRelationship:
    """An ArcGIS relationship class as one of its two layers declares it.

    Attributes:
        related_layer_id (int | str): ArcGIS ID of the layer or table at the other end.
        id (int | None | Unset): Relationship ID on the layer.
        name (None | str | Unset): Relationship class name.
        cardinality (None | str | Unset): 'OneToOne', 'OneToMany' or 'ManyToMany', when the service says.
        role (None | str | Unset): 'Origin' or 'Destination': this layer's end of the relationship.
    """

    related_layer_id: int | str
    id: int | None | Unset = UNSET
    name: None | str | Unset = UNSET
    cardinality: None | str | Unset = UNSET
    role: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        related_layer_id: int | str
        related_layer_id = self.related_layer_id

        id: int | None | Unset
        if isinstance(self.id, Unset):
            id = UNSET
        else:
            id = self.id

        name: None | str | Unset
        if isinstance(self.name, Unset):
            name = UNSET
        else:
            name = self.name

        cardinality: None | str | Unset
        if isinstance(self.cardinality, Unset):
            cardinality = UNSET
        else:
            cardinality = self.cardinality

        role: None | str | Unset
        if isinstance(self.role, Unset):
            role = UNSET
        else:
            role = self.role

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "related_layer_id": related_layer_id,
            }
        )
        if id is not UNSET:
            field_dict["id"] = id
        if name is not UNSET:
            field_dict["name"] = name
        if cardinality is not UNSET:
            field_dict["cardinality"] = cardinality
        if role is not UNSET:
            field_dict["role"] = role

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)

        def _parse_related_layer_id(data: object) -> int | str:
            return cast(int | str, data)

        related_layer_id = _parse_related_layer_id(d.pop("related_layer_id"))

        def _parse_id(data: object) -> int | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(int | None | Unset, data)

        id = _parse_id(d.pop("id", UNSET))

        def _parse_name(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        name = _parse_name(d.pop("name", UNSET))

        def _parse_cardinality(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        cardinality = _parse_cardinality(d.pop("cardinality", UNSET))

        def _parse_role(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        role = _parse_role(d.pop("role", UNSET))

        layer_relationship = cls(
            related_layer_id=related_layer_id,
            id=id,
            name=name,
            cardinality=cardinality,
            role=role,
        )

        layer_relationship.additional_properties = d
        return layer_relationship

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
