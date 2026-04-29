---
phase: 219
slug: oc-audit-remediate-idp-mapping
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-29
---

# Phase 219 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio (Python 3.13) |
| **Config file** | `backend/pytest.ini` / `backend/pyproject.toml` (pre-existing) |
| **Quick run command** | `cd backend && pytest tests/test_oauth.py -x` |
| **Targeted runtime-gate run** | `cd backend && pytest tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_community_uses_default_role tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_enterprise_applies_mapping -x` |
| **Targeted schema-gate run** | `cd backend && pytest tests/test_oauth.py::TestIdpRoleMappingGate -x` |
| **Full suite command** | `cd backend && pytest -x` (baseline 1965/1965 must hold; ends at 1970/1970 after this phase adds 5 tests) |
| **Audit re-run command** | `/oc-audit` (Claude Code slash command at repo root) |
| **Doc-state grep** | `grep -c "^## ⚠ MILESTONE CLOSE BLOCKED" docs-internal/audits/oc-separation-audit-v13.1-close.md` (expect 0 outside preserved subsection); `grep -c "^## ✅ MILESTONE CLOSE VERIFIED" .../v13.1-close.md` (expect ≥1) |
| **Estimated runtime** | ~30 s (targeted oauth tests); ~3 min (full backend suite); ~2-5 min (`/oc-audit` re-run) |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && pytest tests/test_oauth.py -x` (~30 s).
- **After every plan wave:** Run `cd backend && pytest -x` (full suite, ~3 min) to confirm 1970/1970 baseline.
- **Before `/gsd-verify-work`:** Full suite green AND `/oc-audit` Boundary ≥ A− AND doc-state grep gates pass.
- **Max feedback latency:** ~30 s for unit-level slices; ~3 min for full-suite check.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 219-01-01 | 01 | 1 | AUDIT-V1 | T-219-01 (community-mode privilege escalation via group mapping) | `OAuthProviderCreate(group_role_mapping={"admins":"admin"})` raises `ValueError("Group-based role mapping requires the GeoLens Enterprise overlay")` in community | unit | `cd backend && pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_create_rejects_group_role_mapping_in_community -x` | ❌ W0 | ⬜ pending |
| 219-01-02 | 01 | 1 | AUDIT-V1 | T-219-01 | `OAuthProviderCreate(group_claim="groups")` raises `ValueError` with D-03 message in community | unit | `cd backend && pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_create_rejects_group_claim_in_community -x` | ❌ W0 | ⬜ pending |
| 219-01-03 | 01 | 1 | AUDIT-V1 | T-219-01 | `OAuthProviderCreate(group_role_mapping={"admins":"admin"})` succeeds with `init_edition(["enterprise"])` | unit | `cd backend && pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_create_accepts_group_mapping_in_enterprise -x` | ❌ W0 | ⬜ pending |
| 219-01-04 | 01 | 1 | AUDIT-V1 | T-219-01 | `OAuthProviderUpdate(group_role_mapping={"admins":"admin"})` raises in community | unit | `cd backend && pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_update_rejects_group_role_mapping_in_community -x` | ❌ W0 | ⬜ pending |
| 219-01-05 | 01 | 1 | AUDIT-V1 | — (D-02 carve-out) | `OAuthProviderCreate(group_role_mapping={})` and `=None` succeed in community ("clear mapping" / no mapping set) | unit | `cd backend && pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_create_with_empty_mapping_allowed_in_community -x` | ❌ W0 | ⬜ pending |
| 219-01-06 | 01 | 1 | AUDIT-V1 | T-219-01 | `find_or_create_oauth_user` with provider seeded directly via ORM (group_claim + non-empty mapping) returns user with `default_role` in community, NOT mapped role | integration (DB) | `cd backend && pytest tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_community_uses_default_role -x` | ❌ W0 (split from existing `test_group_role_mapping` at line 458) | ⬜ pending |
| 219-01-07 | 01 | 1 | AUDIT-V1 | T-219-01 | Same setup as slice 6 but `init_edition(["enterprise"])` → user has mapped role | integration (DB) | `cd backend && pytest tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_enterprise_applies_mapping -x` | ❌ W0 (renamed from existing test_group_role_mapping) | ⬜ pending |
| 219-01-08 | 01 | 2 | AUDIT-V1 | — | Pre-existing 1965-test baseline still passes (post-phase: 1970-test baseline) | integration (full) | `cd backend && pytest -x` | ✓ | ⬜ pending |
| 219-01-09 | 01 | 2 | AUDIT-V1 | T-219-02 (boundary regression) | `/oc-audit` re-run produces Boundary Integrity ≥ A− with zero 🔴 violations under the OAuth IdP cluster | manual / skill-driven | `/oc-audit` slash command; inspect Boundary row in Scorecard | ✓ skill canonical | ⬜ pending |
| 219-01-10 | 01 | 2 | AUDIT-V1 | — (close-artifact integrity) | `oc-separation-audit-v13.1-close.md` no longer has top-level `## ⚠ MILESTONE CLOSE BLOCKED` heading; has `## ✅ MILESTONE CLOSE VERIFIED` | doc structural | `grep -c "^## ⚠ MILESTONE CLOSE BLOCKED" docs-internal/audits/oc-separation-audit-v13.1-close.md` (expect 0); `grep -c "^## ✅ MILESTONE CLOSE VERIFIED" ...` (expect ≥1) | ✓ doc exists | ⬜ pending |
| 219-01-11 | 01 | 2 | AUDIT-V1 | T-219-01 | POST `group_role_mapping={"admins":"admin"}` to `/settings/oauth-providers/` returns 422 with D-03 message in community | manual smoke | `curl -sS -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"slug":"test","display_name":"Test","provider_type":"oidc","client_id":"x","client_secret":"y","group_role_mapping":{"admins":"admin"}}' http://localhost:8000/settings/oauth-providers/ \| jq` | ✓ endpoint exists | ⬜ pending |
| 219-01-12 | 01 | 2 | AUDIT-V1 | — | Same payload with `GEOLENS_EDITION=enterprise` returns 200/201 | manual smoke | `GEOLENS_EDITION=enterprise` set on backend container; same `curl` as slice 11 | ✓ endpoint exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] **New `TestIdpRoleMappingGate` class** in `backend/tests/test_oauth.py` covering slices 1-5 (5 unit tests).
- [ ] **Split `test_group_role_mapping`** at `backend/tests/test_oauth.py:458` into:
  - `test_group_role_mapping_community_uses_default_role` (slice 6) — direct ORM `OAuthProvider(...)` insert (NOT via `_create_test_provider()` helper, which routes through the new D-01 validator and would reject the seed).
  - `test_group_role_mapping_enterprise_applies_mapping` (slice 7) — `init_edition(["enterprise"])` setup; existing assertion preserved.
