"""The settings listing reports the width an embedding_dims reset would restore.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import pytest
from httpx import AsyncClient

from app.core.persistent_config import EMBEDDING_DIMS


@pytest.mark.anyio
async def test_embedding_dims_item_carries_the_runtime_default(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The UI compares this with the current value to spot a no-op reset."""
    resp = await client.get("/settings/all/", headers=admin_auth_header)

    assert resp.status_code == 200, resp.text
    items = {i["key"]: i for tab in resp.json()["tabs"].values() for i in tab}
    assert items["embedding_dims"]["default_value"] == int(
        await EMBEDDING_DIMS.resolved_default(test_db_session)
    )
    assert items["log_level"]["default_value"] is None
