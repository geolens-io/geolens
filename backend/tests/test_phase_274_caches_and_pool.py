"""PERF-04 / PERF-05 / PERF-10 regression tests (Phase 274).

Static + behavior tests that run without a database or Redis. Each test
that touches a global cache resets the relevant module-level state via
the helper at the top of the test so cases stay order-independent.
"""

import inspect
import re
import time
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _reset_schema_cache() -> None:
    """Wipe the schema-context cache so tests are order-independent."""
    from app.processing.ai import sql_generator

    sql_generator._schema_cache.clear()


def _reset_has_embeddings_cache() -> None:
    """Wipe the has_embeddings cache so tests are order-independent."""
    from app.processing.embeddings import helpers

    helpers._has_embeddings_cache.clear()


# --- PERF-05: postgresql.conf max_connections --------------------------------


def test_postgresql_conf_max_connections_is_30():
    """PERF-05: max_connections lowered from 50 to 30."""
    conf = (_REPO_ROOT / "db" / "postgresql.conf").read_text()
    # Strip comment-only lines so prose doesn't self-invalidate the gate.
    non_comment_lines = [
        line for line in conf.splitlines() if not line.strip().startswith("#")
    ]
    max_conn_lines = [
        line for line in non_comment_lines if line.startswith("max_connections")
    ]
    assert len(max_conn_lines) == 1, (
        f"Expected exactly one max_connections directive; found {max_conn_lines}"
    )
    # Match `max_connections = 30` allowing trailing whitespace + inline comment.
    assert re.match(
        r"^max_connections\s*=\s*30(\s|$|#)", max_conn_lines[0]
    ), f"PERF-05: expected max_connections = 30, got: {max_conn_lines[0]}"


def test_postgresql_conf_no_longer_says_50():
    """PERF-05: ensure the old `max_connections = 50` directive is gone."""
    conf = (_REPO_ROOT / "db" / "postgresql.conf").read_text()
    non_comment_lines = [
        line for line in conf.splitlines() if not line.strip().startswith("#")
    ]
    for line in non_comment_lines:
        if line.startswith("max_connections"):
            assert "= 50" not in line, (
                f"PERF-05: max_connections must not equal 50; got: {line}"
            )


def test_readme_no_longer_says_perf_05_planned():
    """PERF-05: README forward-reference removed (PERF-05 is now in effect)."""
    readme = (_REPO_ROOT / "README.md").read_text()
    assert "PERF-05 (planned" not in readme, (
        "README still claims PERF-05 is planned; should be in effect."
    )


def test_readme_documents_perf_05_in_effect():
    """PERF-05: README budget table mentions max_connections of 30 in effect."""
    readme = (_REPO_ROOT / "README.md").read_text()
    assert "max_connections" in readme
    # Either the new totals row "30 of 30" or the explicit 50 -> 30 sentence
    # is enough to confirm PERF-05 is documented as live.
    assert (
        "30 of `30 max_connections" in readme
        or "30 of 30 max_connections" in readme
        or "`max_connections` 50 → 30" in readme
        or "max_connections 50 -> 30" in readme
    ), "README must show the PERF-05 envelope (30 of 30) or the 50->30 transition."


def test_env_example_dbm04_comment_references_30():
    """PERF-05: .env.example DBM-04 comment block references max_connections=30."""
    env_example = (_REPO_ROOT / ".env.example").read_text()
    assert "max_connections=30" in env_example or "max_connections = 30" in env_example, (
        ".env.example DBM-04 comment must reference max_connections=30 "
        "after PERF-05 lands."
    )


# --- PERF-04: schema cache partitions on (map_id, content_hash) --------------


class _StubLayer:
    """Minimal duck-type stand-in for ChatMapLayer in cache-key tests."""

    def __init__(
        self,
        *,
        dataset_table_name: str = "t",
        geometry_type: str | None = "Point",
        column_info: list[dict] | None = None,
    ):
        self.dataset_table_name = dataset_table_name
        self.geometry_type = geometry_type
        self.column_info = (
            column_info if column_info is not None else [{"name": "a", "type": "int"}]
        )
        self.sample_values = None


def test_schema_cache_partitions_on_map_id():
    """PERF-04: different maps with identical layers get separate cache entries."""
    from app.processing.ai.sql_generator import _schema_cache_key

    k1 = _schema_cache_key([_StubLayer()], "map-1")
    k2 = _schema_cache_key([_StubLayer()], "map-2")
    assert k1 != k2, (k1, k2)
    # Same map_id + same layers -> same key
    k1_again = _schema_cache_key([_StubLayer()], "map-1")
    assert k1 == k1_again


def test_schema_cache_key_handles_none_map_id():
    """PERF-04: backward-compat - None map_id uses sentinel."""
    from app.processing.ai.sql_generator import _schema_cache_key

    k = _schema_cache_key([_StubLayer()], None)
    assert isinstance(k, tuple) and len(k) == 2
    assert k[0] == "__no_map__"


