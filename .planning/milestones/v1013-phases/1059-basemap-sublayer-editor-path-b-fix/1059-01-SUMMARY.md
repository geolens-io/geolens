---
phase: 1059-basemap-sublayer-editor-path-b-fix
plan: 01
subsystem: api
tags: [pydantic, fastapi, jsonb, validation, basemap, schemas]

# Dependency graph
requires: []
provides:
  - "SublayerOverride Pydantic model with 7 nullable fields + hex validator + extra=forbid"
  - "BasemapConfig.sublayer_overrides: dict[str, SublayerOverride] | None = None field"
  - "22 backend pytest tests covering validation, round-trip, legacy compat, security"
affects: [1059-02, 1059-03, 1059-04]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level compiled regex for Pydantic field_validator (avoids ModelPrivateAttr collision)"
    - "jsonb-additive Pydantic field: SublayerOverride nullable dict field in BasemapConfig, zero migration needed"

key-files:
  created:
    - backend/tests/test_basemap_sublayer_overrides.py
  modified:
    - backend/app/modules/catalog/maps/schemas.py

key-decisions:
  - "Module-level _SUBLAYER_HEX_RE constant instead of class-level _HEX_RE to avoid Pydantic ModelPrivateAttr collision"
  - "Validator on both stroke_color and casing_color via field_validator(*fields) multi-field decoration"

patterns-established:
  - "Module-level compiled regex for Pydantic BaseModel validators: avoids ModelPrivateAttr treatment of _underscore class attributes"

requirements-completed: [BSE-01]

# Metrics
duration: 4min
completed: 2026-05-20
---

# Phase 1059 Plan 01: Backend Pydantic SublayerOverride Schema Summary

**`SublayerOverride` Pydantic model with 7-field per-sublayer style overrides, hex color validator, numeric clamps, extra=forbid, wired into `BasemapConfig.sublayer_overrides` with zero Alembic migration**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-20T03:38:19Z
- **Completed:** 2026-05-20T03:42:25Z
- **Tasks:** 2 (TDD RED + GREEN per task)
- **Files modified:** 2

## Accomplishments

- New `SublayerOverride(BaseModel)` at `backend/app/modules/catalog/maps/schemas.py` with all 7 nullable styling fields, `^#[0-9a-fA-F]{6}$` hex validator (blocks `javascript:`, raw names, short/long hex), Pydantic `ge`/`le` range clamps, and `model_config = ConfigDict(extra="forbid")` locking the D-14 scope guardrail
- `BasemapConfig.sublayer_overrides: dict[str, SublayerOverride] | None = Field(default=None)` field added — zero-migration jsonb-additive; legacy maps without the key deserialize cleanly
- `_clean_basemap_config` in `style_json.py` automatically inherits the new field via `BasemapConfig.model_validate` — no change needed at the 3 existing call sites
- 22 backend pytest tests (14 test functions, 4+6 parametrized cases) covering all threat model mitigations: T-1059A-01 (hex injection), T-1059A-02 (numeric bounds), T-1059A-03 (extra=forbid), T-1059A-04 (legacy compat)

## Task Commits

Each task was committed atomically using TDD RED/GREEN cycle:

1. **Task 1 (RED): Failing tests for SublayerOverride** - `6674f09d` (test)
2. **Task 1+2 (GREEN): SublayerOverride model + BasemapConfig field** - `e2a57455` (feat)

_Note: Task 2 (test file) was written in the RED phase of Task 1; the single GREEN commit implements the schema that makes all 22 tests pass._

## Files Created/Modified

- `backend/app/modules/catalog/maps/schemas.py` — Added `import re`, module-level `_SUBLAYER_HEX_RE`, new `SublayerOverride` class (70 lines), `sublayer_overrides` field in `BasemapConfig`
- `backend/tests/test_basemap_sublayer_overrides.py` — New test file, 227 lines, 14 test functions (22 test cases after parametrize expansion)

## Decisions Made

- **Module-level regex constant** (`_SUBLAYER_HEX_RE = re.compile(...)`) rather than a class-level `_HEX_RE` attribute on `SublayerOverride`. Pydantic v2 treats `_underscore` class attributes as `ModelPrivateAttr` objects — calling `.match()` on a `ModelPrivateAttr` instance raises `AttributeError`. Module-level constant avoids this cleanly.
- **`field_validator("stroke_color", "casing_color")` multi-field decoration** keeps both color fields validated by a single method, consistent with the Pydantic v2 multi-field validator pattern already used in schemas.py.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Moved hex regex from class attribute to module-level constant**
- **Found during:** Task 1 GREEN — implementation smoke check
- **Issue:** `_HEX_RE = re.compile(...)` as a class attribute on `SublayerOverride(BaseModel)` is treated by Pydantic v2 as a `ModelPrivateAttr`. Accessing `cls._HEX_RE.match(v)` in `field_validator` raised `AttributeError: 'ModelPrivateAttr' object has no attribute 'match'`
- **Fix:** Moved regex to module-level `_SUBLAYER_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")` immediately before the `SublayerOverride` class; updated validator to reference `_SUBLAYER_HEX_RE` directly
- **Files modified:** `backend/app/modules/catalog/maps/schemas.py`
- **Verification:** Smoke check `python -c "...SublayerOverride(stroke_color='#ff0000')..."` passed; all 22 tests passed
- **Committed in:** `e2a57455` (part of the GREEN phase commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Necessary correctness fix for Pydantic v2 class-attribute semantics. No scope creep. All plan acceptance criteria satisfied.

## Issues Encountered

- pytest not available as a standalone binary in the Docker API container (`docker compose exec api` returns "exec: pytest: executable file not found"). Tests run via `cd backend && PYTHONPATH=. uv run pytest` from the host (matches the existing pattern documented in the Makefile and other phase test runs). This is the established pattern for this project — not a new issue.

## Known Stubs

None — all fields are fully wired through Pydantic validation. The `sublayer_overrides` dict is persisted opaquely through the existing jsonb column; Plans 02/03/04 will add the frontend integration and MapLibre application layer.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes at trust boundaries introduced. The `SublayerOverride` model adds Pydantic-layer validation for the existing `MapBasemapConfig.basemap_config` jsonb path; no new ingress surface.

## Next Phase Readiness

- Plans 02/03/04 (frontend MapLibre integration, editor UI, cross-context tests) can now `import { SublayerOverride }` shape from the backend schema and reference `BasemapConfig.sublayer_overrides` as the persistence contract
- `_clean_basemap_config` in `style_json.py` automatically passes `sublayer_overrides` through the existing round-trip cleaner — verified by test 12
- Downstream plans should reference this SUMMARY for the `SublayerOverride` field set (7 fields, all nullable) and the opaque keyset contract (D-01)

## Self-Check: PASSED

- `backend/app/modules/catalog/maps/schemas.py` — FOUND, contains `class SublayerOverride`
- `backend/tests/test_basemap_sublayer_overrides.py` — FOUND, 14 test functions, 22 pass
- Commit `6674f09d` — FOUND (test RED phase)
- Commit `e2a57455` — FOUND (feat GREEN phase)
- No Alembic migration files created — CONFIRMED (latest migration: `0017_ingest_job_fanned_out_status.py`)

---
*Phase: 1059-basemap-sublayer-editor-path-b-fix*
*Completed: 2026-05-20*
