from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from ..models.service_probe_result_status import check_service_probe_result_status
from ..models.service_probe_result_status import ServiceProbeResultStatus
from typing import cast


T = TypeVar("T", bound="ServiceProbeResult")


@_attrs_define
class ServiceProbeResult:
    """Result of a single service connectivity probe.

    Attributes:
        name (str): Service name (e.g. 'storage', 'cache', 'oidc:google').
        status (ServiceProbeResultStatus): Probe outcome.
        latency_ms (float): Round-trip latency in milliseconds.
        error (None | str | Unset): Error message when status is 'error'.
    """

    name: str
    status: ServiceProbeResultStatus
    latency_ms: float
    error: None | str | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        status: str = self.status

        latency_ms = self.latency_ms

        error: None | str | Unset
        if isinstance(self.error, Unset):
            error = UNSET
        else:
            error = self.error

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "name": name,
                "status": status,
                "latency_ms": latency_ms,
            }
        )
        if error is not UNSET:
            field_dict["error"] = error

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        name = d.pop("name")

        status = check_service_probe_result_status(d.pop("status"))

        latency_ms = d.pop("latency_ms")

        def _parse_error(data: object) -> None | str | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            return cast(None | str | Unset, data)

        error = _parse_error(d.pop("error", UNSET))

        service_probe_result = cls(
            name=name,
            status=status,
            latency_ms=latency_ms,
            error=error,
        )

        service_probe_result.additional_properties = d
        return service_probe_result

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