- [ ] **Edition-state isolation** — local autouse fixture in `test_oauth.py` mirroring the precedent at `backend/tests/test_edition.py:11-22` (`_reset_edition()` helper + `_clean_edition` autouse fixture). Reuse pattern; do NOT introduce a new isolation mechanism.

*Existing infrastructure covers everything else.* `pytest`, `pytest-asyncio`, `init_edition()` helper, `is_enterprise()` helper, async test DB session, OAuth model — all pre-exist on `main`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `/oc-audit` Boundary Integrity ≥ A− with zero 🔴 in OAuth IdP cluster | AUDIT-V1 (slice 9) | The `/oc-audit` skill is a multi-subagent grader (8 sections, 6 subagents) — its grade letter is the canonical boundary verification artifact for v13.1. Cannot be replaced by a unit test. | 1) Run `/oc-audit` at repo root in Claude Code. 2) Open the produced `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md`. 3) Confirm Scorecard row "Boundary Integrity" letter ≥ A−. 4) Confirm Section 1 has zero 🔴 rows under the OAuth IdP cluster. 5) Discard the date-named file (per CONTEXT.md D-11 — only `v13.1-close.md` is the milestone artifact). |
| Community 422 + Enterprise 200/201 smoke via `curl` | AUDIT-V1 (slices 11-12) | Verifies the FastAPI router → Pydantic → response chain end-to-end. Unit tests cover the validator in isolation; the smoke ensures the validator's `ValueError` surfaces as an HTTP 422 with the D-03 message body. | See "Code Examples §" in `219-RESEARCH.md` (the `curl` payload + expected JSON shape). Run against a local docker-compose backend with admin token. Repeat with `GEOLENS_EDITION=enterprise` set on the backend container. |
| `oc-separation-audit-v13.1-close.md` amendment in place | AUDIT-V1 (slice 10) | Verifies the doc edits per D-12 actually land (banner swap + scorecard row + Section 1 + Section 8 + P1 triage row + Executive Summary sweep). Each edit is small; the structural grep + manual visual scan is faster than testing each individually. | Run the two `grep -c` checks (above). Then visually scan: 1) line 20 region — banner is `## ✅ MILESTONE CLOSE VERIFIED — Phase 219 closed boundary gap` with the prior BLOCKED banner preserved as `### Pre-remediation state (2026-04-29)` subsection; 2) Scorecard Boundary row letter is the new grade with re-written rationale; 3) Section 1 (lines 53-55 region) — three 🔴 rows are now 🟢 with new code-location citations; 4) Section 8 grade-delta — new "v13.1-close (post-219)" column added with Boundary `Met? ✅`; 5) P1 Residual Triage row 1 — verdict column appended with **Closed by Phase 219 (2026-04-29)**. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies (slices 1-8 automated; slices 9-12 are manual-by-design — see "Manual-Only Verifications" above; this is acceptable for an audit-driven boundary phase)
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (slices 1-8 are automated and contiguous; slice 9 is manual-by-design at the boundary layer; slice 10 has automated grep verification; this satisfies continuity)
- [ ] Wave 0 covers all MISSING references (`TestIdpRoleMappingGate` class, split runtime tests, autouse edition fixture)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30 s for unit slices; < 3 min for full suite; < 5 min for audit re-run
- [ ] `nyquist_compliant: true` set in frontmatter (set by planner once plans are written and tests are stubbed)

**Approval:** pending
