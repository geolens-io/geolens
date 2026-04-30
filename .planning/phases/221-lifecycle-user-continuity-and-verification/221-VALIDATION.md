---
phase: 221
slug: lifecycle-user-continuity-and-verification
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-30
---

# Phase 221 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) |
| **Config file** | `backend/pyproject.toml` (`[tool.pytest.ini_options]`); `lifecycle` marker registered Phase 220 |
| **Quick run command** | `cd backend && pytest -m lifecycle -x -q` |
| **Full suite command** | `cd backend && pytest -q` |
| **Estimated runtime** | ~25-40 seconds (lifecycle subset); ~5 minutes (full suite) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && pytest -m lifecycle -x -q`
- **After every plan wave:** Run `cd backend && pytest -q` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green; `cd backend && ruff check .` must be clean
- **Max feedback latency:** 60 seconds (lifecycle subset)

---

## Per-Task Verification Map

> Filled by gsd-planner during plan generation. The planner MUST emit one row per task and tie each to LIFECYCLE-06 or LIFECYCLE-07 with a concrete `pytest` invocation or `grep` assertion against the produced file.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 221-XX-XX | XX | X | LIFECYCLE-06/07 | — | (planner fills) | unit/integration/doc | `(planner fills)` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] No new fixtures required — `_seed_saml_provider`, `saml_overlay_registered`, `_cleanup_lifecycle_rows` all inherited from Phase 220 / Phase 217
- [ ] No new framework install — pytest + `lifecycle` marker already registered in `backend/pyproject.toml`
- [ ] No new dependencies — `hash_password`, `log_action`, `require_permission("manage_users")` all already imported in `backend/app/modules/admin/`

*Existing infrastructure covers all phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Operator follows the runbook end-to-end against a deactivated edition | LIFECYCLE-06 (SC#2 doc surface) | Runbook is operator-facing prose; doc-test would be a reading-comprehension proxy | Render `docs/edition-deactivation.md`, walk the new "Handling existing SAML users" section start-to-finish on a staging stack, confirm copy-paste curl + `/auth/login/` flow works |
| `audit_log` row produced by the new endpoint is visible in operator audit-trail tooling | LIFECYCLE-06 (SC#1 audit history) | Audit-tooling UX is out-of-scope for Phase 221 | After running the conversion against staging, query `SELECT * FROM audit_log WHERE action='auth.convert_saml_to_local'` and confirm the row matches expected shape |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (none expected — infra is reused)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s for lifecycle subset
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
