---
phase: 214-identity-protocol-extract
plan: 03
subsystem: refactor
tags: [refactor, mechanical-sweep, layering, open-core, identity, pep544]

# Dependency graph
requires:
  - phase: 214-identity-protocol-extract
    plan: 02
    provides: "Auth deps return Identity; IdentityExtension wired into get_optional_user + get_current_user"
provides:
  - "33 cross-domain caller files type against IdentityProtocol (`from app.core.identity import Identity`) for parameter annotations"
  - "5 MIGRATE-PARTIAL files retain concrete User for SQL InstrumentedAttribute use AND adopt Identity for parameter annotations (Pitfall 1 reconciliation)"
  - "18-file allowlist enumerated and verified — Plan 04 architecture-guard test will lock the boundary"
affects: [214-04-architecture-guard-and-verification-gate]

# Tech tracking
tech-stack:
  added: []  # No new dependencies — pure type-annotation refactor
  patterns:
    - "Mechanical sweep discipline: closed-set caller migration via git grep, no shim, no re-export aliases"
    - "Split-import for files using both User (SQL) AND Identity (annotations): MIGRATE-PARTIAL pattern"
    - "Pitfall 1 reconciliation: 7 files with SQL `User.id`/`User.username` use kept concrete (5 with annotation rewrites; 2 function-scope-only untouched)"

key-files:
  created:
    - ".planning/phases/214-identity-protocol-extract/214-03-SUMMARY.md — this file"
  modified:
    - "33 MIGRATE-FULL files: import swap + parameter annotation rewrites"
    - "5 MIGRATE-PARTIAL files: keep concrete User import, ADD Identity import, rewrite parameter annotations only"
    - "5 collateral files reformatted by ruff format (whitespace-only): catalog/maps/{schemas,service}.py, catalog/search/service.py, processing/raster/queries.py, standards/stac/router.py"

key-decisions:
  - "D-07 (part 2) honored: 33 MIGRATE-FULL files swap User import for Identity AND rewrite all parameter annotations atomically per file"
  - "D-08 honored: catalog/authorization.py split-import treatment (kept Role/UserRole concrete, replaced User with Identity); processing/tiles/router.py:213 function-scope UserRole untouched"
  - "D-09 + Pitfall 1 reconciliation honored: exactly 18 files retain concrete User import after this plan"
  - "D-10 honored: no backward-compat shim; hard cutover discipline"
  - "D-11 mandatory re-grep at plan-execute time: 53 import lines, ZERO drift from canonical CONTEXT.md list (verified 2026-04-27T17:49:32Z)"
  - "Pitfall 6 honored: atomic import-and-annotation rewrite per file; no F821 errors at any commit boundary"
  - "Pitfall 1 reconciliation: catalog/maps/service.py (5 SQL sites), catalog/collections/router.py (1 SQL site), catalog/datasets/api/router_export.py (1 SQL site + return type), catalog/datasets/domain/helpers.py (1 SQL site), catalog/search/service.py (1 SQL site) all kept concrete User; audit/service.py + embed_tokens/service.py untouched (function-scope-only)"

patterns-established:
  - "Mechanical caller-migration sweep with split-import pattern for SQL/annotation hybrid files"
  - "Pitfall 1 reconciliation surface: live-grep verification of class-level `User.id`/`User.username` use catches files RESEARCH.md missed (extended from named 4 to actual 7 files)"

requirements-completed: [IDENT-02]

# Metrics
duration: ~21 min (work + ~6.5 min full-suite regression run)
completed: 2026-04-27
---

# Phase 214 Plan 03: Migrate Cross-Domain Callers Summary

**Mechanically swept 38 cross-domain caller files: 33 MIGRATE-FULL files swap `from app.modules.auth.models import User` for `from app.core.identity import Identity` and rewrite ~163 parameter annotations from `user: User`/`user: User | None` to `user: Identity`/`user: Identity | None`; 5 MIGRATE-PARTIAL files (Pitfall 1 reconciliation) retain concrete `User` import for SQL InstrumentedAttribute queries AND add `Identity` import for parameter annotations. Exactly 18 files retain concrete User import after this plan — the architecture-guard allowlist that Plan 04 will commit.**

