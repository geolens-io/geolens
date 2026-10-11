from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define


from uuid import UUID


T = TypeVar("T", bound="MapPatch")


@_attrs_define
class MapPatch:
    """Partial map update. PUT /maps/{map_id} edits the map's content.

    Attributes:
        owner_id (UUID): Admin only: transfer the map to this active user.
    """

    owner_id: UUID

    def to_dict(self) -> dict[str, Any]:
        owner_id = str(self.owner_id)

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "owner_id": owner_id,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        owner_id = UUID(d.pop("owner_id"))

        map_patch = cls(
            owner_id=owner_id,
        )

        return map_patch
