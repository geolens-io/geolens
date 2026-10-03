"""A merge import that would delete the stored embeddings needs a current preview token.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import pytest
from httpx import AsyncClient

from app.core.persistent_config import EMBEDDING_DIMS
from tests.test_embedding_width_reset_and_import import (
    _publish_width,
    _width_other_than,
)
from tests.test_settings_router import _column_dims
from tests.test_settings_router import (
    restore_embedding_settings as restore_embedding_settings,
)

_TOKEN = "X-Config-Preview-Token"


async def _preview(client, headers, width):
    resp = await client.post(
        "/config-ops/dry-run/?mode=merge",
        json={"settings": {"embedding_dims": width}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["preview_token"]


async def _merge(client, headers, width, token=None):
    return await client.post(
        "/config-ops/import/?mode=merge",
        json={"settings": {"embedding_dims": width}},
        headers={**headers, **({_TOKEN: token} if token else {})},
    )


@pytest.mark.anyio
async def test_a_width_merge_with_its_current_token_applies(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    restore_embedding_settings,
):
    """The token a width-changing preview returns lets the import apply."""
    target = _width_other_than(await _column_dims(test_db_session))
    token = await _preview(client, admin_auth_header, target)
    assert token

    resp = await _merge(client, admin_auth_header, target, token)

    assert resp.status_code == 200, resp.text
    assert await _column_dims(test_db_session) == target


@pytest.mark.anyio
async def test_a_width_merge_without_a_token_is_refused(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    restore_embedding_settings,
):
    """Nothing is deleted when the operator never previewed the deletion."""
    before = await _column_dims(test_db_session)

    resp = await _merge(
        client, admin_auth_header, _width_other_than(before), token=None
    )

    assert resp.status_code == 409, resp.text
    assert await _column_dims(test_db_session) == before


@pytest.mark.anyio
async def test_a_warning_free_preview_goes_stale_when_the_live_width_changes(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    restore_embedding_settings,
):
    """A preview of a matching width issues no token, so the later change is refused."""
    live = await _column_dims(test_db_session)
    assert await _preview(client, admin_auth_header, live) is None
    other = _width_other_than(live)
    await _publish_width(client, admin_auth_header, test_db_session, other)

    resp = await _merge(client, admin_auth_header, live)

    assert resp.status_code == 409, resp.text
    assert await _column_dims(test_db_session) == other


@pytest.mark.anyio
async def test_a_token_goes_stale_when_the_live_width_changes(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    restore_embedding_settings,
):
    """A token for one live width does not authorize deleting at another."""
    live = await _column_dims(test_db_session)
    target = _width_other_than(live)
    token = await _preview(client, admin_auth_header, target)
    other = _width_other_than(live, target)
    await _publish_width(client, admin_auth_header, test_db_session, other)

    resp = await _merge(client, admin_auth_header, target, token)

    assert resp.status_code == 409, resp.text
    assert await _column_dims(test_db_session) == other


@pytest.mark.anyio
async def test_a_merge_that_keeps_the_width_needs_no_token(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    restore_embedding_settings,
):
    """Merges with no deletion stay token-free."""
    live = await _column_dims(test_db_session)
    await EMBEDDING_DIMS.set(test_db_session, live)

    resp = await _merge(client, admin_auth_header, live)

    assert resp.status_code == 200, resp.text
    assert await _column_dims(test_db_session) == live
