"""Tests for the admin ai-status live provider probe (fix #627).

Key presence != key validity: a rotated upstream key used to fail invisibly
(the 2026-07-21 demo outage). The probe is opt-in (?probe=true), admin-only,
sanitized, and absent — along with any provider call — from default requests.
"""

from types import SimpleNamespace

from httpx import AsyncClient
from pydantic import SecretStr

from app.core.config import settings

# A marker that must NEVER surface in an API response — stands in for raw
# provider error bodies (which can carry URLs, deployments, key fragments).
_SECRET_MARKER = "sk-SECRETLEAK-do-not-echo"


class _FakeAPIStatusError(Exception):
    """Shape-compatible with the SDKs' APIStatusError (has .status_code)."""

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


class _FakeCreate:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return SimpleNamespace(choices=[])


def _fake_openai_client(exc: Exception | None = None):
    completions = _FakeCreate(exc)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def _fake_anthropic_client(exc: Exception | None = None):
    messages = _FakeCreate(exc)
    return SimpleNamespace(messages=messages), messages


class _FakeEmbeddingProvider:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc = exc
        self.embed_calls = 0

    async def resolve_runtime_config(self, db):
        return {"default_model": "text-embedding-3-small", "base_url": None}

    async def embed(self, **kwargs):
        self.embed_calls += 1
        if self.exc is not None:
            # Mirror the real provider: terminal failures are wrapped with
            # the original SDK error as __cause__ (the probe must walk it).
            raise RuntimeError(f"Embedding API call failed: {self.exc}") from self.exc
        return [[0.0] * 4]


async def test_default_request_has_no_probe_and_makes_no_provider_calls(
    client: AsyncClient, admin_auth_header, monkeypatch
):
    """No ?probe=true -> response shape identical to today, zero provider calls."""

    async def _boom(db):
        raise AssertionError("run_ai_probe must not run without ?probe=true")

    monkeypatch.setattr("app.processing.ai.probe.run_ai_probe", _boom)

    resp = await client.get("/admin/ai-status/", headers=admin_auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert "probe" not in body
    # The pre-probe contract fields are all still present.
    for field in (
        "provider",
        "model",
        "enabled",
        "configured",
        "semantic_search_enabled",
        "has_embeddings",
    ):
        assert field in body


async def test_probe_with_working_keys_reports_ok(
    client: AsyncClient, admin_auth_header, monkeypatch
):
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    chat_client, chat_calls = _fake_openai_client()
    monkeypatch.setattr(
        "app.processing.ai.llm_loop.get_openai_client", lambda base_url: chat_client
    )
    embed_provider = _FakeEmbeddingProvider()
    monkeypatch.setattr(
        "app.platform.extensions.get_embedding_provider",
        lambda name: embed_provider,
    )

    resp = await client.get("/admin/ai-status/?probe=true", headers=admin_auth_header)
    assert resp.status_code == 200
    probe = resp.json()["probe"]
    assert probe["chat"] == {"configured": True, "ok": True}
    assert probe["embeddings"] == {"configured": True, "ok": True}
    assert chat_calls.calls == 1
    assert embed_provider.embed_calls == 1


async def test_probe_with_invalid_key_is_sanitized_and_still_200(
    client: AsyncClient, admin_auth_header, monkeypatch
):
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("synthetic-test-key"))
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    chat_exc = _FakeAPIStatusError(
        f"Error code: 401 - Access denied {_SECRET_MARKER}", status_code=401
    )
    chat_client, _ = _fake_openai_client(chat_exc)
    monkeypatch.setattr(
        "app.processing.ai.llm_loop.get_openai_client", lambda base_url: chat_client
    )
    embed_exc = _FakeAPIStatusError(
        f"Error code: 401 - invalid subscription key {_SECRET_MARKER}",
        status_code=401,
    )
    monkeypatch.setattr(
        "app.platform.extensions.get_embedding_provider",
        lambda name: _FakeEmbeddingProvider(embed_exc),
    )

    resp = await client.get("/admin/ai-status/?probe=true", headers=admin_auth_header)
    assert resp.status_code == 200
    probe = resp.json()["probe"]
    assert probe["chat"] == {
        "configured": True,
        "ok": False,
        "status": 401,
        "error": "authentication failed",
    }
    # The embeddings failure arrives WRAPPED (provider wraps the SDK error);
    # the probe walks __cause__ to recover the status code.
    assert probe["embeddings"] == {
        "configured": True,
        "ok": False,
        "status": 401,
        "error": "authentication failed",
    }
    assert _SECRET_MARKER not in resp.text


async def test_probe_chat_only_config_reports_embeddings_not_configured(
    client: AsyncClient, admin_auth_header, monkeypatch
):
    monkeypatch.setattr(
        settings, "anthropic_api_key", SecretStr("synthetic-anthropic-key")
    )
    monkeypatch.setattr(settings, "openai_api_key", None)

    anthropic_client, chat_calls = _fake_anthropic_client()
    monkeypatch.setattr(
        "app.processing.ai.llm_loop.get_anthropic_client", lambda: anthropic_client
    )

    resp = await client.get("/admin/ai-status/?probe=true", headers=admin_auth_header)
    assert resp.status_code == 200
    probe = resp.json()["probe"]
    assert probe["chat"] == {"configured": True, "ok": True}
    # Anthropic has no embedding API: not configured, NOT an error.
    assert probe["embeddings"] == {"configured": False}
    assert chat_calls.calls == 1
