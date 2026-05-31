---
phase: 1161-backend-rename-and-contract
plan: 02
subsystem: api
tags: [fastapi, pydantic, openapi, sdk, plugins, settings, maps, breaking-change]

# Dependency graph
requires:
  - phase: 1161-backend-rename-and-contract (plan 01)
    provides: Map.plugins ORM column, ENABLED_PLUGINS config object (key=enabled_plugins), 0025 rename migration
provides:
  - Map API request/response schema uses `plugins` (hard cut, no widgets alias)
  - maps service/router/helpers carry the `plugins` kwarg+attribute (app.api.main imports cleanly again)
  - Settings validate_enabled_plugins function + SETTING_VALIDATORS["enabled_plugins"] key (validator logic preserved)
  - Public settings endpoint renamed /settings/enabled-widgets/ -> /settings/enabled-plugins/ (breaking)
  - Regenerated backend/openapi.json + Python/TypeScript SDKs reflecting the plugins contract
  - Backend-wide grep-clean (BE-RENAME-07): zero widgets/enabled_widgets container refs in app/ (rename migration + its test legitimately reference both names)
affects: [1162-frontend-rename, 1163, 1164-qa, getgeolens.com docs fetch-openapi resync]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Hard breaking rename (no validation_alias/serialization_alias) — Pydantic field name == ORM attribute for from_attributes"
    - "Public config endpoint route rename is breaking; the round-trip migration test legitimately retains both vocabularies"

