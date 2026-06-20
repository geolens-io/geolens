"""Quota schemas for per-user upload and storage quotas (QUOTA-01..04)."""

from pydantic import BaseModel


class UserQuotaUsage(BaseModel):
    """Per-user quota usage: current consumption vs configured caps."""

    bytes_used: int
    dataset_count: int
    storage_cap: int  # configured cap in bytes; 0 = unlimited
    count_cap: int  # configured dataset cap; 0 = unlimited
