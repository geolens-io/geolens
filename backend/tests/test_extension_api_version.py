"""Tests for EXTENSION_API_VERSION constant + overlay compat check (OCG-04 core half).

Covers:
- An overlay declaring the matching version loads successfully.
- An overlay declaring an incompatible version raises RuntimeError (NOT swallowed to warning).
- An overlay that does not declare a version (treated as version-0/legacy) LOADS with a WARNING
  (backward compatibility — see check_extension_api_version; only declared-mismatch hard-fails).
- A non-version loader exception (e.g. ImportError) is still caught + logged (broad-except preserved).

References: OCG-04
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _reset_registry():
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset registry AND isolate from environment-discovered entry points."""
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield
    _reset_registry()


class TestExtensionApiVersionConstant:
    """EXTENSION_API_VERSION constant exists and is a positive integer."""

    def test_version_is_integer(self):
        """EXTENSION_API_VERSION is an int (not str, not float)."""
        from app.platform.extensions.version import EXTENSION_API_VERSION

        assert isinstance(EXTENSION_API_VERSION, int), (
            f"EXTENSION_API_VERSION must be int, got {type(EXTENSION_API_VERSION)}"
        )

    def test_version_matches_required_connector_contract(self):
        """v2 covers the required connector discovery/dispatch methods."""
        from app.platform.extensions.version import EXTENSION_API_VERSION

        assert EXTENSION_API_VERSION == 2


class TestCheckExtensionApiVersion:
    """check_extension_api_version() helper raises exactly when expected."""

    def test_matching_version_passes(self):
        """check_extension_api_version raises nothing when declared == core version."""
        from app.platform.extensions.version import (
            EXTENSION_API_VERSION,
            check_extension_api_version,
        )

        # Should not raise
        check_extension_api_version("my_overlay", EXTENSION_API_VERSION)

    def test_wrong_version_raises_runtime_error(self):
        """Declared version != core version → RuntimeError naming overlay + both versions."""
        from app.platform.extensions.version import (
            EXTENSION_API_VERSION,
            check_extension_api_version,
        )

        wrong_version = EXTENSION_API_VERSION + 99

        with pytest.raises(RuntimeError) as exc_info:
            check_extension_api_version("acme_overlay", wrong_version)

        msg = str(exc_info.value)
        assert "acme_overlay" in msg, f"Error message must name the overlay; got: {msg}"
        assert str(wrong_version) in msg or str(EXTENSION_API_VERSION) in msg, (
            f"Error message must contain version numbers; got: {msg}"
        )

    def test_none_version_allowed_as_legacy(self):
        """Declared version=None (legacy overlay) is ALLOWED with a WARNING — NOT raised.

        Backward compatibility: the already-released enterprise overlay predates
        EXTENSION_API_VERSION; hard-failing undeclared would brick it on a core
        upgrade. Skew protection only fires on a declared-but-mismatched version.

        Patches the module logger directly (not caplog) so the assertion is immune
        to cross-test global logging state.
        """
        from app.platform.extensions import version as version_mod
        from app.platform.extensions.version import check_extension_api_version

        with patch.object(version_mod, "logger") as mock_logger:
            # Must NOT raise
            check_extension_api_version("legacy_overlay", None)

        assert mock_logger.warning.called, (
            "Undeclared overlay must log a WARNING (legacy/version-0 tolerance)"
        )
        warn_args = mock_logger.warning.call_args
        assert "legacy_overlay" in warn_args.args, (
            f"WARNING must name the overlay; got args: {warn_args.args}"
        )

    def test_error_message_contains_both_versions(self):
        """Version-mismatch error message names both the declared and core versions."""
        from app.platform.extensions.version import (
            EXTENSION_API_VERSION,
            check_extension_api_version,
        )

        declared = (
            EXTENSION_API_VERSION - 1
            if EXTENSION_API_VERSION > 1
            else EXTENSION_API_VERSION + 1
        )

        with pytest.raises(RuntimeError) as exc_info:
            check_extension_api_version("old_overlay", declared)

        msg = str(exc_info.value)
        assert str(declared) in msg, f"Declared version {declared} missing from: {msg}"
        assert str(EXTENSION_API_VERSION) in msg, (
            f"Core version {EXTENSION_API_VERSION} missing from: {msg}"
        )


