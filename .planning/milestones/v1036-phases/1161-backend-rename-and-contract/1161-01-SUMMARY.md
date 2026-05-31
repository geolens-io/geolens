---
phase: 1161-backend-rename-and-contract
plan: 01
subsystem: backend
tags: [migration, rename, schema, app-settings, persistent-config, breaking]
dependency_graph:
  requires: []
  provides: [catalog.maps.plugins-column, enabled_plugins-config-key, Map.plugins-orm, ENABLED_PLUGINS]
  affects: [backend, alembic, catalog-maps, app-settings, persistent-config]
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
  - "The persisted config store is catalog.app_settings (the AppSetting model, schema=catalog) — the brief/REQUIREMENTS 'persistent_config' table name is fictional; the migration UPDATEs catalog.app_settings"
  - "maps column ops pass schema='catalog'; the config UPDATE is schema-qualified catalog.app_settings"
  - "Round-trip test provisions its own uuid-suffixed throwaway Postgres DB (psycopg v3) with extensions+role+schemas, builds the URL from env (not app.core.config) so it does not trigger conftest's shared-template session fixture"
  - "app.api.main import left intentionally broken (settings/router.py still imports ENABLED_WIDGETS) — that consumer rename is plan 02"
metrics:
  duration: "75m"
  completed: "2026-05-30"
---

# Phase 1161 Plan 01: Backend Rename & Contract (Wave 1) Summary

Reversible Alembic migration `0025` renames `catalog.maps.widgets` -> `plugins` and the
`enabled_widgets` config key (stored in `catalog.app_settings`) -> `enabled_plugins`, with the `Map`
ORM model and `persistent_config.py` updated to match — a hard breaking cut with a symmetric
downgrade, proven by an isolated upgrade/downgrade/re-upgrade round-trip test that preserves row
values.

## What Was Built

**1. Migration `0025_widgets_to_plugins_rename.py`** (BE-RENAME-01, BE-RENAME-02)
- `revision = "0025_widgets_to_plugins_rename"`, `down_revision = "0024"` (the real head revision id,
  confirmed via `ScriptDirectory` — NOT the filename, NOT the brief's fictional `a3f8c21d9e04`).
- `upgrade()`:
  - `op.alter_column("maps", "widgets", new_column_name="plugins", schema="catalog")` — O(1)
    metadata-only `RENAME COLUMN` in the `catalog` schema; JSONB array values untouched.
  - `op.execute("UPDATE catalog.app_settings SET key='enabled_plugins' WHERE key='enabled_widgets'")`
    — in-place key rename, value preserved.
- `downgrade()` reverses both symmetrically (`plugins`->`widgets`, `enabled_plugins`->`enabled_widgets`).
- Resolves as the single alembic head (no branch conflict).

**2. Round-trip test `test_migration_0025_plugins_rename.py`** (BE-RENAME-01 acceptance)
- Provisions its own uuid-suffixed throwaway Postgres DB (parallel-safe under `-n 4`), runs the real
  `alembic upgrade head` -> `downgrade -1` -> `upgrade +1` cycle against it, drops it in teardown.
  Deliberately avoids conftest's session template / per-test clone fixtures so it never corrupts
  shared schema other tests depend on (model documented in a module docstring).
- Builds the DB URL straight from the `POSTGRES_*` env, NOT from `app.core.config.settings` —
  importing app settings would trigger conftest's autouse session DB fixture (which migrates the
  shared `geolens_test` template), coupling this isolated test to shared state.
- **Driver split:** alembic gets an `postgresql+asyncpg://` URL (env.py runs via
  `async_engine_from_config`; a sync `+psycopg` URL under that async engine silently fails to persist
  DDL), while the reflection/seed engine uses `postgresql+psycopg://` (sync).
- Provisions the full migration-chain prerequisites on the bare DB: extensions
  (postgis/pg_trgm/vector/unaccent), the `data` schema, and the cluster-level `geolens_readonly` role
  — these are normally set up by `scripts/init-db.sh`, which a bare `CREATE DATABASE` does not inherit.
  (`env.py` itself creates the `catalog` schema before stamping.)
- Seeds `enabled_plugins = ["legend"]` in `catalog.app_settings` and asserts: plugins present /
  widgets absent after upgrade; revert to `widgets` / `enabled_widgets` with the `["legend"]` value
  preserved after downgrade; plugins / `enabled_plugins` restored after re-upgrade. The `legend` ID
  value survives the full cycle.

**3. ORM + persistent_config rename** (BE-RENAME-03)
- `models.py`: `Map.widgets` -> `Map.plugins` (`Mapped[list | None] = mapped_column(JSONB,
  nullable=True, default=None)` unchanged; comment updated to plugin wording).
