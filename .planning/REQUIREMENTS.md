# Requirements: GeoLens v13.3 Boundary A+ Cleanup

**Defined:** 2026-04-30
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.
**Source spec:** `docs-internal/audits/oc-separation-audit-20260430.md` — §7 P1 bucket
**Milestone goal:** Close the two P1 architectural items from the post-v13.2 open-core separation audit so the next sales-facing pass can claim Boundary Integrity A+ (zero remaining 🟡 risks) and a fully-overlay-capable audit seam. Target grade improvements: Boundary Integrity A → A+, Seam Quality B → B+ (one more 🔴 → 🟢: write-side audit sink).

## v13.3 Requirements

Requirements for v13.3. Each maps to exactly one phase in `.planning/ROADMAP.md`. REQ-IDs introduce two new prefixes for this milestone: `AUDIT` (audit-sink protocol) and `BILLING` (marketplace billing extraction).

### Audit Sink Protocol

Closes the +242% `log_action()` decentralization regression flagged in the 2026-04-30 audit §5. Today, 65 `log_action()` emit sites are scattered across 19 files; an audit-export overlay (Team-tier paywall) would have to patch every one. The fix is a single hook that overlays subscribe to.

- [x] **AUDIT-01**: An `AuditSink` Protocol is defined in `backend/app/platform/extensions/protocols.py` with an `emit(event)` method covering the parameter surface that the existing `log_action()` already accepts (action, actor, resource, before/after diffs, metadata). Defaults from `extensions/defaults.py` provide a no-op community implementation that delegates to the existing `audit_logs` table write.
- [ ] **AUDIT-02**: All 65 `log_action()` emit sites in `backend/app/` route through `get_audit_sink().emit(...)` rather than calling `log_action()` directly. The `log_action()` function itself either (a) becomes the community default sink's `emit()` body, or (b) is removed in favor of the protocol — chosen during `/gsd-discuss-phase`.
- [ ] **AUDIT-03**: Sink-failure semantics are explicit: a sink that raises does not break the surrounding business operation (e.g., a failed dataset publish must not be rolled back because an audit emit failed). Failures are logged via `structlog.exception()` but do not propagate. Defined and tested.
- [ ] **AUDIT-04**: An enterprise audit-export overlay can subscribe additional sinks (file, S3, SIEM, syslog) by registering an `AuditSink` implementation through the existing extension entry-point group, without modifying core code. Verified end-to-end via a fixture-based test sink.
- [ ] **AUDIT-05**: Existing audit behavior is preserved — every event today recorded in `audit_logs` continues to be recorded after the refactor; existing tests pass without modification; no row-count or row-content drift on a deterministic test workload (community default + zero overlays).

### Marketplace Billing Extraction

Removes the 3 remaining 🟡 boundary risks (audit §1 — `core/marketplace.py`, `api/main.py:184-203`, `core/config.py:87-88`). Today, every community deployment ships `boto3` and runs an AWS Marketplace registration call on lifespan startup (inert when the env var is unset, but architectural debt). The fix is to push billing to the enterprise overlay via a `BillingExtension` hook.

- [ ] **BILLING-01**: A `BillingExtension` Protocol is defined in `backend/app/platform/extensions/protocols.py` with at least an `on_startup(app)` hook fired by the FastAPI lifespan. Community default is no-op.
- [ ] **BILLING-02**: `backend/app/core/marketplace.py` is removed from core. Its implementation moves to the enterprise overlay (`geolens-enterprise/geolens_enterprise/billing/`) and registers as a `BillingExtension`.
- [ ] **BILLING-03**: `boto3` is removed from `backend/pyproject.toml` dependencies. Only the enterprise overlay declares it.
- [ ] **BILLING-04**: The lifespan registration at `backend/app/api/main.py:184-203` is replaced with a generic dispatch: `for ext in get_billing_extensions(): ext.on_startup(app)`. Community deployments perform zero AWS API calls and import zero `boto3` symbols.
- [ ] **BILLING-05**: `aws_marketplace_product_code` and `aws_marketplace_public_key_version` either move to the enterprise overlay's settings (preferred) OR remain as opaque pass-through env vars in core `Settings` (acceptable carve-out — chosen during `/gsd-discuss-phase`). The runtime *behavior* (the AWS API call) must not be in core regardless.
- [ ] **BILLING-06**: Audit re-run after both phases ship produces zero 🟡 boundary risks (Boundary Integrity grade A+) and the AWS Marketplace cluster section in §1 of the audit reports "✅ Closed" rather than "🟡 Risk (P2)".

## Future Requirements

Captured for visibility but explicitly deferred from v13.3.

- **AUDIT-FUTURE-01**: Audit-export overlay (Team-tier paywall) — building on the AuditSink seam delivered here, ship a `geolens-enterprise/audit_export/` overlay that streams audit events to S3/SIEM/syslog and renders signed CSV/JSON exports. Lives in the enterprise repo, not v13.3.
- **AUDIT-FUTURE-02**: Compliance reporting (who-accessed-what dashboards, retention policies, SOC2-style report generation). Business-tier feature, requires AuditSink + audit-export overlay + report-template engine.
- **BILLING-FUTURE-01**: Stripe / per-deployment metering (Cloud-tier prerequisite). Builds on `BillingExtension` Protocol delivered here. Phase 999.6 territory.

## Out of Scope

Explicit exclusions for v13.3 with reasoning.

- **No new audit event types.** This milestone refactors the *transport* of audit events, not their content. Adding new event categories or fields belongs to a separate phase.
- **No log retention or rotation policy changes.** Audit retention/rotation is a separate compliance concern; v13.3 preserves current behavior exactly.
- **No SCIM, no SAML changes.** v13.1 + v13.2 shipped the auth-overlay seams; v13.3 does not touch identity at all.
- **No tenant scoping.** Phase 999.6 (Cloud-tier prerequisite, deferred).
- **No `AuditSink` advanced semantics** (back-pressure, batching, ordering across sinks, durable queues). Community deployments use a single in-process sink; if enterprise customers need batching/queuing, that lands in the audit-export overlay.
- **No `BillingExtension` beyond `on_startup`.** The minimum hook to remove the boto3 dependency from core. Per-event metering (`emit_usage`, `record_request`) is for Cloud-tier billing, not v13.3.
- **No GTM document restructure.** v13.3 stays surgical; the broader integration of the 10 locked tier decisions into canonical Community/Enterprise sections of `free-vs-enterprise.md` is a separate docs sweep.

## Traceability

| Requirement | Phase |
|---|---|
| AUDIT-01 | Phase 222 |
| AUDIT-02 | Phase 222 |
| AUDIT-03 | Phase 222 |
| AUDIT-04 | Phase 222 |
| AUDIT-05 | Phase 222 |
| BILLING-01 | Phase 223 |
| BILLING-02 | Phase 223 |
| BILLING-03 | Phase 223 |
| BILLING-04 | Phase 223 |
| BILLING-05 | Phase 223 |
| BILLING-06 | Phase 223 |
