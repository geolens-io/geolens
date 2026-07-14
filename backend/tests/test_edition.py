"""Tests for edition detection and enterprise guard."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException


def _reset_edition():
    """Reset edition state between tests."""
    import app.core.edition as ed_mod

    ed_mod._info = None


@pytest.fixture(autouse=True)
def _clean_edition():
    _reset_edition()
    yield
    _reset_edition()


class TestEditionDetection:
    def test_edition_defaults_community(self):
        """get_edition() returns community before init."""
        from app.core.edition import get_edition

        info = get_edition()
        assert info.edition == "community"

    def test_edition_env_override_enterprise(self):
        """With GEOLENS_EDITION=enterprise, init_edition sets enterprise."""
        from app.core.edition import get_edition, init_edition

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterprise"}):
            init_edition([])

        assert get_edition().edition == "enterprise"

    def test_edition_env_override_community(self):
        """With GEOLENS_EDITION=community + extensions, init_edition sets community."""
        from app.core.edition import get_edition, init_edition

        with patch.dict("os.environ", {"GEOLENS_EDITION": "community"}):
            init_edition(["some_ext"])

        assert get_edition().edition == "community"

    def test_invalid_edition_env_fails_closed(self):
        """A typo must not silently fall through to community/auto-detection."""
        from app.core.edition import get_edition, init_edition

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterpise"}):
            with pytest.raises(RuntimeError, match="GEOLENS_EDITION"):
                init_edition([])

        assert get_edition().edition == "community"

    def test_edition_auto_detect_enterprise(self):
        """With no env var + non-empty extensions, edition=enterprise."""
        from app.core.edition import get_edition, init_edition

        with patch.dict("os.environ", {}, clear=False):
            # Ensure GEOLENS_EDITION is not set
            import os

            os.environ.pop("GEOLENS_EDITION", None)
            init_edition(["enterprise_ext"])

        assert get_edition().edition == "enterprise"

    def test_edition_auto_detect_community(self):
        """With no env var + empty extensions, edition=community."""
        from app.core.edition import get_edition, init_edition

        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("GEOLENS_EDITION", None)
            init_edition([])

        assert get_edition().edition == "community"

    def test_is_enterprise(self):
        """is_enterprise() returns True only when edition is enterprise."""
        from app.core.edition import init_edition, is_enterprise

        with patch.dict("os.environ", {"GEOLENS_EDITION": "community"}):
            init_edition([])
        assert is_enterprise() is False

        _reset_edition()

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterprise"}):
            init_edition([])
        assert is_enterprise() is True


class TestEnterpriseGuard:
    def test_require_enterprise_raises_404(self):
        """require_enterprise() raises HTTPException(404) when community."""
        from app.core.edition import init_edition
        from app.platform.extensions.guards import require_enterprise

        with patch.dict("os.environ", {"GEOLENS_EDITION": "community"}):
            init_edition([])

        with pytest.raises(HTTPException) as exc_info:
            require_enterprise()

        assert exc_info.value.status_code == 404

    def test_enterprise_gate_no_detail_body(self):
        """Enterprise gate 404 response must not leak edition/upgrade info."""
        from app.core.edition import init_edition
        from app.platform.extensions.guards import require_enterprise

        with patch.dict("os.environ", {"GEOLENS_EDITION": "community"}):
            init_edition([])

        with pytest.raises(HTTPException) as exc_info:
            require_enterprise()

        exc = exc_info.value
        detail_str = str(exc.detail) if exc.detail else ""
        for word in ("enterprise", "upgrade", "feature"):
            assert word.lower() not in detail_str.lower(), (
                f"Guard 404 detail must not contain '{word}'"
            )


class TestEditionEndpoint:
    """Integration tests for GET /api/settings/edition/ endpoint."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.api.main import app

        return TestClient(app)

    def test_edition_endpoint_returns_community(self, client):
        """GET /api/settings/edition/ returns 200 with edition and features."""
        resp = client.get("/api/settings/edition/")
        assert resp.status_code == 200
        data = resp.json()
        assert "edition" in data
        assert "features" in data
        assert data["edition"] == "community"
        assert isinstance(data["features"], list)

    def test_edition_endpoint_no_auth_required(self, client):
        """GET /api/settings/edition/ without Authorization header returns 200."""
        resp = client.get("/api/settings/edition/")
        assert resp.status_code == 200
        assert "Authorization" not in resp.request.headers

    def test_edition_endpoint_returns_tenancy_mode_field(self, client):
        """GET /api/settings/edition/ returns tenancy_mode field (FEOVL-02 additive)."""
        resp = client.get("/api/settings/edition/")
        assert resp.status_code == 200
        data = resp.json()
        assert "tenancy_mode" in data, (
            "tenancy_mode field must be present in edition response"
        )

    def test_edition_endpoint_single_tenant_default(self, client):
        """tenancy_mode defaults to 'single_tenant' when GEOLENS_TENANCY_MODE is unset."""
        resp = client.get("/api/settings/edition/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenancy_mode"] == "single_tenant", (
            f"Expected 'single_tenant' but got {data['tenancy_mode']!r}; "
            "community/enterprise deployments must default single_tenant"
        )

    def test_edition_endpoint_additive_existing_fields_unchanged(self, client):
        """tenancy_mode is additive — edition + features remain unchanged."""
        resp = client.get("/api/settings/edition/")
        assert resp.status_code == 200
        data = resp.json()
        assert "edition" in data
        assert "features" in data
        assert data["edition"] == "community"
        assert isinstance(data["features"], list)

    def test_edition_endpoint_multi_tenant_mode(self, client):
        """With GEOLENS_TENANCY_MODE=multi_tenant, tenancy_mode == 'multi_tenant'."""
        import app.core.config as cfg_mod

        original = cfg_mod.settings.geolens_tenancy_mode
        try:
            cfg_mod.settings.geolens_tenancy_mode = "multi_tenant"
            resp = client.get("/api/settings/edition/")
            assert resp.status_code == 200
            data = resp.json()
            assert data["tenancy_mode"] == "multi_tenant", (
                f"Expected 'multi_tenant' but got {data['tenancy_mode']!r}"
            )
        finally:
            cfg_mod.settings.geolens_tenancy_mode = original
