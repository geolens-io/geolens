---
phase: 220-lifecycle-runbooks-and-preservation
verified: 2026-04-29T00:00:00Z
status: human_needed
score: 5/5 must-haves verified (static); SC#4 runtime execution requires CI
overrides_applied: 0
human_verification:
  - test: "Run the lifecycle pytest end-to-end against a live test database with the geolens-enterprise overlay installed"
    expected: "`cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` exits 0 with `test_overlay_removal_preserves_saml_data PASSED`"
    why_human: "Requires Docker stack (PostgreSQL + PostGIS + pgvector) and an editable install of `~/Code/geolens-enterprise`; the verifier sandbox cannot run those services. The test was authored to spec, statically verified (13 grep assertions + collection-only check), and CI is wired (Plan 06) to execute it on push to main once the GEOLENS_ENTERPRISE_TOKEN secret is added by the repo owner."
  - test: "Add the GEOLENS_ENTERPRISE_TOKEN repository secret in GitHub Settings"
    expected: "On push to main, the `Backend Tests` job's `Checkout geolens-enterprise` step is not skipped; pytest invocation logs read `Running pytest with lifecycle marker INCLUDED (overlay installed)`; lifecycle test passes"
    why_human: "Secret creation is an out-of-band repo-settings action; the verifier cannot add secrets. Until the token is added, fork PRs and main pushes both run with the lifecycle marker DESELECTED — that is the safe-by-design fallback per Plan 06 D-06."
---

# Phase 220: Lifecycle Runbooks and Preservation — Verification Report

**Phase Goal:** Operators have authoritative documentation for the enterprise→community downgrade and re-upgrade lifecycle, and data-preservation behavior is verified by an automated test.
**Verified:** 2026-04-29
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Operator can read `docs/edition-deactivation.md` covering the full enterprise→community downgrade sequence (pre-flight, env switch, SAML inventory, data-fate matrix) | VERIFIED | 186-line runbook with all 12 required literal tokens; 10 sections including pre-flight checklist, 6-step deactivation sequence, data-fate matrix, destructive path |
| 2 | Operator can read `docs/edition-reactivation.md` confirming `deferred=True` SAML columns and `oauth_providers` rows survive deactivation | VERIFIED | 75-line thin runbook; 5-step post-reactivation verification checklist; ≤120-line discipline honored; cross-link to deactivation runbook present |
| 3 | `docs/saml.md` no longer presents `alembic downgrade -1` as primary deactivation path; cross-links to `edition-deactivation.md`, labels alembic path destructive/opt-in with mandatory data-export | VERIFIED | Negative grep `migration is reversible.*alembic downgrade` returns 0 matches; 2 occurrences of `edition-deactivation.md`; `destructive` label and `Deactivating SAML` heading present; targeted edit (13+1 lines, well under 35 budget) |
| 4 | Integration test `pytest -m lifecycle` exercises deactivate path and asserts `oauth_providers` SAML rows + 4 `deferred=True` `oauth_providers` columns intact after edition flag toggled off | VERIFIED (static) — runtime PENDING (CI) | Test file authored to D-04 spec; all 13 grep assertions pass; pytest collects 1 item cleanly; schema-correct ORM seed against User (username/password_hash/nullable email) confirmed against `backend/app/modules/auth/models.py:18-55`; runtime end-to-end execution requires Docker + overlay (routed to human verification) |
| 5 | Either non-destructive alembic path exists OR `edition-deactivation.md` documents destructive path with explicit mandatory-export step | VERIFIED | Plan elected D-02 (no e003-style path; runbook documents destructive alembic with mandatory `pg_dump` pre-step and verbatim e002.downgrade() deletion order); `mandatory and required` label present in destructive section |

