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

if TYPE_CHECKING:
    from ..models.manifest_catalog import ManifestCatalog
    from ..models.manifest_client import ManifestClient
    from ..models.manifest_dataset import ManifestDataset


T = TypeVar("T", bound="ManifestApplyRequest")


@_attrs_define
class ManifestApplyRequest:
    """
    Attributes:
        manifest_version (ManifestApplyRequestManifestVersion): Manifest format. Version 2 adds `client`, which it
            requires, and `upload:<job_id>` sources.
        catalog (ManifestCatalog):
        datasets (list[ManifestDataset]):
        dry_run (bool | Unset):  Default: False.
        client (ManifestClient | None | Unset): The publishing client. Required in version 2, refused in 1.
    """

    manifest_version: ManifestApplyRequestManifestVersion
    catalog: ManifestCatalog
    datasets: list[ManifestDataset]
    dry_run: bool | Unset = False
    client: ManifestClient | None | Unset = UNSET

    def to_dict(self) -> dict[str, Any]:
        from ..models.manifest_client import ManifestClient

        manifest_version: str = self.manifest_version

        catalog = self.catalog.to_dict()

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

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "manifest_version": manifest_version,
                "catalog": catalog,
                "datasets": datasets,
            }
        )
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run
        if client is not UNSET:
            field_dict["client"] = client

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_catalog import ManifestCatalog
        from ..models.manifest_client import ManifestClient
        from ..models.manifest_dataset import ManifestDataset

        d = dict(src_dict)
        manifest_version = check_manifest_apply_request_manifest_version(
            d.pop("manifest_version")
        )

        catalog = ManifestCatalog.from_dict(d.pop("catalog"))

        datasets = []
        _datasets = d.pop("datasets")
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

        manifest_apply_request = cls(
            manifest_version=manifest_version,
            catalog=catalog,
            datasets=datasets,
            dry_run=dry_run,
            client=client,
        )

        return manifest_apply_request
