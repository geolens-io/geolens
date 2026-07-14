"""Tests for the single-slot conflict guard + wrap-don't-replace contract (SLOT-01/02).

Covers:
- Duplicate single-slot writes raise ExtensionSlotConflictError naming key + both providers.
- Parametrized over every key in SINGLE_SLOT_KEYS.
- Additive-slot keys (audit_sinks, billing_extensions, ai_providers, embedding_providers, notification_sinks, _routers) are exempt.
- A single overlay claiming each slot exactly once passes (enterprise-boots-green case).
- The guard observes writes made DURING the loader callback.
- The wrap-don't-replace convention is documented in protocols.py (structural test).

References: SLOT-01, SLOT-02
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


def _reset_registry():
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False
    ext_mod._slot_owners.clear()


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset registry AND isolate from environment-discovered entry points."""
    _reset_registry()
    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield
    _reset_registry()


def _make_ep(name: str, loader_fn):
    """Return a minimal mock entry-point whose .load() returns loader_fn with the correct version."""
    from unittest.mock import MagicMock

    from app.platform.extensions.version import EXTENSION_API_VERSION

    ep = MagicMock()
    ep.name = name
    loader_fn.EXTENSION_API_VERSION = EXTENSION_API_VERSION
    ep.load.return_value = loader_fn
    return ep


class TestSingleSlotConflictGuard:
    """Duplicate non-additive writes raise ExtensionSlotConflictError."""

    @pytest.mark.parametrize(
        "slot_key",
        [
            "permission",
            "identity",
            "processing_port",
            "catalog_port",
            "workflow",
            "branding",
            "audit",
            "auth",
            "entitlement",  # Phase 1207 / ENTSEAM-01
            "connectors",
            "data_serving",
        ],
    )
    def test_duplicate_single_slot_raises(self, slot_key):
        """Two loaders each writing registry[slot_key] → ExtensionSlotConflictError.

        The error must name:
        - The conflicting slot key.
        - Both provider class names (prior + new).
        """
        from app.platform.extensions import load_extensions
        from app.platform.extensions import ExtensionSlotConflictError

        class FirstProvider:
            pass

        class SecondProvider:
            pass

        first_instance = FirstProvider()
        second_instance = SecondProvider()

        def _loader_a(registry: dict):
            registry[slot_key] = first_instance

        def _loader_b(registry: dict):
            registry[slot_key] = second_instance

        ep_a = _make_ep("overlay_alpha", _loader_a)
        ep_b = _make_ep("overlay_beta", _loader_b)

        with patch("app.platform.extensions.entry_points", return_value=[ep_a, ep_b]):
            with pytest.raises(ExtensionSlotConflictError) as exc_info:
                load_extensions()

        msg = str(exc_info.value)
        assert slot_key in msg, f"Error must name the slot key '{slot_key}'; got: {msg}"
        assert "FirstProvider" in msg, f"Error must name prior provider; got: {msg}"
        assert "SecondProvider" in msg, f"Error must name new provider; got: {msg}"

    def test_single_overlay_single_slot_no_raise(self):
        """A single overlay claiming a single-slot key once passes without error."""
        from app.platform.extensions import _extensions, load_extensions

        class MyPermission:
            pass

        def _loader(registry: dict):
            registry["permission"] = MyPermission()

        ep = _make_ep("solo_overlay", _loader)

        with patch("app.platform.extensions.entry_points", return_value=[ep]):
            load_extensions()  # Must not raise

        assert "permission" in _extensions

    def test_guard_observes_writes_during_callback(self):
        """The slot guard must detect writes made DURING (not before) the loader invocation."""
        from app.platform.extensions import load_extensions
        from app.platform.extensions import ExtensionSlotConflictError

        # First overlay writes the slot during its callback
        class AImpl:
            pass

        class BImpl:
            pass

        writes_log = []

        def _loader_a(registry: dict):
            writes_log.append("a")
            registry["catalog_port"] = AImpl()

        def _loader_b(registry: dict):
            writes_log.append("b")
            registry["catalog_port"] = BImpl()

        ep_a = _make_ep("a_overlay", _loader_a)
        ep_b = _make_ep("b_overlay", _loader_b)

        with patch("app.platform.extensions.entry_points", return_value=[ep_a, ep_b]):
            with pytest.raises(ExtensionSlotConflictError):
                load_extensions()

        # Both loaders were at least partially invoked (conflict found after second write)
        assert "a" in writes_log

    def test_all_single_slot_keys_are_guarded(self):
        """Every key in SINGLE_SLOT_KEYS triggers the conflict guard when written twice."""
        from app.platform.extensions import (
            SINGLE_SLOT_KEYS,
            ExtensionSlotConflictError,
        )
        from app.platform.extensions import load_extensions

        for key in SINGLE_SLOT_KEYS:
            _reset_registry()

            class Impl1:
                pass

            class Impl2:
                pass

            def _make_loader_a(k):
                def _loader(registry):
                    registry[k] = Impl1()

                return _loader

            def _make_loader_b(k):
                def _loader(registry):
                    registry[k] = Impl2()

                return _loader

            ep_a = _make_ep(f"{key}_overlay_a", _make_loader_a(key))
            ep_b = _make_ep(f"{key}_overlay_b", _make_loader_b(key))

            with patch(
                "app.platform.extensions.entry_points", return_value=[ep_a, ep_b]
            ):
                with pytest.raises(ExtensionSlotConflictError, match=key):
                    load_extensions()


