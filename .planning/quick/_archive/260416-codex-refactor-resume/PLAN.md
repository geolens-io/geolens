---
description: Resume and complete the backend package restructuring started by Codex
status: validated
slug: codex-refactor-resume
---

# Resume Codex Backend Refactoring — Validated Plan

## Source of Truth

Target architecture is defined by the **third-party QA audit** (the "handoff document").
Codex was executing that audit's 10-phase plan. This plan picks up where Codex stopped.

---

## Audit Phase Completion Map

| Audit Phase | Description | Status | Notes |
|-------------|------------|--------|-------|
| 1. Establish structure | Create `api/`, `core/`, `modules/`, `processing/`, `standards/`, `platform/`, `observability/` | **DONE** | All top-level dirs exist |
| 2. Move root infra | config, db, logging, runtime, deps, edition, marketplace, public_urls → `core/` | **MOSTLY DONE** | 3 files incomplete: `edition.py` and `persistent_config.py` have reverse shims (core → old); `public_urls.py` is DUPLICATED in both locations |
| 3. Move observability + worker | health, metrics, worker_health → `observability/`; worker → `platform/jobs/` | **PARTIAL** | `observability/` exists with shims; old `health/`, `metrics/`, `worker.py`, `worker_health.py` still contain real code |
| 4. Move domain modules | auth, admin, audit, settings, embed_tokens, catalog → `modules/` | **NOT DONE** | 70 forward-pointing shims (`from app.old import *`); real code still in old dirs |
| 5. Rename services → sources | `services/` → `modules/catalog/sources/` | **NOT DONE** | Shim structure exists; `arcgis.py` and `wfs.py` moved to `adapters/` subdir |
| 6. Split datasets internally | `datasets/` → `datasets/api/` + `datasets/domain/` | **NOT DONE** | Shim structure exists |
| 7. Move processing modules | ai, embeddings, export, ingest, raster, tiles, vector → `processing/` | **NOT DONE** | 40 shims; real code in old dirs |
| 8. Move standards | ogc, stac, dcat → `standards/` | **NOT DONE** | 9 shims; real code in old dirs |
| 9. Add api/router.py | Aggregate router composition | **MOSTLY DONE** | Real code, but 3 imports still use old paths (`config_ops`, `extensions`, `middleware`) |
| 10. Remove shims | Delete backward-compat shims | **NOT DONE** | — |

---

## Codex's Shim Strategy

```
Direction of current shims (132 files):
NEW file (app/modules/admin/router.py)  →  from app.admin.router import *  →  OLD file (real code)

What needs to happen (flip):
OLD file (app/admin/router.py)  →  from app.modules.admin.router import *  →  NEW file (real code)
```

For each module: replace new shim with real code, update imports, convert old file to backward-compat shim.

---

## Verified Risks

### BLOCKER — Procrastinate Task Names

**Problem**: Procrastinate derives task names from `func.__module__ + "." + func.__name__` (verified in procrastinate 3.7.3 source: `utils.py:147-154`, `tasks.py:107-108`). When `ingest_file` moves from `app.ingest.tasks` to `app.processing.ingest.tasks`, its `__module__` changes. Any in-flight jobs in `procrastinate_jobs` with `task_name = 'app.ingest.tasks.ingest_file'` would fail with `TaskNotFound`.

**The plan's original mitigation (shim re-exports) does NOT work**: `from app.processing.ingest.tasks import *` re-exports the same Python objects with their NEW `__module__`. Procrastinate registers them under the new name only.

**Fix**: Add `aliases` to every `@task_app.task()` decorator when moving:
```python
@task_app.task(queue="ingest", retry=2, aliases=["app.ingest.tasks.ingest_file"])
async def ingest_file(...):
```

