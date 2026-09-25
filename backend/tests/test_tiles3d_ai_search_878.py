"""The AI's search_datasets tool can surface a tiles3d dataset (#878 U6).

`add_layer` already refuses the record type with a 400 (see
`test_tiles3d_record_type_refusals.py`), so a search result the AI can't map
fails safely rather than silently. No filter narrows the AI's search results.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.platform.extensions.defaults import DefaultProcessingPort
from app.processing.ai.service import _execute_search_tool
from tests.factories import create_dataset, create_map_via_api, get_user_id

pytestmark = pytest.mark.anyio


@pytest.fixture
async def tiles3d_layer(test_db_session):
    """A published tiles3d dataset with no feature table, owned by admin."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Campus tileset {uuid.uuid4().hex[:8]}",
        table_name=f"tiles3d_{uuid.uuid4().hex[:12]}",
        record_type="tiles3d_dataset",
        source_format="3dtiles",
        source_filename="tileset.json",
        geometry_type=None,
        feature_count=None,
    )
    rec_id = dataset.record_id
    yield dataset
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": rec_id}
    )
    await test_db_session.commit()


async def test_search_datasets_can_return_a_tiles3d_dataset_and_add_layer_still_refuses(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    tiles3d_layer,
):
    """search_datasets returns the tileset; add_layer on it still 400s."""
    port = DefaultProcessingPort()
    results = await _execute_search_tool(
        test_db_session,
        SimpleNamespace(id=str(tiles3d_layer.record.created_by)),
        {"admin"},
        {"q": tiles3d_layer.record.title},
        port=port,
    )

    assert str(tiles3d_layer.id) in {r["id"] for r in results}

    map_id = (await create_map_via_api(client, admin_auth_header))["id"]
    resp = await client.post(
        f"/maps/{map_id}/layers",
        json={"dataset_id": str(tiles3d_layer.id)},
        headers=admin_auth_header,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "This dataset cannot be added to a map"
