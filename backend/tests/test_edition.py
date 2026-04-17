"""Tests for edition detection and enterprise guard."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException


def _reset_edition():
    """Reset edition state between tests."""
    import app.edition as ed_mod

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
        from app.main import app

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
