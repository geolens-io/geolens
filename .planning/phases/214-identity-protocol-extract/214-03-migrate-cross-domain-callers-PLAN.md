---
phase: 214-identity-protocol-extract
plan: 03
type: execute
wave: 3
depends_on: ["214-02"]
files_modified:
  - backend/app/modules/audit/router.py
  - backend/app/modules/embed_tokens/admin_router.py
  - backend/app/modules/embed_tokens/router.py
  - backend/app/modules/settings/router.py
  - backend/app/modules/catalog/maps/router.py
  - backend/app/modules/catalog/records/router.py
  - backend/app/modules/catalog/layers/router.py
  - backend/app/modules/catalog/datasets/api/router.py
  - backend/app/modules/catalog/datasets/api/router_data.py
  - backend/app/modules/catalog/datasets/api/router_metadata.py
  - backend/app/modules/catalog/datasets/api/router_reupload.py
  - backend/app/modules/catalog/datasets/api/router_vrt.py
  - backend/app/modules/catalog/datasets/domain/service.py
  - backend/app/modules/catalog/features/router.py
  - backend/app/modules/catalog/search/router.py
  - backend/app/modules/catalog/search/cache.py
  - backend/app/modules/catalog/sources/router.py
  - backend/app/modules/catalog/sources/stac_router.py
  - backend/app/modules/catalog/collections/service.py
  - backend/app/modules/catalog/authorization.py
  - backend/app/modules/catalog/maps/service.py
  - backend/app/processing/ingest/service.py
  - backend/app/processing/ingest/router.py
  - backend/app/processing/tiles/router.py
  - backend/app/processing/ai/service.py
  - backend/app/processing/ai/router.py
  - backend/app/processing/ai/streaming.py
  - backend/app/processing/ai/chat_service.py
  - backend/app/processing/export/router.py
  - backend/app/platform/sandbox/__init__.py
  - backend/app/platform/sandbox/validator.py
  - backend/app/platform/jobs/router.py
  - backend/app/platform/config_ops/router.py
  - backend/app/standards/ogc/router.py
autonomous: true
requirements: [IDENT-02]
requirements_addressed: [IDENT-02]
tags: [refactor, mechanical-sweep, layering, open-core, identity]

must_haves:
  truths:
    - "D-07 (part 2): Cross-domain caller files swap their `from app.modules.auth.models import User` import for `from app.core.identity import Identity`, and rewrite EVERY parameter annotation `user: User` → `user: Identity` (and `user: User | None` → `user: Identity | None`). The two-step migration is mandatory per RESEARCH § Pitfall 6 — doing only the import swap leaves dangling `User` references that ruff F821 flags immediately."
    - "D-08: Sites that import `Role` and/or `UserRole` together with `User` for SQL-filter use (e.g., `catalog/maps/service.py`'s `User, UserRole` import at line 19, `catalog/authorization.py`'s `Role, User, UserRole` import at line 21) keep `Role` and `UserRole` concrete. Only the `User` symbol in those imports is touched. For files where SQL queries also use `User.id`/`User.username` as `InstrumentedAttribute` descriptors, those files are ALLOWLISTED (kept concrete entirely) per the Pitfall 1 reconciliation below."
    - "D-09 + Pitfall 1 reconciliation: The architecture-guard allowlist for Plan 04 includes the 7 files where Pitfall 1's SQL-attribute concern applies: `audit/service.py`, `embed_tokens/service.py`, `catalog/maps/service.py`, `catalog/collections/router.py`, `catalog/datasets/api/router_export.py`, `catalog/datasets/domain/helpers.py`, `catalog/search/service.py`. These files KEEP concrete `User` import for SQL queries; their parameter annotations may still use `Identity` if the file imports both. Plan 03 ALSO migrates the parameter annotations in these files (where they exist) but DOES NOT remove the `User` import."
    - "D-10: No backward-compat re-export shim is left in `app.modules.auth.models`. No `Identity` re-export is added to `app.modules.auth`. The migration is a hard cutover."
    - "D-11: Mandatory re-grep at plan-execute time. Run `git grep -nE 'from app\\.modules\\.auth\\.models import' -- backend/app/` BEFORE making any edits and confirm the file count matches the canonical list (53 lines per RESEARCH live-grep 2026-04-27, OR drift to whatever the actual count is on the day Plan 03 runs). If new lines appeared (e.g., a quick task added a new router that imports User), include them in the migration. If existing lines disappeared, remove them from the file list."
    - "Behavior preservation: every endpoint that previously took `user: User = Depends(get_current_active_user)` now takes `user: Identity = Depends(get_current_active_user)`. The runtime object is unchanged (still a concrete `User` instance, structural subtype of `Identity`), so attribute reads (`.id`, `.username`, `.email`, `.roles`, `.is_active`, `.created_at`) work identically. Sensitive-attribute reads (`.password_hash`, `.auth_provider`, `.last_login_at`, `.status`, `.updated_at`) do NOT exist in the migrated files (verified by RESEARCH live grep — confined to allowlisted modules)."
    - "Behavior preservation: function-scope deferred imports (e.g., `embed_tokens/service.py:312` — but Pitfall 1 reconciles this back to allowlist; `processing/tiles/router.py:213` — imports `UserRole`, not `User`, so untouched) keep their deferral. Plan 03 only touches files that have `User` in the imported-names list."
    - "Test fixtures (under `backend/tests/`) construct `User(...)` directly and pass them to endpoint helpers. Since `User` structurally satisfies `Identity`, fixtures work unchanged. Plan 04's architecture-guard test pathspec excludes `:!backend/tests/` (D-19) so test fixtures don't trip the User-import guard."
    - "After this plan, exactly THESE 11 files retain `from app.modules.auth.models import .*\\bUser\\b` lines: (a) `auth/**` — 6 files (D-09), (b) `admin/router.py`, `admin/service.py` — 2 files (D-09), (c) `audit/models.py` (TYPE_CHECKING relationship), `api/main.py` (Base.metadata registration), `processing/ingest/tasks_raster.py` (worker registration) — 3 files. PLUS the 7 SQL-attribute files added by the Pitfall 1 reconciliation: `audit/service.py`, `embed_tokens/service.py`, `catalog/maps/service.py`, `catalog/collections/router.py`, `catalog/datasets/api/router_export.py`, `catalog/datasets/domain/helpers.py`, `catalog/search/service.py`. Total: 18 files retaining the concrete `User` import (Plan 04's architecture-guard test pathspec must allowlist all 18)."
    - "Reconciliation note (planning_context): The RESEARCH § Pitfall 1 reconciliation extends to MORE files than RESEARCH explicitly named. Live-grep verification on 2026-04-27 found SQL `User.id`/`User.username` attribute use in 7 files (audit/service.py at line 43, embed_tokens/service.py at lines 322+, catalog/maps/service.py at lines 224+/1156+, catalog/collections/router.py at line 353, catalog/datasets/api/router_export.py at line 175, catalog/datasets/domain/helpers.py at line 31, catalog/search/service.py at line 233). All 7 use `select(User).where(User.id == ...)` or `select(...User.username...)` patterns that BREAK if `User` is replaced with the `Identity` Protocol (which is not a SQLAlchemy InstrumentedAttribute holder). All 7 are added to the architecture-guard allowlist."
    - "Reconciliation note (planning_context): RESEARCH § Pitfall 9 is honored — Plan 02 already duplicated the wire-in across `get_optional_user` and `get_current_user` rather than refactoring `get_current_user` to delegate. Plan 03 inherits whatever Plan 02 produced; if Plan 02's smoke test passed, Plan 03 starts from a working green baseline."
  artifacts:
    - path: "backend/app/modules/audit/router.py"
      provides: "Migrated: User import → Identity import; user: User → user: Identity"
      contains: "from app.core.identity import Identity"
    - path: "backend/app/modules/catalog/authorization.py"
      provides: "Split import: keep `from app.modules.auth.models import Role, UserRole` AND add `from app.core.identity import Identity`. Function parameter annotations user: User|None → user: Identity|None"
      contains: "from app.core.identity import Identity"
    - path: "backend/app/modules/catalog/maps/service.py"
      provides: "ALLOWLISTED for User import (SQL InstrumentedAttribute use at lines 224, 255, 368, 1156, 1236) — keeps `from app.modules.auth.models import User, UserRole` AND adds `from app.core.identity import Identity` for parameter annotations"
      contains: "from app.core.identity import Identity"
  key_links:
    - from: "All migrated files"
      to: "backend/app/core/identity.py:Identity"
      via: "module-level import"
      pattern: "from app\\.core\\.identity import Identity"
    - from: "Plan 04 architecture-guard test pathspec"
      to: "All 18 allowlisted files"
      via: "git grep `:!path` exclusions"
      pattern: ":!backend/app"
