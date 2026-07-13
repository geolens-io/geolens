"""Tenant Host routing is bound to configured domains, never arbitrary Host."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _app_with_probe():
    from app.api.middleware.tenant_context import TenantContextMiddleware

    called: list[bool] = []

    async def _probe(request):
        called.append(True)
        return JSONResponse(
            {
                "ok": True,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "tenant_public_origin": getattr(
                    request.state, "tenant_public_origin", None
                ),
            }
        )

    app = Starlette(routes=[Route("/{path:path}", _probe)])
    app.add_middleware(TenantContextMiddleware)
    return app, called


def _access_token() -> str:
    from app.core.config import settings

    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tid": str(uuid.uuid4()),
            "jti": uuid.uuid4().hex,
            "token_version": 1,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


@pytest.mark.parametrize(
    ("path", "extra_headers", "cookies"),
    [
        ("public", {}, None),
        ("api-key", {"x-api-key": "tenant-key"}, None),
        ("auth/refresh", {}, {"refresh_token": "opaque-refresh"}),
        ("jwt", {"authorization": "valid-token-placeholder"}, None),
    ],
    ids=["anonymous", "api-key", "refresh", "jwt"],
)
def test_forged_foreign_host_is_rejected_before_any_auth_fallback(
    monkeypatch, path, extra_headers, cookies
):
    import app.api.middleware.tenant_context as tenant_context

    monkeypatch.setattr(tenant_context, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_context.settings, "tenant_base_domain", "geolens.app")
    monkeypatch.setattr(
        tenant_context.settings,
        "tenant_trusted_hosts",
        "localhost,127.0.0.1,::1,api,testserver",
    )
    if path == "jwt":
        extra_headers = {"authorization": f"Bearer {_access_token()}"}

    app, called = _app_with_probe()
    response = TestClient(app).get(
        f"/{path}",
        headers={"host": "acme.attacker.example", **extra_headers},
        cookies=cookies,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Host is not trusted for tenant routing"
    assert called == []


def test_configured_tenant_suffix_resolves_slug(monkeypatch):
    import app.api.middleware.tenant_context as tenant_context

    tenant_id = str(uuid.uuid4())
    seen: list[str | None] = []

    async def _resolve(signal):
        seen.append(signal)
        return tenant_id

    monkeypatch.setattr(tenant_context, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_context.settings, "tenant_base_domain", "geolens.app")
    monkeypatch.setattr(tenant_context.settings, "tenant_trusted_hosts", "testserver")
    app, called = _app_with_probe()
    with patch.object(tenant_context, "_resolve_tenant_uuid", side_effect=_resolve):
        response = TestClient(app).get(
            "/public", headers={"host": "acme.geolens.app:443"}
        )

    assert response.status_code == 200
    assert called == [True]
    assert seen == ["acme"]
    assert response.json()["tenant_id"] == tenant_id
    assert response.json()["tenant_public_origin"] == "http://acme.geolens.app:443"


@pytest.mark.parametrize(
    "host",
    [
        "nested.acme.geolens.app",
        "acme.geolens.app.attacker.example",
        "evil.example@acme.geolens.app",
        "acme.geolens.app/path",
        "acme.geolens.app:invalid",
    ],
)
def test_malformed_or_suffix_confusion_hosts_are_rejected(monkeypatch, host):
    import app.api.middleware.tenant_context as tenant_context

    monkeypatch.setattr(tenant_context, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_context.settings, "tenant_base_domain", "geolens.app")
    monkeypatch.setattr(tenant_context.settings, "tenant_trusted_hosts", "testserver")
    app, called = _app_with_probe()
    response = TestClient(app).get("/public", headers={"host": host})
    assert response.status_code == 400
    assert called == []


def test_exact_internal_service_host_remains_available(monkeypatch):
    import app.api.middleware.tenant_context as tenant_context

    monkeypatch.setattr(tenant_context, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_context.settings, "tenant_base_domain", None)
    monkeypatch.setattr(
        tenant_context.settings,
        "tenant_trusted_hosts",
        "localhost,127.0.0.1,::1,api,testserver",
    )
    app, called = _app_with_probe()
    response = TestClient(app).get("/health", headers={"host": "api:8000"})
    assert response.status_code == 200
    assert called == [True]


def test_tenant_host_settings_normalize_and_reject_wildcards():
    from tests.test_config import _make_settings

    configured = _make_settings(
        tenant_base_domain="GeoLens.Example.",
        tenant_trusted_hosts=" API, localhost,API,::1 ",
    )
    assert configured.tenant_base_domain == "geolens.example"
    assert configured.tenant_trusted_hosts_list == ["api", "localhost", "::1"]

    with pytest.raises(ValueError, match="TENANT_BASE_DOMAIN"):
        _make_settings(tenant_base_domain="*.geolens.example")
