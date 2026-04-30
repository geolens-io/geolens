---
phase: 221-lifecycle-user-continuity-and-verification
verified: 2026-04-30T16:00:00Z
status: passed
score: 3/3 must-haves verified
overrides_applied: 0
---

# Phase 221: lifecycle-user-continuity-and-verification Verification Report

**Phase Goal:** Existing SAML-authenticated users have a safe, documented re-onboarding path when their edition is deactivated, and a CI test confirms the full deactivate→reactivate round-trip is lossless.

**Verified:** 2026-04-30T16:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|---|---|---|
| SC#1 | An admin can convert a SAML-authenticated user's account to local-password via a documented procedure without losing audit history, group memberships, or dataset ownership | VERIFIED | Endpoint `/admin/users/{user_id}/convert-saml-to-local/` registered (router.py:254). LIFECYCLE-06 test asserts audit_log preservation (test_lifecycle.py:543-554), user_roles preservation (test_lifecycle.py:533-541), and Record.created_by + Dataset.record_id chain preservation (test_lifecycle.py:579-600). Documentation procedure present at docs/edition-deactivation.md:142+ |
| SC#2 | `docs/edition-deactivation.md` includes a "Handling existing SAML users" section describing the re-onboarding procedure | VERIFIED | Section heading at docs/edition-deactivation.md:142. TODO blockquote ("Phase 221 ships the user re-onboarding") REMOVED. Curl uses trailing slash `/convert-saml-to-local/` (line 186) and `/auth/login/` (lines 175, 210). No `/auth/token` references. |
| SC#3 | A CI test (`pytest -m lifecycle`) exercises the deactivate→reactivate round-trip and asserts User identities, `oauth_providers` rows, and audit trail entries are intact | VERIFIED | `test_deactivate_reactivate_roundtrip_preserves_saml_data` exists (test_lifecycle.py:608). Asserts seeded `test.seed.lifecycle` audit_log row survives (lines 786-799). 4 deferred SAML columns asserted via `undefer_group("saml")` (lines 749-760). User row + OAuthAccount linkage assertions present. **`pytest -x -q -m lifecycle tests/test_lifecycle.py` → 3 passed in 4.38s.** |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `backend/app/modules/admin/schemas.py::SamlToLocalConversion` | Pydantic schema with `password: str = Field(min_length=8, max_length=256)` | VERIFIED | Class at line 83; password Field at line 93 with min_length=8, max_length=256. No imports needed. |
| `backend/app/modules/admin/service.py::AdminService.convert_saml_user_to_local` | Service method: load → validate → mutate → flush → return `(User, str)` | VERIFIED | Method at line 175. 6-step flow per D-01 implemented. Imports `OAuthAccount, OAuthProvider` from `app.modules.auth.oauth.models`. No `db.commit()` or `log_action` calls inside service (verified). |
| `backend/app/modules/admin/router.py::convert_saml_to_local` | POST route at `/users/{user_id}/convert-saml-to-local/` (trailing slash) with self-conversion guard, ValueError → 404/422 mapping, audit log write | VERIFIED | Route at line 254 with trailing slash. Self-guard at lines 279-283 with exact wording "Cannot convert your own account; use a different admin account". Audit action `auth.convert_saml_to_local` at line 307. Allow-listed details `{"from": "saml", "to": "local", "provider_slug": ...}` at line 310. |
| `backend/tests/test_lifecycle.py::test_convert_saml_user_to_local_preserves_user_data` | Integration test exercising endpoint via TestClient with audit_log + user_roles + ownership preservation | VERIFIED | Function at line 332. 10 invariants asserted including audit_log seeding (line 425-432), user_roles seeding (line 419-421), Record + Dataset seeding (line 444-468), allow-list verification (line 573-577). |
| `backend/tests/test_lifecycle.py::test_deactivate_reactivate_roundtrip_preserves_saml_data` | Round-trip test using Pattern 3 Shape A; SEEDED audit_log row asserted | VERIFIED | Function at line 608. Pattern 3 Shape A reactivation at lines 723-730. Seeded audit_log assertion at lines 786-799. 4 deferred SAML columns + OAuthAccount + User row all asserted. |
| `docs/edition-deactivation.md` "Handling existing SAML users" section | New section replacing line-81 TODO; trailing-slash curl; OIDC appendix | VERIFIED | Section at line 142. TODO removed. Curl at line 186 uses trailing slash. OIDC appendix present. Self-conversion blocked callout present. |
| `docs/edition-reactivation.md` "Note on previously converted SAML users" section | One-paragraph forward-pointer | VERIFIED | Section at line 68. References `edition-deactivation` and `deferred` roadmap. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `router.py::convert_saml_to_local` | `service.py::AdminService.convert_saml_user_to_local` | Service method call before `log_action` and `db.commit()` | WIRED | Line 287: `await service.convert_saml_user_to_local(user_id, body.password)` |
| `service.py::convert_saml_user_to_local` | `local.py::hash_password` | `user.password_hash = hash_password(password)` before flipping `auth_provider` | WIRED | Line 231: `user.password_hash = hash_password(password)` |
| `router.py::convert_saml_to_local` | `audit/service.py::log_action` | log_action call AFTER service returns, BEFORE db.commit() | WIRED | Lines 304-312: log_action with action=`auth.convert_saml_to_local`, allow-listed details, then `await db.commit()` at line 313 |
| `test_lifecycle.py::test_convert_saml_user_to_local_preserves_user_data` | `POST /admin/users/{user_id}/convert-saml-to-local/` | `client.post(...)` with `headers=admin_auth_header` | WIRED | Lines 473-477 |
| `test_lifecycle.py::round_trip_test` | `_extensions / _routers / edition_mod._info` | Three explicit clear+repopulate operations | WIRED | Deactivate (lines 705-707): `_extensions.clear(); _routers.clear(); init_edition([])`. Reactivate (lines 727-730): `_extensions["auth"]=ext; _extensions["identity"]=ext; _routers.append(saml_router); init_edition(["enterprise"])` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| All 3 lifecycle tests pass | `cd backend && uv run pytest -x -q -m lifecycle tests/test_lifecycle.py` | `3 passed, 16 warnings in 4.38s` | PASS |
| Ruff lint clean across backend | `cd backend && uv run ruff check .` | `All checks passed!` | PASS |
| Endpoint registered on FastAPI router | (planner verified during plan execution per 221-01-SUMMARY.md) | route `/admin/users/{user_id}/convert-saml-to-local/` registered | PASS |
| `## Handling existing SAML users` section exists | `grep "## Handling existing SAML users" docs/edition-deactivation.md` | line 142 match | PASS |
| TODO blockquote removed | `grep "Phase 221 ships the user re-onboarding" docs/edition-deactivation.md` | no match | PASS |
| Curl uses trailing slash | `grep "convert-saml-to-local/" docs/edition-deactivation.md` | line 186 match | PASS |
| Token endpoint correct | `grep "/auth/login/" docs/edition-deactivation.md` | lines 175, 210 match | PASS |
| No wrong token endpoint | `grep "/auth/token" docs/edition-deactivation.md` | no match | PASS |
| Round-trip test exists | `grep test_deactivate_reactivate_roundtrip_preserves_saml_data tests/test_lifecycle.py` | line 608 match | PASS |
| Conversion test exists | `grep test_convert_saml_user_to_local_preserves_user_data tests/test_lifecycle.py` | line 332 match | PASS |

