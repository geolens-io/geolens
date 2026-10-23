"""A style import answers with only the layers the caller can read when it returns.

The import checks each layer's dataset before it saves, and the response is
built after the save. A dataset that leaves the caller's reach in between keeps
its layer in the map, but its title and columns stay out of the response, as
on every other map read.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.maps import router as maps_router

from tests.factories import create_dataset, create_user, get_user_id


def _style(*dataset_ids: uuid.UUID) -> dict:
    return {
        "version": 8,
        "name": f"Imported {uuid.uuid4().hex[:6]}",
        "sources": {
            f"s{i}": {
                "type": "vector",
                "metadata": {"geolens": {"dataset_id": str(dataset_id)}},
            }
            for i, dataset_id in enumerate(dataset_ids)
        },
        "layers": [
            {
                "id": f"layer-{i}",
                "type": "fill",
                "source": f"s{i}",
                "source-layer": "data",
            }
            for i in range(len(dataset_ids))
        ],
    }


async def test_import_response_leaves_out_a_layer_the_caller_can_no_longer_read(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    admin_id = await get_user_id(test_db_session, "admin")
    editor, _ = await create_user(client, admin_auth_header, "editor")
    kept = await create_dataset(test_db_session, created_by=admin_id, name="Kept")
    hidden = await create_dataset(test_db_session, created_by=admin_id, name="Hidden")
    await test_db_session.commit()

    record_history = maps_router.record_map_history_event

    async def hide_dataset_then_record(db, **kwargs):
        # The dataset's owner makes it private while the import is in flight.
        await db.execute(
            update(Record)
            .where(Record.id == hidden.record_id)
            .values(visibility="private")
        )
        return await record_history(db, **kwargs)

    monkeypatch.setattr(
        maps_router, "record_map_history_event", hide_dataset_then_record
    )

    resp = await client.post(
        "/maps/import", json=_style(kept.id, hidden.id), headers=editor
    )

    assert resp.status_code == 201, resp.text
    layers = resp.json()["map"]["layers"]
    assert [layer["dataset_id"] for layer in layers] == [str(kept.id)]
    assert "Hidden" not in resp.text
