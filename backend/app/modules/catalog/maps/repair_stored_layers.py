"""One-off repair of stored map layers that read a column by the wrong name.

Run once, from ``backend/``::

    python -m app.modules.catalog.maps.repair_stored_layers

It loads each vector layer with its dataset's recorded ``column_info``,
rewrites the layer's column references to the stored names with
``repair_layer_columns``, saves the layers that changed, and prints what it
changed and what it skipped: a layer whose dataset recorded no columns, a
layer that no longer reads as a layer, and a map another change holds are
all skipped. Each map is repaired in a transaction of its own, under the
row lock a layer save takes, so a save in progress waits rather than
interleaving; a rerun repairs anything a concurrent save overwrote.

The command writes only ``map_layers`` rows. A map layer carries no
``updated_at`` of its own and the maps row is not touched, so a map's
``updated_at`` does not move. A published map is served from the live layer
rows, so a repaired layer shows in the published map at once, with no
republish needed; the publish-time marker is the map's ``updated_at``, so a
republish after the repair records the same ``updated_at`` it recorded
before.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
        for entry in self.layers:
            where = f"map {entry.map_id} layer {entry.layer_id}"
            if entry.status == "repaired":
                changes = ", ".join(
                    f"{old} -> {new}" for old, new in sorted(entry.repaired.items())
                )
                lines.append(f"{where}: repaired {changes}")
            elif entry.status == "unchanged":
                if entry.unrepaired:
                    left = ", ".join(
                        f"{name} ({why})"
                        for name, why in sorted(entry.unrepaired.items())
                    )
                    lines.append(f"{where}: unchanged, left {left}")
                else:
                    lines.append(f"{where}: unchanged")
            else:
                lines.append(f"{where}: skipped ({entry.reason})")
        lines.append(
            f"{self.repaired_count} repaired, "
            f"{self.unchanged_count} unchanged, "
            f"{self.skipped_count} skipped"
        )
        return "\n".join(lines)


def _repair_layer(
    layer: MapLayer,
    column_info: Sequence[dict[str, Any]] | None,
    report: RepairReport,
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
    before = {name: getattr(layer_in, name) for name in _LAYER_JSON_FIELDS}
    repaired_layer, result = repair_layer_columns(layer_in, column_info)
    entry.repaired = dict(result.repaired)
    entry.unrepaired = dict(result.unrepaired)
    if not result.repaired:
        entry.status = "unchanged"
        report.layers.append(entry)
        return
    for name in _LAYER_JSON_FIELDS:
        value = getattr(repaired_layer, name)
        if value == before[name]:
            continue
        if name == "popup_config":
            setattr(
                layer,
                name,
                value.model_dump(exclude_unset=True) if value is not None else None,
            )
        else:
            setattr(layer, name, value)
    entry.status = "repaired"
    report.layers.append(entry)


async def _repair_map(
    session: AsyncSession, map_id: uuid.UUID, report: RepairReport
) -> None:
    """Repair one map's vector layers and commit, or record them skipped."""
    rows = (
        await session.execute(
            select(MapLayer, Dataset.column_info)
            .join(Dataset, MapLayer.dataset_id == Dataset.id)
            .where(MapLayer.map_id == map_id)
            .where(MapLayer.layer_type.in_(_VECTOR_LAYER_TYPES))
            .order_by(MapLayer.sort_order, MapLayer.id)
        )
    ).all()
    try:
        await bounded_row_lock(
            session,
            select(Map.id).where(Map.id == map_id).with_for_update(key_share=True),
            message="Another change to this map is in progress.",
        )
    except CatalogLockConflict:
        for layer, _ in rows:
            report.layers.append(
                StoredLayerRepair(
                    map_id=map_id,
                    layer_id=layer.id,
                    dataset_id=layer.dataset_id,
                    status="skipped",
                    reason="another change to the map is in progress",
                )
            )
        return
    for layer, column_info in rows:
        _repair_layer(layer, column_info, report)
    await session.commit()


async def repair_stored_layers(session: AsyncSession) -> RepairReport:
    """Repair every stored vector layer against its dataset's recorded columns.

    Each map is repaired in a transaction of its own, so a map the lock
    cannot be taken for is skipped without losing the maps already repaired.
    """
    report = RepairReport()
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
        await _repair_map(session, map_id, report)
    return report


if __name__ == "__main__":
    import asyncio

    async def _run() -> None:
        from app.core.db import async_session  # late-bound

        async with async_session() as session:
            report = await repair_stored_layers(session)
        print(report.format())

    asyncio.run(_run())
