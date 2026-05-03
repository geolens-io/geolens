from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field


if TYPE_CHECKING:
    from ..models.connectivity_result_oidc_providers import (
        ConnectivityResultOidcProviders,
    )
    from ..models.service_probe_result import ServiceProbeResult


T = TypeVar("T", bound="ConnectivityResult")


@_attrs_define
class ConnectivityResult:
    """Aggregate connectivity validation result.

    Attributes:
        cache (ServiceProbeResult): Result of a single service connectivity probe.
        oidc_providers (ConnectivityResultOidcProviders): Per-provider OIDC discovery probe results, keyed by provider
            slug.
        storage (ServiceProbeResult): Result of a single service connectivity probe.
    """

    cache: ServiceProbeResult
    oidc_providers: ConnectivityResultOidcProviders
    storage: ServiceProbeResult
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        cache = self.cache.to_dict()

        oidc_providers = self.oidc_providers.to_dict()

        storage = self.storage.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "cache": cache,
                "oidc_providers": oidc_providers,
                "storage": storage,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.connectivity_result_oidc_providers import (
            ConnectivityResultOidcProviders,
        )
        from ..models.service_probe_result import ServiceProbeResult

        d = dict(src_dict)
        cache = ServiceProbeResult.from_dict(d.pop("cache"))

        oidc_providers = ConnectivityResultOidcProviders.from_dict(
            d.pop("oidc_providers")
        )

        storage = ServiceProbeResult.from_dict(d.pop("storage"))

        connectivity_result = cls(
            cache=cache,
            oidc_providers=oidc_providers,
            storage=storage,
        )

        connectivity_result.additional_properties = d
        return connectivity_result

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
