from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


from dateutil.parser import isoparse
from uuid import UUID
import datetime

if TYPE_CHECKING:
    from ..models.saved_search_response_params import SavedSearchResponseParams


T = TypeVar("T", bound="SavedSearchResponse")


@_attrs_define
class SavedSearchResponse:
    """Response for a single saved search.

    Attributes:
        id (UUID):
        name (str):
        params (SavedSearchResponseParams):
        created_at (datetime.datetime):
        updated_at (datetime.datetime):
    """

    id: UUID
    name: str
    params: SavedSearchResponseParams
    created_at: datetime.datetime
    updated_at: datetime.datetime
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        id = str(self.id)

        name = self.name

        params = self.params.to_dict()

        created_at = self.created_at.isoformat()

        updated_at = self.updated_at.isoformat()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "id": id,
                "name": name,
                "params": params,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.saved_search_response_params import SavedSearchResponseParams

        d = dict(src_dict)
        id = UUID(d.pop("id"))

        name = d.pop("name")

        params = SavedSearchResponseParams.from_dict(d.pop("params"))

        created_at = isoparse(d.pop("created_at"))

        updated_at = isoparse(d.pop("updated_at"))

        saved_search_response = cls(
            id=id,
            name=name,
            params=params,
            created_at=created_at,
            updated_at=updated_at,
        )

        saved_search_response.additional_properties = d
        return saved_search_response

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
