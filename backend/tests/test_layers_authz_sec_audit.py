"""Regression tests for layer column DDL owner/admin authorization."""

import pytest
from httpx import AsyncClient

from tests.factories import create_dataset, get_user_id


@pytest.mark.anyio
async def test_editor_cannot_add_column_to_public_dataset_they_do_not_own(
    client: AsyncClient,
    admin_auth_header: dict,
    editor_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="Public Layer DDL Target",
        visibility="public",
    )

    resp = await client.post(
        f"/layers/{dataset.id}/columns/",
        json={"column": {"name": "new_attr", "type": "text"}},
        headers=editor_auth_header,
    )

    assert resp.status_code == 403
