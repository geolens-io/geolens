"""Regression coverage for tenant-routed ingest, export, and raster storage keys."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


_SCHEMA_A = "data_t_00000000_0000_0000_0000_000000000001"
_SCHEMA_B = "data_t_00000000_0000_0000_0000_000000000002"


async def _successful_process(*args, **kwargs):
    process = MagicMock()
    process.returncode = 0
    return process


async def _successful_communicate(*args, **kwargs):
    return b"", b""


@pytest.mark.anyio
async def test_file_ingest_command_targets_each_tenant_schema(monkeypatch):
    from app.processing.ingest import ogr

    commands: list[tuple[str, ...]] = []

    async def capture(*args, **kwargs):
        commands.append(args)
        return await _successful_process()

    monkeypatch.setattr(ogr.asyncio, "create_subprocess_exec", capture)
    monkeypatch.setattr(ogr, "_communicate_with_timeout", _successful_communicate)

    for schema in (_SCHEMA_A, _SCHEMA_B):
        await ogr.run_ogr2ogr(
            "/tmp/source.geojson",
            "roads",
            "PG:dummy",
            geometry_type="Point",
            schema=schema,
        )

    targets = [cmd[cmd.index("-nln") + 1] for cmd in commands]
    assert targets == [f"{_SCHEMA_A}.roads", f"{_SCHEMA_B}.roads"]
    assert "data.roads" not in targets


@pytest.mark.anyio
async def test_service_ingest_command_targets_tenant_schema(monkeypatch):
    from app.processing.ingest import ogr

    commands: list[tuple[str, ...]] = []

    async def capture(*args, **kwargs):
        commands.append(args)
        return await _successful_process()

    monkeypatch.setattr(ogr.asyncio, "create_subprocess_exec", capture)
    monkeypatch.setattr(ogr, "_communicate_with_timeout", _successful_communicate)

    await ogr.run_ogr2ogr_service(
        "WFS:https://example.test/wfs",
        "roads",
        "roads_staging",
        "PG:dummy",
        "wfs",
        schema=_SCHEMA_A,
    )

    assert commands[0][commands[0].index("-nln") + 1] == (f"{_SCHEMA_A}.roads_staging")


@pytest.mark.anyio
async def test_ogr_export_reads_only_requested_tenant_schema(monkeypatch, tmp_path):
    from app.processing.export import ogr

    commands: list[tuple[str, ...]] = []

    async def capture(*args, **kwargs):
        commands.append(args)
        return await _successful_process()

    monkeypatch.setattr(ogr.asyncio, "create_subprocess_exec", capture)
    monkeypatch.setattr(ogr, "_communicate_with_timeout", _successful_communicate)

    await ogr.run_ogr2ogr_export(
        "roads",
        str(tmp_path / "roads.geojson"),
        "GeoJSON",
        schema=_SCHEMA_B,
    )

    assert f"{_SCHEMA_B}.roads" in commands[0]
    assert "data.roads" not in commands[0]


def test_physical_storage_keys_are_isolated_by_tenant():
    from app.platform.storage.titiler_url import resolve_storage_key

    logical = "rasters/dataset-id/source.cog.tif"
    assert resolve_storage_key(logical, tenant_id="tenant-a") == (
        f"tenants/tenant-a/{logical}"
    )
    assert resolve_storage_key(logical, tenant_id="tenant-b") == (
        f"tenants/tenant-b/{logical}"
    )
    assert resolve_storage_key(logical) == logical
    assert (
        resolve_storage_key("https://example.test/source.tif", tenant_id="tenant-a")
        == "https://example.test/source.tif"
    )


def test_managed_storage_fails_closed_without_tenant_context(monkeypatch):
    from app.platform.storage.titiler_url import resolve_storage_key

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    with pytest.raises(RuntimeError, match="requires tenant context"):
        resolve_storage_key("rasters/dataset-id/source.cog.tif")


def test_map_assets_use_physical_tenant_namespace(monkeypatch):
    from app.core.db.tenant_session import current_tenant_var
    from app.modules.catalog.maps.router import _map_asset_storage_key

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    token = current_tenant_var.set("tenant-a")
    try:
        assert _map_asset_storage_key("maps/thumbnails/map-id.png") == (
            "tenants/tenant-a/maps/thumbnails/map-id.png"
        )
        assert _map_asset_storage_key("maps/og-images/map-id.jpg") == (
            "tenants/tenant-a/maps/og-images/map-id.jpg"
        )
    finally:
        current_tenant_var.reset(token)


def test_map_assets_fail_closed_without_hosted_tenant(monkeypatch):
    from app.core.db.tenant_session import current_tenant_var
    from app.modules.catalog.maps.router import _map_asset_storage_key

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    token = current_tenant_var.set(None)
    try:
        with pytest.raises(RuntimeError, match="requires tenant context"):
            _map_asset_storage_key("maps/thumbnails/map-id.png")
    finally:
        current_tenant_var.reset(token)


def test_vrt_rewrite_relativizes_with_physical_tenant_key(tmp_path):
    import posixpath
    from xml.etree.ElementTree import parse

    from app.processing.raster.vrt_rewrite import rewrite_vrt_sources

    vrt = tmp_path / "source.vrt"
    vrt.write_text(
        "<VRTDataset><VRTRasterBand><SimpleSource><SourceFilename>"
        "/vsis3/bucket/tenants/tenant-a/rasters/source/cog.tif"
        "</SourceFilename></SimpleSource></VRTRasterBand></VRTDataset>"
    )
    physical_vrt_key = (
        "tenants/tenant-a/rasters/vrt/generations/generation-a/source.vrt"
    )

    rewrite_vrt_sources(vrt, vrt_storage_key=physical_vrt_key)

    node = parse(vrt).find(".//SourceFilename")
    assert node is not None and node.text is not None
    resolved = posixpath.normpath(
        posixpath.join(posixpath.dirname(physical_vrt_key), node.text)
    )
    assert resolved == "tenants/tenant-a/rasters/source/cog.tif"


def test_vrt_reap_retains_old_quicklooks_when_regeneration_has_none():
    from app.processing.ingest.tasks_vrt import (
        _prior_generation_storage_keys_to_reap,
    )

    keys = _prior_generation_storage_keys_to_reap(
        vrt_key="rasters/vrt/old/source.vrt",
        quicklook_256_key="rasters/vrt/old/quicklook_256.png",
        quicklook_512_key="rasters/vrt/old/quicklook_512.png",
        replace_quicklook_256=False,
        replace_quicklook_512=False,
        tenant_id=None,
    )

    assert keys == ["rasters/vrt/old/source.vrt"]


def test_ingest_worker_fails_closed_without_tenant_context(monkeypatch):
    from app.core.db.tenant_session import current_tenant_var
    from app.processing.ingest.tasks_common import (
        _current_tenant_role,
        _current_tenant_schema,
    )

    monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
    token = current_tenant_var.set(None)
    try:
        with pytest.raises(RuntimeError, match="missing tenant context"):
            _current_tenant_schema()
        with pytest.raises(RuntimeError, match="missing tenant context"):
            _current_tenant_role()
    finally:
        current_tenant_var.reset(token)


@pytest.mark.parametrize("schema", ["data;drop", "data-other", "Data Tenant"])
@pytest.mark.anyio
async def test_gdal_command_rejects_unsafe_schema_before_spawn(monkeypatch, schema):
    from app.processing.ingest import ogr

    spawned = False

    async def capture(*args, **kwargs):
        nonlocal spawned
        spawned = True
        return await _successful_process()

    monkeypatch.setattr(ogr.asyncio, "create_subprocess_exec", capture)

    with pytest.raises(ValueError, match="Invalid table name"):
        await ogr.run_ogr2ogr("/tmp/source.geojson", "roads", "PG:dummy", schema=schema)
    assert spawned is False
