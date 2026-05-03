from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset


if TYPE_CHECKING:
    from ..models.infrastructure_config import InfrastructureConfig
    from ..models.infrastructure_response_health import InfrastructureResponseHealth
    from ..models.infrastructure_response_oidc_providers import (
        InfrastructureResponseOidcProviders,
    )


T = TypeVar("T", bound="InfrastructureResponse")


@_attrs_define
class InfrastructureResponse:
    """
    Attributes:
        config (InfrastructureConfig):
        health (InfrastructureResponseHealth): Health probe results keyed by provider name (db, storage, cache, llm,
            embedding).
        oidc_providers (InfrastructureResponseOidcProviders | Unset): Health probe results for configured OAuth/OIDC
            providers, keyed by slug.
    """

    config: InfrastructureConfig
    health: InfrastructureResponseHealth
    oidc_providers: InfrastructureResponseOidcProviders | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        config = self.config.to_dict()

        health = self.health.to_dict()

        oidc_providers: dict[str, Any] | Unset = UNSET
        if not isinstance(self.oidc_providers, Unset):
            oidc_providers = self.oidc_providers.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "config": config,
                "health": health,
            }
        )
        if oidc_providers is not UNSET:
            field_dict["oidc_providers"] = oidc_providers

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.infrastructure_config import InfrastructureConfig
        from ..models.infrastructure_response_health import InfrastructureResponseHealth
        from ..models.infrastructure_response_oidc_providers import (
            InfrastructureResponseOidcProviders,
        )

        d = dict(src_dict)
        config = InfrastructureConfig.from_dict(d.pop("config"))

        health = InfrastructureResponseHealth.from_dict(d.pop("health"))

        _oidc_providers = d.pop("oidc_providers", UNSET)
        oidc_providers: InfrastructureResponseOidcProviders | Unset
        if isinstance(_oidc_providers, Unset):
            oidc_providers = UNSET
        else:
            oidc_providers = InfrastructureResponseOidcProviders.from_dict(
                _oidc_providers
            )

        infrastructure_response = cls(
            config=config,
            health=health,
            oidc_providers=oidc_providers,
        )

        infrastructure_response.additional_properties = d
        return infrastructure_response

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
