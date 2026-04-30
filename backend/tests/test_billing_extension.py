"""Phase 223 — BillingExtension protocol + dispatch tests.

Covers:
  - BILLING-01 (Plan 01: this file's Wave-0 unit tests — Protocol shape + no-op
    default + accessor lazy fallback)
  - BILLING-04 (Plan 02: dispatch loop happy path / raising / hanging /
    isolated)
  - BILLING-05 (Plan 03: settings removal verification)
  - Enterprise overlay registration pattern (Plan 05: setdefault+append
    integration test)

BILLING-02 architecture guard lives in test_layering.py (Plan 04).
"""

from __future__ import annotations

import inspect

import pytest


def test_billing_extension_protocol_shape() -> None:
    """BILLING-01: BillingExtension Protocol + DefaultBillingExtension exist with correct shape."""
    from app.platform.extensions.defaults import DefaultBillingExtension
    from app.platform.extensions.protocols import BillingExtension

    # Protocol is runtime_checkable (D-06)
    assert hasattr(BillingExtension, "_is_runtime_protocol") or hasattr(
        BillingExtension, "_is_protocol"
    ), "BillingExtension must be a runtime_checkable Protocol (D-06)"

    # DefaultBillingExtension satisfies the protocol structurally
    assert isinstance(DefaultBillingExtension(), BillingExtension), (
        "DefaultBillingExtension must structurally satisfy BillingExtension Protocol"
    )

    # on_startup is async (D-08 — async-only)
    assert inspect.iscoroutinefunction(
        DefaultBillingExtension().on_startup
    ), "DefaultBillingExtension.on_startup must be async (D-08)"


@pytest.mark.anyio
async def test_default_billing_extension_is_noop() -> None:
    """BILLING-01 / D-07: DefaultBillingExtension.on_startup is a literal no-op.

    Calling it returns None and does not raise. Mirrors DefaultIdentityExtension
    discipline — community default behavior is identical to today's behavior
    when AWS_MARKETPLACE_PRODUCT_CODE is unset (zero AWS API calls, zero side
    effects).
    """
    from app.platform.extensions.defaults import DefaultBillingExtension

    ext = DefaultBillingExtension()
    # Pass any object as app — default doesn't use it (loose typing on default
    # parameter; precedent: DefaultIdentityExtension)
    result = await ext.on_startup(object())

    assert result is None, (
        "DefaultBillingExtension.on_startup must return None (no-op contract — D-07)"
    )


def test_get_billing_extensions_default_fallback() -> None:
    """BILLING-01: get_billing_extensions() returns [DefaultBillingExtension()] when slot missing.

    Mirrors Phase 222's get_audit_sinks() lazy-default behavior. The accessor
    must NEVER return None — call sites (lifespan dispatch loop, Plan 02)
    expect a non-empty list to iterate over.
    """
    from app.platform.extensions import _extensions, get_billing_extensions
    from app.platform.extensions.defaults import DefaultBillingExtension

    # Snapshot + clear slot to simulate community deployment with no overlay
    saved = _extensions.get("billing_extensions")
    _extensions.pop("billing_extensions", None)
    try:
        exts = get_billing_extensions()
        assert isinstance(exts, list), "get_billing_extensions must return list"
        assert len(exts) == 1, (
            f"Expected exactly one DefaultBillingExtension when slot is missing; "
            f"got len={len(exts)}"
        )
        assert isinstance(exts[0], DefaultBillingExtension), (
            f"Expected DefaultBillingExtension; got {type(exts[0]).__name__}"
        )
    finally:
        if saved is not None:
            _extensions["billing_extensions"] = saved
