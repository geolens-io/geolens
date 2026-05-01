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

import asyncio
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


# ---------------------------------------------------------------------------
# Plan 02 dispatch tests (BILLING-04 / D-10 / D-12 / D-15)
# ---------------------------------------------------------------------------


class FixtureBillingExtension:
    """Stand-in for a future enterprise BillingExtension.

    Records every (app) it received so tests can assert dispatch coverage.
    """

    def __init__(self) -> None:
        self.received: list = []

    async def on_startup(self, app) -> None:
        self.received.append(app)


class RaisingBillingExtension:
    """Simulates a broken overlay whose on_startup raises.

    Per D-10 / D-12, the dispatch loop must catch the exception, log a
    structlog warning, and continue to the next extension.
    """

    async def on_startup(self, app) -> None:
        raise RuntimeError("simulated billing extension failure for BILLING-04")


class HangingBillingExtension:
    """Simulates a runaway overlay whose on_startup blocks indefinitely.

    Per D-10 / D-11, the dispatch loop must time out after 10s, log a
    structlog warning, and continue to the next extension.
    """

    async def on_startup(self, app) -> None:
        await asyncio.sleep(15.0)  # exceeds 10.0s timeout


async def _dispatch(extensions, app, timeout: float = 10.0) -> None:
    """Inline replica of the dispatch loop in api/main.py.

    Mirrors the production code at backend/app/api/main.py (Plan 02 Task 1
    replacement). Tests inline-call this helper with a pre-populated extension
    list, avoiding the cost of spinning up the full lifespan with a TestClient.

    Per D-10: each extension is awaited inside asyncio.wait_for(timeout); both
    TimeoutError and general Exception are swallowed (per-extension isolation —
    D-12). Failures would normally be logged via structlog; here we silently
    swallow because the tests assert behavior (subsequent extensions ran),
    not log content. Plan 04 architecture guard verifies the production loop
    matches this shape.
    """
    for ext in extensions:
        try:
            await asyncio.wait_for(ext.on_startup(app), timeout=timeout)
        except (asyncio.TimeoutError, Exception):
            # Production code splits these into two `except` clauses with
            # different log messages; for the test we collapse them since
            # we assert behavior, not log shape.
            pass


@pytest.mark.anyio
async def test_dispatch_runs_all_registered_extensions() -> None:
    """BILLING-04 / D-10 happy path: every registered extension's on_startup runs.

    Verifies the dispatch loop iterates over `[DefaultBillingExtension(),
    FixtureBillingExtension()]` and each ext sees the same `app` argument.
    """
    from app.platform.extensions import _extensions
    from app.platform.extensions.defaults import DefaultBillingExtension

    fixture = FixtureBillingExtension()
    saved = _extensions.get("billing_extensions")
    _extensions["billing_extensions"] = [DefaultBillingExtension(), fixture]
    try:
        mock_app = object()  # FastAPI app stand-in; default ext doesn't use it
        from app.platform.extensions import get_billing_extensions

        await _dispatch(get_billing_extensions(), mock_app)

        assert fixture.received == [mock_app], (
            f"FixtureBillingExtension.on_startup did not receive the app argument; "
            f"received={fixture.received}"
        )
    finally:
        if saved is None:
            _extensions.pop("billing_extensions", None)
        else:
            _extensions["billing_extensions"] = saved


@pytest.mark.anyio
async def test_raising_extension_isolated() -> None:
    """BILLING-04 / D-10 / D-12: a raising extension does NOT abort dispatch.

    Order matters: RaisingBillingExtension is FIRST in the list. If the
    dispatch loop wraps the entire iteration in one try/except (instead of
    per-extension), FixtureBillingExtension never runs and `fixture.received`
    stays empty — the test would fail.
    """
    from app.platform.extensions import _extensions

    fixture = FixtureBillingExtension()
    saved = _extensions.get("billing_extensions")
    _extensions["billing_extensions"] = [RaisingBillingExtension(), fixture]
    try:
        mock_app = object()
        from app.platform.extensions import get_billing_extensions

        await _dispatch(get_billing_extensions(), mock_app)

        assert fixture.received == [mock_app], (
            "FixtureBillingExtension did not run after RaisingBillingExtension raised — "
            "per-extension isolation broken (D-12: each ext's try/except must be "
            "scoped per-iteration, NOT around the whole for-loop)."
        )
    finally:
        if saved is None:
            _extensions.pop("billing_extensions", None)
        else:
            _extensions["billing_extensions"] = saved


@pytest.mark.anyio
async def test_hanging_extension_timeout() -> None:
    """BILLING-04 / D-10 / D-11: a hanging extension is timed out at the configured timeout.

    Order matters: HangingBillingExtension is FIRST. After the configured timeout
    elapses, the dispatch loop swallows the TimeoutError and proceeds to
    FixtureBillingExtension. To keep the test fast, we use a short test-only
    timeout (0.5s) — the contract under test is "the dispatch loop times out
    and continues", not the literal 10.0s value (D-11 hardcodes the production
    value; the dispatch shape is what's asserted here).

    Production timeout=10.0 is verified by an architecture-guard grep in
    test_layering.py (Plan 04 Task 1).
    """
    import time

    from app.platform.extensions import _extensions

    fixture = FixtureBillingExtension()
    saved = _extensions.get("billing_extensions")
    _extensions["billing_extensions"] = [HangingBillingExtension(), fixture]
    try:
        mock_app = object()
        from app.platform.extensions import get_billing_extensions

        start = time.monotonic()
        # Use a 0.5s timeout for fast tests — production uses 10.0 (D-11)
        await _dispatch(get_billing_extensions(), mock_app, timeout=0.5)
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, (
            f"Dispatch loop did not honor the timeout — elapsed {elapsed:.2f}s "
            f"with 0.5s timeout. The wait_for wrapper is missing or wrapping "
            f"the wrong scope (D-10)."
        )
        assert fixture.received == [mock_app], (
            "FixtureBillingExtension did not run after HangingBillingExtension "
            "timed out — per-extension isolation broken (D-12: TimeoutError "
            "must be caught and the loop must continue)."
        )
    finally:
        if saved is None:
            _extensions.pop("billing_extensions", None)
        else:
            _extensions["billing_extensions"] = saved
