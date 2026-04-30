---
phase: 220
slug: lifecycle-runbooks-and-preservation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-29
---

# Phase 220 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3+ (anyio_mode=auto, asyncio_mode=strict) |
| **Config file** | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` |
| **Full suite command** | `cd backend && uv run pytest -v -m 'not perf' --cov=app --cov-fail-under=58.5` |
| **Doc-content check** | `bash scripts/check-phase-220-docs.sh` (or inline grep block — see below) |
| **Estimated runtime** | ~2s (lifecycle test alone); ~120s full suite |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` (~2s)
- **After every plan wave:** Run full backend suite + doc-grep block
- **Before `/gsd-verify-work`:** Full suite green AND every doc-grep assertion green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 220-01-* | 01 | 1 | LIFECYCLE-01, LIFECYCLE-05 | — | Operator runbook present, mandatory pg_dump pre-step labeled destructive | doc-grep | See LIFECYCLE-01/05 grep block | ❌ W0 | ⬜ pending |
| 220-02-* | 02 | 1 | LIFECYCLE-02 | — | Reactivation runbook present, post-reactivation verify section | doc-grep | See LIFECYCLE-02 grep block | ❌ W0 | ⬜ pending |
| 220-03-* | 03 | 1 | LIFECYCLE-03 | — | docs/saml.md no longer presents alembic-downgrade as primary | doc-grep (negative + positive) | See LIFECYCLE-03 grep block | ❌ W0 (edit) | ⬜ pending |
| 220-04-* | 04 | 1 | LIFECYCLE-04 | — | Overlay-removal preserves SAML rows + 4 deferred columns + oauth_accounts row | integration test | `pytest tests/test_lifecycle.py::test_overlay_removal_preserves_saml_data -v -m lifecycle` | ❌ W0 (test) | ⬜ pending |
| 220-05-* | 05 | 2 | LIFECYCLE-04 | — | CI installs geolens-enterprise overlay; lifecycle marker collected | grep + workflow run | `grep -q geolens-enterprise .github/workflows/ci.yml` + observed CI green | ❌ W0 (CI) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_lifecycle.py` — new file; covers LIFECYCLE-04
- [ ] `backend/pyproject.toml` `markers` list — register `lifecycle` marker (one-line addition alongside existing `perf`, `requires_ogr2ogr`, `architecture` markers)
- [ ] `docs/edition-deactivation.md` — new file; covers LIFECYCLE-01, LIFECYCLE-05
- [ ] `docs/edition-reactivation.md` — new file; covers LIFECYCLE-02
- [ ] `docs/saml.md` Installation section — targeted edit; covers LIFECYCLE-03
- [ ] `.github/workflows/ci.yml` — overlay install + fork-PR gating (enables LIFECYCLE-04 in CI)
- [ ] No framework install needed — pytest, uv, anyio all already present

---

## Doc-Content Greps (LIFECYCLE-01, 02, 03, 05)

```bash
# LIFECYCLE-01 — deactivation runbook content
test -f docs/edition-deactivation.md
grep -q -i 'pre-flight' docs/edition-deactivation.md
grep -q -i 'pg_dump' docs/edition-deactivation.md
grep -q 'oauth_providers' docs/edition-deactivation.md
grep -q -i 'docker compose down' docs/edition-deactivation.md
grep -q 'GEOLENS_EDITION' docs/edition-deactivation.md
grep -q -E 'defense.in.depth|defense-in-depth' docs/edition-deactivation.md
grep -q -i 'data-fate\|data fate' docs/edition-deactivation.md

# LIFECYCLE-02 — reactivation runbook content
test -f docs/edition-reactivation.md
grep -q -i 'verify\|verification' docs/edition-reactivation.md
grep -q '/auth/saml' docs/edition-reactivation.md

# LIFECYCLE-03 — saml.md retargeted
# Negative: legacy "reversible alembic downgrade" framing GONE
! grep -E 'migration is reversible.*alembic downgrade' docs/saml.md
# Positive: cross-link to runbook present + destructive label present
grep -q 'edition-deactivation.md' docs/saml.md
grep -q -i 'destructive' docs/saml.md

# LIFECYCLE-05 — destructive path explicitly documented
grep -q -i 'destructive' docs/edition-deactivation.md
grep -q 'pg_dump' docs/edition-deactivation.md
grep -q -E -i 'mandatory|required' docs/edition-deactivation.md

# Cross-link symmetry
grep -q 'edition-reactivation' docs/edition-deactivation.md
grep -q 'edition-deactivation' docs/edition-reactivation.md
grep -q 'edition-deactivation' docs/saml.md
```

---

## Test Execution Checks (LIFECYCLE-04)

```bash
# Marker registered in pyproject.toml
grep -q 'lifecycle:' backend/pyproject.toml

# Test runs and exits clean
cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle
# Expected: test_overlay_removal_preserves_saml_data PASSED

# Test must assert all 5 schema-state preconditions:
#   1. oauth_providers row with provider_type='saml' present after registry clear
#   2. All 4 deferred columns (idp_entity_id, idp_sso_url, idp_certificate, sp_entity_id) populated
#   3. oauth_accounts row linking provider→user present
#   4. users row with auth_provider='oauth' present
#   5. is_enterprise() == False; default extension classes returned by typed accessors
```

---

## CI Integration Checks

```bash
# Workflow amended to install enterprise overlay
grep -q 'geolens-enterprise' .github/workflows/ci.yml
grep -q -E 'GEOLENS_ENTERPRISE_TOKEN|secrets.GEOLENS' .github/workflows/ci.yml
# Fork-PR gating present (skips when secrets unavailable)
grep -q -E "secrets.GEOLENS_ENTERPRISE_TOKEN != ''|github.event.pull_request.head.repo.fork == false" .github/workflows/ci.yml
```

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Runbook narrative quality | LIFECYCLE-01, LIFECYCLE-02 | Operator-facing prose; grep can't measure clarity | Reviewer reads docs/edition-deactivation.md and docs/edition-reactivation.md end-to-end and confirms operator can execute without external help |
| Cross-link reachability | LIFECYCLE-03 | Markdown link rendering is renderer-specific | Reviewer opens docs/saml.md in repo viewer (GitHub) and clicks the runbook link |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter (after planner finalizes per-task mapping)

**Approval:** pending
