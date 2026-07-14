from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field


T = TypeVar("T", bound="StaleCleanupResponse")


@_attrs_define
class StaleCleanupResponse:
    """
    Attributes:
        local_files_reaped (int):
        pending_failed (int):
        running_failed (int):
        staged_cleanup_failures (int):
        staged_paths_considered (int):
        staged_paths_skipped (int):
        storage_objects_reaped (int):
        terminal_jobs_purged (int):
        total_affected (int):
        total_cleaned (int):
        vrt_assets_recovered (int):
        vrt_generations_failed (int):
    """

    local_files_reaped: int
    pending_failed: int
    running_failed: int
    staged_cleanup_failures: int
    staged_paths_considered: int
    staged_paths_skipped: int
    storage_objects_reaped: int
    terminal_jobs_purged: int
    total_affected: int
    total_cleaned: int
    vrt_assets_recovered: int
    vrt_generations_failed: int
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        local_files_reaped = self.local_files_reaped

        pending_failed = self.pending_failed

        running_failed = self.running_failed

        staged_cleanup_failures = self.staged_cleanup_failures

        staged_paths_considered = self.staged_paths_considered

        staged_paths_skipped = self.staged_paths_skipped

        storage_objects_reaped = self.storage_objects_reaped

        terminal_jobs_purged = self.terminal_jobs_purged

        total_affected = self.total_affected

        total_cleaned = self.total_cleaned

        vrt_assets_recovered = self.vrt_assets_recovered

        vrt_generations_failed = self.vrt_generations_failed

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update(
            {
                "local_files_reaped": local_files_reaped,
                "pending_failed": pending_failed,
                "running_failed": running_failed,
                "staged_cleanup_failures": staged_cleanup_failures,
                "staged_paths_considered": staged_paths_considered,
                "staged_paths_skipped": staged_paths_skipped,
                "storage_objects_reaped": storage_objects_reaped,
                "terminal_jobs_purged": terminal_jobs_purged,
                "total_affected": total_affected,
                "total_cleaned": total_cleaned,
                "vrt_assets_recovered": vrt_assets_recovered,
                "vrt_generations_failed": vrt_generations_failed,
            }
        )

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        local_files_reaped = d.pop("local_files_reaped")

        pending_failed = d.pop("pending_failed")

        running_failed = d.pop("running_failed")

        staged_cleanup_failures = d.pop("staged_cleanup_failures")

        staged_paths_considered = d.pop("staged_paths_considered")

        staged_paths_skipped = d.pop("staged_paths_skipped")

        storage_objects_reaped = d.pop("storage_objects_reaped")

        terminal_jobs_purged = d.pop("terminal_jobs_purged")

        total_affected = d.pop("total_affected")

        total_cleaned = d.pop("total_cleaned")

        vrt_assets_recovered = d.pop("vrt_assets_recovered")

        vrt_generations_failed = d.pop("vrt_generations_failed")

        stale_cleanup_response = cls(
            local_files_reaped=local_files_reaped,
            pending_failed=pending_failed,
            running_failed=running_failed,
            staged_cleanup_failures=staged_cleanup_failures,
            staged_paths_considered=staged_paths_considered,
            staged_paths_skipped=staged_paths_skipped,
            storage_objects_reaped=storage_objects_reaped,
            terminal_jobs_purged=terminal_jobs_purged,
            total_affected=total_affected,
            total_cleaned=total_cleaned,
            vrt_assets_recovered=vrt_assets_recovered,
            vrt_generations_failed=vrt_generations_failed,
        )

        stale_cleanup_response.additional_properties = d
        return stale_cleanup_response

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
