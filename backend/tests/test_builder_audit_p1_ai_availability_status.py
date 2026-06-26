"""builder-audit P1-11 + P1-12: AI availability signal for non-admin editors,
and admin AI status built from the SELECTED LLM provider.

P1-11: a ``use_ai_chat`` editor can read ``GET /ai/availability/`` (a
public-safe boolean) while a viewer cannot, and missing provider keys yield a
graceful ``available=false`` rather than a 403/503.

P1-12: admin status ``configured`` reflects the SELECTED ``LLM_PROVIDER`` key,
not "any key exists", so admin status and chat readiness agree for crossed
provider/key combinations.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.modules.admin import router as admin_router
from app.processing.ai import router as ai_router


# ---------------------------------------------------------------------------
# P1-12: admin AI status keyed off the SELECTED provider
# ---------------------------------------------------------------------------


def _set_keys(monkeypatch, *, anthropic, openai):
    """Patch the provider API keys on the shared settings singleton."""
    monkeypatch.setattr(
        admin_router.app_settings, "anthropic_api_key", anthropic, raising=False
    )
    monkeypatch.setattr(
        admin_router.app_settings, "openai_api_key", openai, raising=False
    )


def test_status_anthropic_selected_with_anthropic_key_configured(monkeypatch):
    _set_keys(monkeypatch, anthropic="sk-ant", openai=None)
    resp = admin_router._ai_status(True, "anthropic")
    assert resp.configured is True
    assert resp.provider == "anthropic"


def test_status_openai_selected_with_openai_key_configured(monkeypatch):
    _set_keys(monkeypatch, anthropic=None, openai="sk-openai")
    resp = admin_router._ai_status(True, "openai_compatible")
    assert resp.configured is True
    assert resp.provider == "openai"


def test_status_anthropic_selected_but_only_openai_key_unconfigured(monkeypatch):
    """Selected provider is anthropic but only an OpenAI key exists: the
    secondary key must NOT flip ``configured`` true."""
    _set_keys(monkeypatch, anthropic=None, openai="sk-openai")
    resp = admin_router._ai_status(True, "anthropic")
    assert resp.configured is False
    assert resp.provider is None


def test_status_openai_selected_but_only_anthropic_key_unconfigured(monkeypatch):
    _set_keys(monkeypatch, anthropic="sk-ant", openai=None)
    resp = admin_router._ai_status(True, "openai_compatible")
    assert resp.configured is False
    assert resp.provider is None


# ---------------------------------------------------------------------------
# P1-12: admin status and chat readiness AGREE for crossed combos
# ---------------------------------------------------------------------------


def _patch_runtime(monkeypatch, *, provider: str, enabled: bool = True):
    """Patch AI_ENABLED / LLM_PROVIDER on the ai router to fixed values."""
    fake_enabled = MagicMock()
    fake_enabled.get = AsyncMock(return_value=enabled)
    fake_provider = MagicMock()
    fake_provider.get = AsyncMock(return_value=provider)
    monkeypatch.setattr(ai_router, "AI_ENABLED", fake_enabled)
    monkeypatch.setattr(ai_router, "LLM_PROVIDER", fake_provider)


@pytest.mark.anyio
async def test_anthropic_selected_only_openai_key_status_and_chat_agree(monkeypatch):
    _set_keys(monkeypatch, anthropic=None, openai="sk-openai")
    _patch_runtime(monkeypatch, provider="anthropic")

    status_resp = admin_router._ai_status(True, "anthropic")
    available = await ai_router._ai_availability(db=AsyncMock())

    assert status_resp.configured is False
    assert available is False  # agreement: both report unavailable

    with pytest.raises(HTTPException) as exc:
        await ai_router._check_ai_available(db=AsyncMock())
    assert exc.value.status_code == 503


@pytest.mark.anyio
async def test_openai_selected_only_anthropic_key_status_and_chat_agree(monkeypatch):
    _set_keys(monkeypatch, anthropic="sk-ant", openai=None)
    _patch_runtime(monkeypatch, provider="openai_compatible")

    status_resp = admin_router._ai_status(True, "openai_compatible")
    available = await ai_router._ai_availability(db=AsyncMock())

    assert status_resp.configured is False
    assert available is False

    with pytest.raises(HTTPException) as exc:
        await ai_router._check_ai_available(db=AsyncMock())
    assert exc.value.status_code == 503


@pytest.mark.anyio
async def test_selected_provider_configured_status_and_chat_agree_available(
    monkeypatch,
):
    _set_keys(monkeypatch, anthropic="sk-ant", openai=None)
    _patch_runtime(monkeypatch, provider="anthropic")

    status_resp = admin_router._ai_status(True, "anthropic")
    available = await ai_router._ai_availability(db=AsyncMock())

    assert status_resp.configured is True
    assert available is True
    # _check_ai_available must NOT raise when selected provider is configured.
    await ai_router._check_ai_available(db=AsyncMock())


@pytest.mark.anyio
async def test_availability_false_when_ai_disabled(monkeypatch):
    _set_keys(monkeypatch, anthropic="sk-ant", openai=None)
    _patch_runtime(monkeypatch, provider="anthropic", enabled=False)
    assert await ai_router._ai_availability(db=AsyncMock()) is False


# ---------------------------------------------------------------------------
# P1-11: /ai/availability/ permission boundary (editor allowed, viewer denied)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_availability_endpoint_unauthenticated_401(client: AsyncClient):
    resp = await client.get("/ai/availability/")
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_availability_endpoint_viewer_forbidden(
    client: AsyncClient, viewer_auth_header: dict
):
    """A viewer lacks use_ai_chat and is rejected with 403 (not a leaky 503)."""
    resp = await client.get("/ai/availability/", headers=viewer_auth_header)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_availability_endpoint_editor_allowed_shape(
    client: AsyncClient, editor_auth_header: dict
):
    """An editor with use_ai_chat reaches the endpoint and gets a boolean."""
    resp = await client.get("/ai/availability/", headers=editor_auth_header)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body.get("available"), bool)
    # Public-safe: must NOT leak provider/model/key detail.
    assert "provider" not in body
    assert "model" not in body


@pytest.mark.anyio
async def test_availability_endpoint_editor_sees_available_when_configured(
    client: AsyncClient, editor_auth_header: dict, viewer_auth_header: dict, monkeypatch
):
    """Editor sees available=true when AI is enabled + the selected provider has
    a key; a viewer is still forbidden in the same configured state."""
    monkeypatch.setattr(
        ai_router.settings, "anthropic_api_key", "sk-ant", raising=False
    )
    monkeypatch.setattr(ai_router.settings, "openai_api_key", None, raising=False)
    _patch_runtime(monkeypatch, provider="anthropic")

    resp = await client.get("/ai/availability/", headers=editor_auth_header)
    assert resp.status_code == 200
    assert resp.json()["available"] is True

    resp_viewer = await client.get("/ai/availability/", headers=viewer_auth_header)
    assert resp_viewer.status_code == 403


@pytest.mark.anyio
async def test_availability_endpoint_editor_disabled_state_no_503(
    client: AsyncClient, editor_auth_header: dict, monkeypatch
):
    """Missing selected-provider key yields available=false with HTTP 200 (a
    safe disabled state), NOT a 503 that would spam the console."""
    monkeypatch.setattr(ai_router.settings, "anthropic_api_key", None, raising=False)
    monkeypatch.setattr(ai_router.settings, "openai_api_key", None, raising=False)
    _patch_runtime(monkeypatch, provider="anthropic")

    resp = await client.get("/ai/availability/", headers=editor_auth_header)
    assert resp.status_code == 200
    assert resp.json()["available"] is False
