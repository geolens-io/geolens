"""Tests for the Phase 269 H-22 query-embedding LRU cache.

The cache lives in `app.modules.catalog.search.service_semantic` and wraps
`generate_embedding` so that repeated identical queries don't re-call the
provider's embedding API. Tests focus on the cache wrapper directly to
keep the suite fast and deterministic — production hybrid-search paths
exercise the wrapper indirectly via `test_hybrid_search.py`.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.modules.catalog.search import service_semantic


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear the embedding cache before every test."""
    service_semantic._embedding_cache_clear()
    yield
    service_semantic._embedding_cache_clear()


def _mock_session_with_model(model_name: str = "text-embedding-3-small"):
    """Build a session whose EMBEDDING_MODEL.get returns model_name."""
    session = MagicMock()
    return session


# fix(#1546): the cache key carries the configuration fingerprint alongside the
# model name. These tests are about the OTHER key components, so they hold it
# constant; `test_cache_partitioned_by_configuration` below is the one that
# moves it.
_FINGERPRINT = "cfg-fingerprint-a"


_MODEL = "text-embedding-3-small"
_DIMS = 1536
_BASE_URL = "https://api.openai.com/v1"


def _mock_port(
    *,
    return_value=None,
    side_effect=None,
    fingerprint=_FINGERPRINT,
    model=_MODEL,
):
    """CatalogPort double: the provider call plus the #1546 configuration read.

    `resolve_embedding_config` answers the whole live configuration, which is
    what lets the caller PIN the provider call to the same one it filters rows
    on (#1546 review r1).
    """
    port = MagicMock()
    port.generate_embedding = AsyncMock(
        return_value=return_value, side_effect=side_effect
    )
    port.resolve_embedding_config = AsyncMock(
        return_value=(model, _DIMS, _BASE_URL, fingerprint)
    )
    return port


@pytest.mark.asyncio
async def test_generate_embedding_caches_result_on_second_call():
    """Second call with identical text + model should hit the cache."""
    fake_vector = [0.1] * 1536
    mock_port = _mock_port(return_value=fake_vector)
    session = _mock_session_with_model()

    with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
        first = await service_semantic.generate_embedding("hello world", session)
        second = await service_semantic.generate_embedding("hello world", session)

    assert first == fake_vector
    assert second == fake_vector
    # Provider hit exactly once even though we called twice.
    assert mock_port.generate_embedding.call_count == 1


@pytest.mark.asyncio
async def test_cache_key_is_case_insensitive_and_strips_whitespace():
    """`(text.strip().lower(), model)` cache key collides on case + whitespace."""
    fake_vector = [0.2] * 1536
    mock_port = _mock_port(return_value=fake_vector)
    session = _mock_session_with_model()

    with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
        await service_semantic.generate_embedding("Hello World", session)
        await service_semantic.generate_embedding("  hello world  ", session)
        await service_semantic.generate_embedding("HELLO WORLD", session)

    # All three are the same canonical key — provider hit only once.
    assert mock_port.generate_embedding.call_count == 1


@pytest.mark.asyncio
async def test_cache_partitioned_by_model_name():
    """Two different model names should NOT share cache entries."""
    fake_v1 = [0.3] * 1536
    fake_v2 = [0.4] * 1536
    mock_port = _mock_port(side_effect=[fake_v1, fake_v2])
    session = _mock_session_with_model()

    with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
        mock_port.resolve_embedding_config = AsyncMock(
            return_value=("text-embedding-3-small", _DIMS, _BASE_URL, _FINGERPRINT)
        )
        r1 = await service_semantic.generate_embedding("query", session)
        mock_port.resolve_embedding_config = AsyncMock(
            return_value=("text-embedding-3-large", _DIMS, _BASE_URL, _FINGERPRINT)
        )
        r2 = await service_semantic.generate_embedding("query", session)

    assert r1 == fake_v1
    assert r2 == fake_v2
    assert mock_port.generate_embedding.call_count == 2