### Pitfall Verification

| Pitfall | Check | Status |
|---|---|---|
| Pitfall 4 (trailing slash on URL) | Route in router.py uses trailing slash; curl examples in docs use trailing slash | PASS |
| Pitfall 5 (deferred enterprise imports) | `from geolens_enterprise` only at lines 723-724 inside test body, NOT module-level | PASS — verified by `grep -n "from geolens_enterprise" tests/test_lifecycle.py` showing only matches inside test body |
| Pitfall 7 (no `not lifecycle` in addopts) | `pyproject.toml` addopts is `-m 'not perf'` (no `not lifecycle`) | PASS |
| T-221-03 (no password in audit details) | `grep -E -i 'details=.*password|password.*details' router.py` returns empty | PASS |
| T-221-01 (self-conversion guard) | `current_user.id == user_id` → 422 with exact wording | PASS — line 279-283 |
| Pitfall 2 (no register_extensions in tests) | `grep register_extensions tests/test_lifecycle.py` returns empty | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| LIFECYCLE-06 | 221-01, 221-02, 221-03 | SAML re-onboarding path with audit/groups/ownership preservation | SATISFIED | Endpoint shipped + runbook section + LIFECYCLE-06 test passes; REQUIREMENTS.md line 31 marked `[x]` complete |
| LIFECYCLE-07 | 221-03 | Round-trip symmetry test in CI | SATISFIED | `test_deactivate_reactivate_roundtrip_preserves_saml_data` runs in CI under `pytest -m lifecycle`; REQUIREMENTS.md line 37 marked `[x]` complete |

### Anti-Patterns Found

None.

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| (none) | — | TODO/FIXME/PLACEHOLDER scan returned no matches in any modified file | — | — |

### Human Verification Required

None for automated verification of the phase goal. The Manual-Only verifications listed in 221-VALIDATION.md (operator-end-to-end runbook walkthrough; audit-tooling UX; GitHub markdown anchor rendering) are out-of-scope concerns explicitly flagged as not blocking phase completion. They surface in milestone-level UAT, not phase-level verification.

### Gaps Summary

No gaps. All three roadmap Success Criteria are satisfied with substantive, wired, data-flowing implementations:

- **SC#1 (procedure):** Endpoint exists, is reachable, validates inputs, performs the documented 6-step transaction, writes the audit log with allow-listed details, and is exercised by an integration test that asserts every preservation invariant the runbook promises.
- **SC#2 (docs):** New "Handling existing SAML users" section is in place; Phase 220's TODO blockquote is gone; all pitfall mitigations (trailing slash, correct token endpoint, ordering note, self-conversion warning, password-not-in-audit) are documented exactly as the code implements them.
- **SC#3 (round-trip test):** Test runs under `pytest -m lifecycle` in 4.38s. Asserts the seeded `audit_log` row survives the cycle (D-10 contract). Asserts the 4 deferred SAML columns retain their values via `undefer_group("saml")`. Asserts User identity, OAuthAccount linkage, and `is_enterprise()` toggle symmetry.

The lifecycle test suite is green. Ruff is clean. No regressions in existing admin tests (per 221-01-SUMMARY.md: `tests/test_admin_user_operations.py` 9 passed).

---

*Verified: 2026-04-30T16:00:00Z*
*Verifier: Claude (gsd-verifier)*
