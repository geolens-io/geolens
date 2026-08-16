import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import anyio
import pytest
from httpx import AsyncClient
from pydantic import SecretStr


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
    assert response.mvt_source_layer_prefix == "data"


@pytest.mark.anyio
async def test_get_tile_config_exposes_tenant_mvt_source_layer_prefix():
    """The frontend receives the exact source-layer prefix emitted by MVT."""
    from app.modules.settings import router as settings_router

    tenant_id = uuid.uuid4()
    request = SimpleNamespace(
        headers={},
        url=SimpleNamespace(scheme="https"),
        scope={},
        state=SimpleNamespace(tenant_id=str(tenant_id)),
    )
    expected = f"data_t_{str(tenant_id).replace('-', '_')}"
    with (
        patch.object(
            settings_router,
            "app_settings",
            SimpleNamespace(cdn_base_url=None),
        ),
        patch.object(settings_router, "is_multi_tenant", return_value=True),
        patch.object(
            settings_router,
            "tenant_data_schema",
            return_value=expected,
        ) as schema_name,
        patch(
            "app.modules.settings.router.get_public_app_url",
            AsyncMock(return_value="https://acme.example.com"),
        ),
        patch(
            "app.modules.settings.router.get_public_api_url",
            AsyncMock(return_value="https://api.example.com"),
        ),
    ):
        response = await settings_router.get_tile_config(request=request, db=object())

    assert response.mvt_source_layer_prefix == expected
    schema_name.assert_called_once_with(str(tenant_id))


@pytest.mark.anyio
async def test_get_tile_config_fails_closed_without_tenant_context():
    """An unscoped hosted request must not advertise the global data schema."""
    from app.modules.settings import router as settings_router

    request = SimpleNamespace(
        headers={},
        url=SimpleNamespace(scheme="https"),
        scope={},
        state=SimpleNamespace(tenant_id=None),
    )
    with (
        patch.object(
            settings_router,
            "app_settings",
            SimpleNamespace(cdn_base_url=None),
        ),
        patch.object(settings_router, "is_multi_tenant", return_value=True),
        patch(
            "app.modules.settings.router.get_public_app_url",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.modules.settings.router.get_public_api_url",
            AsyncMock(return_value=None),
        ),
    ):
        response = await settings_router.get_tile_config(request=request, db=object())

    assert response.mvt_source_layer_prefix is None


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


# ---------------------------------------------------------------------------
# #1529: the embedding model and its dimensions publish atomically
# ---------------------------------------------------------------------------
#
# `update_settings` used to commit a new `embedding_model` and only then await
# the provider probe that discovers that model's width. For the length of that
# network call the committed pair was the new model beside the OLD model's
# dimension count — committed, stable, and self-consistent, so no reader could
# tell it from a real configuration by reading it twice.
#
# These tests drive the endpoint itself with a probe that blocks, and look at
# the committed pair from a SEPARATE connection while the probe is in flight.
# That is the window, opened deliberately and observed from outside.

_OLD_MODEL = "atomic-publish-model-a"
_NEW_MODEL = "atomic-publish-model-b"
_OLD_DIMS = 1536
_PROBED_DIMS = 768


class _ProbeProvider:
    """Base fake embedding provider: records what each probe asked for."""

    def __init__(self):
        self.calls: list[dict] = []

    async def resolve_runtime_config(self, session):
        return {
            "default_model": "provider-fallback-model",
            "default_dims": 1536,
            "base_url": "http://embeddings.invalid",
        }

    async def embed(self, *, texts, model, dimensions, base_url, timeout):
        raise NotImplementedError


class _FixedWidthProbeProvider(_ProbeProvider):
    """Answers every probe with a vector of one fixed width."""

    def __init__(self, width: int):
        super().__init__()
        self._width = width

    async def embed(self, *, texts, model, dimensions, base_url, timeout):
        self.calls.append({"model": model, "dimensions": dimensions})
        return [[0.0] * self._width for _ in texts]


class _BlockingProbeProvider(_FixedWidthProbeProvider):
    """Holds the probe open until a reader has looked at the published pair.

    A real probe is a provider network call, so the window is however long that
    takes. Blocking on an event is the same window under test control: the
    reader below cannot look "somewhere in the middle" by luck, it looks while
    the call is provably still in flight.
    """

    def __init__(self, width: int):
        super().__init__(width)
        self.entered = anyio.Event()
        self.release = anyio.Event()

    async def embed(self, *, texts, model, dimensions, base_url, timeout):
        self.calls.append({"model": model, "dimensions": dimensions})
        self.entered.set()
        await self.release.wait()
        return [[0.0] * self._width for _ in texts]