@pytest.mark.asyncio
async def test_cache_partitioned_by_configuration():
    """fix(#1546): one model name, two configurations, two cache entries.

    The stored rows are filtered by the LIVE configuration. If this cache kept
    serving a query vector generated under the previous one, the filter would
    be selecting rows from configuration B and comparing them against a vector
    made under configuration A — the cross-space comparison #1546 is about,
    with the row filter looking entirely correct. The bug would have moved into
    the cache rather than been fixed.
    """
    fake_a = [0.7] * 1536
    fake_b = [0.8] * 1536
    mock_port = _mock_port(side_effect=[fake_a, fake_b])
    session = _mock_session_with_model()

    # Same model name throughout: the endpoint moved, not the model.
    with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
        mock_port.resolve_embedding_config = AsyncMock(
            return_value=(_MODEL, _DIMS, "https://endpoint-a.invalid/v1", "cfg-a")
        )
        first = await service_semantic.generate_embedding("query", session)
        repeat = await service_semantic.generate_embedding("query", session)

        mock_port.resolve_embedding_config = AsyncMock(
            return_value=(_MODEL, _DIMS, "https://endpoint-b.invalid/v1", "cfg-b")
        )
        after_change = await service_semantic.generate_embedding("query", session)

    # The repeat under one configuration is still a cache hit — the partition
    # must not be a blanket disable.
    assert first == repeat == fake_a
    assert after_change == fake_b
    assert mock_port.generate_embedding.call_count == 2


@pytest.mark.asyncio
async def test_the_provider_call_is_pinned_to_the_resolved_configuration():
    """fix(#1546 review r1, codex P1): one read, used for all three purposes.

    The configuration decides three things in a single search: which stored
    rows are comparable, what the cache entry is keyed on, and which endpoint
    produces the query vector. While the provider re-resolved the third for
    itself, an admin change landing between the read and the call produced a
    vector under configuration B, cached it under A, and ranked A-stamped rows
    against it. That is the cross-space comparison the whole change exists to
    prevent, reintroduced inside one request.

    The edit lands from INSIDE the provider call, which is where a real one
    spends its time; the same shape `test_embedding_backfill_base_url_pinning`
    uses. What the provider was asked for has to be the configuration resolved
    before it, not the one live by the time it ran.
    """
    session = _mock_session_with_model()
    mock_port = _mock_port(return_value=[0.9] * 1536)
    seen: list[tuple] = []

    async def _generate(text, sess, *, pinned=None):
        seen.append(pinned)
        # The admin's edit lands here, mid-call.
        mock_port.resolve_embedding_config = AsyncMock(
            return_value=("model-after", 768, "https://after.invalid/v1", "cfg-after")
        )
        return [0.9] * 1536

    mock_port.generate_embedding = AsyncMock(side_effect=_generate)
    mock_port.resolve_embedding_config = AsyncMock(
        return_value=(_MODEL, _DIMS, _BASE_URL, "cfg-before")
    )

    with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
        await service_semantic.generate_embedding("pinned query", session)

        # Non-vacuity: the edit really did land, so an unpinned call would have
        # had a different configuration to reach for.
        assert (await mock_port.resolve_embedding_config(session))[0] == "model-after"

    # The provider was asked for the configuration resolved BEFORE the call.
    assert seen == [(_MODEL, _DIMS, _BASE_URL)]
    # And the entry is keyed on that same one, so the next request under the
    # new configuration misses rather than being served this vector.
    assert ("pinned query", _MODEL, "cfg-before") in service_semantic._embedding_cache


@pytest.mark.asyncio
async def test_an_unresolvable_configuration_still_reaches_the_provider():
    """A caller with no config to pin must not silently skip the provider.

    `generate_embedding` is reachable outside search (the CatalogPort surface),
    and a configuration that cannot be resolved is the provider's problem to
    report, not a reason to answer with nothing. It goes through unpinned and
    uncached, which is exactly what it did before any of this existed.
    """
    session = _mock_session_with_model()
    mock_port = _mock_port(return_value=[0.4] * 1536)
    mock_port.resolve_embedding_config = AsyncMock(return_value=None)

    with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
        vector = await service_semantic.generate_embedding("no config", session)

    assert vector == [0.4] * 1536
    assert mock_port.generate_embedding.await_args.kwargs["pinned"] is None
    # Nothing was cached: there is no configuration to key it on.
    assert len(service_semantic._embedding_cache) == 0


