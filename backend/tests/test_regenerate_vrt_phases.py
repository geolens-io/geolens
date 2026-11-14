"""Unit tests for the pure phases of VRT regeneration: the build plan and the metadata copy."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.processing.ingest import tasks_vrt

_SNAPSHOT_AT = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _claim(source_ids, *, vrt_type=None, resolution_strategy=None):
    row = SimpleNamespace(
        asset_uri="rasters/v/source.vrt",
        quicklook_256_uri="rasters/v/q256.png",
        quicklook_512_uri=None,
        vrt_type=vrt_type,
        resolution_strategy=resolution_strategy,
    )
    return tasks_vrt._ClaimedRegeneration(
        vrt_asset_row=row,
        source_ids=source_ids,
        staged_source_ids=None,
        vrt_owner_id="owner",
    )


def test_plan_refuses_a_member_the_snapshot_lost():
    """Every claimed member must be in the snapshot, and the refusal names the missing ones."""
    kept, lost = uuid.uuid4(), uuid.uuid4()
    assets = [SimpleNamespace(dataset_id=kept, asset_uri="rasters/a/cog.tif")]
    with pytest.raises(ValueError, match=f"no longer available: {lost}$"):
        tasks_vrt._plan_from_snapshot(
            _claim([kept, lost]), _SNAPSHOT_AT, assets, vrt_dataset_id="vrt-1"
        )


def test_plan_carries_the_served_keys_and_build_defaults(monkeypatch):
    """The plan keeps the served keys and defaults a mosaic at the finest resolution."""
    member = uuid.uuid4()
    assets = [SimpleNamespace(dataset_id=member, asset_uri="rasters/a/cog.tif")]
    monkeypatch.setattr(
        tasks_vrt,
        "resolve_vrt_source_path",
        lambda uri, tenant_id: f"/vsi/{uri}",
    )
    plan = tasks_vrt._plan_from_snapshot(
        _claim([member]), _SNAPSHOT_AT, assets, vrt_dataset_id="vrt-1"
    )
    assert plan.source_paths == ["/vsi/rasters/a/cog.tif"]
    assert plan.ordered_assets == assets
    assert plan.snapshot_at == _SNAPSHOT_AT
    assert (plan.vrt_storage_key, plan.vrt_ql256_uri, plan.vrt_ql512_uri) == (
        "rasters/v/source.vrt",
        "rasters/v/q256.png",
        None,
    )
    assert (plan.vrt_type, plan.resolution_strategy) == ("mosaic", "finest")
    assert plan.vrt_owner_id == "owner"


def test_metadata_copy_keeps_quicklooks_that_were_not_rerendered():
    """A quicklook that failed to render keeps its served key; nodata is stored as text."""
    asset = SimpleNamespace(
        quicklook_256_uri="old256", quicklook_512_uri="old512", set_crs=lambda m: None
    )
    built = tasks_vrt._BuiltVrt(
        vrt_path="scratch/x.vrt",
        overview_paths=None,
        prior_overview_href=None,
        meta={"nodata": 0, "epsg": 4326, "band_count": 3, "is_dem_candidate": True},
        sha256="abc",
        size=42,
        ql256=b"png",
        ql512=None,
    )
    tasks_vrt._apply_regenerated_metadata(
        asset,
        built,
        next_vrt_storage_key="new.vrt",
        next_ql256_uri="new256",
        next_ql512_uri="new512",
    )
    assert asset.asset_uri == "new.vrt"
    assert asset.quicklook_256_uri == "new256"
    assert asset.quicklook_512_uri == "old512"
    assert (asset.sha256, asset.size_bytes, asset.nodata) == ("abc", 42, "0")
    assert (asset.epsg, asset.band_count, asset.is_dem) == (4326, 3, True)
    assert asset.dtype is None