class TestAdditiveSlotExempt:
    """Additive-slot keys are exempt from the conflict guard."""

    @pytest.mark.parametrize(
        "slot_key,write_fn",
        [
            (
                "audit_sinks",
                lambda registry: registry.setdefault("audit_sinks", []).append(
                    object()
                ),
            ),
            (
                "billing_extensions",
                lambda registry: registry.setdefault("billing_extensions", []).append(
                    object()
                ),
            ),
            (
                "ai_providers",
                lambda registry: registry.setdefault("ai_providers", {}).update(
                    {"test_provider": object()}
                ),
            ),
            (
                "embedding_providers",
                lambda registry: registry.setdefault("embedding_providers", {}).update(
                    {"test_emb": object()}
                ),
            ),
            (
                "notification_sinks",
                lambda registry: registry.setdefault("notification_sinks", []).append(
                    object()
                ),
            ),
            (
                "_routers",
                lambda registry: registry.setdefault("_routers", []).append(object()),
            ),
        ],
    )
    def test_additive_slot_no_raise(self, slot_key, write_fn):
        """Two overlays both writing an additive slot → NO raise."""
        from app.platform.extensions import load_extensions

        # Bind write_fn into a closure for each loader
        def _make_loader(fn):
            def _loader(registry: dict):
                fn(registry)

            return _loader

        ep_a = _make_ep("additive_overlay_a", _make_loader(write_fn))
        ep_b = _make_ep("additive_overlay_b", _make_loader(write_fn))

        with patch("app.platform.extensions.entry_points", return_value=[ep_a, ep_b]):
            load_extensions()  # Must NOT raise

    def test_additive_keys_set_matches_expectation(self):
        """ADDITIVE_SLOT_KEYS contains exactly the expected keys."""
        from app.platform.extensions import ADDITIVE_SLOT_KEYS

        expected = frozenset(
            {
                "audit_sinks",
                "billing_extensions",
                "ai_providers",
                "embedding_providers",
                "notification_sinks",  # Phase 1229 NOTIF-01
                "_routers",
            }
        )
        assert ADDITIVE_SLOT_KEYS == expected, (
            f"ADDITIVE_SLOT_KEYS mismatch: expected {expected}, got {ADDITIVE_SLOT_KEYS}"
        )


class TestSingleSlotKeySet:
    """SINGLE_SLOT_KEYS contains exactly the expected governance ports."""

    def test_single_slot_keys_match_expectation(self):
        from app.platform.extensions import SINGLE_SLOT_KEYS

        expected = frozenset(
            {
                "permission",
                "identity",
                "processing_port",
                "catalog_port",
                "workflow",
                "branding",
                "audit",
                "auth",
                "entitlement",  # Phase 1207 / ENTSEAM-01
                "connectors",
                "data_serving",
            }
        )
        assert SINGLE_SLOT_KEYS == expected, (
            f"SINGLE_SLOT_KEYS mismatch: expected {expected}, got {SINGLE_SLOT_KEYS}"
        )


class TestWrapDontReplaceDocumented:
    """SLOT-02: wrap-don't-replace rule must be documented in protocols.py docstrings."""

    def test_protocols_module_contains_wrap_rule(self):
        """protocols.py must document the wrap-don't-replace rule (not just in a comment)."""
        import inspect

        from app.platform.extensions import protocols

        source = inspect.getsource(protocols)
        # The wrap-don't-replace rule must appear in a docstring context
        assert "wrap" in source.lower(), (
            "protocols.py must document the wrap-don't-replace rule for single-slot "
            "extensions. SLOT-02 requires this convention be documented on Protocol "
            "docstrings."
        )

    def test_load_extensions_docstring_mentions_wrap_convention(self):
        """load_extensions() docstring must reference the wrap-don't-replace convention."""
        import inspect

        from app.platform.extensions import load_extensions

        docstring = inspect.getdoc(load_extensions) or ""
        assert "wrap" in docstring.lower() or "SLOT-02" in docstring, (
            "load_extensions() docstring must mention the wrap-don't-replace rule (SLOT-02)."
        )


class TestEnterpriseBootsGreen:
    """Simulated enterprise overlay claiming each single slot once → no raise."""

    def test_single_overlay_claims_all_slots(self):
        """An overlay claiming ALL single-slot keys (one instance each) passes."""
        from app.platform.extensions import (
            _extensions,
            load_extensions,
            SINGLE_SLOT_KEYS,
        )

        class EnterprisePort:
            pass

        def _enterprise_loader(registry: dict):
            for key in SINGLE_SLOT_KEYS:
                registry[key] = EnterprisePort()

        ep = _make_ep("enterprise_overlay", _enterprise_loader)

        with patch("app.platform.extensions.entry_points", return_value=[ep]):
            load_extensions()  # Must not raise

        for key in SINGLE_SLOT_KEYS:
            assert key in _extensions, f"Expected '{key}' to be registered; missing"
