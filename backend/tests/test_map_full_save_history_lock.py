"""A full layer save reads the keyed layers it compares under the map's lock,
so a publish that commits while it waits is part of what it changed."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

import app.core.db as db_module
from app.modules.catalog.maps.models import MapEditHistoryEvent, MapLayer
from app.processing.ingest.manifest_schemas import ManifestApplyRequest
from app.processing.ingest.manifest_service import apply_manifest
from tests.test_manifest_maps_dry_run import _body, _http_request
from tests import test_map_save_dataset_delete_lock_order as lock_order
from tests.test_map_share_waits_on_dataset_change import _until_blocked

pytestmark = pytest.mark.usefixtures("_init_tile_pool_for_tests")

# Fixtures the lock-order tests define, shared as they are.
world = lock_order.world
children = lock_order.children
_entry = lock_order._entry
_RED = {"circle-color": "#ff0000"}


async def test_a_full_save_behind_a_publish_records_the_change_it_overwrote(
    client: AsyncClient, world, test_db_session, children
):
    map_id, layer_id = world["map_id"], world["layer_id"]
    stored = (
        await test_db_session.execute(
            sa.select(MapLayer)
            .where(MapLayer.id == layer_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    written_back = {
        "id": str(layer_id),
        "dataset_id": str(stored.dataset_id),
        "paint": stored.paint,
        "layout": stored.layout,
        "style_config": stored.style_config,
        "opacity": stored.opacity,
        "display_name": stored.display_name,
    }
    await test_db_session.rollback()

    async with db_module.async_session() as publisher:
        await publisher.execute(
            sa.text("SELECT id FROM catalog.maps WHERE id = :id FOR UPDATE"),
            {"id": map_id},
        )
        await publisher.execute(
            sa.update(MapLayer).where(MapLayer.id == layer_id).values(paint=_RED)
        )
        save = asyncio.create_task(
            client.put(
                f"/maps/{map_id}",
                json={"layers": [written_back]},
                headers=world["headers"],
            )
        )
        children.append(save)
        await _until_blocked(publisher, save)
        await publisher.commit()
    response = await save

    assert response.status_code == 200, response.text
    async with db_module.async_session() as session:
        [replaced] = (
            await session.scalars(
                sa.select(MapEditHistoryEvent).where(
                    MapEditHistoryEvent.map_id == map_id,
                    MapEditHistoryEvent.action == "layer.replace",
                )
            )
        ).all()
        assert replaced.details["keyed_styling_changed"] is True
        entry = _entry(world["key"], world["dataset_id"])
        entry["styling"] = "replace_if_unedited"
        result = await apply_manifest(
            session,
            ManifestApplyRequest.model_validate(_body(entry, dry_run=False)),
            world["owner"],
            _http_request(),
        )
    assert (result.maps[0].styling, [m.code for m in result.maps[0].messages]) == (
        "kept",
        ["A070"],
    )
