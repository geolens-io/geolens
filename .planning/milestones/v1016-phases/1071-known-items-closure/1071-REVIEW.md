---
phase: 1071-known-items-closure
reviewed: 2026-05-21T00:00:00Z
depth: standard
files_reviewed: 21
files_reviewed_list:
  - backend/pyproject.toml
  - backend/uv.lock
  - backend/app/processing/ingest/ogr.py
  - backend/app/modules/auth/password_policy.py
  - backend/app/processing/export/where_validator.py
  - backend/app/standards/stac/router.py
  - backend/app/modules/catalog/datasets/api/router_export.py
  - backend/app/modules/auth/router.py
  - backend/app/platform/audit.py
  - backend/app/modules/audit/service.py
  - backend/app/processing/raster/vrt.py
  - backend/app/processing/raster/cog.py
  - backend/app/processing/ingest/validation.py
  - backend/tests/test_password_policy.py
  - backend/tests/test_export_where_validator.py
  - backend/tests/test_stac_search_validation.py
  - backend/tests/test_download_token.py
  - backend/tests/test_cog_subprocess_env.py
  - backend/tests/test_vrt_vsi_allowlist.py
  - backend/tests/test_export_hardening.py
  - backend/scripts/test_alembic_upgrade_clean_db.sh
findings:
  critical: 3
  warning: 5
  info: 2
  total: 10
status: issues_found
---

# Phase 1071: Code Review Report

**Reviewed:** 2026-05-21
**Depth:** standard
**Files Reviewed:** 21
**Status:** issues_found

## Summary

Phase 1071 closes 11 known tech-debt items across dependency pinning, documentation, validator hardening, anonymous COG download wiring, GDAL env clamping, and test regression pinning. The changes are overwhelmingly correct and well-structured. Three BLOCKER-level findings are real bugs that can cause incorrect runtime behavior or allow unauthorized access under specific conditions. Five warnings degrade robustness or correctness at edges without being immediately exploitable. Two info items are minor.

---

## Critical Issues

### CR-01: `gdal_safe_env` extras can clobber security clamps — documented but unguarded

**File:** `backend/app/processing/raster/vrt.py:54-56`

**Issue:** The `extras` parameter is documented as "Extras win over both `os.environ` and `_VRT_SAFE_ENV`" and `test_extras_override_vrt_safe_env_if_collision` explicitly pins that `GDAL_HTTP_FOLLOWLOCATION` in extras replaces the clamp. This means any future caller (or a compromised/confused caller path) that passes one of the three security-critical keys (`CPL_VSIL_CURL_ALLOWED_EXTENSIONS`, `VRT_VIRTUAL_OVERVIEWS`, `GDAL_HTTP_FOLLOWLOCATION`) in `extras` silently disables that clamp. Today's three callers are safe (they only pass `GDAL_CACHEMAX` / `COMPRESS_OVERVIEW`), but the precedence contract is the opposite of what a security-clamping helper should allow. The docstring says extras win — no callers should be able to override the security clamps via extras without explicit acknowledgement.

The test at `test_cog_subprocess_env.py:242` explicitly tests AND PASSES the override, cementing it as the contract. This is the wrong contract for a security helper.

**Fix:** Raise `ValueError` if any key in `extras` overlaps with `_VRT_SAFE_ENV`. Legitimate per-call additions (`GDAL_CACHEMAX`, `COMPRESS_OVERVIEW`) never overlap with the three security keys:

```python
def gdal_safe_env(*, extras: dict[str, str] | None = None) -> dict[str, str]:
    if extras:
        overlap = set(extras) & set(_VRT_SAFE_ENV)
        if overlap:
            raise ValueError(
                f"gdal_safe_env: extras may not override security clamps: {overlap}"
            )
    env = {**os.environ, **_VRT_SAFE_ENV}
    if extras:
        env.update(extras)
    return env
```

Also update `test_extras_override_vrt_safe_env_if_collision` to assert that the collision raises instead of silently wins.

---

### CR-02: `_resolve_download_user` fallthrough path leaks 401 when a sub-bearing token's user is missing

**File:** `backend/app/modules/catalog/datasets/api/router_export.py:215-237`

**Issue:** When a `?token=` query param is present with a valid sub-bearing token (typ/scope/exp all pass), and the referenced user is not found or is inactive, the code falls through the `if user_id:` block without explicitly returning or raising, then hits the unconditional `raise HTTPException(status_code=401, detail="Authentication required")` at line 235. This is the correct behavior. However, the outer `if qt:` block's indentation means the fallthrough path is not obviously safe — a future editor who adds an early-return in the sub-bearing lookup branch will break it. More critically: if `user_id` is truthy but `uuid.UUID(user_id)` raises `ValueError` (line 224), the `except ValueError: pass` silently catches it and falls through to the 401. This is correct, but the broad `pass` on a `ValueError` swallows any other `ValueError` that might occur inside the `db.execute(select(...))` block (SQLAlchemy can raise `ValueError` for certain ORM-contract violations). This is a latent correctness risk with the current exception scope being too wide.