---

<objective>
Mechanically sweep ~33 cross-domain caller files: swap `from app.modules.auth.models import User` for `from app.core.identity import Identity`, and rewrite every `user: User` / `user: User | None` parameter annotation to `user: Identity` / `user: Identity | None`. For 7 files where SQL queries use `User.id` / `User.username` as InstrumentedAttribute descriptors (per the Pitfall 1 reconciliation surfaced by live-grep verification on 2026-04-27), the file is added to the Plan 04 architecture-guard allowlist instead — those files KEEP `from app.modules.auth.models import User` for SQL use, but their FastAPI parameter annotations still get migrated to `Identity` so the function signatures consistently type against the Protocol surface.

Purpose: Realize ROADMAP SC#2 ("All 51 cross-domain `User` import sites across the 11 domains type against `IdentityProtocol` (or an alias of it), not the concrete SQLAlchemy class"). After this plan lands, no cross-domain code outside the 18-file allowlist imports the concrete `User` ORM. Plan 04's architecture-guard test then locks the boundary.

Output: ~33 files modified. Each file's diff is small (one import line swap, plus N parameter annotation rewrites — typically 1-10 per file). Total LOC delta: ~150 line changes across the 33 files. Full pytest baseline (≥1999 passing) holds because the Protocol/concrete-User contract is structural — no fixture, body, or test logic changes are needed.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/214-identity-protocol-extract/214-CONTEXT.md
@.planning/phases/214-identity-protocol-extract/214-RESEARCH.md
@.planning/phases/214-identity-protocol-extract/214-VALIDATION.md
@.planning/phases/214-identity-protocol-extract/214-01-SUMMARY.md
@.planning/phases/214-identity-protocol-extract/214-02-SUMMARY.md
@.planning/phases/213-catalog-authz-relocate/213-02-SUMMARY.md
@backend/app/core/identity.py
@backend/app/modules/auth/dependencies.py

<interfaces>
<!-- The exhaustive migration matrix. Run `git grep -nE 'from app\.modules\.auth\.models import' -- backend/app/` IMMEDIATELY before starting and reconcile the live count vs. this list — if drift exists, adjust the file list. -->

#### MIGRATE-FULL (26 files): swap `User` import → `Identity` import; rewrite all parameter annotations.

For each file below, the canonical migration is:
1. Find the line: `from app.modules.auth.models import User` (or `import User, UserRole` etc.).
2. If the import line is JUST `import User`: replace with `from app.core.identity import Identity` (and remove the original line).
3. If the import line is `import User, UserRole` (or any combination with other auth-models symbols): SPLIT into two imports — keep `from app.modules.auth.models import UserRole` (or whichever non-User names) AND add `from app.core.identity import Identity`.
4. Rewrite EVERY occurrence of `user: User` (parameter annotation) to `user: Identity`. Rewrite `user: User | None` to `user: Identity | None`. Use a search-and-replace; verify with grep after.
5. Verify ruff F821 (undefined name `User`) does NOT fire — the import-and-annotation rewrites must be atomic per file.