class _ExplodingProbeProvider(_ProbeProvider):
    """Fails every probe, the way an unreachable or misconfigured provider does."""

    async def embed(self, *, texts, model, dimensions, base_url, timeout):
        self.calls.append({"model": model, "dimensions": dimensions})
        raise RuntimeError("simulated provider failure")


def _install_probe_provider(monkeypatch, provider) -> None:
    """Route BOTH probe paths at ``provider``.

    The pre-fix tree probes through `probe_embedding_dimensions`, which binds
    `get_embedding_provider` into the embeddings service module at import time.
    The fixed tree probes from the settings router, which resolves the same
    name out of `app.platform.extensions` at call time. Patching both is what
    lets one test body run against either tree — which is what makes an
    observed red run mean anything.
    """
    import app.platform.extensions as extensions_module
    from app.core.config import settings as core_settings
    from app.processing.embeddings import service as service_module

    monkeypatch.setattr(
        extensions_module, "get_embedding_provider", lambda _name: provider
    )
    monkeypatch.setattr(
        service_module, "get_embedding_provider", lambda _name: provider
    )
    # Both probe paths refuse to call a provider without a key configured.
    monkeypatch.setattr(core_settings, "openai_api_key", SecretStr("probe-test-key"))


async def _column_dims(session) -> int | None:
    """Declared width of the vector column, or None if the table is absent."""
    from sqlalchemy import text

    return (
        await session.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid = 'catalog.record_embeddings'::regclass "
                "AND attname = 'embedding' AND NOT attisdropped"
            )
        )
    ).scalar_one_or_none()


@pytest.fixture
async def restore_embedding_settings(test_db_session):
    """Put the embedding pair and the vector column back afterwards.

    The per-worker database is shared across the whole session, and these tests
    change global configuration and run real DDL.
    """
    from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL
    from app.processing.embeddings.service import rebuild_embedding_column

    before = (
        await EMBEDDING_MODEL.get(test_db_session),
        await EMBEDDING_DIMS.get(test_db_session),
        await _column_dims(test_db_session),
    )
    yield
    await EMBEDDING_MODEL.set(test_db_session, before[0])
    await EMBEDDING_DIMS.set(test_db_session, before[1])
    if before[2] is not None and before[2] > 0:
        await rebuild_embedding_column(test_db_session, before[2])


@pytest.mark.anyio
async def test_no_reader_sees_the_new_model_beside_the_old_dimensions(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """The window itself: look at the committed pair while the probe is running.

    On the publish-then-probe tree the reader below sees `(_NEW_MODEL,
    _OLD_DIMS)` — a pair that never existed in any configuration — and the
    request has not even reached the provider's answer yet.
    """
    import app.core.db as db_module
    from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL

    # Non-vacuity: if the probed width matched the old one, the new model
    # beside the old width would be a legitimate pair and there would be
    # nothing here to detect.
    assert _PROBED_DIMS != _OLD_DIMS
    assert _NEW_MODEL != _OLD_MODEL

    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _OLD_DIMS)

    provider = _BlockingProbeProvider(_PROBED_DIMS)
    _install_probe_provider(monkeypatch, provider)
    # The column rebuild has its own test below; stub it so this one is about
    # the published pair and nothing else.
    rebuild = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.processing.embeddings.service.rebuild_embedding_column", rebuild
    )

    observations: list[tuple] = []

    async def _look_while_the_probe_is_in_flight():
        try:
            # A tree that never opens the window would otherwise hang here.
            with anyio.fail_after(30):
                await provider.entered.wait()
            # A separate connection, so this reads committed state — exactly
            # what a backfill, a semantic search, or the coverage stats read.
            async with db_module.async_session() as reader:
                observations.append(
                    (
                        await EMBEDDING_MODEL.get_uncached(reader),
                        await EMBEDDING_DIMS.get_uncached(reader),
                    )
                )
        finally:
            provider.release.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(_look_while_the_probe_is_in_flight)
        resp = await client.put(
            "/settings/",
            json={"settings": {"embedding_model": _NEW_MODEL}},
            headers=admin_auth_header,
        )

    assert resp.status_code == 200
    # Non-vacuity: the probe has to have run, against the model being
    # published, asking for its natural width. Without that call there is no
    # window and the reader below is just reading the settled state.
    assert provider.calls == [{"model": _NEW_MODEL, "dimensions": None}]
    # The finding: mid-probe, the committed pair is still the OLD one, whole.
    assert observations == [(_OLD_MODEL, _OLD_DIMS)]
    # And afterwards it is the NEW one, whole.
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _NEW_MODEL
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == _PROBED_DIMS
    # The detected width reaches the column rebuild too — the auto-detect and
    # explicit-dims branches are no longer mutually exclusive.
    rebuild.assert_awaited_once()
    assert rebuild.await_args.args[1] == _PROBED_DIMS