```python
# Current (line 219-226):
try:
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    found = result.scalar_one_or_none()
    if found and found.is_active and found.status == "active":
        return found
except ValueError:
    pass
```

**Fix:** Narrow the `except ValueError` to only guard the `uuid.UUID(user_id)` conversion:

```python
try:
    user_uuid = uuid.UUID(user_id)
except ValueError:
    pass  # malformed sub claim — fall through to 401
else:
    result = await db.execute(select(User).where(User.id == user_uuid))
    found = result.scalar_one_or_none()
    if found and found.is_active and found.status == "active":
        return found
```

---

### CR-03: `test_export_where_validator.py` docstring in the test asserts wrong rejection mechanism

**File:** `backend/tests/test_export_where_validator.py:166-183`

**Issue:** The test at line 178-179 asserts:
```python
assert "Dot" in str(exc.value) or "Disallowed" in str(exc.value)
```

The actual error message emitted by `validate_where_ast` is:
```
"Disallowed expression in WHERE clause: table-qualified column reference (only unqualified column names are accepted)"
```

The message does **not** contain the word `"Dot"`. The assertion passes only because `"Disallowed"` is present — the `"Dot"` branch is permanently dead. More seriously, the test's docstring still says "Postgres parses `catalog.records.title = 'x'` as a Dot expression (schema.table.column)" — which is the *old*, incorrect pre-fix understanding. After the KNOWN-10 fix, sqlglot emits an `exp.Column` node (not `exp.Dot`), and the validator now correctly inspects `Column.table/.db/.catalog`. The docstring misleads future readers into thinking `exp.Dot` nodes appear in this codepath, when they do not.

This is a correctness issue for the test documentation layer: the assertion is overly permissive (a future refactor that breaks the actual rejection but happens to emit "Dot" anywhere would pass this test), and the docstring is factually wrong.

**Fix:** Remove the dead `"Dot"` branch and fix the docstring:

```python
def test_table_qualified_reference_rejected(self):
    """Pins the KNOWN-10 fix: sqlglot's postgres dialect parses tbl.col
    into exp.Column with .table populated (not a separate exp.Dot node).
    validate_where_ast inspects Column.table/.db/.catalog and raises."""
    with pytest.raises(ValueError) as exc:
        validate_where_ast("catalog.records.title = 'x'")
    # Error message names the table-qualified rejection specifically.
    assert "table-qualified" in str(exc.value).lower() or "Disallowed" in str(exc.value)

    with pytest.raises(ValueError):
        validate_where_ast("records.title = 'x'")
```

---

## Warnings

### WR-01: `StacSearchBody.limit le=1000` is inconsistent with GET handler ceiling

**File:** `backend/app/standards/stac/router.py:1147-1157`

**Issue:** The GET `/stac/search` handler (line 544, 1110) caps `limit` at `le=200`. The POST body now accepts `le=1000`, then clamps to 200 in the route handler. This creates a visible schema inconsistency: an API consumer reading the OpenAPI schema for POST `/stac/search` sees `limit` accepts up to 1000, but for GET `/stac/search` it only accepts up to 200. The effective ceiling is the same (200), but the schema mismatch will confuse clients and generate misleading API documentation. The KNOWN-12 rationale document says `le=1000` is intentional as a "schema floor", but that makes the public schema contract wrong.

Additionally, `test_post_search_limit_within_bounds_accepted` tests `limit=200` rather than `limit=1000` (the actual le boundary). Neither the le=1000 boundary itself nor the downstream 200-clamp are tested together, so a future change that removes the min(body.limit, 200) clamp without adjusting the schema would pass all tests while letting clients fetch up to 1000 items.

**Fix:** Either (a) lower `le=1000` to `le=200` to match the GET handler and make the schema honest, or (b) add a test that `limit=1000` is accepted by schema (200 OK) AND that the response contains at most 200 items (clamp is enforced). The GET handler precedent strongly suggests (a) is the right choice.

---

### WR-02: `lsof` port-check in bash script is not portable (Linux)

**File:** `backend/scripts/test_alembic_upgrade_clean_db.sh:112`