def test_schema_cache_key_returns_tuple():
    """PERF-04: cache key is now a tuple (map_key, content_hash)."""
    from app.processing.ai.sql_generator import _schema_cache_key

    k = _schema_cache_key([_StubLayer()], "map-1")
    assert isinstance(k, tuple)
    assert len(k) == 2
    assert k[0] == "map-1"
    # content hash is md5 hex (32 chars)
    assert isinstance(k[1], str) and len(k[1]) == 32


def test_build_sql_schema_context_signature_includes_map_id():
    """PERF-04: function signature exposes map_id parameter."""
    from app.processing.ai.sql_generator import build_sql_schema_context

    sig = inspect.signature(build_sql_schema_context)
    assert "map_id" in sig.parameters, sig
    # map_id should default to None for backwards-compat with existing callers
    assert sig.parameters["map_id"].default is None


def test_schema_cache_max_bumped_to_64():
    """PERF-04: cache size bound is 64 (per CONTEXT.md sane-bound constraint)."""
    from app.processing.ai import sql_generator

    assert sql_generator._SCHEMA_CACHE_MAX == 64


def test_schema_cache_partition_yields_independent_results():
    """PERF-04: cache stores independent entries for two different map_ids."""
    from app.processing.ai.sql_generator import build_sql_schema_context

    _reset_schema_cache()
    layers = [_StubLayer()]
    r1 = build_sql_schema_context(layers, map_id="map-A")
    r2 = build_sql_schema_context(layers, map_id="map-B")
    # Both calls produce the same DDL (layers are identical)
    assert r1 == r2
    # But the cache holds two entries because the keys differ
    from app.processing.ai import sql_generator

    assert len(sql_generator._schema_cache) == 2
    keys = list(sql_generator._schema_cache.keys())
    map_keys = {k[0] for k in keys}
    assert map_keys == {"map-A", "map-B"}


def test_schema_cache_eviction_at_64():
    """PERF-04: cache evicts oldest entry when at _SCHEMA_CACHE_MAX capacity."""
    from app.processing.ai import sql_generator
    from app.processing.ai.sql_generator import build_sql_schema_context

    _reset_schema_cache()
    # Insert 64 entries — at capacity.
    for i in range(64):
        build_sql_schema_context([_StubLayer()], map_id=f"map-{i:03d}")
    assert len(sql_generator._schema_cache) == 64
    # 65th insert evicts oldest, total still bounded.
    build_sql_schema_context([_StubLayer()], map_id="map-overflow")
    assert len(sql_generator._schema_cache) == 64
    # The overflow entry must be present.
    keys = list(sql_generator._schema_cache.keys())
    assert any(k[0] == "map-overflow" for k in keys)


def test_chat_service_call_site_passes_map_id():
    """PERF-04: chat-edit threads map_id into the schema_context call.

    Phase 276 CODE-02: chat_service was split into a facade + chat_*.py
    sub-modules; the actual ``build_sql_schema_context`` call now lives in
    ``chat_actions._handle_query_data``. The PERF-04 contract still holds
    (map_id is threaded through), so this test checks both modules and
    accepts the call in either source — preserving the original intent
    after the facade decomposition.
    """
    from app.processing.ai import chat_actions, chat_service

    pattern = r"build_sql_schema_context\([^)]*map_id\s*="
    sources = (inspect.getsource(chat_service), inspect.getsource(chat_actions))
    assert any(re.search(pattern, src) for src in sources), (
        "PERF-04: chat_service or chat_actions must thread map_id into "
        "build_sql_schema_context"
    )


def test_handle_query_data_signature_accepts_map_id():
    """PERF-04: _handle_query_data exposes map_id keyword."""
    from app.processing.ai.chat_service import _handle_query_data

    sig = inspect.signature(_handle_query_data)
    assert "map_id" in sig.parameters
    # Optional with default None for backwards-compat with existing tests.
    assert sig.parameters["map_id"].default is None


def test_execute_chat_tool_signature_accepts_map_id():
    """PERF-04: _execute_chat_tool exposes map_id keyword to thread it down."""
    from app.processing.ai.chat_service import _execute_chat_tool

    sig = inspect.signature(_execute_chat_tool)
    assert "map_id" in sig.parameters
    assert sig.parameters["map_id"].default is None


# --- PERF-10: has_embeddings cache partitions on model name ------------------


def test_has_embeddings_cache_is_dict_keyed_on_model():
    """PERF-10: cache is a dict, not a single global tuple."""
    from app.processing.embeddings import helpers

    assert isinstance(helpers._has_embeddings_cache, dict)


