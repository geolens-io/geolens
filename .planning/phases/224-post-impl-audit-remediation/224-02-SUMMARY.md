---
phase: 224-post-impl-audit-remediation
plan: "02"
subsystem: backend-type-safety
tags: [pydantic, schemas, alembic, maps, persistent-config, audit-remediation]
requirements: [AUDIT-P1-6, AUDIT-P1-7, AUDIT-P1-8, AUDIT-P1-9, AUDIT-P1-10, AUDIT-P1-11, AUDIT-P1-12]

dependency_graph:
  requires: []
  provides:
    - Pydantic max_length aligned to SQL VARCHAR widths (9 fields, 3 schema files)
    - MapVisibility enum with 4 values matching CHECK constraint
    - MapLayerInput.layer_type as Literal validation
    - Absolute share_url via get_public_app_url in all 3 share token handlers
    - PersistentConfig parameterized generics for BASEMAPS, MAP_DEFAULTS, ENABLED_WIDGETS, ROLE_PERMISSIONS
  affects:
    - backend/app/datasets/schemas.py
    - backend/app/records/schemas.py
    - backend/app/auth/schemas.py
    - backend/app/maps/schemas.py
    - backend/app/maps/router.py
    - backend/app/persistent_config.py

tech_stack:
  added: []
  patterns:
    - Literal union types for Pydantic fields backed by SQL CHECK constraints
    - ContactRole / KeywordType Literal type aliases for reuse across Create/Update schemas
    - Top-level import of BasemapEntry/MapDefaultsResponse in persistent_config.py (no circular import)

key_files:
  created:
    - backend/alembic/versions/2026_04_12_1102-989ae68d7859_tighten_pydantic_varchar_constraints_p1_.py
  modified:
    - backend/app/datasets/schemas.py
    - backend/app/records/schemas.py
    - backend/app/auth/schemas.py
    - backend/app/maps/schemas.py
    - backend/app/maps/router.py
    - backend/app/persistent_config.py

decisions:
  - SQL VARCHAR columns already matched new Pydantic limits — Alembic migration is documentation-only (no ALTER statements needed)
  - ContactRole and KeywordType added as module-level Literal type aliases for reuse in both Create and Update schemas
  - BasemapEntry/MapDefaultsResponse imported at top of persistent_config.py (not inline) — safe since settings/schemas.py has no back-import

metrics:
  duration: "~25 minutes"
  completed: "2026-04-12"
  tasks: 4
  files: 7
---

# Phase 224 Plan 02: Backend Type Safety Audit Remediation Summary

Resolved 7 backend type safety audit findings (P1-6 through P1-12): Pydantic schema fields that were wider than their SQL columns or missing enum/Literal constraints, relative share_url construction, and bare generic PersistentConfig declarations.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | P1-6/P1-7/P1-8 — Tighten Pydantic max_length | f8967298 | datasets/schemas.py, records/schemas.py, auth/schemas.py, alembic/versions/ |
| 2 | P1-9/P1-10 — MapVisibility + MapLayerInput Literal | dbee83d5 | maps/schemas.py |
| 3 | P1-11 — Absolute share_url via get_public_app_url | a08464a1 | maps/router.py |
| 4 | P1-12 — Parameterize PersistentConfig generics | fda44efd | persistent_config.py |
| - | Ruff E402/F401 fix | 515b058b | persistent_config.py, alembic migration |

## What Was Built

**P1-6 (DatasetMeta max_length drift):** Tightened `update_frequency` from 1000→30, `record_status` 1000→20, `sensitivity_classification` 1000→20, `language` 1000→10 — all now match their `String(N)` SQL columns.

**P1-7 (Record* column-width mismatches):** `RecordContact.role` changed from `str (max_length=100)` to `ContactRole` Literal type matching the CHECK constraint's 20 allowed values (VARCHAR(30)). `RecordKeyword.keyword_type` changed to `KeywordType` Literal matching the 15-value CHECK constraint (VARCHAR(20)). `RecordDistribution.distribution_type` 200→30, `.format` 200→50, `.media_type` 255→100.