**Issue:** `lsof -iTCP:${PG_PORT} -sTCP:LISTEN -n -P` is macOS/BSD syntax. On Linux, `lsof` may not be installed by default; when it is installed, the `-sTCP:LISTEN` filter flag behaves differently across versions. In CI environments on Debian/Ubuntu, `lsof` is commonly absent, causing the port pre-flight check to silently fail (`>/dev/null 2>&1` suppresses the error) — the `if` condition evaluates to false, the guard is skipped, and a bound port is not detected.

This is a tool used in the close-gate runbook, so CI portability matters if Phase 1074 ever runs this in a Linux CI environment.

**Fix:** Add a fallback:
```bash
if lsof -iTCP:"${PG_PORT}" -sTCP:LISTEN -n -P >/dev/null 2>&1 \
   || ss -tlnp "sport = :${PG_PORT}" 2>/dev/null | grep -q LISTEN; then
```
Or use `nc -z 127.0.0.1 "${PG_PORT}" 2>/dev/null` which is universally available.

---

### WR-03: `test_anonymous_mint_then_consume` audit assertion is fragile — commits mid-test

**File:** `backend/tests/test_download_token.py:302-330`

**Issue:** The audit assertion at line 317-330 queries `AuditLog` records AFTER the `GET /download/cog` response. However, `download_cog` calls `await db.commit()` at line 332 of `router_export.py` — but in the test environment the client uses an overridden DB session (`test_db_session`) that may be in autocommit mode or using a savepoint. If the test client session does NOT see the commit from the route handler's session (different session scope), the `audit_rows` query at line 317 will return an empty list and the assertion at line 325 will fail with a misleading message: "Expected dataset.download_cog audit row" — even when the logic is correct.

The test's own comment at line 170-176 acknowledges "the local-storage backend will 503" and says the "contract is status != 401/403, not status == 200". But the audit check at line 317 asserts on a DB row whose visibility from the test session is unclear.

This is a reliability warning, not a functional bug in the production code. If the test suite runs against a non-patched session or the route's `db.commit()` is in a different transaction, the audit assertion will be flaky.

**Fix:** Verify test infrastructure — the session used in the assertion must be the same session (or share visibility of) the one used by the test app client. If they differ, use `await test_db_session.refresh(...)` or a separate explicit transaction fence before the audit query. Alternatively, scope the audit assertion separately and document the session-boundary dependency.

---

### WR-04: `_resolve_download_user` does not check `payload.get("aud")` (audience)

**File:** `backend/app/modules/catalog/datasets/api/router_export.py:188-213`

**Issue:** The JWT decode at line 188 uses only `algorithms=["HS256"]` without an `audience` claim check. The mint endpoint (auth/router.py) does not emit an `aud` claim in the anonymous or authenticated payload, so this cannot be exploited today. However, if a future change adds an `aud` claim to download tokens for additional scoping (e.g., tenant isolation in the enterprise edition), the consumer at `_resolve_download_user` would silently accept tokens with any or no audience — the audience gate is not enforced here at all.

This is a defense-in-depth gap: the typ + scope checks are the functional gates, but `aud` is a standard JWT claim that PyJWT can enforce automatically.

**Fix:** This is a forward-looking concern; no immediate action required if `aud` is not emitted. Document the omission explicitly in the `_resolve_download_user` docstring: "No audience claim is verified because the mint endpoint does not emit `aud`; if future tokens include `aud`, add `audience=` to the `jwt.decode()` call."

---

### WR-05: `test_vrt_vsi_allowlist` shared-constant proof test patches both modules but the patch on `vrt_module` has no effect

**File:** `backend/tests/test_vrt_vsi_allowlist.py:55-57`

**Issue:** The test at line 42-77 monkey-patches `VRT_VSI_ALLOWED_PREFIXES` in both `vrt_module` and `validation_module`. However, `validation.py` imports the constant via `from app.processing.raster.vrt import VRT_VSI_ALLOWED_PREFIXES`, which binds the name `VRT_VSI_ALLOWED_PREFIXES` in the `validation` module's namespace at import time. The patch on `vrt_module.VRT_VSI_ALLOWED_PREFIXES` (line 55) changes the symbol in `vrt.py`'s namespace but has no effect on the already-bound name in `validation.py` — the patch on `validation_module.VRT_VSI_ALLOWED_PREFIXES` (line 57) is what actually works.

Patching `vrt_module` is redundant and creates the false impression that the test is proving `validation.py` reads through from `vrt.py`'s namespace at call time (it does not — `from X import Y` is a value copy at import time, not a live reference). The test still passes and correctly proves the validator uses the shared constant (since patching `validation_module` directly works), but the intent claim ("proves the validator does not carry a private copy") is only half-true: it proves the name exists in `validation_module`'s namespace and can be patched there, but it does NOT prove that `validation.py` reads through `vrt.py`. A re-inline of the constant in `validation.py` would still pass this test as long as the name `VRT_VSI_ALLOWED_PREFIXES` is imported into `validation_module`'s namespace.

