"""Regression coverage for tenant-sensitive application caches."""

from __future__ import annotations

import importlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.platform.cache import tenant_cache_context_available, tenant_cache_key
from app.platform.cache.memory import InMemoryCacheProvider


TENANT_A = "00000000-0000-0000-0000-0000000000a1"
TENANT_B = "00000000-0000-0000-0000-0000000000b2"


@pytest.fixture
def multi_tenant(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    token = current_tenant_var.set(None)
    try:
        yield
    finally:
        current_tenant_var.reset(token)


def _set_tenant(tenant_id: str):
    return current_tenant_var.set(tenant_id)


def test_single_tenant_cache_keys_remain_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "single_tenant")
    token = current_tenant_var.set(None)
    try:
        assert tenant_cache_key("catalog:datasets:admin:0:50") == (
            "catalog:datasets:admin:0:50"
        )
    finally:
        current_tenant_var.reset(token)


def test_multi_tenant_cache_keys_are_partitioned_and_fail_closed(multi_tenant):
    assert tenant_cache_context_available() is False
    with pytest.raises(ValueError, match="tenant_id is required"):
        tenant_cache_key("catalog:datasets:admin:0:50")

    token_a = _set_tenant(TENANT_A)
    try:
        key_a = tenant_cache_key("catalog:datasets:admin:0:50")
    finally:
        current_tenant_var.reset(token_a)

    token_b = _set_tenant(TENANT_B)
    try:
        key_b = tenant_cache_key("catalog:datasets:admin:0:50")
    finally:
        current_tenant_var.reset(token_b)

    assert key_a == f"catalog:datasets:admin:0:50:tenant:{TENANT_A}"
    assert key_b == f"catalog:datasets:admin:0:50:tenant:{TENANT_B}"
    assert key_a != key_b


def test_unscoped_host_bypasses_anonymous_request_caches(multi_tenant):
    from app.modules.catalog.search import cache as search_cache

    assert search_cache.is_anon_cacheable(None) is False

    token = _set_tenant(TENANT_A)
    try:
        assert tenant_cache_context_available() is True
        assert search_cache.is_anon_cacheable(None) is True
    finally:
        current_tenant_var.reset(token)


class _MemoryCache:
    def __init__(self):
        self.values: dict[str, object] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: object, *, ttl: int):
        self.values[key] = value

    async def delete(self, key: str):
        self.values.pop(key, None)


@pytest.mark.anyio
async def test_admin_dataset_and_collection_lists_do_not_share_cache_entries(
    multi_tenant,
    monkeypatch: pytest.MonkeyPatch,
):
    datasets_router = importlib.import_module("app.modules.catalog.datasets.api.router")
    collections_router = importlib.import_module(
        "app.modules.catalog.collections.router"
    )
    cache = _MemoryCache()
    user = MagicMock(id=uuid.uuid4())
    db = AsyncMock()

    monkeypatch.setattr(datasets_router, "get_cache", lambda: cache)
    monkeypatch.setattr(collections_router, "get_cache", lambda: cache)
    monkeypatch.setattr(
        datasets_router, "get_user_roles", AsyncMock(return_value={"admin"})
    )
    monkeypatch.setattr(
        collections_router, "get_user_roles", AsyncMock(return_value={"admin"})
    )
    monkeypatch.setattr(
        datasets_router,
        "get_dataset_service_url",
        AsyncMock(return_value="https://api.example.test"),
    )

    async def datasets_for_tenant(*_args, **_kwargs):
        return [], 1 if current_tenant_var.get() == TENANT_A else 2

    async def collections_for_tenant(*_args, **_kwargs):
        return [], 3 if current_tenant_var.get() == TENANT_A else 4

    monkeypatch.setattr(datasets_router, "get_datasets_list", datasets_for_tenant)
    monkeypatch.setattr(collections_router, "list_collections", collections_for_tenant)
    monkeypatch.setattr(
        collections_router, "batch_collection_extents", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        collections_router,
        "batch_collection_dataset_counts",
        AsyncMock(return_value={}),
    )

    results = []
    for tenant_id in (TENANT_A, TENANT_B):
        token = _set_tenant(tenant_id)
        try:
            datasets = await datasets_router.list_all_datasets(
                request=MagicMock(), user=user, db=db, skip=0, limit=50
            )
            collections = await collections_router.list_collections_endpoint(
                user=user, db=db, skip=0, limit=50
            )
            results.append((datasets.total, collections.total))
        finally:
            current_tenant_var.reset(token)

    assert results == [(1, 3), (2, 4)]
    assert set(cache.values) == {
        f"catalog:datasets:admin:0:50:tenant:{TENANT_A}",
        f"catalog:collections:admin:0:50:tenant:{TENANT_A}",
        f"catalog:datasets:admin:0:50:tenant:{TENANT_B}",
        f"catalog:collections:admin:0:50:tenant:{TENANT_B}",
    }