| # | File | Line | Current import | Notes |
|---|------|------|----------------|-------|
| 1 | `backend/app/modules/settings/router.py` | 12 | `from app.modules.auth.models import User` | parameter annotation rewrite only |
| 2 | `backend/app/modules/audit/router.py` | 31 | `from app.modules.auth.models import User` | param annotations at lines 51, 94, etc. |
| 3 | `backend/app/modules/embed_tokens/admin_router.py` | 10 | `from app.modules.auth.models import User` | param annotations |
| 4 | `backend/app/modules/embed_tokens/router.py` | 27 | `from app.modules.auth.models import User` | param annotations |
| 5 | `backend/app/modules/catalog/maps/router.py` | 25 | `from app.modules.auth.models import User` | many param annotations (~17 sites — see grep results); pure parameter use, no SQL InstrumentedAttribute reads in this file |
| 6 | `backend/app/modules/catalog/records/router.py` | 10 | `from app.modules.auth.models import User` | param annotations |
| 7 | `backend/app/modules/catalog/layers/router.py` | 11 | `from app.modules.auth.models import User` | param annotations |
| 8 | `backend/app/modules/catalog/datasets/api/router.py` | 27 | `from app.modules.auth.models import User` | param annotations |
| 9 | `backend/app/modules/catalog/datasets/api/router_data.py` | 22 | `from app.modules.auth.models import User` | param annotations |
| 10 | `backend/app/modules/catalog/datasets/api/router_metadata.py` | 21 | `from app.modules.auth.models import User` | param annotations |
| 11 | `backend/app/modules/catalog/datasets/api/router_reupload.py` | 20 | `from app.modules.auth.models import User` | param annotations |
| 12 | `backend/app/modules/catalog/datasets/api/router_vrt.py` | 18 | `from app.modules.auth.models import User` | param annotations |
| 13 | `backend/app/modules/catalog/datasets/domain/service.py` | 28 | `from app.modules.auth.models import User` | param annotations only — no SQL use of User |
| 14 | `backend/app/modules/catalog/features/router.py` | 14 | `from app.modules.auth.models import User` | param annotations |
| 15 | `backend/app/modules/catalog/search/router.py` | 18 | `from app.modules.auth.models import User` | param annotations only |
| 16 | `backend/app/modules/catalog/search/cache.py` | 12 | `from app.modules.auth.models import User` | param annotations |
| 17 | `backend/app/modules/catalog/sources/router.py` | 14 | `from app.modules.auth.models import User` | param annotations |
| 18 | `backend/app/modules/catalog/sources/stac_router.py` | 23 | `from app.modules.auth.models import User` | param annotations |
| 19 | `backend/app/modules/catalog/collections/service.py` | 26 | `from app.modules.auth.models import User` | param annotations only — no SQL use of User |
| 20 | `backend/app/modules/catalog/authorization.py` | 21 | `from app.modules.auth.models import Role, User, UserRole` | SPLIT: keep `from app.modules.auth.models import Role, UserRole`; ADD `from app.core.identity import Identity`. Param annotations at lines 35, 48, 98, 112, 137 rewrite to `Identity` |
| 21 | `backend/app/processing/ingest/service.py` | 19 | `from app.modules.auth.models import User` | param annotations |
| 22 | `backend/app/processing/ingest/router.py` | 22 | `from app.modules.auth.models import User` | param annotations |
| 23 | `backend/app/processing/tiles/router.py` | 20 | `from app.modules.auth.models import User` | MODULE-LEVEL — migrate. Note: line 213 has a function-scope `from app.modules.auth.models import UserRole` which is UNTOUCHED (D-08 — UserRole stays concrete; not `User`) |
| 24 | `backend/app/processing/ai/service.py` | 31 | `from app.modules.auth.models import User` | param annotations |
| 25 | `backend/app/processing/ai/router.py` | 41 | `from app.modules.auth.models import User` | param annotations |
| 26 | `backend/app/processing/ai/streaming.py` | 32 | `from app.modules.auth.models import User` | param annotations |
| 27 | `backend/app/processing/ai/chat_service.py` | 28 | `from app.modules.auth.models import User` | param annotations |
| 28 | `backend/app/processing/export/router.py` | 15 | `from app.modules.auth.models import User` | param annotations |
| 29 | `backend/app/platform/sandbox/__init__.py` | 17 | `from app.modules.auth.models import User` | param annotations |
| 30 | `backend/app/platform/sandbox/validator.py` | 17 | `from app.modules.auth.models import User` | param annotations |
| 31 | `backend/app/platform/jobs/router.py` | 13 | `from app.modules.auth.models import User` | param annotations |
| 32 | `backend/app/platform/config_ops/router.py` | 12 | `from app.modules.auth.models import User` | param annotations |
| 33 | `backend/app/standards/ogc/router.py` | 10 | `from app.modules.auth.models import User` | param annotations |

#### MIGRATE-PARTIAL — annotations only, KEEP concrete `User` import (Pitfall 1 reconciliation, allowlisted in Plan 04)

These 7 files use `User` as a SQLAlchemy InstrumentedAttribute holder in SQL queries. Migrating the import would break `select(User).where(User.id == ...)` etc. Strategy: keep `from app.modules.auth.models import User` (or `User, UserRole`) AND add `from app.core.identity import Identity`. Rewrite parameter annotations only.

| # | File | Line | Action |
|---|------|------|--------|
| A | `backend/app/modules/audit/service.py` | 24 | Function-scope deferred import inside `_apply_filters_to_query` — UNTOUCHED. The function does NOT have a `user: User` parameter; it takes scalar filter args. No annotations to rewrite. ALLOWLIST entry only. |
| B | `backend/app/modules/embed_tokens/service.py` | 312 | Function-scope deferred import inside `list_embed_tokens` — UNTOUCHED. SQL use at lines 322+. ALLOWLIST entry only. The `service.py` file does NOT have `user: User` parameter annotations elsewhere (verify with grep). |
| C | `backend/app/modules/catalog/maps/service.py` | 19 | `from app.modules.auth.models import User, UserRole` — KEEP. SQL use at lines 224, 255, 368, 1156, 1236. ADD `from app.core.identity import Identity`. Rewrite parameter annotations at lines 63 (`user: User`), 602, 648, 980 (`user: User | None`) → `Identity` / `Identity | None`. |
| D | `backend/app/modules/catalog/collections/router.py` | 15 | `from app.modules.auth.models import User` — KEEP (SQL use at line 353). ADD `from app.core.identity import Identity`. Rewrite parameter annotations to `Identity`. |
| E | `backend/app/modules/catalog/datasets/api/router_export.py` | 24 | `from app.modules.auth.models import User` — KEEP (SQL use at line 175). ADD `from app.core.identity import Identity`. Rewrite parameter annotations to `Identity`. |
| F | `backend/app/modules/catalog/datasets/domain/helpers.py` | 9 | `from app.modules.auth.models import User` — KEEP (SQL use at line 31). ADD `from app.core.identity import Identity`. Rewrite parameter annotations to `Identity`. |
| G | `backend/app/modules/catalog/search/service.py` | 31 | `from app.modules.auth.models import User` — KEEP (SQL use at line 233). ADD `from app.core.identity import Identity`. Rewrite parameter annotations to `Identity`. |

For files C-G: the file ends up with TWO User-related imports — `User` (concrete, for SQL) and `Identity` (Protocol, for annotations). Plan 04's allowlist excludes these 7 files from the architecture-guard test, so the lingering concrete `User` import does NOT cause a regression. This is the same pattern Plan 02 used for `auth/dependencies.py` (kept `User` for `select(User).where(User.id == user_id)` AND added `Identity` for return-type annotations).

#### NO-OP — keep concrete `User`, no annotation changes (already on allowlist per CONTEXT.md D-09)

These 11 lines (across 8 files) are NOT touched by Plan 03. Plan 04's allowlist covers them.

