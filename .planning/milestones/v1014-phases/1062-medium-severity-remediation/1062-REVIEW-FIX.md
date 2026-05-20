---
phase: 1062
fixed_at: 2026-05-20T21:28:09Z
review_path: .planning/phases/1062-medium-severity-remediation/1062-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 1062: Code Review Fix Report

**Fixed at:** 2026-05-20T21:28:09Z
**Source review:** .planning/phases/1062-medium-severity-remediation/1062-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (4 Critical + 5 Warning)
- Fixed: 9
- Skipped: 0
- Info findings: 3 (deferred to pending todos per scope)

## Fixed Issues

### CR-01: Atomic change_password — single-transaction revocation

**Files modified:** `backend/app/modules/auth/service.py`, `backend/app/modules/auth/router.py`, `backend/tests/test_jwt_revocation.py`
**Commit:** 35960cb7
**Applied fix:** Added `commit: bool = True` keyword parameter to `revoke_all_tokens`. The `change_password` route now calls `revoke_all_tokens(current_user.id, commit=False)` so the password hash mutation, token revocation (refresh tokens + token_version bump), and audit row all land in one `await db.commit()`. Previously revoke_all_tokens committed internally, leaving the audit row in a separate implicit transaction. Added `test_change_password_new_password_usable_after_change` regression test that asserts the new password is always persisted when change-password returns 204.

**Note:** The reviewer's description of the lockout risk was accurate in spirit (two-transaction ordering), but the password hash was already in the first commit (set before calling revoke_all_tokens). The true gap was the audit row. The fix makes the invariant explicit and fully atomic regardless.

---

### CR-02: SAML-to-local conversion bumps token_version

**Files modified:** `backend/app/modules/admin/service.py`, `backend/tests/test_lifecycle.py`
**Commit:** a632ae95
**Applied fix:** Added `update` and `RefreshToken` to admin/service.py imports. Added two new steps to `convert_saml_user_to_local` after the auth_provider flip: (7) bump `User.token_version` via an UPDATE so any outstanding SAML access JWT is rejected on the next request; (8) revoke all active refresh tokens belt-and-suspenders. Added `test_convert_saml_user_invalidates_prior_jwt` lifecycle test that mints a service-level JWT for the SAML user before conversion and asserts it returns 401 afterward.

---

### CR-03: `_update_sync_cache` warms semantic/basemap rate limits

**Files modified:** `backend/app/core/persistent_config.py`, `backend/tests/test_cache.py`
**Commit:** f9b00834
**Applied fix:** Extended the `if self.key in (...)` allowlist in `_update_sync_cache` to include `"semantic_search_rate_limit"` and `"basemap_proxy_rate_limit"`. Without this, DB-overridden values were never written to `_sync_rate_limit_cache` and `get_cached_*_rate_limit()` always returned the compile-time defaults. Added three regression tests: direct cache readthrough for each key, plus a source-level structural guard that checks both keys appear in the method source.

**Test result:** 3/3 unit tests pass without DB dependency.

---

### CR-04: EmbedToken CSP query includes `expires_at IS NULL`

**Files modified:** `backend/app/modules/catalog/maps/service_public.py`, `backend/tests/test_embed_framing_csp.py`
**Commit:** 213f4f93
**Applied fix:** Replaced `EmbedToken.expires_at > func.now()` with `or_(EmbedToken.expires_at.is_(None), EmbedToken.expires_at > func.now())`. The `or_` import was already present. Added `_create_non_expiring_embed_token` helper and `test_shared_map_with_non_expiring_embed_token_uses_allowed_origins` regression test covering the community-edition default (non-expiring token with `expires_at=None`).

---

### WR-01: Document excluded expression types in ALLOWED_EXPRESSIONS

**Files modified:** `backend/app/processing/export/where_validator.py`
**Commit:** 94af1f26
**Applied fix:** Added explicit guard comments next to `exp.Neg` and where `exp.Dot` would go, explaining why binary arithmetic operators (exp.Add/Sub/Mul/Div) are intentionally excluded (injection risk), and why table-qualified column references (exp.Dot) are excluded (single unqualified column names only). The comments prevent future maintainers from adding `exp.Add` by analogy with `exp.Neg`.

---

### WR-02: Remove embedding rate limit from `/search/facets/`

**Files modified:** `backend/app/modules/catalog/search/router.py`
**Commit:** 4837ee22
**Applied fix:** Removed `@limiter.limit(_semantic_search_rate_limit)` decorator from `search_facets_endpoint`. The endpoint performs pure SQL aggregation and never invokes the embedding model. The 30/min cap (SEC-S11) was silently throttling SPA users who refresh the search UI normally. The rate limit remains on `/search/datasets/` and `/datasets/{id}/related/` where embedding calls actually happen. Added explanatory comment.

---

### WR-03: Add policy description to `ChangePasswordRequest.new_password`

**Files modified:** `backend/app/modules/auth/schemas.py`
**Commit:** 15108671
**Applied fix:** Added `description=` to `new_password`'s `Field(...)` explaining that the schema floor is `min_length=8` but the runtime policy enforces min 12 chars and 3+ character classes (SEC-S16). Also added a comment explaining the intentional floor vs. policy split so future maintainers do not raise the schema min to 12 and accidentally break the OpenAPI floor semantics.

---

### WR-04: Explicit None check for token_version in `create_access_token`

**Files modified:** `backend/app/modules/auth/service.py`
**Commit:** d5e52a2a
**Applied fix:** Replaced `result.scalar_one_or_none() or 1` with `_raw_version if _raw_version is not None else 1`. The `or 1` form coerced a DB value of 0 to 1 (0 is falsy). In normal operation token_version starts at 1 (migration server_default), so 0 is unreachable — but explicit intent is clearer and guards against unexpected DB state without altering behavior.

---

### WR-05: Widen nginx `/m/` regex to include bare `/m/` path

**Files modified:** `frontend/nginx.conf`
**Commit:** 5d8b7c9a
**Applied fix:** Changed `location ~ ^/m/.+` to `location ~ ^/m/` so the bare `/m/` path (no suffix) also matches the embed-framing block that omits `X-Frame-Options`. Previously, `/m/` fell through to `location /`, which inherited `X-Frame-Options: SAMEORIGIN` from the server scope — inconsistent with `/m/<token>` where XFO is intentionally absent. Added documentation comments explaining why the server-scope SAMEORIGIN on `location /` is intentional (SPA routes not designed for framing) while `/m/*` paths omit XFO.

---

## Skipped Issues

None — all 9 in-scope findings were applied.

## Deferred (Info — out of scope per gates)

| ID | Title | Reason |
|---|---|---|
| IN-01 | `.env.example` missing PASSWORD_MIN_LENGTH/PASSWORD_REQUIRE_CLASSES | Deferred to pending todos |
| IN-02 | `validate_password_complexity` whitespace as symbol — error message | Deferred to pending todos |
| IN-03 | `where_validator.py` no test for exp.Dot bypass path | Deferred to pending todos |

## Pytest Summary

- **Pure unit tests (no DB):** 64 passed, 3 skipped (test_export_where_validator.py + test_cache.py)
- **CR-03 regression tests:** 3/3 passed
- **DB-dependent integration tests:** DB setup failing in local environment (pre-existing: same error reproduces against unchanged main branch). Tests are syntactically valid and collected correctly.

---

_Fixed: 2026-05-20T21:28:09Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