- `persistent_config.py`: `ENABLED_WIDGETS` -> `ENABLED_PLUGINS` with `key="enabled_plugins"`,
  `label="Enabled Plugins"`, the `# -- Plugins --` section header, and the `:128` env_default comment
  — all renamed. Zero case-insensitive `widget` references remain in either file.

## Verification Results

| Check | Result |
|-------|--------|
| Alembic graph: single head `0025`, `down_revision == "0024"` | PASS (`GRAPH=OK`) |
| Round-trip test (sequential) | PASS (`SEQ_EXIT=0`, `1 passed`) |
| Round-trip test under `-n 4` (CI default) | PASS (`N4_EXIT=0`, `1 passed`) |
| No orphaned throwaway test DBs after run | PASS (`ORPHAN_DBS=NONE`) |
| Model+config import (`Map.plugins`, no `widgets`; `ENABLED_PLUGINS.key=='enabled_plugins'`, no `ENABLED_WIDGETS`) | PASS (`MODEL_CONFIG_IMPORT=OK`) |
| Zero case-insensitive `widget` matches in models.py + persistent_config.py | PASS (`WIDGET_GREP=CLEAN`) |
| `0001_baseline.py` and `0024` byte-for-byte unchanged (committed + working tree) | PASS (empty `git diff`) |
| `app.api.main` import intentionally broken (plan-02 boundary) | CONFIRMED (`APP_MAIN_IMPORT=BROKEN_AS_EXPECTED`, `ImportError: cannot import name 'ENABLED_WIDGETS'`) |

Migration revision id: **`0025_widgets_to_plugins_rename`** (down_revision `0024`).

## Commits

| Commit | Type | Content |
|--------|------|---------|
| `0d1505ba` | feat | Migration `0025_widgets_to_plugins_rename.py` (initial) |
| `f2a3eed2` | test | Round-trip test (initial) |
| `078cc76a` | feat | `Map.widgets->plugins` + `ENABLED_WIDGETS->ENABLED_PLUGINS` |
| `03f395b4` | docs | First SUMMARY/REQUIREMENTS/STATE pass (premature — superseded by this corrected SUMMARY) |
| `6aae8e85` | fix | Migration UPDATE target -> `catalog.app_settings` (the real table) |
| `7a13d4db` | fix | Throwaway-DB prerequisites (extensions/role/schemas) + env-derived URL |
| `d751ac88` | docs | Interim SUMMARY/STATE correction (superseded by the final docs commit) |
| `f2789a4a` | fix | alembic gets an asyncpg URL (psycopg under async engine silently no-ops DDL) |

## Plugin ID Value Preservation

The migration only renames the column NAME and the config KEY — it never touches row values. The
round-trip test seeds and asserts the real plugin ID value `["legend"]` survives upgrade -> downgrade
-> re-upgrade unchanged. No `measurement`/`legend` string literal was modified anywhere in this plan.

## Intentional App-Import Break (Plan 02 Boundary)