**Score:** 5/5 truths verified statically. SC#4 runtime test execution is routed to human verification (Docker + overlay required) — the test is correctly authored and CI is wired to execute it on push to main once the GEOLENS_ENTERPRISE_TOKEN secret is added.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `docs/edition-deactivation.md` | Operator runbook with pre-flight, sequence, data-fate matrix, destructive path | VERIFIED | 186 lines, 10 sections; all 12 doc-grep tokens present (pre-flight, pg_dump, oauth_providers, docker compose down, GEOLENS_EDITION, defense-in-depth, destructive, mandatory/required, edition-reactivation, (saml.md), data-fate); no emojis; deletion order matches e002.downgrade() exactly |
| `docs/edition-reactivation.md` | Thin reactivation runbook + 5-step verification checklist | VERIFIED | 75 lines (≤120 budget); all 5 doc-grep tokens present (verify, /auth/saml, edition-deactivation, oauth_providers, deferred); does not duplicate saml.md activation walkthrough |
| `docs/saml.md` (targeted edit) | Installation section retargeted; legacy "reversible alembic" framing gone; cross-link to runbook present | VERIFIED | Line 48 replaced with destructive-labeled blockquote linking to edition-deactivation.md; new `### Deactivating SAML` subsection added at end of Installation; 14-line diff (well under 35); 2 occurrences of `edition-deactivation.md`; `destructive` and `Deactivating SAML` headings present |
| `backend/pyproject.toml` (lifecycle marker) | Marker registered with verbatim string; addopts unchanged | VERIFIED | Line 75 contains `"lifecycle: edition deactivation/reactivation tests requiring enterprise overlay (Phase 220 LIFECYCLE-04)",`; addopts still `-m 'not perf'`; no `not lifecycle` deselection |
| `backend/tests/test_lifecycle.py` | Single async test exercising registry-clear simulation | VERIFIED (static) | 233 lines; all 13 grep assertions pass (@pytest.mark.lifecycle, saml_overlay_registered, _extensions.clear(), _routers.clear(), init_edition([]), undefer_group, all 4 Default*Extension classes, auth_provider == 'oauth' assertion, no alembic downgrade, no _outstanding_requests, no replay_cache); pytest collection succeeds (1 item); schema-correct seed against User(username, password_hash, nullable email) per actual model |
| `.github/workflows/ci.yml` | Cross-repo checkout + overlay install + fork-PR gating + conditional pytest | VERIFIED | All 8 CI greps pass: `repository: ishiland/geolens-enterprise`, `GEOLENS_ENTERPRISE_TOKEN` ×3, `secrets.GEOLENS_ENTERPRISE_TOKEN != ''`, `uv add --editable ../geolens-enterprise`, `OVERLAY_INSTALLED` ×3, both pytest invocations (`not perf` AND `not perf and not lifecycle`); YAML parses cleanly (verified in venv with pyyaml); diff scope ≤60 lines |
| `.planning/REQUIREMENTS.md` (LIFECYCLE-04 wording) | Says `oauth_providers`, not `User` | VERIFIED | Literal `the 4 \`deferred=True\` SAML columns on \`oauth_providers\`` present; legacy `SAML columns on \`User\`` absent |
| `.planning/ROADMAP.md` (Phase 220 SC#4 wording) | Says `oauth_providers` columns, not `User` columns | VERIFIED | Literal `4 \`deferred=True\` \`oauth_providers\` columns` present; legacy `4 \`deferred=True\` User columns` absent |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `docs/edition-deactivation.md` | `docs/edition-reactivation.md` | markdown link | WIRED | Line 11 (at-a-glance table) + line 142 + line 185 reference reactivation runbook; `[`docs/edition-reactivation.md`](edition-reactivation.md)` |
| `docs/edition-deactivation.md` | `docs/saml.md` | markdown link (IdP-side cleanup) | WIRED | Line 186 reference; `[`docs/saml.md`](saml.md)` resolves with `(saml.md)` literal |
| `docs/edition-reactivation.md` | `docs/edition-deactivation.md` | markdown link (inverse) | WIRED | Line 5 + line 74 reference deactivation runbook |
| `docs/edition-reactivation.md` | `docs/saml.md` | markdown link (activation reference) | WIRED | Line 3 + line 20 + line 75 reference saml.md Installation section |
| `docs/saml.md` | `docs/edition-deactivation.md` | markdown link in retargeted bullet + new subsection | WIRED | 2 occurrences of `edition-deactivation.md` (one in line-48 callout, one in `### Deactivating SAML` subsection) |
| `backend/tests/test_lifecycle.py` | `backend/tests/conftest.py` | `saml_overlay_registered` fixture | WIRED | Test parameter `saml_overlay_registered` matches conftest.py fixture (lines 454-484); pytest collection confirms fixture resolves |
| `backend/tests/test_lifecycle.py` | `app.platform.extensions` | imports `_extensions`, `_routers`, accessors, defaults | WIRED | Lines 44-57 import the registry symbols and Default* classes; pytest collection succeeds |
| `backend/tests/test_lifecycle.py` | `app.core.edition` | `init_edition([])` flips `is_enterprise()` | WIRED | Line 40 imports `app.core.edition as edition_mod`; lines 129/179 call `init_edition(["enterprise"])` and `init_edition([])` |
| `.github/workflows/ci.yml backend-test` | `geolens-enterprise` repository | `actions/checkout@v4` with repository + token + path | WIRED | Lines 241-247 inject the second checkout gated by `secrets.GEOLENS_ENTERPRISE_TOKEN != ''` |
| `.github/workflows/ci.yml backend-test` | `backend/tests/test_lifecycle.py` | conditional pytest invocation | WIRED | Lines 322-330: when overlay installed, pytest runs with `-m 'not perf'` (lifecycle included); else `-m 'not perf and not lifecycle'` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Lifecycle pytest collects cleanly | `cd backend && uv run pytest --collect-only tests/test_lifecycle.py -m lifecycle` | `1 test collected in 0.03s` (`test_overlay_removal_preserves_saml_data`) | PASS |
| YAML workflow parses cleanly | `python3 -m venv … && pip install pyyaml && python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` | No exception, exits 0 | PASS |
| Pytest marker registered (--markers list) | Implicit via collection succeeding (collection runs marker validation when `-m lifecycle` used) | Test resolves to lifecycle-marked function | PASS |
| End-to-end test execution | `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` against live test DB | SKIP — requires Docker stack + geolens-enterprise install | SKIP (routed to human verification) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| LIFECYCLE-01 | Plan 01 | Operator deactivation runbook walks through enterprise→community downgrade end-to-end | SATISFIED | `docs/edition-deactivation.md` shipped; 12 doc-grep assertions pass; covers pre-flight, env switch, SAML inventory, sequence, data-fate matrix |
| LIFECYCLE-02 | Plan 02 | Operator reactivation runbook confirms `deferred=True` SAML columns + `oauth_providers` rows survive | SATISFIED | `docs/edition-reactivation.md` shipped; 5 doc-grep assertions pass; 5-step verification checklist with `information_schema.columns` and `count(*)` SQL |
| LIFECYCLE-03 | Plan 03 | `docs/saml.md` cross-links to runbook; flags alembic destructive | SATISFIED | Surgical 14-line edit; legacy framing absent; cross-link present (×2); `Deactivating SAML` subsection added; `destructive` label present |
| LIFECYCLE-04 | Plans 04, 05, 06 | Integration test in CI exercises deactivate path; asserts SAML rows + 4 deferred `oauth_providers` columns intact | SATISFIED (static) — runtime NEEDS HUMAN | Marker registered; test authored to D-04 spec; collects cleanly; CI wired to execute on push-to-main once GEOLENS_ENTERPRISE_TOKEN secret added; schema-correct seed verified against actual User model. Runtime end-to-end pass requires Docker + overlay → routed to human verification. |
| LIFECYCLE-05 | Plan 01 | Either non-destructive alembic path OR runbook documents destructive path with mandatory data-export step | SATISFIED | Plan elected the documentation route per D-02; `### Mandatory pre-step: pg_dump snapshot` section present in `docs/edition-deactivation.md`; `mandatory and required` literal present |

**No orphaned requirements.** All 5 phase-220 requirement IDs (LIFECYCLE-01..05) are claimed by plans 01-06, accounted for, and have implementation evidence.

LIFECYCLE-06 and LIFECYCLE-07 are explicitly mapped to Phase 221 in REQUIREMENTS.md traceability table — those are NOT in this phase's scope and are not gaps for Phase 220.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none detected) | — | — | — | Scanned `docs/edition-deactivation.md`, `docs/edition-reactivation.md`, `backend/tests/test_lifecycle.py`, `.github/workflows/ci.yml` for TODO/FIXME/PLACEHOLDER/emoji — clean. The runbook contains a forward-looking note about Phase 221 ("Phase 221 ships the user re-onboarding procedure...") which is informational, NOT a stub — Phase 221 is the next milestone phase covering LIFECYCLE-06. |

### Human Verification Required

#### 1. End-to-end lifecycle test execution

**Test:** Run `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` against a live test database with the `geolens-enterprise` overlay installed (editable install via `uv add --editable ~/Code/geolens-enterprise`).
**Expected:** `test_overlay_removal_preserves_saml_data PASSED` in <5s. The test seeds an OAuthProvider (provider_type='saml', all 4 deferred SAML columns populated), an OAuthAccount linkage row, and a User with auth_provider='oauth'; clears `_extensions` + `_routers` + `init_edition([])`; asserts the rows + columns survive and the typed accessors return Default* classes.
**Why human:** Requires Docker stack (PostgreSQL with PostGIS + pgvector) and an editable install of `geolens-enterprise` private repo. The verifier sandbox cannot run those services. The test is correctly authored (13 static grep assertions + clean pytest collection confirm the contract).

#### 2. Add GEOLENS_ENTERPRISE_TOKEN repo secret + observe CI

**Test:** Add `GEOLENS_ENTERPRISE_TOKEN` (fine-grained PAT with `Contents: Read` on `ishiland/geolens-enterprise`) as a GitHub Actions repository secret; push a commit to a branch with this Phase 220 work; observe the `Backend Tests` job log.
**Expected:** Log line "Running pytest with lifecycle marker INCLUDED (overlay installed)" appears; lifecycle test passes in CI; coverage stays ≥58.5%.
**Why human:** Repository secret creation is an out-of-band action requiring repo-owner GitHub access. Without the secret, CI runs with `-m 'not perf and not lifecycle'` and the lifecycle test is silently skipped — that is the safe-by-design fallback per Plan 06 D-06, but it means the runtime guarantee for LIFECYCLE-04 only materializes after the secret is configured.

### Gaps Summary

No gaps found in the codebase. All 5 must-haves verified statically. All 6 plans shipped their specified artifacts; all 23 doc-content greps from VALIDATION.md pass; all 8 CI integration greps pass; all 13 lifecycle-test greps pass; pytest collects 1 item cleanly. The single remaining item — runtime end-to-end execution of the lifecycle test — is intentional and architectural: the test exercises an enterprise overlay that lives in a separate private repo, so its execution is wired to CI (Plan 06) rather than the verifier sandbox. This is the standard split for the open-core boundary established in v13.1; it is not a phase-220 gap.

---

*Verified: 2026-04-29*
*Verifier: Claude (gsd-verifier)*
