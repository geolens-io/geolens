"""Requests hand their pooled connection back before waiting on an AI or embedding provider."""

import uuid
from types import SimpleNamespace

import pytest

import app.processing.ai.chat_service as chat_service
import app.processing.ai.metadata_service as metadata_service
import app.processing.ai.service as ai_service
import app.processing.ai.sql_generator as sql_generator
import app.processing.ai.streaming as streaming
from app.core.db import release_connection
from app.modules.catalog.search import service_semantic
from app.modules.catalog.search.service_filters import SearchFilters
from app.processing.ai.llm_loop import ToolLoopExhaustedError, ToolLoopResult

pytestmark = pytest.mark.anyio


class _RequestSession:
    """A request session that tracks whether it holds a pooled connection."""

    def __init__(self) -> None:
        # The request's own reads (auth, budget, config) already checked one out.
        self.holding = True
        self.new: set = set()
        self.dirty: set = set()
        self.deleted: set = set()
        self.nested = False

    def in_nested_transaction(self) -> bool:
        return self.nested

    async def commit(self) -> None:
        self.holding = False

    def checkout(self) -> None:
        self.holding = True


class _Stop(Exception):
    pass


def _async_return(value):
    async def _f(*_a, **_k):
        return value

    return _f


def _user():
    return SimpleNamespace(id=uuid.uuid4())


class TestReleaseConnection:
    async def test_commits_an_idle_session(self):
        session = _RequestSession()
        await release_connection(session)
        assert session.holding is False

    async def test_keeps_a_session_with_unflushed_changes(self):
        session = _RequestSession()
        session.new = {object()}
        await release_connection(session)
        assert session.holding is True

    async def test_keeps_a_session_inside_a_savepoint(self):
        session = _RequestSession()
        session.nested = True
        await release_connection(session)
        assert session.holding is True


@pytest.fixture
def _map_generation(monkeypatch):
    """Drive the map-generation tool loop with one search tool call."""
    session = _RequestSession()
    observed: list[tuple[str, bool]] = []

    async def _search_tool(sess, *_a, **_k):
        sess.checkout()
        return []

    async def _complete(*, tool_executor, **_k):
        observed.append(("provider", session.holding))
        await tool_executor("search_datasets", {})
        observed.append(("after tool", session.holding))
        raise ToolLoopExhaustedError("stop")

    monkeypatch.setattr(
        ai_service, "resolve_provider", _async_return(("anthropic", "m", {}))
    )
    monkeypatch.setattr(
        ai_service,
        "get_ai_provider",
        lambda _p: SimpleNamespace(complete=_complete),
    )
    monkeypatch.setattr(ai_service, "_get_available_basemaps", _async_return([]))
    monkeypatch.setattr(ai_service, "_should_send_sample_values", _async_return(False))
    monkeypatch.setattr(ai_service, "_execute_search_tool", _search_tool)
    return session, observed


class TestMapGeneration:
    async def test_streaming_loop_holds_no_connection_while_the_provider_works(
        self, _map_generation
    ):
        session, observed = _map_generation
        events = [
            e
            async for e in ai_service.stream_generate_map(
                session, _user(), set(), "a map", port=SimpleNamespace()
            )
        ]
        assert [e["type"] for e in events] == ["error"]
        assert observed == [("provider", False), ("after tool", False)]

    async def test_blocking_loop_holds_no_connection_while_the_provider_works(
        self, _map_generation
    ):
        session, observed = _map_generation
        with pytest.raises(ValueError):
            await ai_service.generate_map_from_prompt(
                session, _user(), set(), "a map", port=SimpleNamespace()
            )
        assert observed == [("provider", False), ("after tool", False)]

    async def test_repair_round_holds_no_connection(self, monkeypatch):
        session = _RequestSession()
        observed: list[bool] = []

        async def _complete(**_k):
            observed.append(session.holding)
            return ToolLoopResult(text="<map_spec>{}</map_spec>")

        monkeypatch.setattr(
            ai_service,
            "get_ai_provider",
            lambda _p: SimpleNamespace(complete=_complete),
        )
        monkeypatch.setattr(
            "app.processing.ai.token_usage.record_token_usage", _async_return(None)
        )
        monkeypatch.setattr(ai_service, "record_token_usage", _async_return(None))
        await ai_service._retry_parse_map_spec(
            "garbled", "anthropic", "m", {}, session=session, user_id=None
        )
        assert observed == [False]


