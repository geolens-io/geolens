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
    """Reset registry AND isolate from environment-discovered entry points.

    The enterprise overlay is editable-installable in the backend test
    venv (so the enterprise migration adding overlay-only columns
    auto-runs at session setup). That install adds the
    ``geolens.extensions`` entry
    point, which would otherwise pollute the registry whenever a test
    calls ``load_extensions()``. We patch ``entry_points`` to default-empty
    so each test starts from a known-empty discovery surface and can opt
    in to its own mock entry points via ``with patch(...)``.
    """
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
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


class TestGetIdentityExtension:
    """Tests for the get_identity_extension() typed accessor (Phase 214 D-13)."""

    def test_get_identity_extension_returns_default_when_unregistered(self):
        """No enterprise overlay registered -> returns DefaultIdentityExtension."""
        from app.platform.extensions import get_identity_extension
        from app.platform.extensions.defaults import DefaultIdentityExtension

        ext = get_identity_extension()

        assert isinstance(ext, DefaultIdentityExtension)

    def test_get_identity_extension_returns_registered_when_present(self):
        """An overlay registered under 'identity' is returned by the accessor."""
        from app.platform.extensions import _extensions, get_identity_extension

        sentinel = object()
        _extensions["identity"] = sentinel

        ext = get_identity_extension()

        assert ext is sentinel

    @pytest.mark.asyncio
    async def test_default_identity_extension_resolve_returns_none(self):
        """DefaultIdentityExtension.resolve_identity_from_token returns None for any input.

        Enforces Pitfall 8: the method MUST be async — calling `await` on it
        must not raise TypeError. Enterprise auth overlays rely on this
        contract for their DB-lookup wire-in.
        """
        from app.platform.extensions.defaults import DefaultIdentityExtension

        ext = DefaultIdentityExtension()
        result = await ext.resolve_identity_from_token("any-token", None, None)

        assert result is None


class TestProtocolOverlayDispatch:
    """Tests for the get_*_extension() typed accessors' overlay-dispatch behavior.

    Phase 276 CODE-03 — closes M-11 / M-54: BrandingExtension, AuthExtension,
    and AuditExtension Protocol seams previously had only OSS-side
    default-shape tests (TestProtocolDefaults above). These tests lock the
    overlay-dispatch boundary so a regression where the accessor accidentally
    returns the default while a fake overlay is registered fails loudly.

    Pattern mirrors test_get_identity_extension_returns_registered_when_present
    (line 226+) — same try/finally teardown discipline, same sentinel
    assertion shape, same single-class-per-Protocol grouping.
    """

    def test_branding_extension_overlay_dispatch(self):
        """Phase 276 CODE-03: A registered overlay under 'branding' is returned by the accessor.

        Mirrors the IdentityExtension dispatch test (line 226+). Closes M-11 / M-54.
        """
        from app.platform.extensions import _extensions, get_branding_extension
        from app.platform.extensions.defaults import DefaultBrandingExtension

        class FakeBrandingOverlay:
            def get_branding_defaults(self) -> dict:
                return {"show_badge": False, "_test_sentinel": "branding-overlay"}

        # Sanity: pre-condition is the OSS default
        assert isinstance(get_branding_extension(), DefaultBrandingExtension)

        # Register the fake overlay
        previous = _extensions.get("branding")
        _extensions["branding"] = FakeBrandingOverlay()
        try:
            ext = get_branding_extension()
            assert isinstance(ext, FakeBrandingOverlay), (
                "get_branding_extension() did not return the registered overlay"
            )
            # Sentinel proves the fake's method runs (not the default's)
            assert (
                ext.get_branding_defaults().get("_test_sentinel") == "branding-overlay"
            )
        finally:
            if previous is None:
                _extensions.pop("branding", None)
            else:
                _extensions["branding"] = previous

        # Post-condition: registry is restored
        assert isinstance(get_branding_extension(), DefaultBrandingExtension)

    def test_audit_extension_overlay_dispatch(self):
        """Phase 276 CODE-03: A registered overlay under 'audit' is returned by the accessor.

        Mirrors the IdentityExtension dispatch test (line 226+). Closes M-11 / M-54.
        """
        from app.platform.extensions import _extensions, get_audit_extension
        from app.platform.extensions.defaults import DefaultAuditExtension

        class FakeAuditOverlay:
            def get_export_formats(self) -> list[str]:
                return ["test-overlay-format", "_test_sentinel"]

        # Sanity: pre-condition is the OSS default
        assert isinstance(get_audit_extension(), DefaultAuditExtension)

        # Register the fake overlay
        previous = _extensions.get("audit")
        _extensions["audit"] = FakeAuditOverlay()
        try:
            ext = get_audit_extension()
            assert isinstance(ext, FakeAuditOverlay), (
                "get_audit_extension() did not return the registered overlay"
            )
            # Sentinel proves the fake's method runs (not the default's [])
            formats = ext.get_export_formats()
            assert "test-overlay-format" in formats
            assert "_test_sentinel" in formats
        finally:
            if previous is None:
                _extensions.pop("audit", None)
            else:
                _extensions["audit"] = previous

        # Post-condition: registry is restored
        assert isinstance(get_audit_extension(), DefaultAuditExtension)

    def test_auth_extension_overlay_dispatch(self):
        """Phase 276 CODE-03: A registered overlay under 'auth' is returned by the accessor.

        Mirrors the IdentityExtension dispatch test (line 226+). Closes M-11 / M-54.
        """
        from app.platform.extensions import _extensions, get_auth_extension
        from app.platform.extensions.defaults import DefaultAuthExtension

        class FakeAuthOverlay:
            def get_auth_methods(self) -> list[str]:
                return ["test-overlay-method", "_test_sentinel"]

        # Sanity: pre-condition is the OSS default
        assert isinstance(get_auth_extension(), DefaultAuthExtension)

        # Register the fake overlay
        previous = _extensions.get("auth")
        _extensions["auth"] = FakeAuthOverlay()
        try:
            ext = get_auth_extension()
            assert isinstance(ext, FakeAuthOverlay), (
                "get_auth_extension() did not return the registered overlay"
            )
            # Sentinel proves the fake's method runs (not the default's [])
            methods = ext.get_auth_methods()
            assert "test-overlay-method" in methods
            assert "_test_sentinel" in methods
        finally:
            if previous is None:
                _extensions.pop("auth", None)
            else:
                _extensions["auth"] = previous

        # Post-condition: registry is restored
        assert isinstance(get_auth_extension(), DefaultAuthExtension)