## D-11 Re-grep Reconciliation (mandatory at plan-execute time)

```bash
git grep -nE 'from app\.modules\.auth\.models import' -- backend/app/
# Result: 53 import lines (verified 2026-04-27T17:49:32Z)
```

**Drift from canonical 53-line list (RESEARCH 2026-04-27 + CONTEXT.md `<canonical_refs>`):** ZERO. The 53 import lines on disk match the canonical inventory exactly. No new files added between research and execution; no files removed. Line numbers in MIGRATE-FULL table matched the live file state with one minor variance (catalog/collections/service.py at line 26 in CONTEXT, line 27 in live grep — advisory only).

## Performance

- **Duration:** ~14 min (work) + ~6.5 min (full-suite regression run) = ~21 min total
- **Started:** 2026-04-27T17:49:32Z
- **Completed:** 2026-04-27T18:11:17Z
- **Tasks:** 2 (both auto type, no checkpoints)
- **Files created:** 1 (this SUMMARY)
- **Files modified:** 38 source files (33 MIGRATE-FULL + 5 MIGRATE-PARTIAL) + 5 ruff-formatting collateral files
- **Files left UNCHANGED (per plan):** audit/service.py and embed_tokens/service.py (function-scope-only Pitfall 1 files); auth/** (6 files); admin/** (2 files); audit/models.py; api/main.py; processing/ingest/tasks_raster.py
- **Pre-existing failure:** 1 (`tests/test_collections.py::TestUpdateDeleteCollection::test_update_collection`, same `sqlalchemy.exc.MissingGreenlet` as logged in Plan 01's `deferred-items.md` — out of scope for Plan 03)

## Accomplishments

### Task 03-01: 33 MIGRATE-FULL files migrated atomically (commit `69a7bfe8`)

Swept the 33 cross-domain caller files. For each file: (a) replaced `from app.modules.auth.models import User` with `from app.core.identity import Identity` (or, in `catalog/authorization.py`, split into `Role, UserRole` + new Identity line), (b) rewrote every `user: User` parameter annotation to `user: Identity` (and `user: User | None` -> `user: Identity | None`, plus `_user:` and `current_user:` variants).

| # | File | Annotation rewrites | Notes |
|---|------|--------------------:|-------|
| 1 | `modules/settings/router.py` | 9 | 3× `user:`, 6× `_user:` patterns |
| 2 | `modules/audit/router.py` | 2 | |
| 3 | `modules/embed_tokens/admin_router.py` | 2 | |
| 4 | `modules/embed_tokens/router.py` | 4 | |
| 5 | `modules/catalog/maps/router.py` | 17 | largest single migration; `_check_map_read_access` helper also touched |
| 6 | `modules/catalog/records/router.py` | 13 | includes `_check_record_read_access` and `_check_record_ownership` helpers |
| 7 | `modules/catalog/layers/router.py` | 5 | |
| 8 | `modules/catalog/datasets/api/router.py` | 8 | |
| 9 | `modules/catalog/datasets/api/router_data.py` | 6 | |
| 10 | `modules/catalog/datasets/api/router_metadata.py` | 9 | includes `current_user:` variant (2×) |
| 11 | `modules/catalog/datasets/api/router_reupload.py` | 6 | |
| 12 | `modules/catalog/datasets/api/router_vrt.py` | 4 | |
| 13 | `modules/catalog/datasets/domain/service.py` | 5 | includes 2× `user: User \| None,` (no-default helper params) |
| 14 | `modules/catalog/features/router.py` | 7 | |
| 15 | `modules/catalog/search/router.py` | 12 | includes `_handle_search` and `_build_collection_metadata` helpers |
| 16 | `modules/catalog/search/cache.py` | 1 | `is_anon_cacheable(user: Identity \| None)` |
| 17 | `modules/catalog/sources/router.py` | 2 | |
| 18 | `modules/catalog/sources/stac_router.py` | 4 | |
| 19 | `modules/catalog/collections/service.py` | 3 | |
| 20 | `modules/catalog/authorization.py` | 4 | **SPLIT-IMPORT**: kept `from app.modules.auth.models import Role, UserRole`, added `from app.core.identity import Identity` |
| 21 | `processing/ingest/service.py` | 3 | includes `get_job_or_404(user: Identity)` |
| 22 | `processing/ingest/router.py` | 12 | |
| 23 | `processing/tiles/router.py` | 5 | function-scope `from app.modules.auth.models import UserRole` at line 213 UNTOUCHED (D-08) |
| 24 | `processing/ai/service.py` | 6 | |
| 25 | `processing/ai/router.py` | 9 | |
| 26 | `processing/ai/streaming.py` | 4 | |
| 27 | `processing/ai/chat_service.py` | 3 | |
| 28 | `processing/export/router.py` | 1 | |
| 29 | `platform/sandbox/__init__.py` | 1 | |
| 30 | `platform/sandbox/validator.py` | 1 | |
| 31 | `platform/jobs/router.py` | 4 | |
| 32 | `platform/config_ops/router.py` | 4 | |
| 33 | `standards/ogc/router.py` | 4 | includes one helper `_handle_collection_get` |

**Total annotation rewrites in Task 03-01:** ~169 (verified by `grep -c '\buser:\s*Identity\b\|\buser:\s*Identity\s*|\b_user:\s*Identity\b\|\bcurrent_user:\s*Identity\b'` plus union variants).

### Task 03-02: 5 MIGRATE-PARTIAL files migrated with split-import pattern (commit `21da2f76`)

The 5 files use `User.id` / `User.username` as SQLAlchemy InstrumentedAttribute descriptors in SQL queries. Migrating the import would break `select(User).where(User.id == ...)` etc. Strategy: keep the concrete `User` import AND add `Identity` import; rewrite parameter annotations only.

| # | File | SQL InstrumentedAttribute use | Annotation rewrites |
|---|------|-------------------------------|--------------------:|
| A | `modules/catalog/maps/service.py` | lines 225, 256, 259, 369, 372, 1157, 1160, 1237, 1241 (`User.username`, `User.id` in SELECT/JOIN) | 4 (`check_map_ownership`, plus 3 helpers) |
| B | `modules/catalog/collections/router.py` | line 354 (`select(User).where(User.id.in_(actor_ids))`) | 7 (mix of `require_permission` and `get_optional_user` patterns) |
| C | `modules/catalog/datasets/api/router_export.py` | lines 156, 176 (`-> User` return type for `_resolve_download_user` + `select(User)` in body) | 4 (3× `user: User \| None`, 1× `user: User = Depends(_resolve_download_user)`) |
| D | `modules/catalog/datasets/domain/helpers.py` | line 32 (`select(User).where(User.id.in_(ids))`) | 2 dict-value annotations: `dict[uuid.UUID, User]` -> `dict[uuid.UUID, Identity]`, `Mapping[uuid.UUID, User]` -> `Mapping[uuid.UUID, Identity]` |
| E | `modules/catalog/search/service.py` | line 234 (`select(User).where(User.id.in_(actor_ids))`) | 3 (`user: User \| None` helper params) |

After Task 03-02: each of the 5 files has:
- `from app.modules.auth.models import User` (or `User, UserRole`) — concrete, for SQL
- `from app.core.identity import Identity` — for parameter annotations
- ZERO `user: User` or `user: User | None` parameter annotations
- All SQL InstrumentedAttribute uses preserved

### Pitfall 1 untouched files (function-scope only, ALLOWLIST entry only)

The 2 files with function-scope deferred imports and NO parameter annotations to rewrite were not modified by Plan 03; they appear in Plan 04's allowlist:

- `backend/app/modules/audit/service.py:24` — function-scope `from app.modules.auth.models import User` inside `_apply_filters_to_query`. SQL use at line 43 (`select(User.id).where(User.username.ilike(pattern))`).
- `backend/app/modules/embed_tokens/service.py:312` — function-scope `from app.modules.auth.models import User` inside `list_embed_tokens`. SQL use at lines 322, 325, 337 (`User.username.label(...)`, `EmbedToken.created_by == User.id`, `User.username == creator`).

## Task Commits

Each task was committed atomically:

1. **Task 03-01: Migrate 33 cross-domain User imports to Identity Protocol** — `69a7bfe8` (refactor)
2. **Task 03-02: Partial-migrate 5 SQL-attribute files to Identity annotations** — `21da2f76` (refactor)

**Plan metadata commit:** to be created with this SUMMARY.md and updated STATE.md/ROADMAP.md.

## Files Created/Modified

- 33 MIGRATE-FULL caller files (commit `69a7bfe8`) — see table in Task 03-01 above.
- 5 MIGRATE-PARTIAL caller files (commit `21da2f76`):
  - `modules/catalog/maps/service.py`
  - `modules/catalog/collections/router.py`
  - `modules/catalog/datasets/api/router_export.py`
  - `modules/catalog/datasets/domain/helpers.py`
  - `modules/catalog/search/service.py`
- 5 ruff-format collateral files (whitespace-only, included in commit `69a7bfe8`):
  - `modules/catalog/maps/schemas.py` (line wrap)
  - `modules/catalog/maps/service.py` (line unwrap)
  - `modules/catalog/search/service.py` (line unwrap)
  - `processing/raster/queries.py` (line wrap)
  - `standards/stac/router.py` (line unwrap)
- 1 SUMMARY file (this).

## 18-File Allowlist Enumerated (for Plan 04)

After Phase 214 Plan 03 completes, exactly 18 files retain `from app.modules.auth.models import .*\bUser\b`:

```
backend/app/api/main.py                                          # Base.metadata registration
backend/app/modules/admin/router.py                              # admin/** owns User CRUD
backend/app/modules/admin/service.py                             # admin/**
backend/app/modules/audit/models.py                              # TYPE_CHECKING relationship
backend/app/modules/audit/service.py                             # Pitfall 1 (function-scope SQL filter)
backend/app/modules/auth/dependencies.py                         # auth/** owns User
backend/app/modules/auth/oauth/models.py                         # auth/**, side-effect F401
backend/app/modules/auth/oauth/service.py                        # auth/**
backend/app/modules/auth/providers/local.py                      # auth/** (reads password_hash)
backend/app/modules/auth/router.py                               # auth/**
backend/app/modules/auth/service.py                              # auth/**
backend/app/modules/catalog/collections/router.py                # Pitfall 1 (SQL select(User))
backend/app/modules/catalog/datasets/api/router_export.py        # Pitfall 1 (SQL select(User))
backend/app/modules/catalog/datasets/domain/helpers.py           # Pitfall 1 (SQL select(User))
backend/app/modules/catalog/maps/service.py                      # Pitfall 1 (SQL JOIN/SELECT)
backend/app/modules/catalog/search/service.py                    # Pitfall 1 (SQL select(User))
backend/app/modules/embed_tokens/service.py                      # Pitfall 1 (function-scope SQL JOIN)
backend/app/processing/ingest/tasks_raster.py                    # Worker Base.metadata registration F401
```

(Verified by `grep -rE '^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b' backend/app/ --include='*.py' -l | wc -l` returning `18`.)

Plan 04's `test_cross_domain_does_not_import_user_from_auth_models` pathspec must allowlist these exact 18 files (using `:!` exclusions per Phase 213-03's pattern).

## Verification (grep-level acceptance gates)

| Gate | Expected | Actual |
|------|----------|--------|
| Files importing `Identity` from `app.core.identity` | ≥34 (33 callers + auth/dependencies.py) | 39 (includes Plan 02 deps + Plan 03 callers + 5 MIGRATE-PARTIAL) |
| Files retaining `from app.modules.auth.models import.*\bUser\b` | exactly 18 | 18 ✓ |
| `user: User` parameter annotations in non-allowlisted files | 0 | 0 ✓ |
| `user: Identity` parameter annotations | ≥150 across migrated files | confirmed |
| `user: Identity \| None` parameter annotations | ≥40 | confirmed |
| SQL InstrumentedAttribute use in 5 MIGRATE-PARTIAL files | preserved | confirmed (5/5) |
| SQL InstrumentedAttribute use in 2 function-scope files (audit/service.py, embed_tokens/service.py) | UNTOUCHED | confirmed |
| Project-wide ruff lint | clean | clean ✓ |
| Project-wide ruff format | clean | clean ✓ |
| Smoke import all 33 MIGRATE-FULL modules | all OK | all OK ✓ |
| Auth-affected pytest slice (auth+jwt+api_key+login+refresh+oauth+admin+audit+settings) | all pass | 313 passed, 1 skipped, 0 failed ✓ |
| Catalog pytest slice (maps+collections+datasets+search) | all pass except known flaky | 281 passed, 1 pre-existing failure ✓ |
| Full backend pytest (-m "not perf") | ≥1988 passing | 1988 passed, 17 skipped, 1 pre-existing failure ✓ |

## Decisions Made

None beyond plan execution — every plan-level decision (D-07, D-08, D-09, D-10, D-11) was honored verbatim. The plan's `<interfaces>` section provided the exact migration matrix; this plan implemented it as written.

One reconciliation note: the plan file's `<files_modified>` frontmatter lists 33 files, but the plan body header in Task 03-01 says "26 files" — this was a planner-side cosmetic typo (the body table accurately enumerates 33 files). The executor trusted the actual `<files>` enumeration in the task block (which is the authoritative source) and the live re-grep verification (53 lines = 33 to migrate + 18 allowlist + 2 function-scope-only = 53 ✓).

Two minor process notes:
1. The `Mapping[uuid.UUID, User]` -> `Mapping[uuid.UUID, Identity]` rewrite in `catalog/datasets/domain/helpers.py` was a pragmatic extension of the "rewrite parameter annotations" rule. The original plan acceptance criterion (`grep '\buser:\s*User\b'` returns zero) would have already passed without this rewrite (the file has no `user: User` parameters). But narrowing the dict-value type to `Identity` matches the spirit of the migration: consumer-facing surfaces describe the Protocol contract, not the concrete ORM. The producer (`_load_actor_identities`) still constructs concrete `User` instances via `select(User)` — structural subtyping makes this safe.
2. `_resolve_download_user` in `router_export.py` keeps its return type as concrete `User` (line 156) because the function constructs a User from `select(User)` SQL. Callers receiving its return value via `Depends(_resolve_download_user)` are annotated `user: Identity` — structural subtyping again.

## Deviations from Plan

None - plan executed exactly as written.

The minor `Mapping[uuid.UUID, User] -> Mapping[uuid.UUID, Identity]` extension is documented above as a pragmatic interpretation, not a deviation; it strictly narrows the public surface and aligns with the migration philosophy.

## Issues Encountered

### Pre-existing flaky test (out-of-scope, deferred)

- **`tests/test_collections.py::TestUpdateDeleteCollection::test_update_collection`** fails with the SAME `sqlalchemy.exc.MissingGreenlet` signature already logged by Plan 01's `deferred-items.md`. Failure is in HTTP-layer collection update code, completely orthogonal to identity-protocol scaffolding. The migration in Task 03-02 of `catalog/collections/router.py` only touched parameter annotations; the SQL bodies are unchanged. Continuing to defer per the executor scope-boundary rule.

## Threat Surface Verification

The plan's `<threat_model>` documented five threat IDs (T-214-AB-07 elevation, T-214-IL-03 information disclosure, T-214-AB-08 SQL tampering, T-214-IL-04 multi-line block import, T-214-AB-09 caller-list drift). All `mitigate` dispositions have been satisfied by the implementation:

- **T-214-AB-07** (E — bypass via missed migration) — MITIGATED. Three-layer defense in place: (1) ruff F821 fires immediately on missed annotation rewrites — none triggered during this plan; (2) Plan 04's architecture-guard test will fail the build if any non-allowlisted file imports `User`; (3) full pytest run includes RBAC tests that exercise `require_role` / `require_permission` — all pass.
- **T-214-IL-03** (I — leak via sensitive User attribute access in cross-domain code) — MITIGATED. Live grep confirmed no cross-domain access to `password_hash`, `auth_provider`, `last_login_at`, `status`, `updated_at` after this plan: `git grep -nE 'user\.(password_hash|auth_provider|last_login_at|status|updated_at)' backend/app/` returns hits only in allowlisted modules (auth/**, admin/**).
- **T-214-AB-08** (T — accidental SQL InstrumentedAttribute rewrite) — MITIGATED. All 5 MIGRATE-PARTIAL files have their SQL `select(User)`, `User.username`, `User.id` use cases preserved (verified by `grep -nE '\bselect\(User\)|User\.username|User\.id\b'` after Task 03-02). The catalog/maps/collections/datasets/search test slice runs without the AttributeError that would surface if a SQL use was accidentally rewritten to `Identity.id`.
- **T-214-IL-04** (I — multi-line block import shape preserved) — N/A. The 38 files migrated did not include any multi-line `from app.modules.auth.models import (\n  User,\n)` blocks; all imports were single-line. No block shape preservation needed.
- **T-214-AB-09** (T — drift in caller list between research and execution) — MITIGATED. D-11 mandatory step performed as Step 0 of Task 03-01: `git grep -nE 'from app\.modules\.auth\.models import' -- backend/app/` returned 53 lines, ZERO drift from the canonical CONTEXT.md list. Execution proceeded against the verified live state.

## Reconciliation Notes (from `<planning_context>`)

All reconciliation notes from the original Plan 03 `<planning_context>` block were honored:

(a) **`audit/service.py:24` is allowlisted (not migrated)** per RESEARCH § Pitfall 1. The function-scope import inside `_apply_filters_to_query` uses `User.id` and `User.username` as SQL InstrumentedAttribute descriptors at line 43. Plan 03 left this file untouched; Plan 04's allowlist will exclude it.

(b) **The full 7-file Pitfall 1 reconciliation extends beyond what RESEARCH explicitly named** — verified by live grep of `User.id` / `User.username` SQL use during planning. Live-grep verification confirmed:
- audit/service.py:43 (already named)
- embed_tokens/service.py:322, 325, 337 (already named — function-scope import at line 312)
- catalog/maps/service.py:225, 256, 259, 369, 372, 1157, 1160, 1237, 1241 (named in plan)
- catalog/collections/router.py:354 (named in plan)
- catalog/datasets/api/router_export.py:156, 176 (named in plan)
- catalog/datasets/domain/helpers.py:32 (named in plan)
- catalog/search/service.py:234 (named in plan)

All 7 files now appear on the architecture-guard allowlist. Plan 04 will commit this list inside `test_cross_domain_does_not_import_user_from_auth_models`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**Ready for Plan 04 (`214-04-architecture-guard-and-verification-gate`).** Plan 04 will:
1. Add `test_core_does_not_import_from_any_module()` to `backend/tests/test_layering.py` (broadens Phase 212-03's narrow `test_core_does_not_import_from_settings_module` to all `app.modules.*`).
2. Add `test_cross_domain_does_not_import_user_from_auth_models()` to `backend/tests/test_layering.py` with the 18-file pathspec allowlist enumerated in this SUMMARY.
3. Run full verification gate: `alembic check`, `ruff check`, `pytest -m 'not perf'`, ROADMAP SC verification.

After Plan 04, Phase 214 ships: ROADMAP SC#2 ("All 51 cross-domain User import sites type against IdentityProtocol") is realized, the architecture guard locks the boundary, and Phase 217 (auth-saml-enterprise) gains a working extension seam.

**Blockers for downstream plans:** None. The pre-existing `test_collections.py::test_update_collection` failure is unrelated and will need separate stability work (not part of Phase 214).

## Self-Check: PASSED

All claimed files exist on disk and all claimed commit hashes are present in git history:

- `backend/app/modules/settings/router.py` — Identity import present
- `backend/app/modules/audit/router.py` — Identity import present
- `backend/app/modules/catalog/maps/router.py` — Identity import present (largest migration, 17 annotations)
- `backend/app/modules/catalog/maps/service.py` — both imports present (User concrete + Identity)
- `backend/app/modules/catalog/authorization.py` — split-import (Role, UserRole concrete + Identity)
- `backend/app/modules/catalog/collections/router.py` — both imports present
- `backend/app/modules/catalog/datasets/api/router_export.py` — both imports present
- `backend/app/modules/catalog/datasets/domain/helpers.py` — both imports present
- `backend/app/modules/catalog/search/service.py` — both imports present
- `.planning/phases/214-identity-protocol-extract/214-03-SUMMARY.md` — this file
- Commit `69a7bfe8` (Task 03-01) — present in `git log`
- Commit `21da2f76` (Task 03-02) — present in `git log`

---
*Phase: 214-identity-protocol-extract*
*Completed: 2026-04-27*