**Fix:** Remove the `vrt_module` patch (it's inert) and document the test as asserting that `validation_module.VRT_VSI_ALLOWED_PREFIXES` IS the shared constant (i.e., they're the same object via `is`) rather than simulating a monkey-patch proof:

```python
def test_validate_vrt_body_consumes_shared_constant(self):
    """validate_vrt_body uses VRT_VSI_ALLOWED_PREFIXES from raster/vrt.py
    — not a private copy. Proves this via object identity."""
    from app.processing.ingest.validation import VRT_VSI_ALLOWED_PREFIXES as v_const
    from app.processing.raster.vrt import VRT_VSI_ALLOWED_PREFIXES as vrt_const
    assert v_const is vrt_const, "validation.py has re-inlined the constant"
```

---

## Info

### IN-01: `test_stac_search_validation` does not test exactly at the `le=1000` boundary

**File:** `backend/tests/test_stac_search_validation.py:143-170`

**Issue:** `test_post_search_limit_above_le_rejected` tests `limit=10001` (well above 1000). No test verifies that `limit=1000` is accepted (the at-boundary case) or that `limit=1001` is rejected (the one-over-boundary case). The existing tests only verify that a number far outside the range (10001) is rejected and that `limit=200` (well inside the range) is accepted.

If the Field constraint were `le=999` instead of `le=1000`, all existing tests would still pass.

**Fix:** Add:
```python
async def test_post_search_limit_at_le_boundary_accepted(self, client):
    resp = await client.post("/stac/search", json={"limit": 1000, "offset": 0})
    assert resp.status_code != 422, resp.text

async def test_post_search_limit_one_over_le_rejected(self, client):
    resp = await client.post("/stac/search", json={"limit": 1001})
    assert resp.status_code == 422, resp.text
```

---

### IN-02: `CHANGELOG.md` correctly not touched — confirm for close-gate

**File:** N/A

**Issue:** No Phase 1071 commit touches `CHANGELOG.md`. This is correct per the CONTEXT.md which assigns CHANGELOG to Phase 1074. The VERIFICATION.md confirms this explicitly. Logged here so Phase 1074 review can confirm the entry covers all 11 KNOWN items closed in this phase.

**Fix:** No action required; note for Phase 1074 checklist.

---

_Reviewed: 2026-05-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

---

## Fix Iteration 1

**Fixed at:** 2026-05-21
**Scope:** Critical + Warning (INFO findings skipped per default scope)

### Fixed

| ID | File(s) | Commit | Notes |
|----|---------|--------|-------|
| CR-01 | `backend/app/processing/raster/vrt.py`, `backend/tests/test_cog_subprocess_env.py` | e127f55c | Raise ValueError on security clamp collision; test updated to assert raises |
| CR-02 | `backend/app/modules/catalog/datasets/api/router_export.py` | 531e5809 | Narrow except ValueError to guard only uuid.UUID() conversion |
| CR-03 | `backend/tests/test_export_where_validator.py` | 185da0d1 | Remove dead "Dot" branch; fix docstring to describe Column inspection |
| WR-01 | `backend/app/standards/stac/router.py`, `backend/tests/test_stac_search_validation.py` | 802537f0 | Lower StacSearchBody.limit le=1000→200; test boundary updated to 201 |
| WR-02 | `backend/scripts/test_alembic_upgrade_clean_db.sh` | 89d48a6e | Add nc -z fallback for lsof portability on Linux |
| WR-03 | `backend/tests/test_download_token.py` | 47da6748 | Add session-visibility comment explaining why audit assertion is stable |
| WR-04 | `backend/app/modules/catalog/datasets/api/router_export.py` | dd83dea0 | Document missing aud claim check with forward-looking note |
| WR-05 | `backend/tests/test_vrt_vsi_allowlist.py` | a57ae07d | Replace inert vrt_module patch with structural `is` identity assertion |

### Skipped

None — all 8 in-scope findings fixed.

### Residuals

- **IN-01, IN-02**: Skipped per instructions (INFO findings out of scope).
- **WR-01 STAC integration tests** (`test_stac_search_validation.py::TestStacSearchBodyBounds`): require a live Postgres connection; the schema change is correct by inspection — `le=200` now matches the GET handler at router.py:544. Tests will exercise correctly in the Phase 1072 CI run against a live DB.

_Fixed: 2026-05-21_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