**Affected tasks** (8 total):
| File | Task Function |
|------|--------------|
| `ingest/tasks.py` | `ingest_file` (line 741) |
| `ingest/tasks.py` | `ingest_service` (line 992) |
| `ingest/tasks.py` | `reupload_file` (line 1302) |
| `ingest/tasks.py` | `reupload_service` (line 1506) |
| `ingest/tasks.py` | `ingest_raster` (line 1869) |
| `ingest/tasks.py` | `ingest_vrt` (line 2087) |
| `ingest/tasks.py` | `regenerate_vrt` (line 2276) |
| `embeddings/tasks.py` | `embed_record` (line 11) |

`app.raster.cog` is in `import_paths` but has zero `@task_app.task()` decorators — remove from `import_paths`.

### CRITICAL — Test Mock Patches (231 across 25 files)

Every `patch("app.ingest.tasks.X")` targets a specific module namespace. After the flip, patches must target the NEW path where the function is DEFINED.

**Action**: Update test patches batch-by-batch as each module moves. Most are mechanical `app.X.Y` → `app.{new}.X.Y` replacements, automatable with sed.

### HIGH — Phase 2 Incomplete (3 root files)

- `app/edition.py` — real code at root; `core/edition.py` is a reverse shim (`from app.edition import *`)
- `app/persistent_config.py` — real code at root; `core/persistent_config.py` is a reverse shim
- `app/public_urls.py` — **DUPLICATED**: both root and `core/` have real code with minor docstring diffs

**Action**: Flip these in wave 1. Delete duplicate `core/public_urls.py`, move real `app/public_urls.py` there, leave shim at old path.

### HIGH — `health ↔ config_ops` Circular Dependency

```
health/service.py:85      → from app.config_ops.service import check_oidc_endpoint  (lazy)
config_ops/service.py:407 → from app.health.service import _check_cache, _check_storage, _probe  (lazy)
```
Both are lazy imports (inside functions). Safe as-is. Update paths when modules move.

### HIGH — `api/router.py` and `api/main.py` Still Use Old Paths

`api/router.py:11` imports from `app.config_ops.router` (old path).
`api/main.py:21-29` imports from `app.extensions`, `app.middleware.*` (old paths).

**Action**: Update these imports after wave 2 (when those modules move).

### MEDIUM — Wave 2 Modules Have No Pre-existing Shim Directories

`config_ops/`, `sandbox/`, `extensions/`, `assets/`, `middleware/` have NO target directories created by Codex. These are NOT shim flips — they require creating new directories and moving files from scratch.

Similarly, `observability/health/` is missing shims for `service.py` and `schemas.py` (only `worker.py` has one).

### MEDIUM — Mixed Import Paths Already in Old Code

Some old files already import from new paths:
- `datasets/router_data.py` imports from `app.modules.catalog.validation.*`
- `datasets/router_reupload.py` imports from `app.processing.ingest.validation`
- `embeddings/tasks.py` imports from `app.processing.ingest.tasks`

**Action**: When flipping these files, leave imports that already use canonical new paths unchanged. Only update imports that use old paths.

### MEDIUM — Alembic env.py (12 model imports)

```python
import app.auth.models           # → app.modules.auth.models
import app.datasets.models       # → app.modules.catalog.datasets.domain.models
import app.collections.models    # → app.modules.catalog.collections.models
# ... 9 more
```
Backward-compat shims keep this working during transition. Update to canonical paths in wave 7.

### MEDIUM — conftest.py Dead Code

`conftest.py:157-161` patches `main_module.engine` and `main_module.async_session`, but `app.main` shim doesn't export those. Lines 201-202 restore them. All dead code.

**Action**: Remove lines 157, 160-161, 201-202 in wave 7.

### LOW — Docker Entrypoints

All work via shims. Update in wave 7:
- `Dockerfile:52` — `app.main:app` → `app.api.main:app`
- `docker-compose.yml:105` — same
- `scripts/api-entrypoint.sh:73` — same
- `scripts/worker-entrypoint.sh:58` — `python -m app.worker` → `python -m app.platform.jobs.worker`

### LOW — Logger `__name__` Changes

50+ files. Module names change in structured logs. Only matters if log filtering references module names.

---

## Execution Plan

**Rollback strategy**: Each wave is one atomic commit. Rollback = `git revert <commit-sha>`. Shims ensure both old and new import paths resolve, so partial completion is always a safe intermediate state.