@pytest.mark.anyio
async def test_catalog_invalidation_only_evicts_active_tenant(
    multi_tenant,
    monkeypatch: pytest.MonkeyPatch,
):
    import app.platform.cache as cache_namespace
    from app.platform.cache.tiles import invalidate_catalog_cache

    cache = InMemoryCacheProvider()
    keys = {}
    for tenant_id in (TENANT_A, TENANT_B):
        token = _set_tenant(tenant_id)
        try:
            key = tenant_cache_key("catalog:datasets:admin:0:50")
            keys[tenant_id] = key
            await cache.set(key, tenant_id)
        finally:
            current_tenant_var.reset(token)

    monkeypatch.setattr(cache_namespace, "get_cache", lambda: cache)
    token = _set_tenant(TENANT_A)
    try:
        await invalidate_catalog_cache()
    finally:
        current_tenant_var.reset(token)

    assert await cache.get(keys[TENANT_A]) is None
    assert await cache.get(keys[TENANT_B]) == TENANT_B


@pytest.mark.anyio
async def test_unscoped_collection_metadata_never_populates_shared_cache(multi_tenant):
    search_router = importlib.import_module("app.modules.catalog.search.router")
    search_router._COLLECTION_META_CACHE.clear()

    class _Result:
        def __init__(self, row):
            self._row = row

        def one(self):
            return self._row

    db = AsyncMock()
    db.execute.side_effect = [
        _Result(
            SimpleNamespace(bbox_geojson=None, temporal_start=None, temporal_end=None)
        ),
        _Result(
            SimpleNamespace(geometry_types=[], srids=[], organizations=[], keywords=[])
        ),
    ]

    result = await search_router._build_collection_metadata(
        db, None, "https://api.example.test"
    )

    assert result["id"] == "datasets"
    assert search_router._COLLECTION_META_CACHE == {}


def test_anonymous_search_cache_key_includes_tenant(multi_tenant):
    from app.modules.catalog.search import cache as search_cache
    from app.modules.catalog.search.service import SearchFilters

    keys = []
    for tenant_id in (TENANT_A, TENANT_B):
        token = _set_tenant(tenant_id)
        try:
            keys.append(
                search_cache.build_cache_key(
                    endpoint="search",
                    filters=SearchFilters(q="roads"),
                    user_roles=set(),
                    public_api_url="https://api.example.test",
                )
            )
        finally:
            current_tenant_var.reset(token)

    assert keys[0] != keys[1]
    assert keys[0].endswith(f":tenant:{TENANT_A}")
    assert keys[1].endswith(f":tenant:{TENANT_B}")


@pytest.mark.anyio
async def test_catalog_metadata_and_ai_vocabulary_caches_are_tenant_scoped(
    multi_tenant,
):
    search_router = importlib.import_module("app.modules.catalog.search.router")
    metadata_service = importlib.import_module("app.processing.ai.metadata_service")
    search_router._COLLECTION_META_CACHE.clear()
    metadata_service._vocabulary_cache.clear()

    class _Result:
        def __init__(self, row):
            self._row = row

        def one(self):
            return self._row

    async def build_for(tenant_id: str, organization: str):
        db = AsyncMock()
        db.execute.side_effect = [
            _Result(
                SimpleNamespace(
                    bbox_geojson=None, temporal_start=None, temporal_end=None
                )
            ),
            _Result(
                SimpleNamespace(
                    geometry_types=[],
                    srids=[],
                    organizations=[organization],
                    keywords=[],
                )
            ),
        ]
        port = SimpleNamespace(
            get_catalog_vocabulary=AsyncMock(return_value=[organization])
        )
        token = _set_tenant(tenant_id)
        try:
            collection = await search_router._build_collection_metadata(
                db, None, "https://api.example.test"
            )
            vocabulary = await metadata_service._get_catalog_vocabulary(db, port=port)
        finally:
            current_tenant_var.reset(token)
        return collection, vocabulary

    collection_a, vocabulary_a = await build_for(TENANT_A, "Tenant A")
    collection_b, vocabulary_b = await build_for(TENANT_B, "Tenant B")

    assert collection_a["summaries"]["source_organization"] == ["Tenant A"]
    assert collection_b["summaries"]["source_organization"] == ["Tenant B"]
    assert vocabulary_a == ["Tenant A"]
    assert vocabulary_b == ["Tenant B"]