class TestChat:
    async def test_blocking_chat_holds_no_connection_while_the_provider_works(
        self, monkeypatch
    ):
        session = _RequestSession()
        observed: list[tuple[str, bool]] = []
        tool_name = chat_service.select_chat_tools(True)[0]["name"]

        async def _chat_tool(_name, _input, sess, *_a, **_k):
            sess.checkout()
            return {}

        async def _complete(*, tool_executor, **_k):
            observed.append(("provider", session.holding))
            await tool_executor(tool_name, {})
            observed.append(("after tool", session.holding))
            raise ToolLoopExhaustedError("stop")

        monkeypatch.setattr(
            chat_service, "resolve_provider", _async_return(("anthropic", "m", {}))
        )
        monkeypatch.setattr(
            chat_service,
            "get_ai_provider",
            lambda _p: SimpleNamespace(complete=_complete),
        )
        monkeypatch.setattr(chat_service, "_execute_chat_tool", _chat_tool)
        with pytest.raises(ToolLoopExhaustedError):
            await chat_service.chat_edit_map(
                session, _user(), set(), "recolour", [], port=SimpleNamespace()
            )
        assert observed == [("provider", False), ("after tool", False)]

    async def test_anthropic_stream_round_holds_no_connection(self, monkeypatch):
        session = _RequestSession()
        observed: list[bool] = []

        def _stream(**_k):
            observed.append(session.holding)
            raise _Stop

        client = SimpleNamespace(messages=SimpleNamespace(stream=_stream))
        monkeypatch.setattr(streaming, "_daily_token_budget", _async_return((0, 0)))
        with pytest.raises(_Stop):
            async for _ in streaming._stream_anthropic_chat(
                "hi",
                "sys",
                session,
                _user(),
                set(),
                [],
                model="m",
                client=client,
                port=SimpleNamespace(),
            ):
                pass
        assert observed == [False]

    async def test_openai_stream_round_holds_no_connection(self, monkeypatch):
        session = _RequestSession()
        observed: list[bool] = []

        async def _create(**_k):
            observed.append(session.holding)
            raise _Stop

        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
        )
        monkeypatch.setattr(streaming, "_daily_token_budget", _async_return((0, 0)))
        with pytest.raises(_Stop):
            async for _ in streaming._stream_openai_chat(
                "hi",
                "sys",
                session,
                _user(),
                set(),
                [],
                model="m",
                client=client,
                port=SimpleNamespace(),
            ):
                pass
        assert observed == [False]

    async def test_sql_generation_holds_no_connection(self, monkeypatch):
        session = _RequestSession()
        observed: list[bool] = []

        class _Setting:
            async def get(self, _db):
                return "anthropic"

            async def for_provider(self, *_a):
                return "m"

        async def _complete(**_k):
            observed.append(session.holding)
            return ToolLoopResult(text="SELECT 1")

        provider = SimpleNamespace(
            resolve_runtime_config=_async_return({}), complete=_complete
        )
        monkeypatch.setattr(sql_generator, "LLM_PROVIDER", _Setting())
        monkeypatch.setattr(sql_generator, "LLM_MODEL_LIGHT", _Setting())
        monkeypatch.setattr(sql_generator, "get_ai_provider", lambda _p: provider)
        await sql_generator.generate_sql(session, "how many?", "-- ddl")
        assert observed == [False]


async def test_metadata_draft_holds_no_connection(monkeypatch):
    session = _RequestSession()
    observed: list[bool] = []

    class _Setting:
        async def get(self, _db):
            return "anthropic"

        async def for_provider(self, *_a):
            return "m"

    async def _structured_complete(**_k):
        observed.append(session.holding)
        return SimpleNamespace(), 0, 0

    provider = SimpleNamespace(
        resolve_runtime_config=_async_return({}),
        structured_complete=_structured_complete,
    )
    monkeypatch.setattr(metadata_service, "LLM_PROVIDER", _Setting())
    monkeypatch.setattr(metadata_service, "LLM_MODEL_LIGHT", _Setting())
    monkeypatch.setattr(metadata_service, "get_ai_provider", lambda _p: provider)
    monkeypatch.setattr(metadata_service, "record_token_usage", _async_return(None))
    await metadata_service._generate_structured(
        "sys", "prompt", SimpleNamespace, session
    )
    assert observed == [False]


async def test_semantic_search_holds_no_connection_while_embedding(monkeypatch):
    session = _RequestSession()
    observed: list[bool] = []

    async def _generate_embedding(_text, _session, pinned=None):
        observed.append(session.holding)
        return [0.0, 1.0]

    port = SimpleNamespace(
        has_embeddings=_async_return(True),
        resolve_embedding_config=_async_return(("model", 2, None, "fp")),
        generate_embedding=_generate_embedding,
    )
    monkeypatch.setattr(service_semantic, "get_catalog_port", lambda: port)
    monkeypatch.setattr(
        service_semantic,
        "SEMANTIC_SEARCH_ENABLED",
        SimpleNamespace(get=_async_return(True)),
    )
    service_semantic._embedding_cache_clear()
    service_semantic._embedding_inflight_clear()
    try:
        embedding = await service_semantic.resolve_query_embedding(
            session, SearchFilters(q=f"rivers {uuid.uuid4()}")
        )
    finally:
        service_semantic._embedding_cache_clear()
    assert embedding is not None
    assert observed == [False]