### Wave 0: Pre-flight
1. Create feature branch: `git checkout -b refactor/backend-restructure`
2. Verify app imports: `python -c "from app.api.main import app"`
3. Run tests to establish baseline: `cd backend && uv run pytest tests/ -x --timeout=30`
4. Verify Procrastinate task name format in source:
   ```python
   python -c "from app.ingest.tasks import ingest_file; print(ingest_file.name)"
   ```
   Expected: `app.ingest.tasks.ingest_file` (dotted module path — confirms aliases are needed)

### Wave 1: Complete Phase 2 + Start Phase 3 (Observability)
**Fix phase 2 gaps** (no pre-existing shim — create from scratch):
- Delete duplicate `core/public_urls.py`, move real `app/public_urls.py` → `core/public_urls.py`, leave shim at old path
- Move real `app/edition.py` → `core/edition.py`, flip the reverse shim
- Move real `app/persistent_config.py` → `core/persistent_config.py`, flip the reverse shim

**Phase 3 — observability** (create new files — no shims exist for health service/schemas):
- `health/service.py`, `health/schemas.py` → `observability/health/` (create new)
- `metrics/instrumentator.py`, `metrics/jobs.py`, `metrics/pool.py` → `observability/metrics/` (overwrite shims)
- `worker_health.py` → `observability/health/worker.py` (overwrite shim)
- `worker.py` → `platform/jobs/worker.py` (create new)
- Old files become backward-compat shims

**Verify**: `python -c "from app.observability.health.service import check_health; from app.health.service import check_health"`

### Wave 2: Unmapped Modules (no pre-existing shims — create directories)
- `middleware/` → `api/middleware/` (create `api/middleware/`, move files, leave shims)
- `config_ops/` → `platform/config_ops/` (create dir)
- `sandbox/` → `platform/sandbox/` (create dir)
- `extensions/` → `platform/extensions/` (create dir)
- `assets/` → `platform/assets/` (create dir)
- `models/base.py` → delete (already exists as `core/db/session.py:Base`)
- `utils/` → stays at `app/utils/` (audit agrees)

**After moves**: Update `api/router.py:11` and `api/main.py:21-29` to use canonical paths for moved modules.

### Wave 3: Domain Modules (audit phases 4–6)
**Batch 3a — Leaf modules** (flip shims — target dirs exist):
- `audit/` → `modules/audit/`
- `settings/` → `modules/settings/`
- `validation/` → `modules/catalog/validation/`

**Batch 3b — Auth** (depended on by nearly everything):
- `auth/` → `modules/auth/` (including `oauth/`, `providers/`)

**Batch 3c — Catalog domain**:
- `collections/` → `modules/catalog/collections/`
- `datasets/` → `modules/catalog/datasets/` (with `api/` + `domain/` split per audit phase 6)
- `features/` → `modules/catalog/features/`
- `layers/` → `modules/catalog/layers/`
- `maps/` → `modules/catalog/maps/`
- `records/` → `modules/catalog/records/`
- `search/` → `modules/catalog/search/`
- `services/` → `modules/catalog/sources/` (rename; note `arcgis.py`/`wfs.py` → `adapters/` subdir)
- `embed_tokens/` → `modules/embed_tokens/`
- `admin/` → `modules/admin/`

### Wave 4: Processing Modules (audit phase 7) — HIGHEST RISK WAVE

- `ai/` → `processing/ai/`
- `embeddings/` → `processing/embeddings/`
- `export/` → `processing/export/`
- `ingest/` → `processing/ingest/`
- `raster/` → `processing/raster/`
- `tiles/` → `processing/tiles/`
- `vector/` → `processing/vector/`

**CRITICAL — Procrastinate task migration**:
1. When moving `ingest/tasks.py`, add `aliases` to all 7 task decorators:
   ```python
   @task_app.task(queue="ingest", retry=2, aliases=["app.ingest.tasks.ingest_file"])
   async def ingest_file(...):
   ```