class TestLoadExtensionsVersionEnforcement:
    """load_extensions() enforces EXTENSION_API_VERSION — version mismatches escape."""

    def _make_versioned_ep(self, name: str, declared_version: int | None):
        """Create a mock entry point whose loader module has EXTENSION_API_VERSION."""
        ep = MagicMock()
        ep.name = name

        # Build a mock loader module with the declared version attribute
        loader_module = MagicMock()
        if declared_version is not None:
            loader_module.EXTENSION_API_VERSION = declared_version
        else:
            # No attribute at all — simulates a legacy overlay
            del loader_module.EXTENSION_API_VERSION

        def _loader(registry: dict):
            registry[name] = "loaded"

        loader_module.register_extensions = _loader

        # ep.load() returns the callable directly; the module is accessed via
        # importlib so we store the version on the loader callable itself
        loader_func = MagicMock(
            side_effect=lambda registry: registry.update({name: "loaded"})
        )
        loader_func.EXTENSION_API_VERSION = (
            declared_version
            if declared_version is not None
            else MagicMock(side_effect=AttributeError)
        )

        ep.load.return_value = loader_func
        # Attach module to allow getattr(loader_func, "EXTENSION_API_VERSION", None)
        if declared_version is not None:
            loader_func.EXTENSION_API_VERSION = declared_version
        else:
            # Remove attribute so getattr returns None
            if hasattr(loader_func, "EXTENSION_API_VERSION"):
                del loader_func.EXTENSION_API_VERSION

        return ep

    def test_matching_version_overlay_loads_ok(self):
        """An overlay declaring the core EXTENSION_API_VERSION loads without error."""
        from app.platform.extensions import _extensions, load_extensions
        from app.platform.extensions.version import EXTENSION_API_VERSION

        ep = MagicMock()
        ep.name = "versioned_ext"

        def _loader(registry: dict):
            registry["versioned_ext"] = "ok"

        loader = MagicMock(side_effect=_loader)
        loader.EXTENSION_API_VERSION = EXTENSION_API_VERSION
        ep.load.return_value = loader

        with patch("app.platform.extensions.entry_points", return_value=[ep]):
            load_extensions()  # Must not raise

        assert "versioned_ext" in _extensions

    def test_wrong_version_overlay_raises(self):
        """An overlay declaring wrong EXTENSION_API_VERSION → RuntimeError (not swallowed)."""
        from app.platform.extensions import load_extensions
        from app.platform.extensions.version import EXTENSION_API_VERSION

        ep = MagicMock()
        ep.name = "bad_version_ext"

        def _loader(registry: dict):
            registry["bad_version_ext"] = "should_not_load"

        loader = MagicMock(side_effect=_loader)
        loader.EXTENSION_API_VERSION = EXTENSION_API_VERSION + 99
        ep.load.return_value = loader

        with patch("app.platform.extensions.entry_points", return_value=[ep]):
            with pytest.raises(RuntimeError, match="bad_version_ext"):
                load_extensions()

    def test_no_version_overlay_loads_as_legacy(self):
        """An overlay without EXTENSION_API_VERSION attr LOADS (legacy/version-0), not raised."""
        from app.platform.extensions import load_extensions

        ep = MagicMock()
        ep.name = "legacy_ext"

        def _loader(registry: dict):
            registry["legacy_ext"] = "loaded_as_legacy"

        # Spec-less mock with no EXTENSION_API_VERSION attr → getattr returns None
        loader_clean = MagicMock(spec=[])
        loader_clean.side_effect = _loader
        ep.load.return_value = loader_clean

        with patch("app.platform.extensions.entry_points", return_value=[ep]):
            # Must NOT raise — legacy overlay loads
            load_extensions()

    def test_non_version_import_error_is_logged_not_raised(self, caplog):
        """Non-version loader exception (ImportError at ep.load()) is still caught + logged.

        This preserves the existing broad-except behavior for non-version errors.
        Only version-mismatch RuntimeErrors escape.
        """
        import logging

        from app.platform.extensions import load_extensions

        ep = MagicMock()
        ep.name = "broken_import_ext"
        ep.load.side_effect = ImportError("missing dependency")

        with patch("app.platform.extensions.entry_points", return_value=[ep]):
            with caplog.at_level(logging.WARNING, logger="app.platform.extensions"):
                load_extensions()  # Must NOT raise; ImportError is swallowed+logged

        # Registry stays empty (not loaded), but no exception propagated
        from app.platform.extensions import _extensions

        assert "broken_import_ext" not in _extensions

    def test_invalid_extension_load_priority_fails_loudly(self):
        from app.platform.extensions import load_extensions
        from app.platform.extensions.version import EXTENSION_API_VERSION

        ep = MagicMock()
        ep.name = "invalid_priority_ext"
        loader = MagicMock()
        loader.EXTENSION_API_VERSION = EXTENSION_API_VERSION
        loader.EXTENSION_LOAD_PRIORITY = "last"
        ep.load.return_value = loader

        with patch("app.platform.extensions.entry_points", return_value=[ep]):
            with pytest.raises(RuntimeError, match="EXTENSION_LOAD_PRIORITY"):
                load_extensions()

    def test_extension_priority_beats_discovery_order(self):
        from app.platform.extensions import load_extensions
        from app.platform.extensions.version import EXTENSION_API_VERSION

        calls: list[str] = []

        def foundation(_registry: dict) -> None:
            calls.append("foundation")

        foundation.EXTENSION_API_VERSION = EXTENSION_API_VERSION  # type: ignore[attr-defined]
        foundation.EXTENSION_LOAD_PRIORITY = 10  # type: ignore[attr-defined]

        def wrapper(_registry: dict) -> None:
            calls.append("wrapper")

        wrapper.EXTENSION_API_VERSION = EXTENSION_API_VERSION  # type: ignore[attr-defined]
        wrapper.EXTENSION_LOAD_PRIORITY = 20  # type: ignore[attr-defined]

        wrapper_ep = MagicMock()
        wrapper_ep.name = "wrapper"
        wrapper_ep.load.return_value = wrapper
        foundation_ep = MagicMock()
        foundation_ep.name = "foundation"
        foundation_ep.load.return_value = foundation

        with patch(
            "app.platform.extensions.entry_points",
            return_value=[wrapper_ep, foundation_ep],
        ):
            load_extensions()

        assert calls == ["foundation", "wrapper"]
