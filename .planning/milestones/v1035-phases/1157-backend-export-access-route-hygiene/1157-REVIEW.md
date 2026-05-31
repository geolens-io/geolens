---
phase: 1157-backend-export-access-route-hygiene
reviewed: 2026-05-30T00:00:00Z
depth: deep
files_reviewed: 5
files_reviewed_list:
  - backend/app/processing/export/router.py
  - backend/app/standards/ogc/router.py
  - backend/tests/test_export_access.py
  - backend/tests/test_export.py
  - backend/tests/test_export_hardening.py
findings:
  critical: 0
  warning: 0
  info: 2
  total: 2
status: clean
---

# Phase 1157: Code Review Report

**Reviewed:** 2026-05-30
**Depth:** deep (cross-file: traced auth helpers, reference analog, route-matching precedence)
**Files Reviewed:** 5
**Status:** clean (no BLOCKER/HIGH/MEDIUM; 2 LOW/INFO notes)

## Summary

Phase 1157 changes a security-critical access-control gate (EXP-01), adds a route-shape
alias (API-01), and adds a regression test (EXP-02). I reviewed all five files against the
six focus areas, traced the authorization helpers and the reference analog into their
source, and simulated Starlette route matching to rule out a precedence/shadowing bug.

**The implementation is correct and safe to ship.** Key verifications:

1. **No under-gating (BLOCKER risk — NOT present).** The anonymous branch
   (`router.py:73-82`) calls `check_dataset_access_or_anonymous`, whose anon path
   (`authorization.py:84-96` → `defaults.py:109-110`) enforces
   `visibility=='public' AND record_status=='published'` and raises **404** on denial.
   A defense-in-depth `visibility != "public"` → 403 guard follows. There is no path by
   which an anonymous caller can export private/restricted/unpublished data. The gate is a
   faithful, line-for-line mirror of the already-shipped `download_cog` analog
   (`router_export.py:384-407`).

2. **Capability not dropped (BLOCKER risk — NOT present).** The `export` capability check
   is preserved on the authenticated `else` branch (`router.py:84-92`) via
   `get_user_roles` + `get_effective_permissions` + `matrix.get(role, {}).get("export", False)`.
   An authenticated user whose roles lack `export` still gets 403. `require_permission`
   was relocated, not removed.

3. **Null-safety confirmed.** `user` is `Identity | None`. Every `user.<attr>` access is
   guarded: `user.id if user is not None else None` (audit, `router.py:155`) and
   `request.client.host if request.client else None` (`router.py:165`). `AuditEvent.user_id`
   is typed `uuid.UUID | None` (`platform/audit.py:28`) and explicitly documents the
   anonymous-download case; `audit_emit` tolerates it. `get_optional_user`
   (`dependencies.py:63-103`) returns `None` (never raises) for missing/invalid/expired
   tokens, so the anon branch is reliably reached.

4. **Gotcha avoided.** `check_dataset_access_or_anonymous` / `check_dataset_access` /
   `get_user_roles` are imported directly from `app.modules.catalog.authorization`
   (`router.py:16-20`), NOT routed through the processing port. The Phase 1156
   `port.check_dataset_access_or_anonymous` AttributeError trap is not reproduced. Only
   `port.get_dataset(...)` (a legitimate port method) remains port-routed.

5. **API-01 — no route precedence bug.** Stacked decorators register both
   `/collections/{dataset_id}/items` (canonical, in schema) and `.../items/` (alias,
   `include_in_schema=False`) on the same handler. I simulated Starlette matching: a
   `/items/{feature_id}` request (e.g. `/items/42`) still resolves to the feature route at
   `router.py:473` — the trailing-slash alias regex terminates at the slash and does NOT
   shadow the more-specific feature route, despite the feature route being registered
   after the alias. All symbols (`JSONResponse`, `ERROR_RESPONSES_PUBLIC`,
   `OGCFeatureItemsResponse`) are in scope.

6. **Test quality — real, not mocked-away.** `test_export_access.py` seeds genuine
   datasets via `tests.factories.create_dataset` with explicit `visibility`/`record_status`
   and exercises the live gate (only the OGR file-generation call is mocked, via the same
   pattern as `test_export_hardening.py`; the visibility gate runs unmocked and executes
   *before* export). Deny tests cover anon+unpublished, anon+private, anon+restricted, and
   non-owner-authenticated+private; the positive test asserts a real 200 + non-empty body.
   The API-01 parity test creates an actual PostGIS data table so both URL shapes serve a
   real 200 and the equality assertion is meaningful. The two updated obsolete tests retain
   meaningful coverage: `test_export.py` correctly flips 401→404 (anon now reaches
   not-found), and `test_export_hardening.py` was *strengthened* — it now pins both
   `get_optional_user` resolution AND that the handler source still contains
   `get_effective_permissions` + the `"export"` key, guarding against silent gate removal.

I ran the focused suite (`test_export_access.py` + `test_export.py` +
`test_export_hardening.py`): **38 passed**, consistent with the claimed 142 passed / 3
skipped across the wider export+ogc surface.

## Narrative Findings (AI reviewer)

No BLOCKER, HIGH, or MEDIUM findings. Two LOW/INFO observations below; neither blocks ship.

## Info

### IN-01: `shp` format omitted from the parametrized anon-allow test

**File:** `backend/tests/test_export_access.py:116`
**Issue:** `test_anon_export_all_formats_public_published_allowed` parametrizes over
`["gpkg", "geojson", "csv"]`, omitting `shp`. The EXP-01 requirement states "all file
formats (gpkg/geojson/**shp**/csv)". The in-code comment justifies the omission (shp
produces a zip that "may interact differently with FileResponse"). This is a test-coverage
note, **not a security gap**: the access-control gate (`router.py:72-92`) runs before any
format-specific logic (`router.py:116`, `:122`), so the gate is format-independent and is
already proven for three formats plus the dedicated single-format test.
**Fix (optional):** Add `shp` to the parametrize list and assert `200` (the mock fixture
already special-cases `shp` → `.zip` at `test_export_access.py:63-64`, so it should pass),
or leave a one-line note in the phase summary that shp anon-export was verified via the
QA-01 live-MCP gate rather than the unit matrix.

### IN-02: Non-owner deny test exercises the visibility path, not the capability path

**File:** `backend/tests/test_export_access.py:224-254`
**Issue:** `test_non_owner_export_private_denied` uses a `private+published` dataset, so the
viewer is denied at the `check_dataset_access` visibility check (404 — viewer is not the
owner) before the `export`-capability branch is reached. This correctly proves visibility
denial for a non-owner, which is what EXP-02 requires. However, the distinct
"authenticated user WITH visibility but WITHOUT the `export` capability → 403" path (the
capability gate relocated in EXP-01) is not behaviorally exercised here — it is only pinned
statically by `test_export_hardening.py`'s source-string assertion
(`get_effective_permissions` present in the handler body).
**Fix (optional):** Add a behavioral test that grants the caller dataset visibility (e.g. a
`public+published` dataset, which any authenticated user can see) while their role lacks the
`export` capability, asserting `403 "Missing permission: export"`. This would close the loop
on T-1157-02 (the elevation-of-privilege threat) behaviorally rather than only statically.
Not required — the static pin plus the unchanged-and-mirrored `download_cog` capability
logic make a regression here low-probability.

---

_Reviewed: 2026-05-30_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