def test_has_embeddings_static_source_mentions_perf_10():
    """PERF-10: marker comment is present for traceability."""
    from app.processing.embeddings import helpers

    src = inspect.getsource(helpers)
    assert "PERF-10" in src


def test_has_embeddings_cache_bounded():
    """PERF-10: cache has a documented max-entries bound."""
    from app.processing.embeddings import helpers

    assert hasattr(helpers, "_HAS_EMBEDDINGS_MAX")
    assert isinstance(helpers._HAS_EMBEDDINGS_MAX, int)
    # Operators rarely run more than 2-3 models; 8 is generous.
    assert 1 <= helpers._HAS_EMBEDDINGS_MAX <= 32


def test_has_embeddings_resolver_is_async():
    """PERF-10: _resolve_embedding_model_name is async (matches PersistentConfig.get)."""
    from app.processing.embeddings import helpers

    assert inspect.iscoroutinefunction(helpers._resolve_embedding_model_name)


@pytest.mark.anyio
async def test_has_embeddings_resolver_falls_back_safely():
    """PERF-10: model accessor errors fall back to the sentinel."""
    from app.processing.embeddings import helpers

    # Force the persistent_config getter to raise; helper must catch and
    # return the sentinel string instead of propagating.
    class _FailingSession:
        async def execute(self, *args, **kwargs):  # noqa: D401 — duck-typed stub
            raise RuntimeError("settings missing")

    # The resolver swallows any exception from EMBEDDING_MODEL.get(session).
    # Pass a session whose execute() raises; the path inside .get() that hits
    # session.execute(...) will raise before any value is returned.
    got = await helpers._resolve_embedding_model_name(_FailingSession())  # type: ignore[arg-type]
    assert got == "__model_unknown__"


@pytest.mark.anyio
async def test_has_embeddings_partitions_cache_per_model(monkeypatch):
    """PERF-10: switching the active model produces a fresh cache entry."""
    from app.processing.embeddings import helpers

    _reset_has_embeddings_cache()

    # Stub the resolver to return controllable model names.
    model_holder = {"name": "model-A"}

    async def _fake_resolver(_session):
        return model_holder["name"]

    monkeypatch.setattr(helpers, "_resolve_embedding_model_name", _fake_resolver)

    # Stub session.execute to return an EXISTS scalar without DB access.
    class _FakeResult:
        def __init__(self, value):
            self._value = value

        def scalar_one(self):
            return self._value

    class _FakeSession:
        def __init__(self, value):
            self._value = value
            self.calls = 0

        async def execute(self, *args, **kwargs):
            self.calls += 1
            return _FakeResult(self._value)

    sess = _FakeSession(True)

    # First call: model-A miss -> DB hit -> cache write
    assert await helpers.has_embeddings(sess) is True  # type: ignore[arg-type]
    assert sess.calls == 1
    assert "model-A" in helpers._has_embeddings_cache

    # Second call: same model, same session -> cache hit, no new DB call
    assert await helpers.has_embeddings(sess) is True  # type: ignore[arg-type]
    assert sess.calls == 1

    # Switch model -> fresh cache miss -> new DB call
    model_holder["name"] = "model-B"
    assert await helpers.has_embeddings(sess) is True  # type: ignore[arg-type]
    assert sess.calls == 2
    assert "model-B" in helpers._has_embeddings_cache
    # Both partitions coexist
    assert {"model-A", "model-B"} <= set(helpers._has_embeddings_cache.keys())


@pytest.mark.anyio
async def test_has_embeddings_eviction_bounded(monkeypatch):
    """PERF-10: cache evicts oldest entry when at _HAS_EMBEDDINGS_MAX capacity."""
    from app.processing.embeddings import helpers

    _reset_has_embeddings_cache()

    model_holder = {"name": ""}

    async def _fake_resolver(_session):
        return model_holder["name"]

    monkeypatch.setattr(helpers, "_resolve_embedding_model_name", _fake_resolver)

    class _FakeResult:
        def scalar_one(self):
            return True

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            return _FakeResult()

    sess = _FakeSession()

    # Fill cache to capacity.
    for i in range(helpers._HAS_EMBEDDINGS_MAX):
        model_holder["name"] = f"m{i}"
        await helpers.has_embeddings(sess)  # type: ignore[arg-type]
        # Stagger timestamps so eviction has a unique oldest entry.
        time.sleep(0.001)

    assert len(helpers._has_embeddings_cache) == helpers._HAS_EMBEDDINGS_MAX

    # Insert one more — oldest should evict, total still bounded.
    model_holder["name"] = "m-overflow"
    await helpers.has_embeddings(sess)  # type: ignore[arg-type]
    assert len(helpers._has_embeddings_cache) == helpers._HAS_EMBEDDINGS_MAX
    assert "m-overflow" in helpers._has_embeddings_cache
    # Oldest was 'm0' — must have been evicted.
    assert "m0" not in helpers._has_embeddings_cache
