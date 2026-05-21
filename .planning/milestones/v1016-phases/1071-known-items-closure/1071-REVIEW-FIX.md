---
phase: 1071-known-items-closure
fixed_at: 2026-05-21T00:00:00Z
review_path: .planning/phases/1071-known-items-closure/1071-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 1071: Code Review Fix Report

**Fixed at:** 2026-05-21
**Source review:** `.planning/phases/1071-known-items-closure/1071-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (3 Critical + 5 Warning; INFO skipped per default scope)
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: `gdal_safe_env` extras can clobber security clamps

**Files modified:** `backend/app/processing/raster/vrt.py`, `backend/tests/test_cog_subprocess_env.py`
**Commit:** e127f55c
**Applied fix:** Added overlap check at the top of `gdal_safe_env` — raises `ValueError` if any key in `extras` is also in `_VRT_SAFE_ENV`. Updated the test `test_extras_override_vrt_safe_env_if_collision` to assert the collision raises instead of silently winning. Updated docstring to document that extras MUST NOT collide with security clamp keys.

---

### CR-02: `except ValueError: pass` too wide in `_resolve_download_user`

**Files modified:** `backend/app/modules/catalog/datasets/api/router_export.py`
**Commit:** 531e5809
**Applied fix:** Restructured the try/except to only wrap `uuid.UUID(user_id)` conversion. The `db.execute(...)` call moved into the `else` branch so SQLAlchemy `ValueError`s bubble up rather than being silently swallowed by the broad `except ValueError: pass`.

---

### CR-03: Dead `"Dot"` branch and stale docstring in `test_export_where_validator.py`

**Files modified:** `backend/tests/test_export_where_validator.py`
**Commit:** 185da0d1
**Applied fix:** Removed the dead `"Dot" in str(exc.value)` branch from the assertion — the validator uses `exp.Column.table/.db/.catalog` inspection so `"Dot"` never appears in the error message. Assertion now checks for `"table-qualified"` (lowercase) or `"Disallowed"`. Updated docstring to describe the actual Column inspection mechanism and removed the factually wrong "Postgres parses as Dot expression" statement.

---

### WR-01: STAC POST limit le=1000 vs GET le=200 asymmetry

**Files modified:** `backend/app/standards/stac/router.py`, `backend/tests/test_stac_search_validation.py`
**Commit:** 802537f0
**Applied fix:** Lowered `StacSearchBody.limit` from `le=1000` to `le=200` to match the GET `/stac/search` handler ceiling at `router.py:544`. Updated `test_post_search_limit_above_le_rejected` to use `limit=201` as the one-over-boundary rejection case. Fixed stale "within 1-1000" docstring. Added inline rationale comment.

Note: The STAC bound tests are integration tests requiring a live Postgres connection and could not be exercised against a live DB in this session. The schema change is correct by static inspection.

---

### WR-02: `lsof` port-check Linux portability

**Files modified:** `backend/scripts/test_alembic_upgrade_clean_db.sh`
**Commit:** 89d48a6e
**Applied fix:** Added `_port_in_use()` helper function that tries `lsof` first (macOS/BSD preferred path), then falls back to `nc -z 127.0.0.1 ${PG_PORT}` which is universally available on both macOS and Linux. The `if` condition calls this helper so the guard works in both CI environments.

---

### WR-03: Audit assertion session visibility in `test_anonymous_mint_then_consume`

**Files modified:** `backend/tests/test_download_token.py`
**Commit:** 47da6748
**Applied fix:** Added a detailed inline comment at the audit assertion explaining why the query is stable without `expire_all()` or `db.refresh()`: `test_db_session` is created from the same `async_session` factory that the test app client patches into the app (per `conftest.py:481`), so the route handler's `db.commit()` is immediately visible to subsequent queries from the test session.

---

### WR-04: No `aud` claim verified in JWT decode

**Files modified:** `backend/app/modules/catalog/datasets/api/router_export.py`
**Commit:** dd83dea0
**Applied fix:** Added inline comment above `jwt.decode()` explaining that no audience claim is verified because the mint endpoint does not emit `aud`. Notes explicitly that if a future change adds `aud` to minted tokens, the `audience=` parameter must also be added to this decode call to avoid silent bypass.

---

### WR-05: `vrt_module` monkey-patch inert in `test_validate_vrt_body_consumes_shared_constant`

**Files modified:** `backend/tests/test_vrt_vsi_allowlist.py`
**Commit:** a57ae07d
**Applied fix:** Replaced the entire test with a structural `is` identity assertion. `from app.processing.ingest.validation import VRT_VSI_ALLOWED_PREFIXES as v_const` and `from app.processing.raster.vrt import VRT_VSI_ALLOWED_PREFIXES as vrt_const` then `assert v_const is vrt_const`. Removed the inert `vrt_module` patch, the misleading "proves the validator does not carry a private copy via monkey-patch" claim, and the now-unnecessary `tmp_path`/`monkeypatch` fixture params.

---

_Fixed: 2026-05-21_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