**P1-8 (UserCreate.email max_length):** Changed from 320 to 255, matching the SQL `String(255)` column.

**P1-9 (MapVisibility enum drift):** Added `unlisted = "unlisted"` to the `MapVisibility` enum — now has 4 values matching the SQL CHECK constraint `('private', 'public', 'internal', 'unlisted')`.

**P1-10 (MapLayerInput.layer_type bare str):** Changed to `Literal["vector_geolens", "raster_geolens", "geojson"] | None` — invalid layer types now rejected at Pydantic validation before reaching the DB CHECK constraint.

**P1-11 (share_url relative paths):** All 3 share token handlers (GET, POST, PATCH in `maps/router.py`) now call `await get_public_app_url(db, request=request)` and construct `f"{public_url}/m/{token}"`. The GET handler also gained the missing `request: Request` parameter needed for URL resolution.

**P1-12 (PersistentConfig bare generics):** Four declarations tightened: `BASEMAPS` → `list[BasemapEntry]`, `MAP_DEFAULTS` → `MapDefaultsResponse`, `ENABLED_WIDGETS` → `list[str] | None`, `ROLE_PERMISSIONS` → `dict[str, list[str]]`. `BasemapEntry` and `MapDefaultsResponse` imported at top-level from `app.settings.schemas` (no circular import — schemas.py has no back-dependency on persistent_config).

**Alembic migration:** A documentation-only migration (`989ae68d7859`) was created for P1-6/7/8. All SQL columns already had the correct VARCHAR widths in prior migrations; the migration records the Pydantic schema tightening for audit traceability.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Ruff E402 module-level import not at top (persistent_config.py)**
- **Found during:** Post-Task-4 ruff check
- **Issue:** Plan suggested a local inline import for `BasemapEntry`/`MapDefaultsResponse` to avoid circular imports; placing it mid-file triggered E402
- **Fix:** Moved import to top-level import block (safe — `settings/schemas.py` has no back-import to `persistent_config.py`)
- **Files modified:** `backend/app/persistent_config.py`, `backend/alembic/versions/2026_04_12_1102-*.py` (removed unused op/sa imports)
- **Commit:** 515b058b

**2. [Rule 2 - Missing] Added ContactRole/KeywordType Literal type aliases**
- **Found during:** Task 1
- **Issue:** Plan said to add Literal typing to ContactCreate.role and KeywordCreate.keyword_type, but both schemas also have Update counterparts (ContactUpdate) that needed the same constraint
- **Fix:** Defined `ContactRole` and `KeywordType` as module-level Literal aliases; used in both Create and Update schemas
- **Files modified:** `backend/app/records/schemas.py`
- **Commit:** f8967298

**3. [Rule 1 - Bug] GET share token handler missing `request: Request` parameter**
- **Found during:** Task 3
- **Issue:** The GET `/{map_id}/share/` handler had no `request` parameter in its signature, needed for `get_public_app_url(db, request=request)` call
- **Fix:** Added `request: Request` to the handler signature (FastAPI injects it automatically)
- **Files modified:** `backend/app/maps/router.py`
- **Commit:** a08464a1

## Known Stubs

None.

## Threat Flags

None — all changes tighten existing validation surface, no new network endpoints or trust boundaries introduced.

## Self-Check: PASSED

Files created/modified:
- `backend/app/datasets/schemas.py` — FOUND
- `backend/app/records/schemas.py` — FOUND
- `backend/app/auth/schemas.py` — FOUND
- `backend/app/maps/schemas.py` — FOUND
- `backend/app/maps/router.py` — FOUND
- `backend/app/persistent_config.py` — FOUND
- `backend/alembic/versions/2026_04_12_1102-989ae68d7859_tighten_pydantic_varchar_constraints_p1_.py` — FOUND

Commits verified:
- f8967298 — FOUND
- dbee83d5 — FOUND
- a08464a1 — FOUND
- fda44efd — FOUND
- 515b058b — FOUND
