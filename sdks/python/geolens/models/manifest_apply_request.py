from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from ..models.manifest_apply_request_manifest_version import (
    check_manifest_apply_request_manifest_version,
)
from ..models.manifest_apply_request_manifest_version import (
    ManifestApplyRequestManifestVersion,
)
from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.manifest_catalog import ManifestCatalog
    from ..models.manifest_client import ManifestClient
    from ..models.manifest_dataset import ManifestDataset
    from ..models.manifest_map import ManifestMap


T = TypeVar("T", bound="ManifestApplyRequest")


@_attrs_define
class ManifestApplyRequest:
    """
    Attributes:
        manifest_version (ManifestApplyRequestManifestVersion): Manifest format. Version 2 adds `client`, which it
            requires, and `upload:<job_id>` sources. Version 2 is a preview and may change in any release until the desktop
            connectors ship; version 1 is stable.
        catalog (ManifestCatalog):
        datasets (list[ManifestDataset] | Unset): Required, with at least one entry, in version 1. In version 2 it may
            be empty, or left out, when `maps` is not.
        dry_run (bool | Unset):  Default: False.
        client (ManifestClient | None | Unset): The publishing client. Required in version 2, refused in 1.
        public_fallback (Literal['internal'] | None | Unset): Version 2 only. When public visibility is refused for an
            entry, write it as internal with warning A020 instead of failing it.
        maps (list[ManifestMap] | None | Unset): Version 2 only, which is a preview. Maps built from datasets the caller
            can read, created or updated by key after the request's datasets. A layer can't use a dataset this request only
            queued: send the maps again once its job is complete.
    """

    manifest_version: ManifestApplyRequestManifestVersion
    catalog: ManifestCatalog
    datasets: list[ManifestDataset] | Unset = UNSET
    dry_run: bool | Unset = False
    client: ManifestClient | None | Unset = UNSET
    public_fallback: Literal["internal"] | None | Unset = UNSET
    maps: list[ManifestMap] | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.manifest_client import ManifestClient

        manifest_version: str = self.manifest_version

        catalog = self.catalog.to_dict()

        datasets: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.datasets, Unset):
            datasets = []
            for datasets_item_data in self.datasets:
                datasets_item = datasets_item_data.to_dict()
                datasets.append(datasets_item)

        dry_run = self.dry_run

        client: dict[str, Any] | None | Unset
        if isinstance(self.client, Unset):
            client = UNSET
        elif isinstance(self.client, ManifestClient):
            client = self.client.to_dict()
        else:
            client = self.client

        public_fallback: Literal["internal"] | None | Unset
        if isinstance(self.public_fallback, Unset):
            public_fallback = UNSET
        else:
            public_fallback = self.public_fallback

        maps: list[dict[str, Any]] | None | Unset
        if isinstance(self.maps, Unset):
            maps = UNSET
        elif isinstance(self.maps, list):
            maps = []
            for maps_type_0_item_data in self.maps:
                maps_type_0_item = maps_type_0_item_data.to_dict()
                maps.append(maps_type_0_item)

        else:
            maps = self.maps

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "manifest_version": manifest_version,
                "catalog": catalog,
            }
        )
        if datasets is not UNSET:
            field_dict["datasets"] = datasets
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run
        if client is not UNSET:
            field_dict["client"] = client
        if public_fallback is not UNSET:
            field_dict["public_fallback"] = public_fallback
        if maps is not UNSET:
            field_dict["maps"] = maps

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_catalog import ManifestCatalog
        from ..models.manifest_client import ManifestClient
        from ..models.manifest_dataset import ManifestDataset
        from ..models.manifest_map import ManifestMap

        d = dict(src_dict)
        manifest_version = check_manifest_apply_request_manifest_version(
            d.pop("manifest_version")
        )

        catalog = ManifestCatalog.from_dict(d.pop("catalog"))

        _datasets = d.pop("datasets", UNSET)
        datasets: list[ManifestDataset] | Unset = UNSET
        if _datasets is not UNSET:
            datasets = []
            for datasets_item_data in _datasets:
                datasets_item = ManifestDataset.from_dict(datasets_item_data)

                datasets.append(datasets_item)

        dry_run = d.pop("dry_run", UNSET)

        def _parse_client(data: object) -> ManifestClient | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                client_type_0 = ManifestClient.from_dict(data)

                return client_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(ManifestClient | None | Unset, data)

        client = _parse_client(d.pop("client", UNSET))

        def _parse_public_fallback(data: object) -> Literal["internal"] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            public_fallback_type_0 = cast(Literal["internal"], data)
            if public_fallback_type_0 != "internal":
                raise ValueError(
                    f"public_fallback_type_0 must match const 'internal', got '{public_fallback_type_0}'"
                )
            return public_fallback_type_0
            return cast(Literal["internal"] | None | Unset, data)

        public_fallback = _parse_public_fallback(d.pop("public_fallback", UNSET))

        def _parse_maps(data: object) -> list[ManifestMap] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                maps_type_0 = []
                _maps_type_0 = data
                for maps_type_0_item_data in _maps_type_0:
                    maps_type_0_item = ManifestMap.from_dict(maps_type_0_item_data)

                    maps_type_0.append(maps_type_0_item)

                return maps_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[ManifestMap] | None | Unset, data)

        maps = _parse_maps(d.pop("maps", UNSET))

        manifest_apply_request = cls(
            manifest_version=manifest_version,
            catalog=catalog,
            datasets=datasets,
            dry_run=dry_run,
            client=client,
            public_fallback=public_fallback,
            maps=maps,
        )

        return manifest_apply_request
