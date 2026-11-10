from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="MapPatch")


@_attrs_define
class MapPatch:
    """Partial map update. PUT /maps/{map_id} edits the map's content.

    Attributes:
        owner_id (UUID): Admin only: transfer the map to this active user.
        expected_updated_at (datetime.datetime | None | Unset): The map's `updated_at` the caller read. When set and the
            map has changed since, nothing is written and the answer is 409 with `detail.code` `stale_write`. Omit it to
            write unconditionally.
    """

    owner_id: UUID
    expected_updated_at: datetime.datetime | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        owner_id = str(self.owner_id)

        expected_updated_at: None | str | Unset
        if isinstance(self.expected_updated_at, Unset):
            expected_updated_at = UNSET
        elif isinstance(self.expected_updated_at, datetime.datetime):
            expected_updated_at = self.expected_updated_at.isoformat()
        else:
            expected_updated_at = self.expected_updated_at

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "owner_id": owner_id,
            }
        )
        if expected_updated_at is not UNSET:
            field_dict["expected_updated_at"] = expected_updated_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        owner_id = UUID(d.pop("owner_id"))

        def _parse_expected_updated_at(
            data: object,
        ) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                expected_updated_at_type_0 = isoparse(data)

                return expected_updated_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        expected_updated_at = _parse_expected_updated_at(
            d.pop("expected_updated_at", UNSET)
        )

        map_patch = cls(
            owner_id=owner_id,
            expected_updated_at=expected_updated_at,
        )

        return map_patch
