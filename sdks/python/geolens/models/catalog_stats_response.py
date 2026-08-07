from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, TYPE_CHECKING

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

from typing import cast

if TYPE_CHECKING:
    from ..models.catalog_stats_response_datasets_by_geometry_type import (
        CatalogStatsResponseDatasetsByGeometryType,
    )
    from ..models.catalog_stats_response_datasets_by_visibility import (
        CatalogStatsResponseDatasetsByVisibility,
    )
    from ..models.catalog_stats_response_users_by_status import (
        CatalogStatsResponseUsersByStatus,
    )


T = TypeVar("T", bound="CatalogStatsResponse")


@_attrs_define
class CatalogStatsResponse:
    """
    Attributes:
        total_datasets (int): Total number of datasets in the catalog.
        recent_additions (int): Number of datasets added in the last 30 days.
        total_storage_bytes (int | None): Total storage used by all dataset tables, in bytes. Null if calculation is
            unavailable.
        datasets_by_geometry_type (CatalogStatsResponseDatasetsByGeometryType): Histogram of datasets keyed by geometry
            type (Point, MultiPolygon, etc.).
        datasets_by_visibility (CatalogStatsResponseDatasetsByVisibility): Histogram of datasets keyed by visibility
            level (private, internal, restricted, public).
        users_by_status (CatalogStatsResponseUsersByStatus | Unset): Histogram of users keyed by status (active,
            deactivated, pending).
        total_users (int | Unset): Total number of users in the system. Default: 0.
    """

    total_datasets: int
    recent_additions: int
    total_storage_bytes: int | None
    datasets_by_geometry_type: CatalogStatsResponseDatasetsByGeometryType
    datasets_by_visibility: CatalogStatsResponseDatasetsByVisibility
    users_by_status: CatalogStatsResponseUsersByStatus | Unset = UNSET
    total_users: int | Unset = 0
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        total_datasets = self.total_datasets

        recent_additions = self.recent_additions

        total_storage_bytes: int | None
        total_storage_bytes = self.total_storage_bytes

        datasets_by_geometry_type = self.datasets_by_geometry_type.to_dict()

        datasets_by_visibility = self.datasets_by_visibility.to_dict()

        users_by_status: dict[str, Any] | Unset = UNSET
        if not isinstance(self.users_by_status, Unset):
            users_by_status = self.users_by_status.to_dict()

        total_users = self.total_users

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "total_datasets": total_datasets,
                "recent_additions": recent_additions,
                "total_storage_bytes": total_storage_bytes,
                "datasets_by_geometry_type": datasets_by_geometry_type,
                "datasets_by_visibility": datasets_by_visibility,
            }
        )
        if users_by_status is not UNSET:
            field_dict["users_by_status"] = users_by_status
        if total_users is not UNSET:
            field_dict["total_users"] = total_users

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.catalog_stats_response_datasets_by_geometry_type import (
            CatalogStatsResponseDatasetsByGeometryType,
        )
        from ..models.catalog_stats_response_datasets_by_visibility import (
            CatalogStatsResponseDatasetsByVisibility,
        )
        from ..models.catalog_stats_response_users_by_status import (
            CatalogStatsResponseUsersByStatus,
        )

        d = dict(src_dict)
        total_datasets = d.pop("total_datasets")

        recent_additions = d.pop("recent_additions")

        def _parse_total_storage_bytes(data: object) -> int | None:
            if data is None:
                return data
            return cast(int | None, data)

        total_storage_bytes = _parse_total_storage_bytes(d.pop("total_storage_bytes"))

        datasets_by_geometry_type = (
            CatalogStatsResponseDatasetsByGeometryType.from_dict(
                d.pop("datasets_by_geometry_type")
            )
        )

        datasets_by_visibility = CatalogStatsResponseDatasetsByVisibility.from_dict(
            d.pop("datasets_by_visibility")
        )

        _users_by_status = d.pop("users_by_status", UNSET)
        users_by_status: CatalogStatsResponseUsersByStatus | Unset
        if isinstance(_users_by_status, Unset):
            users_by_status = UNSET
        else:
            users_by_status = CatalogStatsResponseUsersByStatus.from_dict(
                _users_by_status
            )

        total_users = d.pop("total_users", UNSET)

        catalog_stats_response = cls(
            total_datasets=total_datasets,
            recent_additions=recent_additions,
            total_storage_bytes=total_storage_bytes,
            datasets_by_geometry_type=datasets_by_geometry_type,
            datasets_by_visibility=datasets_by_visibility,
            users_by_status=users_by_status,
            total_users=total_users,
        )

        catalog_stats_response.additional_properties = d
        return catalog_stats_response

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