2. When moving `embeddings/tasks.py`, add alias to `embed_record`:
   ```python
   @task_app.task(queue="ingest", retry=1, aliases=["app.embeddings.tasks.embed_record"])
   async def embed_record(...):
   ```
3. Update `import_paths` to new paths:
   ```python
   import_paths=["app.processing.ingest.tasks", "app.processing.embeddings.tasks"]
   ```
   (Remove `app.raster.cog` — has zero task decorators)
4. Keep backward-compat shims at old paths for non-Procrastinate imports

### Wave 5: Standards (audit phase 8)
- `ogc/` → `standards/ogc/`
- `stac/` → `standards/stac/`
- `dcat/` → `standards/dcat/`

### Wave 6: Platform Infrastructure (complete audit phase 3)
- `cache/` → `platform/cache/` (overwrite shims)
- `storage/` → `platform/storage/` (overwrite shims)
- `jobs/` → `platform/jobs/` (overwrite shims)

### Wave 7: Import Standardization + Tests + Entrypoints
- Replace ALL remaining old import paths with canonical new paths across the codebase
- Update 231 test mock patches across 25 test files
- Clean up conftest.py:
  - Remove dead `main_module` patches (lines 157, 160-161, 201-202)
  - Update `import app.database as db_module` → `import app.core.db as db_module`
  - Update `import app.health.service` → `import app.observability.health.service`
  - Update `from app.config import settings` → `from app.core.config import settings`
- Update Alembic `env.py` — 12 model imports to canonical paths
- Update Docker/compose/scripts entrypoints
- **Verify**: full test suite passes

### Wave 8: Cleanup (audit phase 10)
- Delete old empty directories
- Remove backward-compat shims (or keep for Alembic/Docker if preferred)
- Verify Procrastinate aliases can be removed: check `procrastinate_jobs` table for old task names
- Final circular import audit
- Final smoke test: app start, worker start, health endpoint

---

## Per-Module Flip Procedure

For each module being moved:

```
1. Read all files in old dir (app/X/)
2. Read all files in new dir (app/{target}/X/) — currently shims
3. For each .py file in old dir:
   a. Copy content to corresponding new dir file (overwriting the shim)
   b. Update imports within the file:
      - from app.config import → from app.core.config import
      - from app.database import → from app.core.db import
      - from app.dependencies import → from app.core.dependencies import
      - Cross-module refs: use new canonical paths for modules already moved
      - Keep old paths for modules not yet moved (shims will resolve)
      - LEAVE imports that already use canonical new paths unchanged
   c. Replace old file with backward-compat shim:
      from app.{target}.X import *  # noqa: F403
4. Verify both import paths work:
   python -c "from app.{target}.X.router import router; from app.X.router import router"
5. Atomic commit
```

**For modules WITHOUT pre-existing shim dirs** (wave 1 health, wave 2 all):
- Step 2 becomes: Create the target directory with `__init__.py`
- Step 3a becomes: Move file to new location (no shim to overwrite)

---

## Estimated Scope

| Wave | Audit Phases | Files | Commits | Risk |
|------|-------------|-------|---------|------|
| 0 | — | 0 | 0 | None |
| 1 | 2 (fix) + 3 | ~20 | 1 | Medium |
| 2 | — (unmapped) | ~15 | 1 | Medium |
| 3 | 4, 5, 6 | ~100 | 4 | High |
| 4 | 7 | ~50 | 1 | **Critical** (Procrastinate) |
| 5 | 8 | ~15 | 1 | Low |
| 6 | 3 (infra) | ~15 | 1 | Medium |
| 7 | — (standardize) | ~80 | 2 | High (test patches) |
| 8 | 10 (cleanup) | ~30 | 1 | Low |
| **Total** | | **~325** | **~12** | |

---

## Abort Criteria

Stop and reassess if:
- Circular import that can't be resolved with lazy imports
- Procrastinate alias mechanism doesn't work as expected (test with a single task first)
- Test suite failures that can't be traced to import path issues
- More than 3 files require logic changes (not just import updates) to work in new location
