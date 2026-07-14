"""Tenant Host routing is bound to configured domains, never arbitrary Host."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from fastapi import Depends, FastAPI
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


def test_resolved_tenant_host_allows_identity_extension_bearer(monkeypatch):
    import app.api.middleware.tenant_context as tenant_context
    import app.modules.auth.dependencies as auth_dependencies
    from app.core.db.tenant_session import current_tenant_var
    from app.core.dependencies import get_db

    tenant_id = str(uuid.uuid4())
    fake_db = object()
    identity = SimpleNamespace(username="extension-user")
    seen: list[tuple[str, str | None, str | None, object]] = []

    class _IdentityExtension:
        async def resolve_identity_from_token(self, token, request, db):
            seen.append(
                (
                    token,
                    current_tenant_var.get(),
                    getattr(request.state, "tenant_id", None),
                    db,
                )
            )
            return identity

    async def _get_fake_db():
        yield fake_db

    async def _resolve(signal):
        return tenant_id if signal == "acme" else None

    monkeypatch.setattr(tenant_context, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_context.settings, "tenant_base_domain", "geolens.app")
    monkeypatch.setattr(tenant_context.settings, "tenant_trusted_hosts", "testserver")
    monkeypatch.setattr(
        auth_dependencies, "get_identity_extension", lambda: _IdentityExtension()
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _get_fake_db

    @app.get("/probe")
    async def _probe(user=Depends(auth_dependencies.get_current_user)):
        return {"username": user.username}

    app.add_middleware(tenant_context.TenantContextMiddleware)
    with patch.object(tenant_context, "_resolve_tenant_uuid", side_effect=_resolve):
        response = TestClient(app).get(
            "/probe",
            headers={
                "host": "acme.geolens.app",
                "authorization": "Bearer externally-signed-session",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"username": "extension-user"}
    assert seen == [
        ("externally-signed-session", tenant_id, tenant_id, fake_db),
    ]
    assert current_tenant_var.get() is None


def test_unscoped_service_host_rejects_nonlocal_bearer_before_extension(monkeypatch):
    import app.api.middleware.tenant_context as tenant_context
    import app.modules.auth.dependencies as auth_dependencies
    from app.core.dependencies import get_db

    extension_calls: list[str] = []
    handler_calls: list[bool] = []

    class _IdentityExtension:
        async def resolve_identity_from_token(self, token, request, db):
            extension_calls.append(token)
            return SimpleNamespace(username="unexpected")

    async def _get_fake_db():
        yield object()

    monkeypatch.setattr(tenant_context, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_context.settings, "tenant_base_domain", "geolens.app")
    monkeypatch.setattr(tenant_context.settings, "tenant_trusted_hosts", "testserver")
    monkeypatch.setattr(
        auth_dependencies, "get_identity_extension", lambda: _IdentityExtension()
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _get_fake_db

    @app.get("/probe")
    async def _probe(user=Depends(auth_dependencies.get_current_user)):
        handler_calls.append(True)
        return {"username": user.username}

    app.add_middleware(tenant_context.TenantContextMiddleware)
    response = TestClient(app).get(
        "/probe",
        headers={
            "host": "api.geolens.app",
            "authorization": "Bearer externally-signed-session",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Bearer token is invalid or not tenant-bound"
    assert extension_calls == []
    assert handler_calls == []


def test_unrecognized_nonlocal_bearer_remains_unauthorized(monkeypatch):
    import app.api.middleware.tenant_context as tenant_context
    import app.modules.auth.dependencies as auth_dependencies
    from app.core.dependencies import get_db

    tenant_id = str(uuid.uuid4())
    extension_calls: list[str] = []

    class _IdentityExtension:
        async def resolve_identity_from_token(self, token, request, db):
            extension_calls.append(token)
            return None

    async def _get_fake_db():
        yield object()

    async def _resolve(signal):
        return tenant_id if signal == "acme" else None

    monkeypatch.setattr(tenant_context, "is_multi_tenant", lambda: True)
    monkeypatch.setattr(tenant_context.settings, "tenant_base_domain", "geolens.app")
    monkeypatch.setattr(tenant_context.settings, "tenant_trusted_hosts", "testserver")
    monkeypatch.setattr(
        auth_dependencies, "get_identity_extension", lambda: _IdentityExtension()
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _get_fake_db

    @app.get("/probe")
    async def _probe(user=Depends(auth_dependencies.get_current_user)):
        return {"username": user.username}

    app.add_middleware(tenant_context.TenantContextMiddleware)
    with patch.object(tenant_context, "_resolve_tenant_uuid", side_effect=_resolve):
        response = TestClient(app).get(
            "/probe",
            headers={
                "host": "acme.geolens.app",
                "authorization": "Bearer unrecognized-session",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"
    assert extension_calls == ["unrecognized-session"]


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