@pytest.mark.anyio
async def test_a_failed_probe_publishes_neither_half(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """If the probe fails there is no width to publish, so the model stays put."""
    from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL

    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _OLD_DIMS)

    provider = _ExplodingProbeProvider()
    _install_probe_provider(monkeypatch, provider)
    rebuild = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.processing.embeddings.service.rebuild_embedding_column", rebuild
    )

    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_model": _NEW_MODEL}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 502
    # Non-vacuity: a request that never reached the provider would satisfy
    # every assertion below without proving the failure was handled.
    assert provider.calls == [{"model": _NEW_MODEL, "dimensions": None}]
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _OLD_MODEL
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == _OLD_DIMS
    rebuild.assert_not_awaited()


@pytest.mark.anyio
async def test_an_auto_detected_width_rebuilds_the_vector_column(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """A published width the column does not have is the same bug, one layer down.

    Auto-detect used to persist the detected width and leave the column alone,
    because the rebuild only ran on the explicit-dims branch. Every insert then
    failed on the typmod while the configuration read as consistent.
    """
    from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL

    column_before = await _column_dims(test_db_session)
    # Non-vacuity: a dimensionless `vector` column (atttypmod -1) accepts any
    # width, so there would be no mismatch for the rebuild to resolve.
    assert column_before is not None and column_before > 0
    target = 768 if column_before != 768 else 512
    assert target != column_before

    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    await EMBEDDING_DIMS.set(test_db_session, column_before)

    provider = _FixedWidthProbeProvider(target)
    _install_probe_provider(monkeypatch, provider)

    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_model": _NEW_MODEL}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200
    assert provider.calls == [{"model": _NEW_MODEL, "dimensions": None}]
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == target
    # Storage is the one thing no config-level consistency check looks at.
    assert await _column_dims(test_db_session) == target


@pytest.mark.anyio
async def test_a_failed_rebuild_rolls_back_both_published_halves(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """Rolling back the width alone would recreate the mismatched pair.

    A request naming both halves publishes both; a DDL failure has to restore
    both, or the failure path leaves exactly the state the probe ordering was
    changed to prevent.
    """
    from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL

    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _OLD_DIMS)

    monkeypatch.setattr(
        "app.processing.embeddings.service.rebuild_embedding_column",
        AsyncMock(side_effect=RuntimeError("simulated DDL failure")),
    )

    resp = await client.put(
        "/settings/",
        json={
            "settings": {
                "embedding_model": _NEW_MODEL,
                "embedding_dims": _PROBED_DIMS,
            }
        },
        headers=admin_auth_header,
    )

    assert resp.status_code == 503
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == _OLD_DIMS
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _OLD_MODEL


@pytest.mark.anyio
async def test_resending_the_unchanged_model_does_not_probe(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """A save that re-sends the current model must not depend on the provider.

    The AI settings tab sends only dirty fields, but an API or CLI caller can
    PUT the whole tab. Probing on presence rather than on change would turn
    every such save into a 502 whenever the provider is unreachable — and
    would also overwrite an explicitly configured width.
    """
    from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL

    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _OLD_DIMS)

    provider = _ExplodingProbeProvider()
    _install_probe_provider(monkeypatch, provider)

    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_model": _OLD_MODEL}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200
    assert provider.calls == []
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == _OLD_DIMS


@pytest.mark.anyio
async def test_a_probed_width_out_of_range_publishes_neither_half(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
    restore_embedding_settings,
):
    """A detected width goes through the same validator an admin-typed one does.

    The published width becomes the ``vector(N)`` the column is rebuilt to, so
    "whatever the provider answered" is not an acceptable source for it. Out of
    the [1, 4096] range the request is rejected whole, exactly as a typed value
    would be.
    """
    from app.core.persistent_config import EMBEDDING_DIMS, EMBEDDING_MODEL

    await EMBEDDING_MODEL.set(test_db_session, _OLD_MODEL)
    await EMBEDDING_DIMS.set(test_db_session, _OLD_DIMS)

    provider = _FixedWidthProbeProvider(8192)
    _install_probe_provider(monkeypatch, provider)
    rebuild = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.processing.embeddings.service.rebuild_embedding_column", rebuild
    )

    resp = await client.put(
        "/settings/",
        json={"settings": {"embedding_model": _NEW_MODEL}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 422
    assert "embedding_dims" in resp.json()["detail"]
    assert await EMBEDDING_MODEL.get_uncached(test_db_session) == _OLD_MODEL
    assert await EMBEDDING_DIMS.get_uncached(test_db_session) == _OLD_DIMS
    rebuild.assert_not_awaited()
