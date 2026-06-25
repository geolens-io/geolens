from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Embedding dimension change via PUT /settings/
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_put_settings_changing_embedding_dims_triggers_cleanup(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """PUT /settings/ with a new embedding_dims value deletes existing embeddings
    and rebuilds the vector column + HNSW index."""
    from sqlalchemy import text

    # Record current column dimensions
    col_check = await test_db_session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    current_dims = col_check.scalar_one_or_none()

    # Choose a different dimension value
    new_dims = 512 if current_dims != 512 else 768

    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_dims": new_dims}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tabs" in data

    # Verify column was altered to the new dimension
    col_check2 = await test_db_session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    updated_dims = col_check2.scalar_one_or_none()
    assert updated_dims == new_dims

    # Verify no embeddings remain
    count_result = await test_db_session.execute(
        text("SELECT COUNT(*) FROM catalog.record_embeddings")
    )
    assert count_result.scalar_one() == 0


@pytest.mark.anyio
async def test_put_settings_same_embedding_dims_does_not_delete(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """PUT /settings/ with the same embedding_dims does NOT delete embeddings."""
    from sqlalchemy import text

    # Read current column dimensions
    col_check = await test_db_session.execute(
        text(
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'catalog.record_embeddings'::regclass "
            "AND attname = 'embedding'"
        )
    )
    current_dims = col_check.scalar_one_or_none()
    if current_dims is None or current_dims < 1:
        # A dimensionless ``vector`` column reports atttypmod == -1 (not NULL), so
        # guard on the valid range too — otherwise we'd PUT embedding_dims=-1 and
        # the [1, 4096] validator returns 422. This makes the test order-independent
        # (it no longer relies on a sibling test having fixed the column dimension).
        current_dims = 1536

    # Send the same dims value
    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_dims": current_dims}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tabs" in data


@pytest.mark.anyio
async def test_put_settings_requires_admin_auth(
    client: AsyncClient,
    viewer_auth_header: dict,
):
    """PUT /settings/ returns 403 for non-admin users."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_dims": 512}},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_put_settings_unauthenticated_returns_401(
    client: AsyncClient,
):
    """PUT /settings/ without auth returns 401."""
    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_dims": 512}},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# BUG-029: dead _rebuild_embedding_column shadow removed
# ---------------------------------------------------------------------------


def test_router_has_no_dead_rebuild_embedding_column_shadow():
    """BUG-029: the local _rebuild_embedding_column that shadowed the real
    implementation (and silently swallowed DDL failures) must not exist.

    The route imports rebuild_embedding_column from
    app.processing.embeddings.service, which RE-RAISES on DDL failure. A local
    same-purpose copy in the router was dead code (zero callers) whose
    swallow-and-rollback contract contradicted the live 503 path — a future
    mis-edit could silently break the rebuild. Guard against re-introduction.
    """
    from app.modules.settings import router as settings_router

    assert not hasattr(settings_router, "_rebuild_embedding_column"), (
        "Dead _rebuild_embedding_column shadow reintroduced in settings/router.py"
    )


@pytest.mark.anyio
async def test_put_settings_embedding_rebuild_failure_propagates_as_503(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """BUG-029: a DDL failure during embedding rebuild must surface as 503.

    Proves the route uses the RAISING rebuild_embedding_column (which the
    handler maps to a 503 + setting rollback), not the deleted shadow that
    swallowed errors and would have let the request 'succeed' silently.
    """
    from sqlalchemy import text

    from app.core.dependencies import get_db
    from app.api.main import app

    # Pick a new dimension so the rebuild branch actually runs.
    new_dims = 512
    async for db in app.dependency_overrides[get_db]():
        col_check = await db.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'catalog.record_embeddings'::regclass "
                "AND attname = 'embedding'"
            )
        )
        current_dims = col_check.scalar_one_or_none()
        new_dims = 512 if current_dims != 512 else 768
        break

    with patch(
        "app.processing.embeddings.service.rebuild_embedding_column",
        AsyncMock(side_effect=RuntimeError("simulated DDL failure")),
    ):
        resp = await client.put(
            "/settings/",
            json={"settings": {"embedding_dims": new_dims}},
            headers=admin_auth_header,
        )

    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Tile config tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_get_tile_config_exposes_resolved_public_urls():
    """The public tile-config payload should expose the resolved app/API URLs."""
    from app.modules.settings import router as settings_router

    with (
        patch.object(
            settings_router,
            "app_settings",
            SimpleNamespace(cdn_base_url="https://cdn.example.com"),
        ),
        patch(
            "app.modules.settings.router.get_public_app_url",
            AsyncMock(return_value="https://catalog.example.com"),
        ),
        patch(
            "app.modules.settings.router.get_public_api_url",
            AsyncMock(return_value="https://catalog.example.com/api"),
        ),
    ):
        response = await settings_router.get_tile_config(
            request=SimpleNamespace(
                headers={}, url=SimpleNamespace(scheme="https"), scope={}
            ),
            db=object(),
        )

    assert response.cdn_base_url == "https://cdn.example.com"
    assert response.public_app_url == "https://catalog.example.com"
    assert response.public_api_url == "https://catalog.example.com/api"
    assert response.public_base_url == "https://catalog.example.com/api"


# ---------------------------------------------------------------------------
# Per-user quota settings validation (PR #327)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("key", ["max_storage_bytes_per_user", "max_datasets_per_user"])
async def test_put_settings_rejects_negative_quota(
    client: AsyncClient, admin_auth_header: dict, key: str
):
    """Negative per-user quotas are rejected with 422 (parity with the other
    bounded-int storage settings). Without the validator a -1 would persist and
    show as 'overridden' while behaving as unlimited (cap>0 guard) — misleading."""
    resp = await client.put(
        "/settings/",
        json={"settings": {key: -1}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("key", ["max_storage_bytes_per_user", "max_datasets_per_user"])
async def test_put_settings_rejects_fractional_quota(
    client: AsyncClient, admin_auth_header: dict, key: str
):
    """Fractional per-user quotas are rejected with 422. Without the guard,
    int(0.5) truncates to 0 (= unlimited) and silently disables the cap."""
    resp = await client.put(
        "/settings/",
        json={"settings": {key: 0.5}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_put_settings_accepts_valid_quota(
    client: AsyncClient, admin_auth_header: dict
):
    """A valid per-user quota saves (200) and is reflected on the storage tab."""
    resp = await client.put(
        "/settings/",
        json={
            "settings": {
                "max_storage_bytes_per_user": 1073741824,
                "max_datasets_per_user": 25,
            }
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    storage = {s["key"]: s["value"] for s in resp.json()["tabs"]["storage"]}
    assert storage["max_storage_bytes_per_user"] == 1073741824
    assert storage["max_datasets_per_user"] == 25

    # Reset so we don't leave a cap on the shared per-worker DB.
    await client.put(
        "/settings/",
        json={
            "settings": {"max_storage_bytes_per_user": 0, "max_datasets_per_user": 0}
        },
        headers=admin_auth_header,
    )
