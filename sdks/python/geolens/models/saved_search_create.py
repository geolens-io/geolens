from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.saved_search_create_params import SavedSearchCreateParams


T = TypeVar("T", bound="SavedSearchCreate")


@_attrs_define
class SavedSearchCreate:
    """Request body for creating a saved search.

    Attributes:
        name (str):
        params (SavedSearchCreateParams): Serialized SearchParams filters to replay
    """

    name: str
    params: SavedSearchCreateParams
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        params = self.params.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
                "params": params,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.saved_search_create_params import SavedSearchCreateParams

        d = dict(src_dict)
        name = d.pop("name")

        params = SavedSearchCreateParams.from_dict(d.pop("params"))

        saved_search_create = cls(
            name=name,
            params=params,
        )

        saved_search_create.additional_properties = d
        return saved_search_create

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
