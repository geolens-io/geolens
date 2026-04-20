"""Tests for the extension registry, protocols, and defaults."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _reset_registry():
    """Reset extension registry state between tests."""
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False


@pytest.fixture(autouse=True)
def _clean_registry():
    _reset_registry()
    yield
    _reset_registry()


class TestLoadExtensions:
    def test_load_extensions_empty(self):
        """load_extensions() with no enterprise package populates empty registry."""
        from app.platform.extensions import _extensions, load_extensions

        load_extensions()

        from app.platform.extensions import _loaded as loaded_after

        assert loaded_after is True
        assert len(_extensions) == 0

    def test_load_extensions_with_mock_entry_point(self):
        """Mock entry_points to return a callable, verify it registers."""
        from app.platform.extensions import _extensions, load_extensions

        mock_ep = MagicMock()
        mock_ep.name = "test_ext"

        def _loader(registry: dict):
            registry["test_ext"] = "loaded"

        mock_ep.load.return_value = _loader

        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            load_extensions()

        assert "test_ext" in _extensions
        assert _extensions["test_ext"] == "loaded"

    def test_load_extensions_handles_failure(self, caplog):
        """Mock entry_point that raises, verify warning and other extensions still load."""
        from app.platform.extensions import _extensions, load_extensions

        bad_ep = MagicMock()
        bad_ep.name = "bad_ext"
        bad_ep.load.side_effect = Exception("boom")

        good_ep = MagicMock()
        good_ep.name = "good_ext"

        def _loader(registry: dict):
            registry["good_ext"] = "ok"

        good_ep.load.return_value = _loader

        with patch(
            "app.platform.extensions.entry_points", return_value=[bad_ep, good_ep]
        ):
            load_extensions()

        # Good extension loaded despite bad one failing
        assert "good_ext" in _extensions
        assert "bad_ext" not in _extensions


class TestRegistryHelpers:
    def test_get_extension_missing(self):
        """get_extension('nonexistent') returns None."""
        from app.platform.extensions import get_extension, load_extensions

        load_extensions()
        assert get_extension("nonexistent") is None

    def test_has_extension(self):
        """has_extension returns True/False correctly."""
        from app.platform.extensions import _extensions, has_extension, load_extensions

        load_extensions()
        assert has_extension("foo") is False
        _extensions["foo"] = "bar"
        assert has_extension("foo") is True

    def test_list_extensions(self):
        """list_extensions returns list of registered extension names."""
        from app.platform.extensions import (
            _extensions,
            list_extensions,
            load_extensions,
        )

        load_extensions()
        assert list_extensions() == []
        _extensions["alpha"] = 1
        _extensions["beta"] = 2
        assert sorted(list_extensions()) == ["alpha", "beta"]


class TestExtensionRouters:
    def test_get_extension_routers_empty(self):
        """get_extension_routers() returns empty list when no extensions loaded."""
        from app.platform.extensions import get_extension_routers, load_extensions

        load_extensions()
        assert get_extension_routers() == []

    def test_get_extension_routers_populated(self):
        """get_extension_routers() returns routers registered by extensions."""
        from app.platform.extensions import get_extension_routers, load_extensions

        mock_router = MagicMock(name="fake_router")
        mock_ep = MagicMock()
        mock_ep.name = "test_ext"

        def _loader(registry: dict):
            registry["_routers"] = [mock_router]

        mock_ep.load.return_value = _loader

        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            load_extensions()

        routers = get_extension_routers()
        assert len(routers) == 1
        assert routers[0] is mock_router

    def test_get_extension_routers_clears_on_reload(self):
        """Calling load_extensions() twice clears previous routers."""
        from app.platform.extensions import get_extension_routers, load_extensions

        mock_router = MagicMock(name="fake_router")
        mock_ep = MagicMock()
        mock_ep.name = "test_ext"

        def _loader(registry: dict):
            registry["_routers"] = [mock_router]

        mock_ep.load.return_value = _loader

        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            load_extensions()
        assert len(get_extension_routers()) == 1

        # Reload with no extensions — routers should be empty
        with patch("app.platform.extensions.entry_points", return_value=[]):
            load_extensions()
        assert get_extension_routers() == []


class TestProtocolDefaults:
    def test_protocol_defaults(self):
        """Default implementations are runtime_checkable instances of their protocols."""
        from app.platform.extensions.defaults import (
            DefaultAuditExtension,
            DefaultAuthExtension,
            DefaultBrandingExtension,
        )
        from app.platform.extensions.protocols import (
            AuditExtension,
            AuthExtension,
            BrandingExtension,
        )

        assert isinstance(DefaultBrandingExtension(), BrandingExtension)
        assert isinstance(DefaultAuditExtension(), AuditExtension)
        assert isinstance(DefaultAuthExtension(), AuthExtension)

    def test_branding_default_shows_badge(self):
        """DefaultBrandingExtension.get_branding_defaults() returns show_badge=True."""
        from app.platform.extensions.defaults import DefaultBrandingExtension

        result = DefaultBrandingExtension().get_branding_defaults()
        assert result == {"show_badge": True}

    def test_auth_default_methods(self):
        """DefaultAuthExtension.get_auth_methods() returns empty list."""
        from app.platform.extensions.defaults import DefaultAuthExtension

        assert DefaultAuthExtension().get_auth_methods() == []

    def test_audit_default_formats(self):
        """DefaultAuditExtension.get_export_formats() returns empty list."""
        from app.platform.extensions.defaults import DefaultAuditExtension

        assert DefaultAuditExtension().get_export_formats() == []