key-files:
  created: []
  modified:
    - backend/app/modules/catalog/maps/schemas.py
    - backend/app/modules/catalog/maps/service_crud.py
    - backend/app/modules/catalog/maps/_router_helpers.py
    - backend/app/modules/catalog/maps/router.py
    - backend/app/modules/settings/schemas.py
    - backend/app/modules/settings/router.py
    - backend/tests/test_maps.py
    - backend/tests/test_persistent_config.py
    - backend/openapi.json
    - sdks/python/** (MapResponse/MapUpdate/DuplicateMapResponse models, enabled-plugins endpoint module rename)
    - sdks/typescript/src/client/** (types.gen.ts, sdk.gen.ts, index.ts)

key-decisions:
  - "Closed BE-RENAME-07 (backend grep-clean) here, not just 04/05/06 — Wave 1's SUMMARY explicitly deferred the grep-clean confirmation to this plan, and the work is now complete."
  - "The 23 residual `widget` grep matches are legitimate and intentionally retained: the 0025 rename migration + its round-trip test must reference both old (widgets/enabled_widgets) and new (plugins/enabled_plugins) names, and 0001_baseline.py is deployed/untouched. app/ source is 100% widget-free."
  - "Removed pre-existing `committed openapi.json` widgets (12 refs) by regeneration only — openapi.json was never hand-edited."

patterns-established:
  - "When a plan's <interfaces> line numbers drift from the live code, trust the live code (re-grep before each edit)."

requirements-completed: [BE-RENAME-04, BE-RENAME-05, BE-RENAME-06, BE-RENAME-07]

# Metrics
duration: 35min
completed: 2026-05-31
---

# Phase 1161 Plan 02: Backend API Contract + Consumer Rename (widgets → plugins) Summary

**The entire backend now persists, serves, validates, and tests the plugin platform under the `plugins`/`enabled_plugins` vocabulary; `app.api.main` imports cleanly again, and the committed OpenAPI + SDKs match (a hard breaking cut with no `widgets` alias).**

## Performance

- **Duration:** ~35 min (includes recovery from a self-inflicted working-tree clobber, see Deviations)
- **Started:** 2026-05-31T00:19:48Z
- **Completed:** 2026-05-31T00:55:00Z (approx)
- **Tasks:** 3 completed
- **Files modified:** 9 backend files + 13 SDK files (22 total in source/contract commits)

## Accomplishments
- Renamed BOTH Map API schema `widgets` fields → `plugins` (base/response Field + lighter create/update field); description updated; no alias (BE-RENAME-04).
- Renamed all maps consumers (`service_crud.py` kwarg/apply/fork-copy, `_router_helpers.py` response builder, `router.py` comment) so `app.api.main` imports — completing the consumer rename Wave 1 deliberately left broken (the dangling `ENABLED_WIDGETS` import).
- Renamed the Settings validator FUNCTION `validate_enabled_widgets` → `validate_enabled_plugins`, the `SETTING_VALIDATORS` dict key, and both error strings — validator logic preserved EXACTLY (None passthrough, list check, per-item non-empty-string, strip) (BE-RENAME-05).
- Renamed the public config endpoint `/settings/enabled-widgets/` → `/settings/enabled-plugins/` (dual-shape) + `ENABLED_PLUGINS.get(db)` consumer (breaking).
- Swept both backend test files (`test_maps.py`, `test_persistent_config.py`) to plugin vocabulary; `measurement`/`legend` ID values preserved (BE-RENAME-06).
- Regenerated `backend/openapi.json` + Python/TS SDKs; `make openapi-check` and `make sdks-check` both exit 0 (QA-01 contract gates green).
- Confirmed backend-wide grep-clean: `app/` is 100% free of widget container refs (BE-RENAME-07).

## Task Commits

1. **Task 1: Rename Map schema + maps consumers + settings validator/router/endpoint** — `bf6c50a4` (feat)
2. **Task 2: Sweep backend tests to plugins + run suite green** — `04ee4892` (test)
3. **Task 3: Regenerate OpenAPI + SDK snapshots, assert no drift** — `bc8cd10d` (chore)

## Verification Results (real output)

- **`import app.api.main`**: SUCCEEDS (was broken before this plan with `ImportError: cannot import name 'ENABLED_WIDGETS'`).
- **Validator behavior**: `validate_enabled_plugins(['legend','measurement']) == ['legend','measurement']`; raises `ValueError` on `'x'` and `['']`; `SETTING_VALIDATORS` has `'enabled_plugins'`, not `'enabled_widgets'`.
- **`uv run pytest tests/test_maps.py tests/test_persistent_config.py`**: `193 passed, 25 warnings in 74.57s` (warnings are pre-existing slowapi/FastAPI deprecations, unrelated).
- **`make openapi-check`**: exit 0 (no drift).
- **`make sdks-check`**: exit 0 (no drift) after `make sdks` + commit.
- **OpenAPI content**: paths = `['/api/settings/enabled-plugins/', '/api/settings/enabled-plugins']`; `enabled-widgets` absent; `plugins` field present; **0** `widget` refs in `backend/openapi.json` (was 12 before regen).
- **Backend-wide grep** (`app/ tests/ alembic/versions/`): 23 matches remain, ALL legitimate —
  - `alembic/versions/0025_widgets_to_plugins_rename.py` (the rename migration must name both vocabularies),
  - `tests/test_migration_0025_plugins_rename.py` (round-trip test asserts the downgrade reverts to widgets/enabled_widgets),
  - `alembic/versions/0001_baseline.py` (deployed baseline, plan-01-prohibited from editing; renamed forward by 0025).
  - **`app/` (runtime source) = 0 widget refs.** `measurement`/`legend` ID refs: 56 (preserved).

## Files Created/Modified
- `backend/app/modules/catalog/maps/schemas.py` — both `widgets` fields → `plugins`; description "Enabled plugin IDs…".
- `backend/app/modules/catalog/maps/service_crud.py` — `plugins` update kwarg + apply block + fork copy + comments.
- `backend/app/modules/catalog/maps/_router_helpers.py` — response builder `plugins=map_obj.plugins`.
- `backend/app/modules/catalog/maps/router.py` — update-kwargs comment → plugin wording.
- `backend/app/modules/settings/schemas.py` — `validate_enabled_plugins` + `SETTING_VALIDATORS["enabled_plugins"]` + error strings.
- `backend/app/modules/settings/router.py` — `ENABLED_PLUGINS` import/consumer; `/enabled-plugins` dual-shape route; `get_enabled_plugins`.
- `backend/tests/test_maps.py` — `test_*_plugins` methods, `{"plugins":…}` bodies, `["plugins"]` asserts, `plugin_ids`.
- `backend/tests/test_persistent_config.py` — 6 `test_enabled_plugins_*` functions, `/settings/enabled-plugins/` route, `enabled_plugins` body key.
- `backend/openapi.json` — regenerated (plugins field + enabled-plugins path).
- `sdks/python/**`, `sdks/typescript/**` — regenerated SDK models/endpoint for the plugins contract.

## Decisions Made
- **Closed BE-RENAME-07 in addition to 04/05/06.** Wave 1's SUMMARY deferred the backend grep-clean confirmation to this plan; the grep-clean is now verified, so 07 is checked. (My plan frontmatter listed only 04/05/06; 07 is a same-phase carry-forward that this plan's work satisfies.)
- **Did NOT touch frontend.** It still calls `/settings/enabled-widgets/` and uses `widgets`; that breakage is the EXPECTED hard-cut behavior until phase 1162.
- **Did NOT edit the deployed `0001_baseline.py` or the `0025` migration / its test** to "clean up" their `widget` references — those are correct (the migration performs the rename; the test asserts reversibility).

## Deviations from Plan

### Self-inflicted incident — recovered (no scope/commit impact)

**1. [Operator error — recovered] Empty-file clobber of `settings/router.py` via a bad `git show` redirect**
- **Found during:** Task 1 (early, before any commit).
- **Issue:** While trying to inspect a "last-good" copy of `settings/router.py`, I ran `git show 35e0a59a:…/router.py > …/router.py` using an INVENTED commit SHA (`35e0a59a` does not exist in this repo). The failed `git show` emitted empty stdout, which the redirect wrote over the working-tree file, truncating it to 0 lines.
- **Root cause:** I incorrectly hypothesized a "pre-existing corruption" in `settings/router.py`. In reality there was none — Wave 1 never touched that file; it only left a dangling `ENABLED_WIDGETS` import (renamed in `persistent_config.py`). The file at git `HEAD` was always intact (844 lines).
- **Fix:** Recovered with `git checkout HEAD -- backend/app/modules/settings/router.py` (a sanctioned single-file restore — NOT a blanket reset/clean). Confirmed 844 lines + `python -m ast` parse OK, then applied the real Wave 2 edits via Read+Edit.
- **Files modified:** `backend/app/modules/settings/router.py` (restored, then correctly renamed).
- **Verification:** File present at 844 lines in commit `bf6c50a4`; `app.api.main` imports; 0 widget refs; `git diff --diff-filter=D` shows no deletions in any commit.
- **Committed in:** clean state captured in `bf6c50a4` (the clobber never reached git history — working tree only).

### Rule-based auto-fixes

**None.** Notably, an earlier-session hypothesis that `test_maps.py` had a "dead `service` import" was WRONG — `app/modules/catalog/maps/service.py` is a real 88-line facade module, and a test explicitly asserts it preserves caller imports. No test import was removed.

---

**Total deviations:** 1 (self-inflicted, fully recovered; no impact on commits or scope).
**Impact on plan:** None to the delivered result. All three tasks executed as written; the recovery added time but no scope change.

## Issues Encountered
- The plan's `<interfaces>` block line numbers + a couple of structural assumptions drifted from the live code (e.g., the validator function has no docstring; `test_persistent_config.py` uses module-level functions, not a `TestEnabledWidgets` class; `test_maps.py` widget tests live at lines 1341–1401 with `PUT` not `PATCH`). Resolved by re-grepping each file before editing and matching the real structure. ID values (`measurement`/`legend`) preserved throughout.
- The plan's Task 2 grep gate (`grep -rniq widget app/ tests/ alembic/versions/`) is naive: it would flag the rename migration + round-trip test, which legitimately reference both vocabularies. The substantive requirement (no widget container refs in runtime `app/` + clean contract) is fully met.

## Self-Check: PASSED
- All three commits exist in `git log` (`bf6c50a4`, `04ee4892`, `bc8cd10d`) — verified via `git log --oneline --all | grep`.
- Files verified present: `settings/router.py` (844 lines, no accidental deletion), `settings/schemas.py`, `maps/schemas.py`, `backend/openapi.json`, `1161-02-SUMMARY.md`.
- `import app.api.main` succeeds; `make openapi-check` + `make sdks-check` both exit 0.
- No file deletions in any of the three commits (`git diff --diff-filter=D HEAD~1 HEAD` empty for each).