@pytest.mark.asyncio
async def test_cache_partitioned_by_tenant(monkeypatch: pytest.MonkeyPatch):
    """The same provider/model label must not share vectors across tenants."""
    tenant_a = "00000000-0000-0000-0000-0000000000a1"
    tenant_b = "00000000-0000-0000-0000-0000000000b2"
    fake_a = [0.31] * 1536
    fake_b = [0.42] * 1536
    mock_port = _mock_port(side_effect=[fake_a, fake_b])
    session = _mock_session_with_model()
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")

    async def embed_for(tenant_id: str):
        token = current_tenant_var.set(tenant_id)
        try:
            return await service_semantic.generate_embedding("query", session)
        finally:
            current_tenant_var.reset(token)

    mock_port.resolve_embedding_config = AsyncMock(
        return_value=("shared-model", _DIMS, _BASE_URL, _FINGERPRINT)
    )
    with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
        first_a = await embed_for(tenant_a)
        first_b = await embed_for(tenant_b)
        second_a = await embed_for(tenant_a)

    assert first_a == second_a == fake_a
    assert first_b == fake_b
    assert mock_port.generate_embedding.call_count == 2


@pytest.mark.asyncio
async def test_cache_expires_entries_after_ttl():
    """Entries older than the TTL must NOT be returned from cache."""
    fake_v1 = [0.5] * 1536
    fake_v2 = [0.6] * 1536
    mock_port = _mock_port(side_effect=[fake_v1, fake_v2])
    session = _mock_session_with_model()

    with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
        # First call populates the cache with monotonic NOW + 300s TTL.
        await service_semantic.generate_embedding("expire me", session)
        # Manually expire by rewinding the cached entry's expires_at
        # to a past timestamp (more reliable than sleeping 300s).
        key = ("expire me", "text-embedding-3-small", _FINGERPRINT)
        _, vector = service_semantic._embedding_cache[key]
        service_semantic._embedding_cache[key] = (time.monotonic() - 1, vector)

        second = await service_semantic.generate_embedding("expire me", session)

    assert second == fake_v2
    assert mock_port.generate_embedding.call_count == 2


@pytest.mark.asyncio
async def test_empty_input_does_not_populate_cache():
    """Empty strings must bypass cache + delegate directly to provider."""
    mock_port = _mock_port(side_effect=ValueError("empty"))
    session = _mock_session_with_model()

    with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
        with pytest.raises(ValueError):
            await service_semantic.generate_embedding("   ", session)

    assert len(service_semantic._embedding_cache) == 0


@pytest.mark.asyncio
async def test_cache_evicts_oldest_when_over_max_size():
    """OrderedDict-LRU semantics: oldest entry drops when capacity exceeded."""
    # Shrink the cache so the test runs fast.
    original_max = service_semantic._EMBEDDING_CACHE_MAX_SIZE
    service_semantic._EMBEDDING_CACHE_MAX_SIZE = 3
    try:
        mock_port = _mock_port(side_effect=[[float(i)] for i in range(5)])
        session = _mock_session_with_model()

        with patch.object(service_semantic, "get_catalog_port", return_value=mock_port):
            mock_port.resolve_embedding_config = AsyncMock(
                return_value=("model", _DIMS, _BASE_URL, _FINGERPRINT)
            )
            for i in range(5):
                await service_semantic.generate_embedding(f"q{i}", session)

        # Only the 3 most-recently-inserted survive.
        assert len(service_semantic._embedding_cache) == 3
        assert ("q0", "model", _FINGERPRINT) not in service_semantic._embedding_cache
        assert ("q1", "model", _FINGERPRINT) not in service_semantic._embedding_cache
        assert ("q2", "model", _FINGERPRINT) in service_semantic._embedding_cache
        assert ("q3", "model", _FINGERPRINT) in service_semantic._embedding_cache
        assert ("q4", "model", _FINGERPRINT) in service_semantic._embedding_cache
    finally:
        service_semantic._EMBEDDING_CACHE_MAX_SIZE = original_max
