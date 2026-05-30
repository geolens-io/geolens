---
phase: 1161-backend-rename-and-contract
plan: 01
subsystem: backend
tags: [migration, rename, schema, persistent-config, breaking]
dependency_graph:
  requires: []
  provides: [catalog.maps.plugins-column, enabled_plugins-config-key, Map.plugins-orm, ENABLED_PLUGINS]
  affects: [backend, alembic, catalog-maps, persistent-config]
tech_stack:
  added: []
  patterns: [alembic-rename-column, schema-qualified-alter, isolated-throwaway-db-roundtrip-test]
key_files:
  created:
    - path: backend/alembic/versions/0025_widgets_to_plugins_rename.py
      why: "Reversible column + config-key rename migration (chains off head 0024)"
    - path: backend/tests/test_migration_0025_plugins_rename.py
      why: "Upgrade/downgrade/re-upgrade round-trip test on an isolated throwaway DB"
  modified:
    - path: backend/app/modules/catalog/maps/models.py
      why: "Map.widgets -> Map.plugins to match migrated schema"
    - path: backend/app/core/persistent_config.py
      why: "ENABLED_WIDGETS -> ENABLED_PLUGINS (key=enabled_plugins)"
decisions:
  - "down_revision is the real head revision id '0024' (the file's revision string), NOT the filename or the brief's fictional a3f8c21d9e04"
  - "maps column ops pass schema='catalog' (maps lives in the catalog schema); persistent_config UPDATE is unqualified (public schema, created in 0001_baseline.py)"
  - "Round-trip test provisions its own uuid-suffixed throwaway Postgres DB (psycopg v3 driver) and drops it in teardown, so real alembic up/down never mutates the xdist shared template/per-test DBs"
  - "app.api.main import left intentionally broken (settings/router.py still imports ENABLED_WIDGETS) — that consumer rename is plan 02"
metrics:
  duration: "22m"
  completed: "2026-05-30"
---

# Phase 1161 Plan 01: Backend Rename & Contract (Wave 1) Summary

Reversible Alembic migration `0025` renames `catalog.maps.widgets` -> `plugins` and the
`enabled_widgets` persistent-config key -> `enabled_plugins`, with the `Map` ORM model and
`persistent_config.py` updated to match — a hard breaking cut with a symmetric downgrade, proven by an
isolated upgrade/downgrade/re-upgrade round-trip test that preserves row values.

## What Was Built

