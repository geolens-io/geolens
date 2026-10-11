#!/usr/bin/env python3
"""Record the spatial extent of 3D Tiles datasets published without one.

Ingest derives a tileset's extent from its root bounding volume. A dataset
published before GeoLens read a box or sphere volume has none, and nothing
derives it later: a tileset cannot be reuploaded or refreshed. This reads each
such dataset's stored tileset.json, derives the extent with ingest's own code,
and records it.

Usage:
    docker compose exec api /app/.venv/bin/python -m scripts.backfill_tileset_extents --dry-run
    docker compose exec api /app/.venv/bin/python -m scripts.backfill_tileset_extents

In multi-tenant mode, run it once per tenant with ``--tenant <tenant id>``.

Behaviour:

- Reads and writes only records whose extent is null, so a rerun leaves what an
  earlier run recorded alone.
- Loads extensions and checks the required ports as the worker does, so
  pointers and storage resolve through the same overlay. Exits 2 when that
  startup check fails.
- A backfilled dataset shows a new updated time, since its record gains an extent.
- Skips a dataset, with the reason, only when its tileset is valid but its
  bounding volume is not georeferenced.
- Counts a dataset as failed when its tileset pointer is missing or malformed,
  its tileset.json is missing, oversized or fails ingest's checks, or storage
  cannot be read, and carries on. Each means a published dataset's catalog row
  or storage is broken. Exits 1 when any failed, so a wrong bucket or an
  unmounted volume does not pass as a run with nothing to do.
- Prints dataset ids, counts and reasons only, never storage keys.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SELECT_WITHOUT_EXTENT = text(
    "SELECT d.id FROM catalog.datasets d "
    "JOIN catalog.records r ON d.record_id = r.id "
    "WHERE r.record_type = 'tiles3d_dataset' AND r.spatial_extent IS NULL "
    "ORDER BY d.id"
)

_TENANT_EXISTS = text("SELECT id FROM catalog.tenants WHERE id = :tenant_id")

_SET_EXTENT = text(
    "UPDATE catalog.records r SET spatial_extent = ST_GeomFromText(:wkt, 4326) "
    "FROM catalog.datasets d "
    "WHERE d.record_id = r.id AND d.id = :dataset_id AND r.spatial_extent IS NULL"
)

# The pointer names the live attempt's tileset.json, one level below the
# dataset's prefix, as the tileset route requires.
_ATTEMPT_ENTRY = re.compile(r"[A-Za-z0-9_-]+/tileset\.json")


class _Broken(Exception):
    """A published dataset whose pointer or stored tileset is unusable."""


@dataclass
class BackfillReport:
    updated: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def _tileset_json_key(href: str | None, dataset_id: uuid.UUID) -> str | None:
    from app.core.tiles3d import tileset_prefix
    from app.platform.storage.titiler_url import resolve_current_storage_key

    prefix = tileset_prefix(dataset_id)
    if href is None or not href.startswith(prefix):
        return None
    if not _ATTEMPT_ENTRY.fullmatch(href[len(prefix) :]):
        return None
    return resolve_current_storage_key(href)


async def _extent(
    db: AsyncSession, dataset_id: uuid.UUID
) -> tuple[float, float, float, float] | str:
    """The dataset's extent, or why a valid tileset has none.

    Raises :class:`_Broken` for a broken pointer or stored tileset; storage
    errors propagate, a missing tileset.json included.
    """
    from app.core.tiles3d import TILESET_ENTRY_POINT
    from app.core.upload_errors import UnsafeUploadError
    from app.modules.catalog.datasets.domain.service import get_tileset_href
    from app.platform.storage import get_storage
    from app.processing.ingest.tileset import (
        MAX_TILESET_JSON_BYTES,
        parse_tileset_json,
        read_facts,
    )

    key = _tileset_json_key(await get_tileset_href(db, dataset_id), dataset_id)
    # A slow storage read must not hold the catalog's locks.
    await db.rollback()
    if key is None:
        raise _Broken("no usable tileset pointer")
    raw = await get_storage().get_range(key, 0, MAX_TILESET_JSON_BYTES + 1)
    if len(raw) > MAX_TILESET_JSON_BYTES:
        raise _Broken("tileset.json is over the size ingest reads")
    try:
        facts = read_facts(parse_tileset_json(raw, TILESET_ENTRY_POINT))
    except UnsafeUploadError as exc:
        raise _Broken(f"tileset.json fails ingest's checks ({exc.code})") from None
    if facts.extent_bbox is None:
        return f"the root {facts.bounding_volume} is not georeferenced"
    return facts.extent_bbox


async def _end_failed_transaction(db: AsyncSession) -> None:
    """Roll back, since a failed query leaves the transaction aborted."""
    try:
        await db.rollback()
    except Exception as exc:  # broad: must not hide the dataset's recorded failure
        print(f"  rollback failed: {type(exc).__name__}")


async def backfill(db: AsyncSession, *, dry_run: bool = False) -> BackfillReport:
    """Record the extent of every tiles3d dataset without one, committing each."""
    from app.core.geo import bbox_to_extent_wkt

    report = BackfillReport()

    async def fail(dataset_id: uuid.UUID, reason: str) -> None:
        report.failed.append((str(dataset_id), reason))
        print(f"  FAILED  {dataset_id}: {reason}")
        await _end_failed_transaction(db)

    dataset_ids = (await db.execute(_SELECT_WITHOUT_EXTENT)).scalars().all()
    await db.rollback()
    for dataset_id in dataset_ids:
        try:
            extent = await _extent(db, dataset_id)
        except _Broken as exc:
            reason = str(exc)
        except FileNotFoundError:
            reason = "tileset.json is missing from storage"
        except Exception as exc:  # broad: each storage backend raises its own errors
            reason = type(exc).__name__
        else:
            reason = None
        if reason is not None:
            await fail(dataset_id, reason)
            continue
        if isinstance(extent, str):
            report.skipped.append((str(dataset_id), extent))
            print(f"  SKIPPED {dataset_id}: {extent}")
            continue
        if not dry_run:
            try:
                result = await db.execute(
                    _SET_EXTENT,
                    {"wkt": bbox_to_extent_wkt(*extent), "dataset_id": dataset_id},
                )
                await db.commit()
            except Exception as exc:  # broad: a write error fails only this dataset
                await fail(dataset_id, type(exc).__name__)
                continue
            if result.rowcount == 0:
                report.skipped.append((str(dataset_id), "extent already set"))
                print(f"  SKIPPED {dataset_id}: extent already set")
                continue
        report.updated.append(str(dataset_id))
        verb = "WOULD UPDATE" if dry_run else "UPDATED"
        print(f"  {verb} {dataset_id}: {', '.join(f'{v:.6f}' for v in extent)}")

    # Nothing is written under a dry run, but the read transaction still closes.
    await db.rollback()
    tag = " (dry run, nothing written)" if dry_run else ""
    print(
        f"Done: {len(report.updated)} updated, {len(report.skipped)} skipped, "
        f"{len(report.failed)} failed{tag}."
    )
    return report


async def _registered_tenant(db_module, tenant: str) -> str | None:
    """The canonical id of ``tenant`` if the tenant registry, which has no RLS, holds it."""
    try:
        tenant_id = uuid.UUID(tenant)
    except ValueError:
        return None
    async with db_module.async_session() as db:
        if await db.scalar(_TENANT_EXISTS, {"tenant_id": tenant_id}) is None:
            return None
    return str(tenant_id)


async def _run(dry_run: bool, tenant: str | None) -> int:
    import app.core.db as db_module
    from app.core.db.tenant_session import tenant_job_context
    from app.core.tenancy import is_multi_tenant
    from app.platform.extensions.bootstrap import (
        assert_enterprise_ports_resolved,
        bootstrap,
    )

    if is_multi_tenant() != (tenant is not None):
        print(
            "Pass --tenant in multi-tenant mode, and only there: each tenant's "
            "records and storage are read under that tenant.",
            file=sys.stderr,
        )
        return 2

    # The mapper registry must be complete before the catalog port queries it,
    # as the worker ensures before its own bootstrap.
    import app.modules.audit.models  # noqa: F401
    import app.modules.auth.models  # noqa: F401
    import app.modules.catalog.collections.models  # noqa: F401
    import app.modules.catalog.datasets.domain.models  # noqa: F401
    import app.processing.embeddings.models  # noqa: F401

    try:
        await bootstrap(app=None)
        assert_enterprise_ports_resolved()
    except RuntimeError as exc:
        print(f"Startup check failed: {exc}", file=sys.stderr)
        return 2
    if tenant is not None:
        registered = await _registered_tenant(db_module, tenant)
        if registered is None:
            print(f"Unknown tenant: {tenant}", file=sys.stderr)
            return 2
        tenant = registered
    with tenant_job_context(tenant):
        async with db_module.async_session() as db:
            report = await backfill(db, dry_run=dry_run)
    return 1 if report.failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record the extent of 3D Tiles datasets published without one."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be recorded without writing anything.",
    )
    parser.add_argument(
        "--tenant", help="The tenant to backfill; required in multi-tenant mode."
    )
    args = parser.parse_args(argv)
    return asyncio.run(_run(args.dry_run, args.tenant))


if __name__ == "__main__":
    raise SystemExit(main())
