"""The tileset extent backfill records a stored tileset's extent where none is set."""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text

import app.platform.storage.provider as storage_provider
from app.core.config import settings
from app.core.tiles3d import tileset_prefix
from app.platform.extensions.defaults_catalog_port import DefaultCatalogPort
from app.platform.extensions.defaults_extensions import (
    DefaultDataServingExtension,
    DefaultEntitlementPort,
    DefaultIdentityExtension,
    DefaultPermissionExtension,
    DefaultWorkflowExtension,
)
from app.platform.extensions.defaults_processing_port import DefaultProcessingPort
from app.platform.extensions.version import EXTENSION_API_VERSION
from scripts.backfill_tileset_extents import _run, backfill, main
from tests.test_tileset_upload import (  # noqa: F401 -- fixtures
    campus_zip,
    load_job,
    publish,
    queued,
    uploader,
)
from tests.tiles3d_archives import REGION

# The root box of the 3DBAG Amsterdam canal buildings tileset, already in EPSG:4978.
_AMSTERDAM = {
    "box": [
        *(3888597.99, 332796.89, 5027995.84),
        *(-54.22, 595.59, 2.49),
        *(-471.55, -44.46, 365.16),
        *(120.89, 10.35, 156.31),
    ]
}


async def _published(client, session, owner, calls, volume) -> uuid.UUID:
    headers, _ = owner
    job_id = await publish(client, headers, calls, campus_zip(volume=volume))
    return (await load_job(session, job_id)).dataset_id


async def _forget_extent(session, dataset_id: uuid.UUID) -> None:
    """Null the extent, as a dataset published before box extents were read has it."""
    await session.execute(
        text(
            "UPDATE catalog.records r SET spatial_extent = NULL "
            "FROM catalog.datasets d WHERE d.record_id = r.id AND d.id = :id"
        ),
        {"id": dataset_id},
    )
    await session.commit()