**1. Migration `0025_widgets_to_plugins_rename.py`** (BE-RENAME-01, BE-RENAME-02)
- `revision = "0025_widgets_to_plugins_rename"`, `down_revision = "0024"` (the real head revision id,
  confirmed via `ScriptDirectory` — NOT the filename, NOT the brief's fictional `a3f8c21d9e04`).
- `upgrade()`:
  - `op.alter_column("maps", "widgets", new_column_name="plugins", schema="catalog")` — O(1)
    metadata-only `RENAME COLUMN` in the `catalog` schema; JSONB array values untouched.
  - `op.execute("UPDATE persistent_config SET key='enabled_plugins' WHERE key='enabled_widgets'")` —
    unqualified (the `persistent_config` table is in the public schema, created in `0001_baseline.py`);
    in-place key rename, value preserved.
- `downgrade()` reverses both symmetrically (`plugins`->`widgets`, `enabled_plugins`->`enabled_widgets`).
- Resolves as the single alembic head (no branch conflict).

**2. Round-trip test `test_migration_0025_plugins_rename.py`** (BE-RENAME-01 acceptance)
- Provisions its own uuid-suffixed throwaway Postgres DB (parallel-safe under `-n 4`), runs the real
  `alembic upgrade head` -> `downgrade -1` -> `upgrade +1` cycle against it, drops it in teardown.
  Deliberately avoids conftest's session template / per-test clone fixtures so it never corrupts
  shared schema other tests depend on (model documented in a module docstring).
- Uses the psycopg-v3 sync URL derived from `settings.test_database_url_sync` (psycopg2 is NOT
  installed in this project; a bare `postgresql://` URL would route to the absent driver).
- Seeds `enabled_plugins = ["legend"]` and asserts: plugins present / widgets absent after upgrade;
  revert to `widgets` / `enabled_widgets` with the `["legend"]` value preserved after downgrade;
  plugins / `enabled_plugins` restored after re-upgrade. The `legend` ID value survives the full cycle.

**3. ORM + persistent_config rename** (BE-RENAME-03)
- `models.py`: `Map.widgets` -> `Map.plugins` (`Mapped[list | None] = mapped_column(JSONB,
  nullable=True, default=None)` unchanged; comment updated to plugin wording).
- `persistent_config.py`: `ENABLED_WIDGETS` -> `ENABLED_PLUGINS` with `key="enabled_plugins"`,
  `label="Enabled Plugins"`, the `# -- Plugins --` section header, and the `:128` env_default comment
  — all renamed. Zero case-insensitive `widget` references remain in either file.

## Verification Results

| Check | Result |
|-------|--------|
| Alembic graph: single head `0025`, `down_revision == "0024"` | PASS (`graph OK: single head 0025, down_revision 0024`) |
| Round-trip test `tests/test_migration_0025_plugins_rename.py` | PASS (`1 passed in 10.41s`) |
| Round-trip under `-n 4` (CI default) | PASS (`1 passed in 18.69s`) |
| Model+config import assertion (`Map.plugins`, no `widgets`; `ENABLED_PLUGINS.key=='enabled_plugins'`, no `ENABLED_WIDGETS`) | PASS (`model+config OK`) |
| Zero case-insensitive `widget` matches in models.py + persistent_config.py | PASS (`grep clean: ZERO widget refs in both files`) |
| `0001_baseline.py` and `0024` byte-for-byte unchanged | PASS (empty `git diff`) |
| Isolated `persistent_config` import succeeds | PASS |
| `app.api.main` import intentionally broken (plan-02 boundary) | CONFIRMED (`ImportError: cannot import name 'ENABLED_WIDGETS'`) |
| No orphaned throwaway test DBs after run | PASS (`NONE`) |

Migration revision id: **`0025_widgets_to_plugins_rename`** (down_revision `0024`).

## Plugin ID Value Preservation

The migration only renames the column NAME and the config KEY — it never touches row values. The
round-trip test seeds and asserts the real plugin ID value `["legend"]` survives upgrade -> downgrade
-> re-upgrade unchanged. No `measurement`/`legend` string literal was modified anywhere in this plan.

## Intentional App-Import Break (Plan 02 Boundary)

BY DESIGN, `import app.api.main` fails after this plan with
`ImportError: cannot import name 'ENABLED_WIDGETS' from 'app.core.persistent_config'`. The sole
remaining consumer of the old name is `app/modules/settings/router.py` (verified: it is the only file
in `app/` still referencing `ENABLED_WIDGETS`), whose rename is plan 02 (wave 2) scope. This plan did
NOT touch settings/router.py and did NOT run any full-app-import tests — its verification used an
isolated `persistent_config` import per the plan's instructions.

## Deviations from Plan

None affecting behavior. Two minor reconciliations against the plan's interface block (which the
planner flagged as possibly drifted):

1. **persistent_config ref set was smaller than the plan listed.** The plan's interface block guessed
   the `ENABLED_WIDGETS` object used `env_var=`, `env_default_factory=`, and a `description=` string.
   The real object uses `type_=`, `env_default=None`, `tab="map"`, and `label=`. I renamed only the
   widget-bearing parts that actually exist (header `# -- Widgets --`, object name, `key`, `label`, and
   the `:128` comment), preserving the real field structure. The plan's hard gate (ZERO case-insensitive
   `widget` matches) still passes, so no `widget` token was left behind.

2. **Round-trip test driver.** The plan suggested a generic sync engine; the project has psycopg v3
   (not psycopg2), so the test derives its URL from `settings.test_database_url_sync`
   (`postgresql+psycopg://...`). This is a driver-selection detail, not a logic change.

## Threat Model Compliance

- **T-1161-02 (mitigate):** Round-trip test (Task 2) proves downgrade restores original column/key
  names AND preserves the seeded value — satisfied.
- **T-1161-01 / T-1161-03 (accept):** `RENAME COLUMN` is O(1) metadata-only; the config `UPDATE` is an
  exact-match on the unique `key` PK (0 or 1 row) — behavior matches the accepted dispositions.
- **T-1161-SC:** No new dependencies introduced (existing alembic/sqlalchemy/psycopg only). N/A.

No new security surface introduced.

## Notes for Plan 02 (Wave 2)

- The DB column is now `catalog.maps.plugins` and the config key is `enabled_plugins`.
- `Map.plugins` and `ENABLED_PLUGINS` (key `enabled_plugins`) are the new ORM/config names to import.
- `app/modules/settings/router.py` still imports the removed `ENABLED_WIDGETS` — fixing this consumer
  (plus the Map/Settings API schema fields per BE-RENAME-04/05) is plan 02's job and will restore
  `import app.api.main`.

## Self-Check: PASSED

- Files: all 5 created/modified files present on disk.
- Commits: `3d3acef8`, `24e54d1c`, `fc2af6a4` all resolve via `git cat-file -e`.
