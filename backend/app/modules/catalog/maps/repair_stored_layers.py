"""One-off repair of stored map layers that read a column by the wrong name.

Run once, from ``backend/``::

    python -m app.modules.catalog.maps.repair_stored_layers [--dry-run]

It loads each vector layer with its dataset's recorded ``column_info``,
rewrites the layer's column references to the stored names with
``repair_layer_columns``, saves the layers that changed, and prints what it
changed and what it skipped: a layer whose dataset recorded no columns, a
layer that no longer reads as a layer, a layer the renames would leave
invalid (a longer stored name can push the popup title past its limit), and
a map another change holds are all skipped. Each map is repaired in a transaction of its own: the map's
row lock is taken before the layers are read, so the rows are the ones
committed when the lock was taken, and a save that starts after cannot
commit ahead of the repair, because advancing the map's ``updated_at``
waits on the lock the repair holds; a rerun repairs anything a concurrent
save overwrote. With ``--dry-run`` it reports what it would change and
writes nothing, and records no audit event. Each map it repairs records
one ``map.repair_stored_layers`` audit event in the same transaction as the
layer writes.

The command writes only ``map_layers`` rows. A map layer carries no
``updated_at`` of its own and the maps row is not touched, so a map's
``updated_at`` does not move. A published map is served from the live layer
rows, so a repaired layer shows in the published map at once, with no
republish needed. The repair does not move the map's ``updated_at``, so a
republish after the repair sees the same publish-time marker as before;
whether that republish keeps the repaired styling is decided from the
map's edit history, not from ``updated_at``. A repair writes a layer's
fields back as they stand after validation, so a builder key validation
moved out of paint into ``style_config`` is saved with the repaired paint
instead of being lost with it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.service import AuditEvent, audit_emit
from app.modules.catalog.datasets.domain.models import Dataset
from app.modules.catalog.maps.manifest_columns import repair_layer_columns
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.schemas import MapLayerInput
from app.platform.catalog_locks import CatalogLockConflict, bounded_row_lock

# Raster styling reads no feature columns, so only these layer types can
# carry a reference the repair would rewrite.
_VECTOR_LAYER_TYPES = ("vector_geolens", "geojson")
# The layer fields the repair can rewrite, as the stored row holds them.
_LAYER_JSON_FIELDS = (
    "paint",
    "layout",
    "filter",
    "label_config",
    "popup_config",
    "style_config",
)


@dataclass
class StoredLayerRepair:
    """What the repair did to one stored layer."""

    map_id: uuid.UUID
    layer_id: uuid.UUID
    dataset_id: uuid.UUID
    status: str = "unchanged"  # "repaired", "unchanged" or "skipped"
    repaired: dict[str, str] = field(default_factory=dict)
    unrepaired: dict[str, str] = field(default_factory=dict)
    reason: str | None = None


@dataclass
class RepairReport:
    """What one run of the repair did, layer by layer."""

    layers: list[StoredLayerRepair] = field(default_factory=list)
    dry_run: bool = False

    @property
    def repaired_count(self) -> int:
        return sum(1 for entry in self.layers if entry.status == "repaired")

    @property
    def unchanged_count(self) -> int:
        return sum(1 for entry in self.layers if entry.status == "unchanged")

    @property
    def skipped_count(self) -> int:
        return sum(1 for entry in self.layers if entry.status == "skipped")

    def format(self) -> str:
        """The run as printable lines: one per layer, then the totals."""
        lines = []
        if self.dry_run:
            lines.append("Dry run: no changes were written.")
        for entry in self.layers:
            where = f"map {entry.map_id} layer {entry.layer_id}"
            left = ", ".join(
                f"{name} ({why})" for name, why in sorted(entry.unrepaired.items())
            )
            if entry.status == "repaired":
                changes = ", ".join(
                    f"{old} -> {new}" for old, new in sorted(entry.repaired.items())
                )
                verb = "would repair" if self.dry_run else "repaired"
                lines.append(
                    f"{where}: {verb} {changes}" + (f"; left {left}" if left else "")
                )
            elif entry.status == "unchanged":
                lines.append(f"{where}: unchanged" + (f", left {left}" if left else ""))
            else:
                lines.append(f"{where}: skipped ({entry.reason})")
        repaired_word = "would be repaired" if self.dry_run else "repaired"
        lines.append(
            f"{self.repaired_count} {repaired_word}, "
            f"{self.unchanged_count} unchanged, "
            f"{self.skipped_count} skipped"
        )
        return "\n".join(lines)


def _repair_layer(
    layer: MapLayer,
    column_info: Sequence[dict[str, Any]] | None,
    report: RepairReport,
    *,
    dry_run: bool = False,
) -> None:
    """Repair one stored layer in place, recording the outcome in ``report``."""
    entry = StoredLayerRepair(
        map_id=layer.map_id, layer_id=layer.id, dataset_id=layer.dataset_id
    )
    if not column_info:
        entry.status = "skipped"
        entry.reason = "the dataset recorded no columns"
        report.layers.append(entry)
        return
    try:
        layer_in = MapLayerInput.model_validate(
            {
                "dataset_id": layer.dataset_id,
                "paint": layer.paint,
                "layout": layer.layout,
                "filter": layer.filter,
                "label_config": layer.label_config,
                "popup_config": layer.popup_config,
                "style_config": layer.style_config,
            }
        )
    except (ValidationError, ValueError):
        entry.status = "skipped"
        entry.reason = "the stored layer no longer reads as a layer"
        report.layers.append(entry)
        return
    repaired_layer, result = repair_layer_columns(layer_in, column_info)
    entry.repaired = dict(result.repaired)
    entry.unrepaired = dict(result.unrepaired)
    if result.refused is not None:
        entry.status = "skipped"
        entry.reason = f"the repaired layer would not be valid ({result.refused})"
        report.layers.append(entry)
        return
    if not result.repaired:
        entry.status = "unchanged"
        report.layers.append(entry)
        return
    if not dry_run:
        for name in _LAYER_JSON_FIELDS:
            value = getattr(repaired_layer, name)
            if name == "popup_config":
                value = (
                    value.model_dump(exclude_unset=True) if value is not None else None
                )
            if value == getattr(layer, name):
                continue
            setattr(layer, name, value)
    entry.status = "repaired"
    report.layers.append(entry)


async def _repair_map(
    session: AsyncSession,
    map_id: uuid.UUID,
    report: RepairReport,
    *,
    dry_run: bool = False,
) -> None:
    """Repair one map's vector layers and commit, or record them skipped.

    The map's row lock is taken before the layers are read, so the rows are
    the ones committed when the lock was taken.
    """
    try:
        await bounded_row_lock(
            session,
            select(Map.id).where(Map.id == map_id).with_for_update(key_share=True),
            message="Another change to this map is in progress.",
        )
    except CatalogLockConflict:
        layer_ids = (
            await session.execute(
                select(MapLayer.id, MapLayer.dataset_id)
                .where(MapLayer.map_id == map_id)
                .where(MapLayer.layer_type.in_(_VECTOR_LAYER_TYPES))
                .order_by(MapLayer.sort_order, MapLayer.id)
            )
        ).all()
        for layer_id, dataset_id in layer_ids:
            report.layers.append(
                StoredLayerRepair(
                    map_id=map_id,
                    layer_id=layer_id,
                    dataset_id=dataset_id,
                    status="skipped",
                    reason="another change to the map is in progress",
                )
            )
        return
    rows = (
        await session.execute(
            select(MapLayer, Dataset.column_info)
            .join(Dataset, MapLayer.dataset_id == Dataset.id)
            .where(MapLayer.map_id == map_id)
            .where(MapLayer.layer_type.in_(_VECTOR_LAYER_TYPES))
            .order_by(MapLayer.sort_order, MapLayer.id)
        )
    ).all()
    # Only this map's entries are appended below, so the audit reads the
    # slice instead of rescanning every map processed so far.
    repaired_start = len(report.layers)
    for layer, column_info in rows:
        _repair_layer(layer, column_info, report, dry_run=dry_run)
    repaired = [
        entry for entry in report.layers[repaired_start:] if entry.status == "repaired"
    ]
    if repaired and not dry_run:
        await audit_emit(
            session,
            AuditEvent(
                user_id=None,
                action="map.repair_stored_layers",
                resource_type="map",
                resource_id=map_id,
                details={
                    "layers_repaired": len(repaired),
                    "repairs": {
                        str(entry.layer_id): dict(entry.repaired) for entry in repaired
                    },
                },
            ),
        )
    await session.commit()


async def repair_stored_layers(
    session: AsyncSession, *, dry_run: bool = False
) -> RepairReport:
    """Repair every stored vector layer against its dataset's recorded columns.

    Each map is repaired in a transaction of its own, so a map the lock
    cannot be taken for is skipped without losing the maps already repaired.
    With ``dry_run`` nothing is written and no audit event is recorded.
    """
    report = RepairReport(dry_run=dry_run)
    map_ids = [
        row[0]
        for row in await session.execute(
            select(MapLayer.map_id)
            .where(MapLayer.layer_type.in_(_VECTOR_LAYER_TYPES))
            .distinct()
            .order_by(MapLayer.map_id)
        )
    ]
    for map_id in map_ids:
        await _repair_map(session, map_id, report, dry_run=dry_run)
    return report


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        description="Repair stored map layers that read a column by the wrong name."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without writing anything.",
    )
    args = parser.parse_args()

    async def _run() -> None:
        # Import all ORM models so the SQLAlchemy mapper registry is
        # complete before the first query: the audit import alone leaves
        # AuditLog's User relationship unregistered, and a fresh process
        # running only this module fails on its first query without it.
        import app.modules.auth.models  # noqa: F401
        from app.core.db import async_session  # late-bound

        async with async_session() as session:
            report = await repair_stored_layers(session, dry_run=args.dry_run)
        print(report.format())

    asyncio.run(_run())
