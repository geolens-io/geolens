"""Phase 279 ADMIN-03 + ADMIN-04 regression tests.

ADMIN-03 (M-03): Lock the single-source-of-truth contract for enterprise-only
Settings tab keys. Without this gate, future drift between backend
``_ENTERPRISE_ONLY_TABS`` and frontend ``AdminSidebar`` enterpriseOnly flags
can re-emerge silently.

ADMIN-04 (M-04): Lock the unified audit-export format dispatcher. Without
this gate, a future maintainer might re-introduce a parallel hardcoded
format list that diverges from FORMAT_HANDLERS.

These are pure static-analysis / import-level tests; no DB fixtures are
required so they remain stable across CI environments where the test DB may
be unreachable (e.g. lint-only CI lanes).
"""

from pathlib import Path

from app.modules.audit.router import FORMAT_HANDLERS
from app.modules.settings.router import _ENTERPRISE_ONLY_TABS
from app.modules.settings.schemas import EnterpriseTabsResponse


# ---------------------------------------------------------------------------
# ADMIN-03 — Enterprise-tabs single source of truth
# ---------------------------------------------------------------------------


def test_enterprise_only_tabs_constant_includes_branding_and_appearance():
    """Backend frozenset matches the frontend's prior hardcoded enterpriseOnly flags.

    Pre-Phase-279: backend had {'branding'}; frontend had branding+appearance.
    The two drifted silently — community callers could write `appearance`
    settings because `_require_enterprise_for_key` only blocked branding.
    Phase 279 ADMIN-03 reconciles them and this test gates against regression.
    """
    assert "branding" in _ENTERPRISE_ONLY_TABS
    assert "appearance" in _ENTERPRISE_ONLY_TABS
    # The set must remain exactly these two as of v13.13. Adding tabs is a
    # deliberate boundary change and should be paired with an update to this
    # assertion AND a corresponding update to the frontend FALLBACK constant
    # in AdminSidebar.tsx (server-driven hook is the canonical source, but
    # the fallback applies during boot/network failures).
    assert _ENTERPRISE_ONLY_TABS == frozenset({"branding", "appearance"})


def test_enterprise_tabs_response_schema_serializes_sorted():
    """The endpoint returns sorted(set) for stable JSON; validate the response model."""
    resp = EnterpriseTabsResponse(tabs=sorted(_ENTERPRISE_ONLY_TABS))
    assert resp.tabs == ["appearance", "branding"]


def test_enterprise_tabs_endpoint_registered():
    """The GET /enterprise-tabs/ route is registered on the settings router.

    Static-analysis verification that the route handler exists. A full
    request/response test runs in test_settings_admin.py once the integration
    DB fixture is set up; this test is the trip-wire for "did someone delete
    the route".
    """
    from app.modules.settings.router import router as settings_router

    paths = {r.path for r in settings_router.routes if hasattr(r, "path")}
    assert "/settings/enterprise-tabs/" in paths


# ---------------------------------------------------------------------------
# ADMIN-04 — Audit-export unified format dispatcher
# ---------------------------------------------------------------------------


def test_format_handlers_keys_are_exactly_csv_and_json():
    """Core OSS audit router serves exactly csv + json. Anything else
    advertised by an extension is the extension's responsibility."""
    assert set(FORMAT_HANDLERS.keys()) == {"csv", "json"}
    assert FORMAT_HANDLERS["csv"] == "text/csv"
    assert FORMAT_HANDLERS["json"] == "application/json"


def test_audit_router_no_501_branch_remains():
    """Static-analysis: the old `501 NOT_IMPLEMENTED` branch is fully removed."""
    router_path = (
        Path(__file__).resolve().parents[1] / "app" / "modules" / "audit" / "router.py"
    )
    # Strip comments before counting so a future reference in a doc comment
    # doesn't trigger a self-invalidating grep gate.
    text = "\n".join(
        line
        for line in router_path.read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    # The status-code constant is what triggered the old branch. If a future
    # ADMIN-04 walkback restores 501, this gate fails loudly.
    assert "HTTP_501_NOT_IMPLEMENTED" not in text, (
        "audit/router.py must not raise 501 — Phase 279 ADMIN-04 unified the "
        "format dispatcher. Re-introducing 501 violates the single-source-"
        "of-truth contract."
    )


def test_audit_router_502_branch_present_for_format_handlers_drift():
    """The replacement 502 branch must exist and reference FORMAT_HANDLERS."""
    router_path = (
        Path(__file__).resolve().parents[1] / "app" / "modules" / "audit" / "router.py"
    )
    text = router_path.read_text()
    assert "FORMAT_HANDLERS" in text
    assert "HTTP_502_BAD_GATEWAY" in text