@pytest.mark.anyio
async def test_embedding_presence_cache_is_tenant_scoped(
    multi_tenant,
    monkeypatch: pytest.MonkeyPatch,
):
    helpers = importlib.import_module("app.processing.embeddings.helpers")
    helpers._has_embeddings_cache.clear()
    monkeypatch.setattr(
        helpers,
        "_resolve_embedding_model_name",
        AsyncMock(return_value="shared-model"),
    )

    async def value_for(tenant_id: str, value: bool) -> bool:
        result = MagicMock()
        result.scalar_one.return_value = value
        session = AsyncMock()
        session.execute.return_value = result
        token = _set_tenant(tenant_id)
        try:
            return await helpers.has_embeddings(session)
        finally:
            current_tenant_var.reset(token)

    assert await value_for(TENANT_A, True) is True
    assert await value_for(TENANT_B, False) is False


def test_sql_schema_cache_key_is_tenant_scoped(multi_tenant):
    from app.processing.ai.sql_generator import _schema_cache_key

    keys = []
    for tenant_id in (TENANT_A, TENANT_B):
        token = _set_tenant(tenant_id)
        try:
            keys.append(_schema_cache_key([], "same-map"))
        finally:
            current_tenant_var.reset(token)

    assert keys[0] != keys[1]


@pytest.mark.anyio
async def test_embed_token_negative_cache_cannot_poison_another_tenant(
    multi_tenant,
    monkeypatch: pytest.MonkeyPatch,
):
    service = importlib.import_module("app.modules.embed_tokens.service")
    cache = _MemoryCache()
    monkeypatch.setattr(service, "get_cache", lambda: cache)
    monkeypatch.setattr(service, "map_contains_dataset", AsyncMock(return_value=True))

    dataset_id = uuid.uuid4()
    raw_token = "et_tenant_partition_regression"
    token_record = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(TENANT_A),
        allowed_origins=None,
        scoped_dataset_ids=[str(dataset_id)],
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        map_id=uuid.uuid4(),
    )
    monkeypatch.setattr(
        service,
        "get_processing_port",
        lambda: SimpleNamespace(
            get_dataset=AsyncMock(
                return_value=SimpleNamespace(tenant_id=uuid.UUID(TENANT_A))
            )
        ),
    )

    class _Result:
        def scalar_one_or_none(self):
            return token_record if current_tenant_var.get() == TENANT_A else None

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class _Db:
        async def execute(self, *_args, **_kwargs):
            return _Result()

        def begin_nested(self):
            return _Nested()

        async def commit(self):
            return None

    db = _Db()

    tenant_b_token = _set_tenant(TENANT_B)
    try:
        assert (
            await service.validate_embed_token_access(raw_token, dataset_id, db)
            is False
        )
    finally:
        current_tenant_var.reset(tenant_b_token)

    tenant_a_token = _set_tenant(TENANT_A)
    try:
        assert (
            await service.validate_embed_token_access(raw_token, dataset_id, db) is True
        )
    finally:
        current_tenant_var.reset(tenant_a_token)

    assert len(cache.values) == 2
    assert any(key.endswith(f":tenant:{TENANT_A}") for key in cache.values)
    assert any(key.endswith(f":tenant:{TENANT_B}") for key in cache.values)


@pytest.mark.anyio
async def test_embed_token_validation_denies_without_hosted_tenant_context(
    multi_tenant,
    monkeypatch: pytest.MonkeyPatch,
):
    service = importlib.import_module("app.modules.embed_tokens.service")
    cache = _MemoryCache()
    monkeypatch.setattr(service, "get_cache", lambda: cache)
    db = AsyncMock()

    assert (
        await service.validate_embed_token_access("et_unscoped_host", uuid.uuid4(), db)
        is False
    )
    db.execute.assert_not_awaited()
    assert cache.values == {}


@pytest.mark.anyio
async def test_embed_token_invalidation_is_tenant_local(
    multi_tenant,
    monkeypatch: pytest.MonkeyPatch,
):
    service = importlib.import_module("app.modules.embed_tokens.service")
    cache = _MemoryCache()
    monkeypatch.setattr(service, "get_cache", lambda: cache)

    token_hash = "same-token-hash"
    token_record = SimpleNamespace(token_hash=token_hash, is_active=True)
    result = MagicMock()
    result.scalar_one_or_none.return_value = token_record
    db = AsyncMock()
    db.execute.return_value = result

    keys: dict[str, str] = {}
    for tenant_id in (TENANT_A, TENANT_B):
        tenant_token = _set_tenant(tenant_id)
        try:
            key = service._embed_token_cache_key(token_hash)
            keys[tenant_id] = key
            await cache.set(key, {"is_valid": True}, ttl=300)
        finally:
            current_tenant_var.reset(tenant_token)

    tenant_a_token = _set_tenant(TENANT_A)
    try:
        revoked = await service.revoke_embed_token(db, uuid.uuid4(), uuid.uuid4())
    finally:
        current_tenant_var.reset(tenant_a_token)

    assert revoked is token_record
    assert keys[TENANT_A] not in cache.values
    assert keys[TENANT_B] in cache.values
