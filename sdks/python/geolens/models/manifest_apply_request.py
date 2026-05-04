from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define

from ..types import UNSET, Unset

from typing import cast
from typing import Literal

if TYPE_CHECKING:
    from ..models.manifest_catalog import ManifestCatalog
    from ..models.manifest_dataset import ManifestDataset


T = TypeVar("T", bound="ManifestApplyRequest")


@_attrs_define
class ManifestApplyRequest:
    """
    Attributes:
        catalog (ManifestCatalog):
        datasets (list[ManifestDataset]):
        manifest_version (Literal['1']):
        dry_run (bool | Unset):  Default: False.
    """

    catalog: ManifestCatalog
    datasets: list[ManifestDataset]
    manifest_version: Literal["1"]
    dry_run: bool | Unset = False

    def to_dict(self) -> dict[str, Any]:
        catalog = self.catalog.to_dict()

        datasets = []
        for datasets_item_data in self.datasets:
            datasets_item = datasets_item_data.to_dict()
            datasets.append(datasets_item)

        manifest_version = self.manifest_version

        dry_run = self.dry_run

        field_dict: dict[str, Any] = {}

        field_dict.update(
            {
                "catalog": catalog,
                "datasets": datasets,
                "manifest_version": manifest_version,
            }
        )
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.manifest_catalog import ManifestCatalog
        from ..models.manifest_dataset import ManifestDataset

        d = dict(src_dict)
        catalog = ManifestCatalog.from_dict(d.pop("catalog"))

        datasets = []
        _datasets = d.pop("datasets")
        for datasets_item_data in _datasets:
            datasets_item = ManifestDataset.from_dict(datasets_item_data)

            datasets.append(datasets_item)

        manifest_version = cast(Literal["1"], d.pop("manifest_version"))
        if manifest_version != "1":
            raise ValueError(
                f"manifest_version must match const '1', got '{manifest_version}'"
            )

        dry_run = d.pop("dry_run", UNSET)

        manifest_apply_request = cls(
            catalog=catalog,
            datasets=datasets,
            manifest_version=manifest_version,
            dry_run=dry_run,
        )

        return manifest_apply_request
