"""Tests for EntitlementPort Protocol, grant-all default, slot-guard, and dependency.

Covers:
(a) Empty slot returns DefaultEntitlementPort.
(b) Grant-all: has_feature returns True, enforce_limit never raises.
(c) Duplicate 'entitlement' write raises ExtensionSlotConflictError.
(d) require_entitlement allows under the grant-all default via a TestClient route.

References: ENTSEAM-01, SLOT-01
"""

from __future__ import annotations

from types import SimpleNamespace
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
    from unittest.mock import MagicMock as _MagicMock

    from app.platform.extensions.version import EXTENSION_API_VERSION

    ep = _MagicMock()
    ep.name = name
    loader_fn.EXTENSION_API_VERSION = EXTENSION_API_VERSION
    ep.load.return_value = loader_fn
    return ep


# ---------------------------------------------------------------------------
# (a) Empty slot returns DefaultEntitlementPort
# ---------------------------------------------------------------------------


def test_get_entitlement_port_returns_default_on_empty_slot():
    """get_entitlement_port() returns DefaultEntitlementPort when no overlay registered."""
    from app.platform.extensions import get_entitlement_port
    from app.platform.extensions.defaults import DefaultEntitlementPort
    from app.platform.extensions.protocols import EntitlementPort

    port = get_entitlement_port()

    assert isinstance(port, DefaultEntitlementPort)
    assert isinstance(port, EntitlementPort)


# ---------------------------------------------------------------------------
# (b) Grant-all behavior: has_feature -> True, enforce_limit -> no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_entitlement_port_has_feature_returns_true():
    """DefaultEntitlementPort.has_feature returns True for any feature string."""
    from app.platform.extensions.defaults import DefaultEntitlementPort

    port = DefaultEntitlementPort()

    assert await port.has_feature("premium_feature") is True
    assert await port.has_feature("advanced_analytics") is True
    assert await port.has_feature("anything_at_all") is True


@pytest.mark.asyncio
async def test_default_entitlement_port_enforce_limit_never_raises():
    """DefaultEntitlementPort.enforce_limit is a no-op (never raises) for any dimension/n."""
    from app.platform.extensions.defaults import DefaultEntitlementPort

    port = DefaultEntitlementPort()

    # Must return None and not raise for any combination
    result = await port.enforce_limit("datasets", 10**9)
    assert result is None

    result = await port.enforce_limit("storage_gb", 0)
    assert result is None

    result = await port.enforce_limit("api_calls", 1)
    assert result is None


# ---------------------------------------------------------------------------
# (c) Duplicate 'entitlement' write raises ExtensionSlotConflictError
# ---------------------------------------------------------------------------


def test_duplicate_entitlement_slot_raises_conflict_error():
    """Two overlays both writing 'entitlement' → ExtensionSlotConflictError."""
    from app.platform.extensions import ExtensionSlotConflictError, load_extensions

    class FirstEntitlement:
        pass

    class SecondEntitlement:
        pass

    first_instance = FirstEntitlement()
    second_instance = SecondEntitlement()

    def _loader_a(registry: dict):
        registry["entitlement"] = first_instance

    def _loader_b(registry: dict):
        registry["entitlement"] = second_instance

    ep_a = _make_ep("cloud_overlay", _loader_a)
    ep_b = _make_ep("enterprise_overlay", _loader_b)

    with patch("app.platform.extensions.entry_points", return_value=[ep_a, ep_b]):
        with pytest.raises(ExtensionSlotConflictError) as exc_info:
            load_extensions()

    msg = str(exc_info.value)
    assert "entitlement" in msg
    assert "FirstEntitlement" in msg
    assert "SecondEntitlement" in msg


def test_entitlement_in_single_slot_keys():
    """'entitlement' is present in SINGLE_SLOT_KEYS."""
    from app.platform.extensions import SINGLE_SLOT_KEYS

    assert "entitlement" in SINGLE_SLOT_KEYS


# ---------------------------------------------------------------------------
# (d) require_entitlement allows under the grant-all default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_require_entitlement_allows_under_grant_all_default():
    """require_entitlement('feature') does NOT raise when grant-all default is active."""
    from app.platform.extensions.entitlement import require_entitlement

    # Create a minimal request with empty state
    request = SimpleNamespace(state=SimpleNamespace())

    dep = require_entitlement("premium_feature")

    # Should not raise; grant-all default means all features pass
    result = await dep(request)
    assert result is None


@pytest.mark.asyncio
async def test_require_entitlement_uses_request_state_cache():
    """require_entitlement reads/writes a request.state entitlement cache."""
    from app.platform.extensions.entitlement import require_entitlement

    request = SimpleNamespace(state=SimpleNamespace())

    dep = require_entitlement("feature_a")

    # Call twice — second call should hit the cache
    await dep(request)
    # Cache should be populated on request.state
    assert hasattr(request.state, "_entitlement_summary")

    # Second call also passes
    await dep(request)


@pytest.mark.asyncio
async def test_enforce_limit_dependency_is_no_op_under_default():
    """enforce_limit dependency does not raise under the grant-all DefaultEntitlementPort."""
    from app.platform.extensions.entitlement import enforce_limit

    request = SimpleNamespace(state=SimpleNamespace())

    # enforce_limit should be callable as a dependency or directly
    # It accepts dimension and n, delegates to port.enforce_limit
    await enforce_limit(request, "datasets", 1000)  # must not raise