| File | Line | Reason |
|------|------|--------|
| `backend/app/api/main.py` | 26 | `Base.metadata` registration |
| `backend/app/modules/admin/router.py` | 33 | Admin CRUD on User |
| `backend/app/modules/admin/service.py` | 14, 296 | Admin CRUD on User |
| `backend/app/modules/audit/models.py` | 12 | TYPE_CHECKING `Mapped["User"]` relationship |
| `backend/app/modules/auth/dependencies.py` | 14 | auth/** owns User; Plan 02 retyped its public surface to `Identity` |
| `backend/app/modules/auth/models.py` | (defines User) | auth/** owns User |
| `backend/app/modules/auth/oauth/models.py` | 92 | auth/**, side-effect `# noqa: E402, F401` |
| `backend/app/modules/auth/oauth/service.py` | 10 | auth/** |
| `backend/app/modules/auth/providers/local.py` | 9 | auth/** |
| `backend/app/modules/auth/router.py` | 13 | auth/** |
| `backend/app/modules/auth/service.py` | 12 | auth/** |
| `backend/app/processing/ingest/tasks_raster.py` | 142 | Worker process `Base.metadata` registration `# noqa: F401` |
| `backend/app/processing/tiles/router.py` | 213 | function-scope `import UserRole` (not `User`) — D-08 keeps `UserRole` concrete |

#### Architecture-guard allowlist for Plan 04 — full enumeration

Plan 04's `test_cross_domain_does_not_import_user_from_auth_models` pathspec excludes these directories/files:

```
:!backend/app/modules/auth/
:!backend/app/modules/admin/
:!backend/app/modules/audit/models.py
:!backend/app/modules/audit/service.py             # Pitfall 1 reconciliation
:!backend/app/api/main.py
:!backend/app/processing/ingest/tasks_raster.py
:!backend/app/modules/embed_tokens/service.py      # Pitfall 1 reconciliation
:!backend/app/modules/catalog/maps/service.py      # Pitfall 1 reconciliation (SQL JOIN/SELECT)
:!backend/app/modules/catalog/collections/router.py  # Pitfall 1 reconciliation
:!backend/app/modules/catalog/datasets/api/router_export.py  # Pitfall 1 reconciliation
:!backend/app/modules/catalog/datasets/domain/helpers.py     # Pitfall 1 reconciliation
:!backend/app/modules/catalog/search/service.py    # Pitfall 1 reconciliation
:!backend/tests/                                   # test fixtures use User directly (D-19)
```

Plan 04 commits this exact list inside `test_cross_domain_does_not_import_user_from_auth_models`.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 03-01: Re-grep + migrate the 26 MIGRATE-FULL files (import swap + parameter annotation rewrites)</name>
  <files>
    backend/app/modules/settings/router.py, backend/app/modules/audit/router.py, backend/app/modules/embed_tokens/admin_router.py, backend/app/modules/embed_tokens/router.py, backend/app/modules/catalog/maps/router.py, backend/app/modules/catalog/records/router.py, backend/app/modules/catalog/layers/router.py, backend/app/modules/catalog/datasets/api/router.py, backend/app/modules/catalog/datasets/api/router_data.py, backend/app/modules/catalog/datasets/api/router_metadata.py, backend/app/modules/catalog/datasets/api/router_reupload.py, backend/app/modules/catalog/datasets/api/router_vrt.py, backend/app/modules/catalog/datasets/domain/service.py, backend/app/modules/catalog/features/router.py, backend/app/modules/catalog/search/router.py, backend/app/modules/catalog/search/cache.py, backend/app/modules/catalog/sources/router.py, backend/app/modules/catalog/sources/stac_router.py, backend/app/modules/catalog/collections/service.py, backend/app/modules/catalog/authorization.py, backend/app/processing/ingest/service.py, backend/app/processing/ingest/router.py, backend/app/processing/tiles/router.py, backend/app/processing/ai/service.py, backend/app/processing/ai/router.py, backend/app/processing/ai/streaming.py, backend/app/processing/ai/chat_service.py, backend/app/processing/export/router.py, backend/app/platform/sandbox/__init__.py, backend/app/platform/sandbox/validator.py, backend/app/platform/jobs/router.py, backend/app/platform/config_ops/router.py, backend/app/standards/ogc/router.py
  </files>
  <read_first>
    - .planning/phases/214-identity-protocol-extract/214-CONTEXT.md (D-07, D-08, D-09, D-11 — caller migration discipline; D-10 — no shim)
    - .planning/phases/214-identity-protocol-extract/214-RESEARCH.md (lines 562-643 — Caller Inventory authoritative live grep; lines 729-741 — Pitfall 6 atomic import-and-annotation rewrite; lines 992-1029 — caller migration diff canonical pattern; lines 1011-1029 — Sites that import User, UserRole together — KEEP UserRole concrete)
    - .planning/phases/213-catalog-authz-relocate/213-02-SUMMARY.md (companion plan that performed a similar 26-caller mechanical sweep — read for the discipline pattern)
    - backend/app/core/identity.py (verify Identity is exported)
    - backend/app/modules/auth/dependencies.py (verify Plan 02's retyped deps — `get_optional_user` returns `Identity | None`, `get_current_active_user` returns `Identity`; this is the contract callers will Depends() against)
    - backend/app/modules/catalog/authorization.py (full file — note line 21's `from app.modules.auth.models import Role, User, UserRole`; this file is migrated WITH the split-import treatment)
    - backend/app/modules/catalog/maps/router.py (full file — has the most parameter annotations to migrate, ~17 sites)
  </read_first>
  <action>
**Step 0 — Re-grep at plan-execute time (D-11 mandatory):**

```bash
cd /Users/ishiland/Code/geolens
git grep -nE 'from app\.modules\.auth\.models import' -- backend/app/ > /tmp/214-03-callers-live.txt
wc -l /tmp/214-03-callers-live.txt
```

Compare the live count and file list against the 53-line canonical list in CONTEXT.md `<canonical_refs>` "Code (caller files)". Expected count: 53 lines (verified RESEARCH 2026-04-27). If the live count differs:
- New lines (file added by a quick task between research and execution): include the file in the migration if it is cross-domain (apply MIGRATE-FULL pattern), or add to the allowlist if it has SQL InstrumentedAttribute use of `User` (apply MIGRATE-PARTIAL pattern; ALSO update Plan 04's allowlist before committing).
- Removed lines (file refactored away): drop it from this plan's file list.
- Modified line numbers (CONTEXT.md says line 31, file actually has it at line 32): use the live line — line numbers are advisory only.

Document the reconciliation in the SUMMARY at end of plan.

**Step 1 — Process the 26 MIGRATE-FULL files (one at a time, in the order listed in `<interfaces>`):**

For each file, the procedure is:

(a) Read the full file (or at minimum: the imports block AND every line containing `\bUser\b`). Use the Read tool, NOT a series of greps — knowing the surrounding context is critical for correct annotation rewrites.

(b) Edit the import line. The patterns are:

  - **Pattern 1 — Single import:** `from app.modules.auth.models import User` → `from app.core.identity import Identity` (single-line replacement).
  - **Pattern 2 — Mixed import (e.g., `catalog/authorization.py` line 21: `from app.modules.auth.models import Role, User, UserRole`):** SPLIT into two lines:
    ```python
    from app.modules.auth.models import Role, UserRole   # remove User from the list
    from app.core.identity import Identity                 # NEW second line, sorted into the app.core.* import group
    ```
  - **Pattern 3 — Multi-line block import (rare):** preserve block shape; remove `User` from the imported names; add the new `from app.core.identity import Identity` line above the modules-block.

  Verify isort order with `cd backend && uv run ruff check --select=I app/<path>/<file>.py`.

(c) Rewrite EVERY parameter annotation in the file:
  - `user: User` → `user: Identity`
  - `user: User | None` → `user: Identity | None`
  - `user: Optional[User]` → `user: Optional[Identity]` (rare; most code uses PEP 604 `| None`)
  - `users: list[User]` / `users: Sequence[User]` etc. → ditto with `Identity`

  IMPORTANT: only rewrite annotations where `User` is the parameter type. Do NOT rewrite:
  - Variable assignments like `user = User()` (creates a concrete User — would break the constructor call). These should not exist in the migrated files; if they do, the file is a candidate for the Pitfall 1 allowlist instead — STOP and check.
  - SQL queries like `select(User).where(...)` (uses User as InstrumentedAttribute holder). If these exist, the file is a Pitfall 1 candidate — STOP and check; if confirmed, move the file from MIGRATE-FULL to MIGRATE-PARTIAL.
  - Type-only references in docstrings (`:param user: A User instance`) — leave for now; cosmetic only.

  Use the Edit tool with `replace_all=False` and explicit context lines to ensure each rewrite is intentional. For files with many annotations (e.g., `catalog/maps/router.py` has ~17 sites), it's faster to use `replace_all=True` after verifying the regex matches only annotation contexts. Suggested safe regex pattern for `replace_all=True`:
  ```
  Find:    user: User
  Replace: user: Identity
  ```
  After applying `replace_all=True`, verify with `grep -nE "\buser:\s*User\b" backend/app/modules/catalog/maps/router.py` returns ZERO matches. Then handle `user: User | None` and `user: Optional[User]` similarly.

(d) Run ruff against the file: `cd backend && uv run ruff check app/<path>/<file>.py`. Expected: zero errors. If F821 (undefined name `User`) fires, an annotation was missed; grep for `\bUser\b` in the file and rewrite the missed site.

(e) Move to the next file.

**Step 2 — After all 26 files migrated, run a project-wide ruff check:**

```bash
cd backend && uv run ruff check app/
```

Expected: zero errors. If any F821 fires, the file is missing the `Identity` import OR has a `User` annotation that was missed; fix it.

**Step 3 — Verify the auth-affected test slice:**

```bash
cd backend && uv run pytest -k "auth or jwt or api_key or login or refresh or oauth or admin or audit or settings" -v --tb=short -q 2>&1 | tail -30
```

Expected: all tests pass.

**Step 4 — Run the full backend test suite:**

```bash
docker compose exec api uv run pytest -m 'not perf' --tb=short -q 2>&1 | tee /tmp/214-03-pytest.log | tail -10
```

(Fall back to `cd backend && uv run pytest -m 'not perf' --tb=short -q` if docker compose isn't available.)

Expected: ≥1999 passed; same skipped count as the post-Phase-213 baseline. Capture the exact summary line.

If any test fails:
- `ImportError: cannot import name 'User' from 'app.core.identity'` → `Identity` was misspelled or imported from the wrong module.
- `NameError: name 'User' is not defined` (at runtime) → an annotation was rewritten but the import line was not added (`Identity` import missing). Fix the import.
- `TypeError: Cannot instantiate abstract class IdentityProtocol` (extremely unlikely; only if a test fixture tried to construct `Identity()`) → `Identity` is a Protocol, not a class. Test fixtures should construct `User(...)` directly (Pitfall 9 of Phase 213's RESEARCH applies — fixtures use the concrete class).
- Tests that pass `user=User(...)` to a function with `user: Identity` parameter — these PASS at runtime (structural subtyping) and at type-check time (User IS-A Identity). If they fail at runtime, the failure is on a different attribute access, not on the type itself.

**Task 03-01 is the entire mechanical migration in one task** because the 26 file edits are functionally a single atomic refactor — splitting them across multiple tasks would risk intermediate states where ruff F821 fires (mismatched imports vs. annotations within the project).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && uv run ruff check app/ && uv run ruff format --check app/ && bash -c 'count=$(git grep -lE "from app.core.identity import Identity" -- backend/app/ | wc -l); echo "Files with Identity import: $count"; test "$count" -ge "33"' && uv run pytest -k "auth or jwt or api_key or login or refresh or oauth or admin or audit or settings or ai or ingest or maps" -v --tb=short -q 2>&1 | tail -10 | grep -E "[0-9]+ passed"</automated>
  </verify>
  <acceptance_criteria>
    - All 26 MIGRATE-FULL files import `Identity` from `app.core.identity` (verify with `for f in <list of 26 files>; do grep -q "^from app.core.identity import Identity$" "$f" || echo MISSING:$f; done` produces no MISSING output).
    - The 26 MIGRATE-FULL files do NOT have a top-level `from app.modules.auth.models import .*\bUser\b` (verify with `git grep -nE 'from app\.modules\.auth\.models import.*\bUser\b' -- <list of 26 files>` returns zero matches; the `import Role, UserRole` line in `catalog/authorization.py` is the only auth-models import that survives in those files).
    - Zero `user: User` parameter annotations exist anywhere outside the allowlist (verify with `git grep -nE '\buser:\s*User\b' -- backend/app/ ':!backend/app/modules/auth/' ':!backend/app/modules/admin/' ':!backend/app/api/main.py' ':!backend/app/modules/audit/service.py' ':!backend/app/modules/audit/models.py' ':!backend/app/processing/ingest/tasks_raster.py' ':!backend/app/modules/embed_tokens/service.py' ':!backend/app/modules/catalog/maps/service.py' ':!backend/app/modules/catalog/collections/router.py' ':!backend/app/modules/catalog/datasets/api/router_export.py' ':!backend/app/modules/catalog/datasets/domain/helpers.py' ':!backend/app/modules/catalog/search/service.py'` returns zero matches).
    - Project-wide ruff check passes (`cd backend && uv run ruff check app/` exits 0).
    - Project-wide ruff format passes (`cd backend && uv run ruff format --check app/` exits 0).
    - Auth-affected test slice passes (`cd backend && uv run pytest -k "auth or jwt or api_key or login or refresh or oauth or admin or audit or settings or ai or ingest or maps or features or search or sources or collections or layers or records or datasets or embed_tokens or sandbox or jobs or config_ops or ogc or export or tiles" -v --tb=short -q` exits 0).
    - Full backend test suite passes with ≥1999 tests (`docker compose exec api uv run pytest -m 'not perf' --tb=short -q` OR host fallback exits 0; final summary line shows `≥1999 passed`).
    - The reconciliation from `<planning_context>` is honored: NONE of the 7 Pitfall 1 files appear in this task's file list (Task 03-02 handles them with the partial-migration pattern). Verify with `for f in backend/app/modules/audit/service.py backend/app/modules/embed_tokens/service.py backend/app/modules/catalog/maps/service.py backend/app/modules/catalog/collections/router.py backend/app/modules/catalog/datasets/api/router_export.py backend/app/modules/catalog/datasets/domain/helpers.py backend/app/modules/catalog/search/service.py; do grep -q "from app.modules.auth.models import.*\bUser\b" "$f" && echo OK_concrete:$f || echo MISSING_CONCRETE:$f; done` — the 7 files all show `OK_concrete` (i.e., they STILL import the concrete User; Task 03-02 only ADDS the Identity import without removing User).
    - The `audit/service.py:24` reconciliation note is honored: `git grep -E 'from app\.modules\.auth\.models import' -- backend/app/modules/audit/service.py` still returns the function-scope import (untouched).
    - The 1999-test baseline holds with no regression.
  </acceptance_criteria>
  <done>
    All 26 MIGRATE-FULL files have their `User` imports replaced with `Identity` imports, parameter annotations rewritten to `Identity` / `Identity | None`. No F821 errors. Auth/RBAC/audit/settings/ingest/AI/maps/etc. test slices all pass. The project-wide ruff check and the ≥1999-test pytest run both pass. Cross-domain code now types against `IdentityProtocol` for these 26 files.
  </done>
</task>

<task type="auto">
  <name>Task 03-02: Migrate parameter annotations (only) for the 7 MIGRATE-PARTIAL Pitfall-1 files; KEEP concrete User import for SQL InstrumentedAttribute use</name>
  <files>
    backend/app/modules/catalog/maps/service.py
    backend/app/modules/catalog/collections/router.py
    backend/app/modules/catalog/datasets/api/router_export.py
    backend/app/modules/catalog/datasets/domain/helpers.py
    backend/app/modules/catalog/search/service.py
  </files>
  <read_first>
    - .planning/phases/214-identity-protocol-extract/214-CONTEXT.md (D-08 — sites that import Role/UserRole keep them concrete; D-09 — allowlist; D-19 — pathspec exclusions)
    - .planning/phases/214-identity-protocol-extract/214-RESEARCH.md (lines 661-682 — Pitfall 1 audit/service.py SQL-filter detail; lines 1011-1029 — sites that import User, UserRole together)
    - planning_context (system prompt — the reconciliation note: 7 files have SQL `User.id`/`User.username` use; Plan 04 allowlist must include all 7)
    - backend/app/modules/catalog/maps/service.py (full file — verify `User.username.label(...)`, `User.id`, `User.username` SQL uses at lines 224, 255, 368, 1156, 1236; verify parameter annotations at lines 63, 602, 648, 980)
    - backend/app/modules/catalog/collections/router.py (full file — verify SQL use at line 353; check parameter annotations)
    - backend/app/modules/catalog/datasets/api/router_export.py (full file — verify SQL use at line 175; check parameter annotations)
    - backend/app/modules/catalog/datasets/domain/helpers.py (full file — verify SQL use at line 31; check parameter annotations)
    - backend/app/modules/catalog/search/service.py (full file — verify SQL use at line 233; check parameter annotations)
  </read_first>
  <action>
NOTE: This task only modifies 5 of the 7 Pitfall-1 files. The other 2 (`audit/service.py`, `embed_tokens/service.py`) have ONLY function-scope deferred imports and NO parameter annotations to rewrite — they remain entirely untouched by Plan 03 (Plan 04's allowlist is what excludes them from the architecture-guard test).

For each of the 5 files in `<files>` above, the procedure is:

(a) Read the full file. Verify SQL InstrumentedAttribute use of `User` (e.g., `select(User).where(User.id == ...)`, `User.username.label(...)`, `User.id`, `User.username` in JOIN/SELECT clauses). Document the SQL usage line numbers in this task's SUMMARY.

(b) Locate the `from app.modules.auth.models import User` (or `from app.modules.auth.models import User, UserRole`) line. DO NOT REMOVE IT. The concrete `User` is needed for SQL queries.

(c) ADD a new import line: `from app.core.identity import Identity` in the appropriate `from app.core.*` group (alphabetical with other `app.core.*` imports; before `app.modules.*` imports per ruff isort).

(d) Rewrite parameter annotations:
  - `user: User` → `user: Identity` (only at function signatures; NOT at variable assignments or constructors)
  - `user: User | None` → `user: Identity | None`

(e) After the edit, the file has TWO User-related imports:
  - `from app.modules.auth.models import User` (or `User, UserRole`) — used in SQL queries
  - `from app.core.identity import Identity` — used in parameter annotations

  Both are legitimate. Plan 04's architecture-guard allowlist ensures the lingering concrete `User` import does not trigger a regression.

(f) Verify with grep that:
  - `grep -c "^from app.modules.auth.models import" <file>` ≥ 1 (concrete `User` import retained).
  - `grep -c "^from app.core.identity import Identity" <file>` equals 1 (Identity import added).
  - `grep -nE '\buser:\s*User\b' <file>` returns ZERO matches (all parameter annotations migrated).
  - `grep -nE '\bselect\(User\)|User\.username|User\.id\b' <file>` STILL has hits (SQL InstrumentedAttribute use is preserved).

(g) Run `cd backend && uv run ruff check <file>` — expected: zero errors.

**Per-file specifics:**

- `catalog/maps/service.py` (line 19, current: `from app.modules.auth.models import User, UserRole`):
  - Add `from app.core.identity import Identity` at the appropriate place (likely just before line 19; preserve the `User, UserRole` line as-is).
  - Rewrite `user: User` at line 63 (`async def check_map_ownership`) and lines 602, 648 (`user: User`) to `user: Identity`.
  - Rewrite `user: User | None` at line 980 to `user: Identity | None`.
  - Lines 224, 255, 368, 1156, 1236 use `User.username`/`User.id` in SQL — UNTOUCHED.

- `catalog/collections/router.py` (line 15, current: `from app.modules.auth.models import User`):
  - KEEP the User import. ADD `from app.core.identity import Identity`.
  - Rewrite parameter annotations to `Identity`.
  - Line 353 uses `select(User).where(User.id.in_(actor_ids))` — UNTOUCHED.

- `catalog/datasets/api/router_export.py` (line 24, current: `from app.modules.auth.models import User`):
  - KEEP. ADD Identity.
  - Rewrite annotations.
  - Line 175 SQL use UNTOUCHED.

- `catalog/datasets/domain/helpers.py` (line 9, current: `from app.modules.auth.models import User`):
  - KEEP. ADD Identity.
  - Rewrite annotations.
  - Line 31 SQL use UNTOUCHED.

- `catalog/search/service.py` (line 31, current: `from app.modules.auth.models import User`):
  - KEEP. ADD Identity.
  - Rewrite annotations.
  - Line 233 SQL use UNTOUCHED.

**After all 5 file edits:**

```bash
cd backend && uv run ruff check app/
cd backend && uv run ruff format --check app/
cd backend && uv run pytest -k "maps or collections or datasets or search" -v --tb=short -q 2>&1 | tail -10
docker compose exec api uv run pytest -m 'not perf' --tb=short -q 2>&1 | tee /tmp/214-03-pytest-final.log | tail -10
```

Expected: full ≥1999 baseline holds.

If a test fails with `AttributeError: type object 'IdentityProtocol' has no attribute 'id'` or `AttributeError: type object 'IdentityProtocol' has no attribute 'username'`:
- A SQL query was accidentally rewritten from `User.id` / `User.username` to `Identity.id` / `Identity.username` during the annotation sweep. Revert the SQL change; keep the concrete `User` reference in SQL.

If a test fails with `NameError: name 'Identity' is not defined`:
- The `from app.core.identity import Identity` import line was not added or was added to the wrong file scope. Add it.

If a test fails with `NameError: name 'User' is not defined`:
- The `from app.modules.auth.models import User` line was accidentally REMOVED. Restore it; this is a MIGRATE-PARTIAL file (D-09 + Pitfall 1 reconciliation), so the concrete import stays.
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && uv run ruff check app/ && uv run ruff format --check app/ && bash -c 'for f in app/modules/catalog/maps/service.py app/modules/catalog/collections/router.py app/modules/catalog/datasets/api/router_export.py app/modules/catalog/datasets/domain/helpers.py app/modules/catalog/search/service.py; do grep -q "^from app.modules.auth.models import" "$f" && grep -q "^from app.core.identity import Identity" "$f" || (echo MISSING:$f && exit 1); done' && bash -c 'for f in app/modules/catalog/maps/service.py app/modules/catalog/collections/router.py app/modules/catalog/datasets/api/router_export.py app/modules/catalog/datasets/domain/helpers.py app/modules/catalog/search/service.py; do grep -nE "\buser:\s*User\b" "$f" && (echo UNMIGRATED_ANNOTATION:$f && exit 1) || true; done; true' && uv run pytest -k "maps or collections or datasets or search" -v --tb=short -q 2>&1 | tail -10 | grep -E "[0-9]+ passed"</automated>
  </verify>
  <acceptance_criteria>
    - All 5 files have BOTH imports present:
      - `from app.modules.auth.models import User` (or `User, UserRole`) — verify with `for f in <5 files>; do grep -q "^from app.modules.auth.models import.*\bUser\b" "$f" || echo MISSING_USER:$f; done` produces no MISSING output.
      - `from app.core.identity import Identity` — verify with `for f in <5 files>; do grep -q "^from app.core.identity import Identity$" "$f" || echo MISSING_IDENTITY:$f; done` produces no MISSING output.
    - All 5 files have ZERO `user: User` parameter annotations (verify with `for f in <5 files>; do grep -nE '\buser:\s*User\b' "$f" || true; done` produces no output).
    - All 5 files retain their SQL InstrumentedAttribute uses of `User` (spot-check: `grep -nE '\bselect\(User\)|User\.username|User\.id\b' backend/app/modules/catalog/maps/service.py` returns ≥3 hits; same for the others).
    - Project-wide ruff check passes (`cd backend && uv run ruff check app/` exits 0).
    - Project-wide ruff format passes (`cd backend && uv run ruff format --check app/` exits 0).
    - The catalog/maps/collections/datasets/search test slice passes (`cd backend && uv run pytest -k "maps or collections or datasets or search" -v --tb=short -q` exits 0).
    - Full backend test suite passes with ≥1999 tests (`docker compose exec api uv run pytest -m 'not perf' --tb=short -q` OR host fallback exits 0).
    - The 18-file allowlist set is now complete and verifiable: exactly 18 files retain `from app.modules.auth.models import .*\bUser\b` (verify with `git grep -lnE 'from app\.modules\.auth\.models import.*\bUser\b' -- backend/app/ | wc -l` equals 18 — the 6 auth/** files, 2 admin/** files, audit/models.py, audit/service.py, api/main.py, processing/ingest/tasks_raster.py, embed_tokens/service.py, catalog/maps/service.py, catalog/collections/router.py, catalog/datasets/api/router_export.py, catalog/datasets/domain/helpers.py, catalog/search/service.py).
    - Plus exactly 1 file imports `UserRole` (NOT `User`) from auth.models without a `User` symbol — `processing/tiles/router.py:213` (function-scope) — verify with `grep -nE 'from app\.modules\.auth\.models import' backend/app/processing/tiles/router.py` returns the `UserRole` line.
  </acceptance_criteria>
  <done>
    All 5 MIGRATE-PARTIAL files retain concrete `User` import for SQL queries AND adopt `Identity` for parameter annotations. The Pitfall 1 reconciliation is fully realized; the architecture-guard allowlist for Plan 04 is now demonstrably necessary and sufficient. Full pytest baseline holds.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none introduced this plan) | This plan is a mechanical type-annotation refactor. No request boundary changes. The runtime objects flowing through endpoints are still concrete `User` instances; the type system now describes them as `Identity` (a structural superset narrower in surface). |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-214-AB-07 | E (Elevation) — bypass via missed migration | any cross-domain caller still importing concrete `User` outside the allowlist | mitigate | Three-layer defense per RESEARCH § Security Domain: (1) ruff F821 fires immediately if an annotation rewrites `user: User` without the `User` import being present (atomic two-step rewrite enforced by Pitfall 6); (2) Plan 04's `test_cross_domain_does_not_import_user_from_auth_models` architecture-guard test fails the build if any non-allowlisted file imports `User`; (3) the full pytest run includes RBAC integration tests that exercise `require_role` / `require_permission` — they would fail if a caller's annotation drift broke the dep chain. All three layers must be green for CI to pass. |
| T-214-IL-03 | I (Information disclosure) — leak via sensitive User attribute access in cross-domain code | callers that previously accessed `user.password_hash`, `user.auth_provider`, `user.last_login_at`, `user.status`, `user.updated_at` | mitigate | Live grep verification (RESEARCH § Risk surfaces): `grep -rn "user\.\(password_hash\|auth_provider\|last_login_at\|status\|updated_at\)" backend/app/` confirms no cross-domain access exists; all reads of these sensitive attributes are confined to allowlisted modules (auth/**, admin/**). After Plan 03, callers annotated `user: Identity` cannot read these attributes at the type-checking layer (pyright would flag the access); at runtime the attribute access would still succeed (the runtime object IS a User), but no cross-domain caller does this. Plan 04's architecture guard prevents future regressions by blocking the concrete `User` import outside the allowlist. |
| T-214-AB-08 | T (Tampering) — accidental SQL InstrumentedAttribute rewrite | the 5 MIGRATE-PARTIAL files (and 2 untouched function-scope files) | mitigate | Task 03-02's `<acceptance_criteria>` explicitly verifies that SQL InstrumentedAttribute uses (`select(User)`, `User.username`, `User.id`) are STILL PRESENT in the 5 files after the annotation sweep. If the sweep accidentally rewrote a SQL use to `Identity.id` (which would fail at runtime — `Identity` is a Protocol with no descriptors), the test slice for that file (`pytest -k maps`, `-k collections`, etc.) catches it immediately with `AttributeError: type object 'IdentityProtocol' has no attribute 'id'`. |
| T-214-IL-04 | I (Information disclosure) — multi-line block import shape preserved | catalog/datasets/api/router*.py and similar files with multi-line `from app.modules.auth.models import (\n  User,\n)` style | accept | RESEARCH § Risk surfaces notes this; Phase 213 D-04 set the discipline (preserve block shape during mechanical migration). Plan 03 follows it. No new threat surface; just a code-style note. |
| T-214-AB-09 | T (Tampering) — drift in caller list between research and execution | the 53-line caller-import live grep | mitigate | D-11 mandatory step (Task 03-01 Step 0) re-runs the live grep at plan-execute time and reconciles drift before any edits. If new files appeared since RESEARCH 2026-04-27, they're included in the migration; if files moved, line numbers update. The reconciliation is documented in the SUMMARY. |
</threat_model>

<verification>
- IDENT-02 part (a) ("All 51 cross-domain `User` import sites across the 11 domains type against `IdentityProtocol`") — REALIZED: 26 MIGRATE-FULL files swap their `User` import for `Identity`; 5 MIGRATE-PARTIAL files retain concrete `User` for SQL but rewrite parameter annotations to `Identity`; 2 Pitfall-1 files (`audit/service.py`, `embed_tokens/service.py`) have function-scope-only `User` imports with no parameter annotations to rewrite (allowlisted). Total cross-domain coverage: 33 files migrated, 18 files retain concrete `User` (allowlist).
- IDENT-02 part (b) (existing test suite passes) — verified by both Tasks' full pytest gates (≥1999 passed).
- D-07 (two-step migration: import swap + annotation rewrite atomic per file) — verified by Task 03-01's per-file procedure (a-e steps); Task 03-02's split treatment for the 5 partial files.
- D-08 (Role/UserRole stay concrete in mixed imports) — verified by `catalog/authorization.py` line 21 split (`Role, User, UserRole` → `Role, UserRole`) and Task 03-02's preservation of `User, UserRole` in `catalog/maps/service.py:19`.
- D-09 (allowlist) + Pitfall 1 reconciliation — verified by Task 03-02's grep gate that confirms exactly 18 files retain concrete User import.
- D-10 (no shim, hard cutover) — verified by absence of any new re-export or `# alias for ...` in the migrated files.
- D-11 (re-grep at plan-execute time) — Task 03-01 Step 0 mandates this and documents the reconciliation in the SUMMARY.
- Pitfall 6 (atomic import-and-annotation rewrite) — Task 03-01 step (b)(c)(d) sequence enforces atomicity per file.
- Pitfall 1 reconciliation (7 files keep concrete User for SQL) — fully realized: Task 03-02 covers the 5 files with parameter annotations; Plan 04's allowlist covers all 7.
- The 18-file allowlist for Plan 04 is documented in `<interfaces>` "Architecture-guard allowlist for Plan 04 — full enumeration" — Plan 04 commits this exact list.
- ROADMAP SC#2 (cross-domain code types against IdentityProtocol) — REALIZED.
- ROADMAP SC#4 (1965-test baseline holds) — verified by ≥1999 pytest gate.
</verification>

<success_criteria>
- 33 files modified by this plan: 26 MIGRATE-FULL (full import + annotation swap) + 5 MIGRATE-PARTIAL + 2 untouched-but-allowlisted (audit/service.py, embed_tokens/service.py — these 2 are NOT in `files_modified`; they're handled by Plan 04's allowlist alone).
- After Plan 03: exactly 18 files retain `from app.modules.auth.models import .*\bUser\b` lines, all of which match the Plan 04 allowlist.
- Auth, admin, audit, settings, catalog (maps/records/layers/datasets/features/search/sources/collections), processing (ingest/tiles/AI/export), platform (sandbox/jobs/config_ops), and standards (OGC) test slices all pass; full ≥1999 pytest run passes.
- Project-wide ruff check + format both pass.
- The Pitfall 1 reconciliation is fully realized: 7 files with SQL InstrumentedAttribute use of `User` are correctly identified and either left fully concrete (the 2 function-scope-only files) or partially migrated (the 5 with parameter annotations).
- Phase 214 ROADMAP SC#2 is met. Plan 04's architecture-guard test will lock the boundary; this plan provides the migration evidence.
- The reconciliation note from `<planning_context>` (RESEARCH § Pitfall 1 corrects CONTEXT.md `audit/service.py:24` classification) is honored: that file is allowlisted, not migrated.
</success_criteria>

<output>
After completion, create `.planning/phases/214-identity-protocol-extract/214-03-SUMMARY.md` documenting:
- The D-11 re-grep result: file count and any drift from the canonical 53-line list (RESEARCH 2026-04-27).
- The 26 MIGRATE-FULL files migrated, with one-line diff summary each (e.g., "`catalog/maps/router.py`: 17 annotation rewrites + 1 import swap").
- The 5 MIGRATE-PARTIAL files with split-import treatment, with the SQL InstrumentedAttribute use line numbers preserved.
- The 2 Pitfall-1 untouched files (`audit/service.py`, `embed_tokens/service.py`) with their function-scope import line numbers documented for Plan 04's allowlist.
- Test results: auth-affected slice, catalog slice, full backend suite (≥1999 passed).
- The complete 18-file allowlist enumerated for Plan 04's pathspec exclusion (see `<interfaces>` "Architecture-guard allowlist for Plan 04 — full enumeration").
- Confirmation that all reconciliation notes from `<planning_context>` were honored:
  (a) `audit/service.py:24` is allowlisted (not migrated) per RESEARCH § Pitfall 1.
  (b) The full 7-file Pitfall 1 reconciliation extends beyond what RESEARCH explicitly named — verified by live grep of `User.id` / `User.username` SQL use during planning.
- Pointer to Plan 04 as the next plan in the phase (Wave 4 — depends on this plan).
</output>
</content>