BY DESIGN, `import app.api.main` fails after this plan with
`ImportError: cannot import name 'ENABLED_WIDGETS' from 'app.core.persistent_config'`. The sole
remaining consumer of the old name is `app/modules/settings/router.py` (verified: lines 27, 822, 826
— it is the only file in `app/` still referencing `ENABLED_WIDGETS`), whose rename is plan 02 (wave 2)
scope. This plan did NOT touch settings/router.py and did NOT run any full-app-import tests — its
verification used an isolated `persistent_config` import per the plan's instructions.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migration targeted a nonexistent `persistent_config` table; corrected to `catalog.app_settings`**
- **Found during:** Task 2 (round-trip test execution)
- **Issue:** The brief, REQUIREMENTS (BE-RENAME-02/03), and PLAN all said the `enabled_widgets` key
  lives in a table named `persistent_config` and instructed `UPDATE persistent_config SET key=...`.
  **No such table exists.** The persisted PersistentConfig store is `catalog.app_settings` (the
  `AppSetting` model in `app/core/db/models.py:19-24`, `__tablename__="app_settings"`,
  `schema="catalog"`; created in `0001_baseline.py:109`). The original UPDATE failed with
  `asyncpg.exceptions.UndefinedTableError: relation "persistent_config" does not exist` during
  `alembic upgrade` — meaning the migration was NON-RUNNABLE on every database (it would have broken
  `alembic upgrade head` in production and in CI conftest's shared-template setup).
- **Fix:** Both `upgrade()` and `downgrade()` now `UPDATE catalog.app_settings SET key=...`. Value
  preservation and exact-match semantics unchanged. Migration docstring corrected.
- **Files modified:** backend/alembic/versions/0025_widgets_to_plugins_rename.py
- **Commit:** `6aae8e85`

**2. [Rule 3 - Blocking] Round-trip test needed full init-db prerequisites on the throwaway DB**
- **Found during:** Task 2
- **Issue:** A bare `CREATE DATABASE` lacks what `scripts/init-db.sh` provisions. `0001_baseline`
  RAISEs without postgis; `0023_geolens_readonly_role` GRANTs to the cluster role `geolens_readonly`
  (created by init-db.sh, not a migration) and references schemas `catalog`/`data`. Replaying the
  chain from scratch failed first on missing postgis, then on the missing `data` schema / role.
  Additionally, importing `app.core.config` for DB params pulled in conftest's autouse session DB
  fixture, which tried to migrate the shared template with the (then-broken) migration.
- **Fix:** The throwaway-DB fixture now (a) builds the URL from `POSTGRES_*` env directly
  (no app.core.config import), and (b) creates the extensions, `data` schema, and the
  `geolens_readonly` role before running alembic — mirroring init-db.sh.
- **Files modified:** backend/tests/test_migration_0025_plugins_rename.py
- **Commit:** `7a13d4db`

**3. [Rule 1 - Bug] Round-trip test passed alembic a sync (psycopg) URL; alembic's async engine silently no-op'd the DDL**
- **Found during:** Task 2 (final verification)
- **Issue:** `alembic/env.py` runs migrations via `async_engine_from_config` (an async engine). I
  initially handed the alembic `Config` a `postgresql+psycopg://` (sync) URL. Under the async engine
  this ran the whole migration chain WITHOUT persisting DDL to the throwaway DB and then stamped
  `alembic_version`, so reflection found no `catalog.maps` (`NoSuchTableError`). This is a test-harness
  driver bug — the migration itself is correct.
- **Fix:** The alembic `Config` now gets a `postgresql+asyncpg://` URL (`_async_db_url`), while the
  reflection/seed engine stays on `postgresql+psycopg://` (sync). Verified in isolation (`plugins?
  True widgets? False`) and via the test passing sequentially and under `-n 4`.
- **Files modified:** backend/tests/test_migration_0025_plugins_rename.py
- **Commit:** `f2789a4a`

Minor reconciliation (not a behavior change): the plan's interface block guessed the
`ENABLED_WIDGETS` object used `env_var=`/`env_default_factory=`/`description=`; the real object uses
`type_=`/`env_default=None`/`tab=`/`label=`. Only the widget-bearing parts that actually exist were
renamed; the ZERO-`widget`-match gate passes.

## Threat Model Compliance

- **T-1161-02 (mitigate):** Round-trip test (Task 2) proves downgrade restores original column/key
  names AND preserves the seeded value — satisfied.
- **T-1161-01 / T-1161-03 (accept):** `RENAME COLUMN` is O(1) metadata-only; the config `UPDATE` is an
  exact-match on the unique `key` PK of `catalog.app_settings` (0 or 1 row) — behavior matches the
  accepted dispositions.
- **T-1161-SC:** No new dependencies introduced (existing alembic/sqlalchemy/psycopg only). N/A.

No new security surface introduced.

## Self-Check: PASSED

- Files: all 5 created/modified files present on disk.
- Commits: `0d1505ba`, `f2a3eed2`, `078cc76a` (+ docs `03f395b4`/`d751ac88`), `6aae8e85`, `7a13d4db`,
  `f2789a4a` all resolve via `git cat-file -e`.
- Earlier drafts of this SUMMARY listed fabricated commit hashes (`3d3acef8`/`24e54d1c`/`fc2af6a4`,
  then `b85ba2cb`/`b3f9aa76`/`8f2e4a1d`) — those were WRONG (I recorded hashes before running
  `git rev-parse`). All hashes above are the real ones, confirmed via `git log` / `git cat-file -e`
  post-commit.

## Notes for Plan 02 (Wave 2)

- The DB column is now `catalog.maps.plugins` and the config key is `enabled_plugins` (stored in
  `catalog.app_settings`).
- `Map.plugins` and `ENABLED_PLUGINS` (key `enabled_plugins`) are the new ORM/config names to import.
- `app/modules/settings/router.py` still imports the removed `ENABLED_WIDGETS` (lines 27, 822, 826) —
  fixing this consumer (plus the Map/Settings API schema fields per BE-RENAME-04/05) is plan 02's job
  and will restore `import app.api.main`.
- **Heads-up for plan 02's own work:** the brief/REQUIREMENTS use the fictional table name
  `persistent_config`; the real persisted-config table is `catalog.app_settings`. Any further config
  migrations must target `catalog.app_settings`.