async def _extent(client: AsyncClient, owner, dataset_id: uuid.UUID):
    headers, _ = owner
    response = await client.get(f"/datasets/{dataset_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["extent_bbox"]


async def _stored_tileset_json(dataset_id: uuid.UUID) -> str:
    storage = storage_provider.get_storage()
    keys = await storage.list(tileset_prefix(dataset_id))
    return next(key for key in keys if key.endswith("/tileset.json"))


class _SpyCatalogPort(DefaultCatalogPort):
    def __init__(self) -> None:
        self.asked: list[uuid.UUID] = []

    async def get_dataset_assets(self, session, dataset_id):  # type: ignore[no-untyped-def]
        self.asked.append(dataset_id)
        return await super().get_dataset_assets(session, dataset_id)


class _Permission(DefaultPermissionExtension):
    pass


class _Identity(DefaultIdentityExtension):
    pass


class _Workflow(DefaultWorkflowExtension):
    pass


# A loaded overlay makes the edition enterprise, which requires these ports.
_ENTERPRISE_PORTS = {
    "permission": _Permission(),
    "identity": _Identity(),
    "workflow": _Workflow(),
}


class _Processing(DefaultProcessingPort):
    pass


class _Entitlement(DefaultEntitlementPort):
    pass


class _DataServing(DefaultDataServingExtension):
    pass


# Multi-tenant mode also requires the cloud overlay's ports.
_CLOUD_PORTS = {
    "processing_port": _Processing(),
    "entitlement": _Entitlement(),
    "data_serving": _DataServing(),
}


def _overlay(**ports: object) -> MagicMock:
    """An entry point whose loader registers ``ports``, as an installed overlay's does."""

    def register(registry: dict) -> None:
        registry.update(ports)

    register.EXTENSION_API_VERSION = EXTENSION_API_VERSION
    entry_point = MagicMock()
    entry_point.name = "spy_overlay"
    entry_point.load.return_value = register
    return entry_point


@pytest.fixture
def overlays(monkeypatch):
    """The overlays the CLI's bootstrap discovers; the process state is restored after.

    Storage, the caches and RLS setup keep the test's own, so the bootstrap
    only loads extensions and resolves the edition.
    """
    import app.core.edition as edition
    import app.platform.extensions as extensions

    saved = (
        dict(extensions._extensions),
        list(extensions._routers),
        extensions._loaded,
        dict(extensions._slot_owners),
        edition._info,
    )
    # Loading never unregisters a slot, so one an earlier test registered
    # would read as an overlay and make the edition enterprise.
    extensions._extensions.clear()
    for name in ("GEOLENS_EDITION", "GEOLENS_LICENSE_KEY"):
        monkeypatch.delenv(name, raising=False)
    found: list = []
    monkeypatch.setattr(extensions, "entry_points", lambda **_: found)
    for name in ("init_storage", "init_cache", "init_tile_cache"):
        monkeypatch.setattr(
            f"app.platform.extensions.bootstrap.{name}", lambda **_: None
        )
    monkeypatch.setattr("app.core.db.rls.apply_tenancy_rls_from_engine", AsyncMock())
    yield found
    extensions._extensions.clear()
    extensions._extensions.update(saved[0])
    extensions._routers[:] = saved[1]
    extensions._loaded = saved[2]
    extensions._slot_owners.clear()
    extensions._slot_owners.update(saved[3])
    edition._info = saved[4]


def _outcome(report, dataset_id: uuid.UUID) -> str | None:
    key = str(dataset_id)
    if key in report.updated:
        return "updated"
    for name in ("skipped", "failed"):
        for listed, reason in getattr(report, name):
            if listed == key:
                return f"{name}: {reason}"
    return None


async def test_a_georeferenced_box_gets_its_extent_once(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
) -> None:
    """The first run records the extent; the second finds nothing to do."""
    dataset_id = await _published(client, test_db_session, uploader, queued, _AMSTERDAM)
    await _forget_extent(test_db_session, dataset_id)

    first = await backfill(test_db_session)
    extent = await _extent(client, uploader, dataset_id)
    second = await backfill(test_db_session)

    assert _outcome(first, dataset_id) == "updated"
    assert extent == pytest.approx([4.8822, 52.3613, 4.9010, 52.3728], abs=0.001)
    assert _outcome(second, dataset_id) is None
    assert await _extent(client, uploader, dataset_id) == extent


async def test_a_dry_run_writes_nothing(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
) -> None:
    """It reports the dataset it would update and leaves the extent null."""
    dataset_id = await _published(client, test_db_session, uploader, queued, _AMSTERDAM)
    await _forget_extent(test_db_session, dataset_id)

    report = await backfill(test_db_session, dry_run=True)

    assert _outcome(report, dataset_id) == "updated"
    assert await _extent(client, uploader, dataset_id) is None


async def test_a_recorded_extent_is_left_alone(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
) -> None:
    """A dataset that has an extent is never read, let alone rewritten."""
    dataset_id = await _published(
        client, test_db_session, uploader, queued, {"region": REGION}
    )

    report = await backfill(test_db_session)

    assert _outcome(report, dataset_id) is None
    assert await _extent(client, uploader, dataset_id) == pytest.approx(
        [math.degrees(v) for v in REGION[:4]]
    )


async def test_a_local_frame_tileset_is_skipped(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
) -> None:
    """A volume that is not georeferenced has no extent to record."""
    dataset_id = await _published(
        client, test_db_session, uploader, queued, {"box": [0.0] * 12}
    )

    report = await backfill(test_db_session)

    assert _outcome(report, dataset_id) == "skipped: the root box is not georeferenced"
    assert await _extent(client, uploader, dataset_id) is None


async def test_a_missing_tileset_json_fails_the_run(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
    overlays,
) -> None:
    """A live pointer to nothing is a storage fault, so the run exits 1."""
    dataset_id = await _published(client, test_db_session, uploader, queued, _AMSTERDAM)
    await _forget_extent(test_db_session, dataset_id)
    await storage_provider.get_storage().delete(await _stored_tileset_json(dataset_id))

    report = await backfill(test_db_session)
    exit_code = await _run(dry_run=True, tenant=None)

    assert _outcome(report, dataset_id) == (
        "failed: tileset.json is missing from storage"
    )
    assert exit_code == 1
    assert await _extent(client, uploader, dataset_id) is None


async def test_a_pointer_outside_the_tileset_fails(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
) -> None:
    """A published dataset whose pointer is unusable has a broken catalog row."""
    dataset_id = await _published(client, test_db_session, uploader, queued, _AMSTERDAM)
    await _forget_extent(test_db_session, dataset_id)
    await test_db_session.execute(
        text(
            "UPDATE catalog.dataset_assets SET href = 'elsewhere/tileset.json' "
            "WHERE dataset_id = :id AND key = 'tileset'"
        ),
        {"id": dataset_id},
    )
    await test_db_session.commit()

    report = await backfill(test_db_session)

    assert _outcome(report, dataset_id) == "failed: no usable tileset pointer"


@pytest.mark.parametrize(
    ("stored", "reason"),
    [
        (b"not json", "failed: tileset.json fails ingest's checks (tileset_json)"),
        (b" " * 65, "failed: tileset.json is over the size ingest reads"),
    ],
    ids=["refused", "oversized"],
)
async def test_a_stored_tileset_json_ingest_would_refuse_fails(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
    monkeypatch,
    stored: bytes,
    reason: str,
) -> None:
    """Stored bytes ingest would not accept mean storage no longer holds what it published."""
    dataset_id = await _published(client, test_db_session, uploader, queued, _AMSTERDAM)
    await _forget_extent(test_db_session, dataset_id)
    key = await _stored_tileset_json(dataset_id)
    await storage_provider.get_storage().put(key, stored)
    monkeypatch.setattr("app.processing.ingest.tileset.MAX_TILESET_JSON_BYTES", 64)

    report = await backfill(test_db_session)

    assert _outcome(report, dataset_id) == reason
    assert await _extent(client, uploader, dataset_id) is None


async def test_a_failed_query_does_not_fail_the_next_dataset(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
    overlays,
    monkeypatch,
) -> None:
    """A query error aborts only its own dataset's transaction."""
    from app.modules.catalog.datasets.domain import service

    first, second = sorted(
        [
            await _published(client, test_db_session, uploader, queued, _AMSTERDAM)
            for _ in range(2)
        ]
    )
    for dataset_id in (first, second):
        await _forget_extent(test_db_session, dataset_id)
    lookup = service.get_tileset_href

    async def failing_lookup(session, dataset_id):
        if dataset_id == first:
            await session.execute(text("SELECT * FROM catalog.no_such_table"))
        return await lookup(session, dataset_id)

    monkeypatch.setattr(service, "get_tileset_href", failing_lookup)

    report = await backfill(test_db_session)
    exit_code = await _run(dry_run=True, tenant=None)

    assert _outcome(report, first) == "failed: ProgrammingError"
    assert _outcome(report, second) == "updated"
    assert await _extent(client, uploader, second) == pytest.approx(
        [4.8822, 52.3613, 4.9010, 52.3728], abs=0.001
    )
    assert exit_code == 1


async def test_the_catalog_port_comes_from_the_loaded_overlay(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
    overlays,
) -> None:
    """The pointer is read through the overlay's catalog port, as the worker reads it."""
    dataset_id = await _published(client, test_db_session, uploader, queued, _AMSTERDAM)
    await _forget_extent(test_db_session, dataset_id)
    port = _SpyCatalogPort()
    overlays.append(_overlay(catalog_port=port, **_ENTERPRISE_PORTS))

    await _run(dry_run=True, tenant=None)

    assert dataset_id in port.asked


async def test_a_multi_tenant_run_without_the_cloud_ports_stops(
    overlays, monkeypatch, capsys
) -> None:
    """Multi-tenant mode needs every cloud port; a missing one exits 2 before any read."""
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    monkeypatch.setenv("GEOLENS_TENANCY_MODE", "multi_tenant")
    port = _SpyCatalogPort()
    overlays.append(_overlay(catalog_port=port, **_ENTERPRISE_PORTS))

    assert await _run(dry_run=True, tenant=str(uuid.uuid4())) == 2
    assert "processing_port" in capsys.readouterr().err
    assert port.asked == []


async def test_a_tenant_missing_from_the_registry_stops_the_run(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
    overlays,
    monkeypatch,
    capsys,
) -> None:
    """A well-formed id no tenant has would see no rows under RLS, so it exits 2."""
    dataset_id = await _published(client, test_db_session, uploader, queued, _AMSTERDAM)
    await _forget_extent(test_db_session, dataset_id)
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    monkeypatch.setenv("GEOLENS_TENANCY_MODE", "multi_tenant")
    port = _SpyCatalogPort()
    overlays.append(_overlay(catalog_port=port, **_ENTERPRISE_PORTS, **_CLOUD_PORTS))
    tenant = str(uuid.uuid4())

    assert await _run(dry_run=True, tenant=tenant) == 2
    assert f"Unknown tenant: {tenant}" in capsys.readouterr().err
    assert port.asked == []


async def test_a_tenant_given_as_bare_hex_runs_under_its_canonical_id(
    test_db_session, overlays, monkeypatch
) -> None:
    import scripts.backfill_tileset_extents as script
    from app.core.db.tenant_session import current_tenant_var

    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    monkeypatch.setenv("GEOLENS_TENANCY_MODE", "multi_tenant")
    overlays.append(
        _overlay(catalog_port=_SpyCatalogPort(), **_ENTERPRISE_PORTS, **_CLOUD_PORTS)
    )
    tenant_id = uuid.uuid4()
    seen: list[str | None] = []

    async def record_tenant(db, dry_run=False):
        seen.append(current_tenant_var.get())
        return script.BackfillReport()

    monkeypatch.setattr(script, "backfill", record_tenant)
    await test_db_session.execute(
        text("INSERT INTO catalog.tenants (id, slug, name) VALUES (:id, :slug, 'Hex')"),
        {"id": tenant_id, "slug": f"hex-{tenant_id.hex[:8]}"},
    )
    await test_db_session.commit()
    try:
        exit_code = await _run(dry_run=True, tenant=tenant_id.hex)
    finally:
        await test_db_session.execute(
            text("DELETE FROM catalog.tenants WHERE id = :id"), {"id": tenant_id}
        )
        await test_db_session.commit()

    assert exit_code == 0
    assert seen == [str(tenant_id)]


# Raises from the database for one record only, as a row error or lock timeout would.
_REFUSE_UNWRITABLE_FUNCTION = text(
    "CREATE FUNCTION catalog.refuse_unwritable() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF NEW.title = 'unwritable' THEN RAISE EXCEPTION 'unwritable record'; END IF; "
    "RETURN NEW; END; $$"
)
_REFUSE_UNWRITABLE_TRIGGER = text(
    "CREATE TRIGGER refuse_unwritable BEFORE UPDATE OF spatial_extent "
    "ON catalog.records FOR EACH ROW EXECUTE FUNCTION catalog.refuse_unwritable()"
)


async def test_a_failed_write_does_not_stop_the_sweep(
    client: AsyncClient,
    test_db_session,
    uploader,  # noqa: F811
    queued,  # noqa: F811
    overlays,
) -> None:
    """An UPDATE that errors fails its own dataset; the next one is still written."""
    first, second = sorted(
        [
            await _published(client, test_db_session, uploader, queued, _AMSTERDAM)
            for _ in range(2)
        ]
    )
    for dataset_id in (first, second):
        await _forget_extent(test_db_session, dataset_id)
    await test_db_session.execute(
        text(
            "UPDATE catalog.records r SET title = 'unwritable' "
            "FROM catalog.datasets d WHERE d.record_id = r.id AND d.id = :id"
        ),
        {"id": first},
    )
    await test_db_session.execute(_REFUSE_UNWRITABLE_FUNCTION)
    await test_db_session.execute(_REFUSE_UNWRITABLE_TRIGGER)
    await test_db_session.commit()
    try:
        report = await backfill(test_db_session)
        exit_code = await _run(dry_run=False, tenant=None)
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text("DROP TRIGGER IF EXISTS refuse_unwritable ON catalog.records")
        )
        await test_db_session.execute(
            text("DROP FUNCTION IF EXISTS catalog.refuse_unwritable()")
        )
        await test_db_session.commit()

    assert (_outcome(report, first) or "").startswith("failed: ")
    assert _outcome(report, second) == "updated"
    assert await _extent(client, uploader, second) == pytest.approx(
        [4.8822, 52.3613, 4.9010, 52.3728], abs=0.001
    )
    assert await _extent(client, uploader, first) is None
    assert exit_code == 1


def test_a_tenant_outside_multi_tenant_mode_is_refused() -> None:
    """Single-tenant mode has no tenant to read under, so the run stops before any read."""
    assert main(["--dry-run", "--tenant", str(uuid.uuid4())]) == 2
