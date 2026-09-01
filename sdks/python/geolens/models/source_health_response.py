from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.source_health_response_source_health import (
    check_source_health_response_source_health,
)
from ..models.source_health_response_source_health import (
    SourceHealthResponseSourceHealth,
)
from dateutil.parser import isoparse
from typing import cast
from uuid import UUID
import datetime


T = TypeVar("T", bound="SourceHealthResponse")


@_attrs_define
class SourceHealthResponse:
    """Result of one on-demand origin probe (ADR-002, #1222).

    Shares its first three words with ``VrtSourceHealth.status``, so the UI
    renders one legend across VRT members and standalone origins.
    ``VrtSourceHealth`` carries a fourth, VRT-specific value, ``stale``
    (fix(#1221)): it means a member's raster was replaced after the parent
    VRT was last built, and it does not apply to a single-origin probe. This
    endpoint always probes, so it also never returns the OTHER fourth value,
    ``unknown`` — the response-boundary projection of a never-determined NULL
    column, which reaches clients through ``DatasetResponse``, not through
    here.

        Attributes:
            dataset_id (UUID):
            origin (None | str): Origin kind that was probed: service or stac.
            source_health (SourceHealthResponseSourceHealth): healthy — the origin answered and the resource is there.
                missing — the origin answered authoritatively that it is gone (404/410). inaccessible — GeoLens could not
                determine either way, which includes 401/403: access was lost, the data may be intact.
            source_health_detail (None | str | Unset): Why the origin is not healthy, as one of a fixed set of GeoLens
                codes: auth_required, blocked_by_policy, item_withdrawn, network_error, not_found, server_error, timeout,
                unauthorized, unexpected_status. Null when healthy or never probed. Never provider text, a URL, or a response
                body — nothing the origin sent is stored here.
            last_checked_at (datetime.datetime | None | Unset): When GeoLens last contacted this origin, success or failure.
    """

    dataset_id: UUID
    origin: None | str
    source_health: SourceHealthResponseSourceHealth
    source_health_detail: None | str | Unset = UNSET
    last_checked_at: datetime.datetime | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        dataset_id = str(self.dataset_id)

        origin: None | str
        origin = self.origin

        source_health: str = self.source_health

        source_health_detail: None | str | Unset
        if isinstance(self.source_health_detail, Unset):
            source_health_detail = UNSET
        else:
            source_health_detail = self.source_health_detail

        last_checked_at: None | str | Unset
        if isinstance(self.last_checked_at, Unset):
            last_checked_at = UNSET
        elif isinstance(self.last_checked_at, datetime.datetime):
            last_checked_at = self.last_checked_at.isoformat()
        else:
            last_checked_at = self.last_checked_at

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "dataset_id": dataset_id,
                "origin": origin,
                "source_health": source_health,
            }
        )
        if source_health_detail is not UNSET:
            field_dict["source_health_detail"] = source_health_detail
        if last_checked_at is not UNSET:
            field_dict["last_checked_at"] = last_checked_at

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        dataset_id = UUID(d.pop("dataset_id"))

        def _parse_origin(data: object) -> None | str:
            if data is None:
                return data
            return cast(None | str, data)

        origin = _parse_origin(d.pop("origin"))

        source_health = check_source_health_response_source_health(
            d.pop("source_health")
        )

        def _parse_source_health_detail(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        source_health_detail = _parse_source_health_detail(
            d.pop("source_health_detail", UNSET)
        )

        def _parse_last_checked_at(data: object) -> datetime.datetime | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, str):
                    raise TypeError()
                last_checked_at_type_0 = isoparse(data)

                return last_checked_at_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(datetime.datetime | None | Unset, data)

        last_checked_at = _parse_last_checked_at(d.pop("last_checked_at", UNSET))

        source_health_response = cls(
            dataset_id=dataset_id,
            origin=origin,
            source_health=source_health,
            source_health_detail=source_health_detail,
            last_checked_at=last_checked_at,
        )

        source_health_response.additional_properties = d
        return source_health_response

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
