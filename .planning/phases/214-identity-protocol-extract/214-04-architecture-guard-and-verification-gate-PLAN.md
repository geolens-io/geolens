---
phase: 214-identity-protocol-extract
plan: 04
type: execute
wave: 4
depends_on: ["214-03"]
files_modified:
  - backend/tests/test_layering.py
autonomous: true
requirements: [IDENT-01, IDENT-02, IDENT-03]
requirements_addressed: [IDENT-01, IDENT-02, IDENT-03]
tags: [test, architecture, layering, verification, ci, open-core, identity]

must_haves:
  truths:
    - "D-18: `backend/tests/test_layering.py` is extended with TWO new `@pytest.mark.architecture` tests: (1) `test_core_does_not_import_from_any_module` broadens Phase 212-03's `test_core_does_not_import_from_settings_module` from `app.modules.settings` to `app.modules.*` (closes the broader IDENT-01 boundary that `core/identity.py` must respect); (2) `test_cross_domain_does_not_import_user_from_auth_models` regexes against `\\bUser\\b` in `from app.modules.auth.models import` lines across `backend/`, with `:!` pathspec exclusions for the 18-file allowlist (closes ROADMAP SC#2 / IDENT-02)."
    - "D-18 + Claude's Discretion (CONTEXT.md): The narrow Phase 212-03 test `test_core_does_not_import_from_settings_module` is REPLACED by the broader `test_core_does_not_import_from_any_module` (default per CONTEXT.md). The broad test subsumes the narrow one — keeping both adds noise without coverage gain. The Phase 212-03 test for the deleted `app.modules.settings.models` import path (`test_app_settings_imports_only_via_core_db_models`) is KEPT verbatim — it covers a deleted-path regression, not a broad layering rule."
    - "D-19 + Pitfall 1 reconciliation: Test 2's allowlist pathspec includes 13 `:!` exclusions reflecting the live state after Plans 02+03: 6 auth/** files (subsumed by `:!backend/app/modules/auth/`), 2 admin/** files (subsumed by `:!backend/app/modules/admin/`), `audit/models.py` (TYPE_CHECKING relationship), `audit/service.py` (Pitfall 1 — function-scope SQL filter), `api/main.py` (Base.metadata registration), `processing/ingest/tasks_raster.py` (worker registration), and the 5 Pitfall-1 SQL-attribute files (`embed_tokens/service.py`, `catalog/maps/service.py`, `catalog/collections/router.py`, `catalog/datasets/api/router_export.py`, `catalog/datasets/domain/helpers.py`, `catalog/search/service.py`), plus `:!backend/tests/` to prevent self-positive (Pitfall 4) AND test-fixture exemption."
    - "D-20: The module docstring of `test_layering.py` is updated to credit Phases 212, 213, AND 214. The current docstring already references 'Phases 212-213' as scope and 'Phase 214 (identity-protocol-extract) closes additional core->modules edges; Phase 218 will broaden this guard to `from app.modules.<*>` once those phases land' as forward-note. Plan 04 updates this to credit Phase 214 as DONE — closes the broader core/ guard (anticipated by Phase 212-03's docstring) and adds the User-import allowlist test."
    - "D-21: NO runtime conformance test (`assert isinstance(User(), IdentityProtocol)`). The dep chain's existing tests (auth + admin + audit + settings + catalog + processing + platform + standards integration tests) exercise structural conformance end-to-end. If `User` ever stops satisfying `IdentityProtocol` due to a future ORM column rename, the FastAPI dep call sites fail at runtime via `AttributeError`. Adding a third test file for marginal value is rejected per CONTEXT.md."
    - "D-22: NO ruff-level boundary rule (`tool.ruff.lint.per-file-ignores` import prohibition). The architecture-guard tests are the project's convention from Phases 212/213; we don't add a parallel mechanism."
    - "D-23: No alembic migration generated. Verified by `cd backend && uv run alembic check` exit 0 with only pre-existing procrastinate / raw-SQL drift (documented in 212-04-SUMMARY.md and 213-04-SUMMARY.md). The `users`, `roles`, `user_roles`, `api_keys`, `refresh_tokens` tables are unchanged because Phase 214 is a pure-Python type-system refactor."
    - "D-24: ≥1999-test backend baseline holds (the live count after Phase 213's commit `05a60c65` per VALIDATION.md row Test floor). Any non-baseline failure is a defect introduced by Plans 01-03 and is fix-forward in those plans."
    - "D-25: ROADMAP SC#5 (`pyright`/`mypy` reports no new typing regressions) is interpreted SOFTLY. The project does not run pyright/mypy in CI (`backend/pyproject.toml` `[dependency-groups].dev` has only ruff + pytest + coverage). Acceptance: ruff passes, full pytest passes, optional ad-hoc `pyright backend/app/core/identity.py backend/app/modules/auth/dependencies.py` reports no new errors INTRODUCED by Phase 214 (pre-existing pyright errors elsewhere are not blockers)."
    - "D-26: Frontend has zero involvement. `git diff --name-only $(git merge-base HEAD origin/main)..HEAD -- frontend/` produces zero output across all four Phase 214 plans. `make openapi-check` continues to pass without regenerating `backend/openapi.json` because Identity is a Python-typing concept; FastAPI generates OpenAPI from request/response Pydantic schemas, not from dependency return types."
    - "Reconciliation note (planning_context): RESEARCH § Pitfall 1 — `audit/service.py:24` is in the architecture-guard allowlist (NOT migrated). Test 2's pathspec includes `:!backend/app/modules/audit/service.py` per the planning_context reconciliation note."
    - "Reconciliation note (planning_context): RESEARCH § Pitfall 2 — typed accessors DO exist on main (CONTEXT.md is correct). Plan 01 mirrored them; Plan 02 wired the new `get_identity_extension()` accessor. Plan 04 verifies the new accessor's invariant via Task 04-01 grep gate."
    - "Plan 04 produces the exit gate evidence at `.planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md` mirroring 212-04-SUMMARY.md and 213-04-SUMMARY.md format 1:1."
  artifacts:
    - path: "backend/tests/test_layering.py"
      provides: "Architecture guard test extended with two new tests covering Phase 214 IDENT-01 (broadened core/) and IDENT-02 (cross-domain User-import allowlist); module docstring updated to credit Phase 214; narrow Phase 212-03 settings-only test REPLACED by the broader app.modules.* test"
      contains: "test_core_does_not_import_from_any_module"
      min_lines: 240
    - path: ".planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md"
      provides: "Phase verification gate evidence — captured exit codes, pytest summary, alembic output, ruff output, ROADMAP SC#1-#5 mapping; mirrors 213-04-SUMMARY.md format 1:1"
      contains: "VERIFICATION RESULT"
  key_links:
    - from: "Plan 04 verification step"
      to: "ROADMAP.md Phase 214 Success Criteria 1-5"
      via: "1:1 mapping in `<verification>` section below"
      pattern: "SC#"
    - from: "backend/tests/test_layering.py:test_cross_domain_does_not_import_user_from_auth_models"
      to: "backend/ (excluding 13-entry allowlist)"
      via: "subprocess.run + git grep with `:!` pathspec exclusions"
      pattern: ":!backend/app/modules/auth/"
---

<objective>
This plan has TWO concerns that combine into the phase exit gate:

1. **Extend `backend/tests/test_layering.py`** with two new `@pytest.mark.architecture` tests that prevent re-introduction of (a) `core -> modules.*` import edges (broadens Phase 212-03's settings-only guard to all of `app.modules.*` per D-18) and (b) cross-domain `from app.modules.auth.models import User` imports outside the 18-file allowlist (per D-19 + the Pitfall 1 reconciliation). Update the module docstring to credit Phase 214 (D-20). REPLACE the narrow `test_core_does_not_import_from_settings_module` with the broader `test_core_does_not_import_from_any_module` per CONTEXT.md "Claude's Discretion" default.

2. **Run the phase-level verification gate** capturing evidence to `.planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md`: alembic schema-drift check (D-23), full pytest suite (D-24, ≥1999 baseline), ruff lint+format, ROADMAP success-criteria gates (SC#1, #2, #3, #4 — and SC#5 soft per D-25), and the architecture-guard standalone run (now 5 tests after Plan 04's two additions and the narrow-test replacement: 1 Phase 212 + 2 Phase 213 + 2 Phase 214; original Phase 212 narrow `test_core_does_not_import_from_settings_module` is replaced — net count = 5).

Purpose: Phase 218 will re-run `/oc-audit` to verify Boundary grades improved from B to A−. Without an automated guard, the next contributor who adds `from app.modules.auth.models import User` (or a re-export shim) anywhere in the cross-domain code silently reintroduces the audit finding and Phase 218's audit re-run fails. The guard is cheap (one process spawn per test, ~50 ms each) and explicit about the rule (D-18). The verification gate is the proof that ROADMAP SC#1-#5 are met.

Output: ONE source file modified (`backend/tests/test_layering.py`) — extended with two new test functions, the narrow Phase 212 test REPLACED, plus a docstring update. ONE artifact file created (`214-04-SUMMARY.md`) with the verification evidence. The `architecture` marker is already registered in `pyproject.toml` from Phase 212-03; no `pyproject.toml` change is needed.
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
@.planning/phases/214-identity-protocol-extract/214-03-SUMMARY.md
@.planning/phases/213-catalog-authz-relocate/213-03-SUMMARY.md
@.planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md
@.planning/phases/212-core-settings-decouple/212-04-SUMMARY.md
@backend/tests/test_layering.py
@backend/pyproject.toml

<interfaces>
<!-- The exact target shape of `backend/tests/test_layering.py` after Plan 04. The file currently has 5 tests across 209 lines (verified by reading the file 2026-04-27); after Plan 04 it has 5 tests in ~240 lines (1 broadened + 1 retained + 2 from Phase 213 + 2 new from Phase 214). -->

#### Module docstring (lines 1-21) — REWRITE

Current docstring (verbatim):
```
"""Layering rules: core/ must not depend on modules/settings/, and modules/auth/visibility.py is gone.

Enforces open-core boundaries closed by Phases 212 and 213. If a test in this
file fails, a forbidden import (`from app.modules.settings.<...>` under
`backend/app/core/`, OR `from app.modules.auth.visibility import ...` anywhere
under `backend/`) was reintroduced, which violates the layering rules that
modules depend on core (not the reverse) and that catalog authorization lives
in `app.modules.catalog.authorization` (not `app.modules.auth.visibility`).

Scope (Phases 212-213):
- `from app.modules.settings` under `backend/app/core/` (Phase 212 LAYER-01)
- `from app.modules.auth.visibility` anywhere under `backend/` (Phase 213 LAYER-02)
- Broader `auth.visibility` reference catch (Phase 213 LAYER-02; pathspec excludes this test file to avoid the self-positive bug from Phase 212-03 commit b0bd0c2c)

Phase 214 (identity-protocol-extract) closes additional core->modules edges;
Phase 218 will broaden this guard to `from app.modules.<*>` once those phases land.

Markers:
- `@pytest.mark.architecture` - opt-out locally with `pytest -m 'not architecture'`
  (D-07). Runs by default in CI because `addopts` does not exclude it.
"""
```

Replace with:
```
"""Layering rules across Phases 212, 213, and 214.

Enforces open-core boundaries closed by:
- Phase 212 LAYER-01 — core/ must not depend on modules/settings/.
- Phase 213 LAYER-02 — modules/auth/visibility.py is gone; catalog authorization lives at app.modules.catalog.authorization.
- Phase 214 IDENT-01..03 — core/ broadened: must not depend on ANY app.modules.*. Cross-domain code does not import the concrete `User` ORM from `app.modules.auth.models` outside the 18-file allowlist (auth/**, admin/**, plus 7 specific files where `User` is used as a SQLAlchemy InstrumentedAttribute holder for SQL queries).

If a test in this file fails, a forbidden import was reintroduced — the failure
message names the offending lines for fix-forward.

Scope:
- `from app.modules.*` under `backend/app/core/` (Phase 214 IDENT-01 — broadens Phase 212's settings-only guard)
- `from app.modules.settings.models` anywhere under `backend/` (Phase 212 D-05 deleted-path regression)
- `from app.modules.auth.visibility` anywhere under `backend/` (Phase 213 LAYER-02)
- Broader `auth.visibility` reference catch (Phase 213 LAYER-02)
- `from app.modules.auth.models import .*\\bUser\\b` outside the 18-file allowlist (Phase 214 IDENT-02 — pathspec excludes auth/**, admin/**, audit/{models,service}.py, api/main.py, processing/ingest/tasks_raster.py, embed_tokens/service.py, catalog/{maps/service,collections/router,datasets/api/router_export,datasets/domain/helpers,search/service}.py, and tests/)

Phase 218 will re-run `/oc-audit` to verify Boundary B → A−, Seam Quality C → B,
OSS Surface D → C grade improvements.

Markers:
- `@pytest.mark.architecture` - opt-out locally with `pytest -m 'not architecture'`
  (Phase 212-03 D-07). Runs by default in CI because `addopts` does not exclude it.
"""
```

#### Phase 212 narrow test `test_core_does_not_import_from_settings_module` (current lines 75-102) — REPLACE

CURRENT — Phase 212-03 narrow guard:
```python
@pytest.mark.architecture
def test_core_does_not_import_from_settings_module() -> None:
    """`backend/app/core/` must never import from `app.modules.settings`.

    Closes Phase 212 LAYER-01: the `core <-> settings` layering inversion at
    `core/persistent_config.py:30` and `core/public_urls.py:14` is gone, and
    must stay gone.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = _git_grep(
        r"^\s*(from|import)\s+app\.modules\.settings",
        "backend/app/core/",
    )

    # git grep exit codes: 0 = matches found, 1 = no matches, >1 = error
    if result.returncode == 0:
        pytest.fail(
            "Layering violation: backend/app/core/ contains imports from "
            "app.modules.settings (modules must depend on core, not the "
            "reverse). Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

REPLACE WITH (broader Phase 214 guard — D-18 default REPLACE policy per CONTEXT.md "Claude's Discretion"):
```python
@pytest.mark.architecture
def test_core_does_not_import_from_any_module() -> None:
    """`backend/app/core/` must never import from `app.modules.*`.

    Closes Phase 214 IDENT-01 (broadens Phase 212-03's settings-only guard).
    The `core` layer is the lowest layer; modules (auth, catalog, audit,
    settings, ...) depend on core, never the reverse. Phase 214's
    `core/identity.py` is the first new file in `core/` since Phase 212;
    this test ensures it (and any future core/ files) respect the boundary.

    Subsumes Phase 212-03's `test_core_does_not_import_from_settings_module`
    — `app.modules.settings` is a subset of `app.modules.*`. The deleted-path
    regression `test_app_settings_imports_only_via_core_db_models` is kept
    verbatim because it covers a different invariant (the deleted module
    PATH, not just the layering rule).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = _git_grep(
        r"^\s*(from|import)\s+app\.modules\.",
        "backend/app/core/",
    )

    # git grep exit codes: 0 = matches found, 1 = no matches, >1 = error
    if result.returncode == 0:
        pytest.fail(
            "Layering violation: backend/app/core/ contains imports from "
            "app.modules.* (modules must depend on core, not the reverse). "
            "Phase 214 IDENT-01: core/ is the lowest layer. Offending lines:\n"
            + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

#### NEW test 1 — `test_cross_domain_does_not_import_user_from_auth_models` — APPEND at end of file

```python
@pytest.mark.architecture
def test_cross_domain_does_not_import_user_from_auth_models() -> None:
    """`from app.modules.auth.models import .*User` must only appear in the allowlist.

    Closes Phase 214 IDENT-02. The concrete `User` SQLAlchemy ORM stays
    inside `auth/`; cross-domain code (catalog, audit, processing, platform,
    standards) types against `app.core.identity.Identity` (the Protocol
    alias) instead. Allowlist (D-09 + Pitfall 1 reconciliation):

    - `auth/**`         — owns the model
    - `admin/**`        — admin endpoints CRUD User rows; read sensitive
                           fields (password_hash, auth_provider, etc.) NOT
                           on the Identity Protocol
    - `audit/models.py` — `Mapped["User"]` relationship (TYPE_CHECKING)
    - `audit/service.py`— function-scope `select(User.id)` SQL filter
                           (Pitfall 1 reconciliation — InstrumentedAttribute
                           use, not parameter annotation)
    - `api/main.py`     — Base.metadata registration for Alembic discovery
    - `processing/ingest/tasks_raster.py`
                          — Procrastinate worker `Base.metadata` registration
    - `embed_tokens/service.py` — function-scope `select(...User.username...)`
                                   for admin embed-token list (Pitfall 1)
    - `catalog/maps/service.py` — `User.username.label()` in JOINs/SELECTs
                                   for owner display (Pitfall 1)
    - `catalog/collections/router.py` — `select(User).where(User.id.in_(actor_ids))`
                                         for actor enrichment (Pitfall 1)
    - `catalog/datasets/api/router_export.py` — `select(User).where(User.id == ...)`
                                                for export header personalization (Pitfall 1)
    - `catalog/datasets/domain/helpers.py` — `select(User).where(User.id.in_(ids))`
                                              for batched user resolution (Pitfall 1)
    - `catalog/search/service.py` — `select(User).where(User.id.in_(actor_ids))`
                                     for search-result enrichment (Pitfall 1)
    - `tests/`          — fixtures construct `User(...)` directly; structurally
                           valid as Identity at the call site

    The `\\bUser\\b` word-boundary ensures `import UserRole` (no standalone
    `User`) does NOT trip the guard — `UserRole` stays concrete per D-08.
    `import Role, User, UserRole` and `import User` and `import ApiKey, User`
    all DO trip the guard outside the allowlist.

    Maps directly to ROADMAP Phase 214 SC#2.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; install a newer git "
            "or run this test from the host"
        )

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b",
            "--",
            "backend/",
            ":!backend/app/modules/auth/",
            ":!backend/app/modules/admin/",
            ":!backend/app/modules/audit/models.py",
            ":!backend/app/modules/audit/service.py",
            ":!backend/app/api/main.py",
            ":!backend/app/processing/ingest/tasks_raster.py",
            ":!backend/app/modules/embed_tokens/service.py",
            ":!backend/app/modules/catalog/maps/service.py",
            ":!backend/app/modules/catalog/collections/router.py",
            ":!backend/app/modules/catalog/datasets/api/router_export.py",
            ":!backend/app/modules/catalog/datasets/domain/helpers.py",
            ":!backend/app/modules/catalog/search/service.py",
            ":!backend/tests/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Layering violation: cross-domain code imports the concrete "
            "`User` ORM from `app.modules.auth.models`. Phase 214 IDENT-02 "
            "requires cross-domain code to type against "
            "`app.core.identity.Identity` (the Protocol alias) instead. "
            "If this is a legitimate SQL InstrumentedAttribute use, add "
            "the file to the allowlist in this test and document the "
            "reason. Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

The pathspec list MUST exactly match the 13 entries above (in this order or any consistent order). The list is the canonical allowlist; Plan 03 enforced it on the source-tree side.

#### Existing tests UNCHANGED

- `test_app_settings_imports_only_via_core_db_models` (Phase 212-03 D-05 — deleted-path regression) — KEEP verbatim. The broadened Phase 214 test does NOT subsume this one because `app.modules.settings.models` is a deleted path; the broad test catches a layering violation, the narrow test catches a regression to a deleted module path. Both are useful; both stay.
- `test_no_imports_from_auth_visibility` (Phase 213) — KEEP verbatim.
- `test_no_auth_visibility_module_referenced` (Phase 213) — KEEP verbatim.

#### Final test count: 5

Before Plan 04: 4 tests (1 narrow Phase 212 + 1 deleted-path Phase 212 + 2 Phase 213).
After Plan 04: 5 tests (1 broadened Phase 214 + 1 deleted-path Phase 212 + 2 Phase 213 + 2 NEW Phase 214). NET: +1 (replace narrow with broad → no count change for that swap; +1 for User-import allowlist test). Wait: that's actually 4 + 2 NEW - 0 (replacement is 1-for-1) = 5? Let me recount: 4 starting tests, REPLACE narrow Phase 212 (no count change), ADD 1 cross-domain User-import test. Final = 5. The original CONTEXT.md said "two new tests" but only one is genuinely new — the other is a replacement. The verification gate's expected count is 5.

Wait, CONTEXT.md D-18 says "Add two new tests". Re-read: "Add two new `@pytest.mark.architecture` tests... `test_core_does_not_import_from_any_module` AND `test_cross_domain_does_not_import_user_from_auth_models`." If the planner REPLACES the narrow Phase 212 test with `test_core_does_not_import_from_any_module`, only ONE test is genuinely new (the cross-domain User-import one). If the planner ADDS the broad test ALONGSIDE keeping the narrow one, TWO tests are new. The default per CONTEXT.md "Claude's Discretion" is REPLACE — net +1 test. Final count = 5 (was 4: 2 from Phase 212 + 2 from Phase 213, now 1 broadened-from-Phase-212 + 1 deleted-path-Phase-212 + 2 Phase 213 + 1 NEW Phase 214 cross-domain User-import = 5).

#### Verification commands (mirror 213-04 verbatim, swap ROADMAP SC list)

```bash
# 1. Alembic schema-drift check (D-23)
cd backend && uv run alembic check
# Expected: exit 0, "No new upgrade operations." OR pre-existing procrastinate / raw-SQL drift documented in 212-04-SUMMARY.md / 213-04-SUMMARY.md.

# 2. Full backend test suite (D-24, ROADMAP SC#4)
docker compose exec api uv run pytest -m 'not perf' --tb=short -q
# Fallback: cd backend && uv run pytest -m 'not perf' --tb=short -q
# Expected: ≥1999 passed (the post-Phase-213 baseline). Phase 214 adds 3 new tests in tests/test_extensions.py (Plan 01-03), 0 net change in test_layering.py count (replace + add = +1 - 0 = +1, but the original narrow Phase 212 test is gone). Net Phase 214 test count delta: +4 (3 in test_extensions.py + 1 new in test_layering.py). Expected post-Phase-214 floor: ≥2003 passed.

# 3. Ruff lint + format
cd backend && uv run ruff check .
cd backend && uv run ruff format --check .

# 4. ROADMAP SC#1 specific gate: core/identity.py exists with the 4 expected symbols
cd backend && python -c "from app.core.identity import IdentityProtocol, RoleProtocol, IdentityExtension, Identity; assert IdentityProtocol is Identity; print('ok')"
# Expected: exit 0 with "ok"

# 5. ROADMAP SC#2 specific gate: cross-domain code does not import concrete User outside the 18-file allowlist
git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b" -- backend/ \
  ':!backend/app/modules/auth/' ':!backend/app/modules/admin/' \
  ':!backend/app/modules/audit/models.py' ':!backend/app/modules/audit/service.py' \
  ':!backend/app/api/main.py' ':!backend/app/processing/ingest/tasks_raster.py' \
  ':!backend/app/modules/embed_tokens/service.py' ':!backend/app/modules/catalog/maps/service.py' \
  ':!backend/app/modules/catalog/collections/router.py' \
  ':!backend/app/modules/catalog/datasets/api/router_export.py' \
  ':!backend/app/modules/catalog/datasets/domain/helpers.py' \
  ':!backend/app/modules/catalog/search/service.py' \
  ':!backend/tests/'
# MUST exit 1 (no matches; ROADMAP SC#2 satisfied)

# 6. ROADMAP SC#3 specific gate: get_identity_extension() typed accessor exists
cd backend && python -c "from app.platform.extensions import get_identity_extension; from app.platform.extensions.defaults import DefaultIdentityExtension; assert isinstance(get_identity_extension(), DefaultIdentityExtension); print('ok')"
# Expected: exit 0 with "ok"

# 7. Architecture guard standalone (5 tests after Plan 04)
cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short
# Expected: 5 passed (host, .git/ present) OR 5 skipped (container, .git/ excluded by .dockerignore — Pitfall 5)

# 8. Frontend untouched (D-26)
git diff --name-only $(git merge-base HEAD origin/main 2>/dev/null || git rev-parse HEAD~5)..HEAD -- frontend/
# Expected: zero output

# 9. ROADMAP SC#5 (soft per D-25) — optional pyright spot-check
npx --yes pyright backend/app/core/identity.py backend/app/modules/auth/dependencies.py
# Expected: 0 NEW errors introduced by Phase 214's edits (pre-existing pyright errors elsewhere are not blockers).
```

#### Final test count target for the verification gate

Phase 214 contributes these NEW tests:
- `tests/test_extensions.py::TestGetIdentityExtension::test_get_identity_extension_returns_default_when_unregistered` (Plan 01)
- `tests/test_extensions.py::TestGetIdentityExtension::test_get_identity_extension_returns_registered_when_present` (Plan 01)
- `tests/test_extensions.py::TestGetIdentityExtension::test_default_identity_extension_resolve_returns_none` (Plan 01)
- `tests/test_layering.py::test_cross_domain_does_not_import_user_from_auth_models` (Plan 04)

NET delta: +4 tests (one Phase 212 narrow test was replaced, not removed). Post-Phase-214 baseline: ≥2003 passed.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 04-01: Extend test_layering.py — replace narrow Phase 212 test, add cross-domain User-import allowlist test, update docstring</name>
  <files>backend/tests/test_layering.py</files>
  <read_first>
    - .planning/phases/214-identity-protocol-extract/214-CONTEXT.md (D-18, D-19, D-20, D-21, D-22 — architecture-guard decisions)
    - .planning/phases/214-identity-protocol-extract/214-RESEARCH.md (lines 470-530 — Pattern 5 architecture guard via git grep with allowlist exclusions; lines 703-712 — Pitfall 4 self-positive bug; lines 713-728 — Pitfall 5 git-version skip; lines 1031-1113 — full reference for the new tests)
    - .planning/phases/214-identity-protocol-extract/214-VALIDATION.md (Per-Task Verification Map rows 214-04-01, 214-04-02; "Sampling Rate" — full suite required for the phase gate)
    - .planning/phases/213-catalog-authz-relocate/213-03-SUMMARY.md (companion plan that did the same kind of architecture-guard extension — read for the discipline pattern)
    - backend/tests/test_layering.py (current 209-line file — read end-to-end; understand the existing helpers `_has_git_metadata`, `_has_pathspec_magic`, `_git_grep` that this plan reuses verbatim)
    - backend/pyproject.toml (verify the `architecture` pytest marker is registered; line containing `markers = [..., "architecture: ..."]` — Phase 212-03 added it)
    - .planning/phases/214-identity-protocol-extract/214-03-SUMMARY.md (verify the 18-file allowlist matches what Plan 03 left in the source tree; reconcile if drift exists)
  </read_first>
  <action>
Make the following surgical edits to `backend/tests/test_layering.py`. Use the Edit tool for each block. After each block, run `cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short` to catch errors immediately.

**Edit 1 — Replace the module docstring (lines 1-21).**

The current docstring is shown verbatim in `<interfaces>` "Module docstring" above. Replace it with the new docstring shown there. The new docstring credits Phase 214, names the 13-entry allowlist explicitly, references the Pitfall 1 reconciliation, and updates the Phase 218 forward-note.

**Edit 2 — Replace `test_core_does_not_import_from_settings_module` with `test_core_does_not_import_from_any_module` (current lines 75-102).**

The current narrow test is shown in `<interfaces>` above. Replace its function body and name with the broader test shown in `<interfaces>`. The function body uses the existing `_git_grep` helper (lines 65-72 of the current file) — no new helper is needed.

After Edit 2, run `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_any_module -v --tb=short`. Expected: PASS (no `app.modules.*` imports under `backend/app/core/` after Phase 212 + 213 + 214; Plan 01's `core/identity.py` only imports stdlib + fastapi + sqlalchemy.ext.asyncio).

If the test FAILS at this stage with a list of offending lines, the offending file is NOT a Phase 214 plan output — investigate and fix-forward in the appropriate plan. (Most likely culprit if it fails: the plan reused the same broad-test name but kept the narrow regex; double-check the regex is `r"^\s*(from|import)\s+app\.modules\."` not `r"^\s*(from|import)\s+app\.modules\.settings"`.)

**Edit 3 — Append `test_cross_domain_does_not_import_user_from_auth_models` at the end of the file.**

The new test body is shown in `<interfaces>` "NEW test 1" above. Append it AFTER the existing `test_no_auth_visibility_module_referenced` function (which currently ends at line 209 with `f"stderr: {result.stderr}"`).

The new test:
- Uses `subprocess.run([...])` directly (NOT the `_git_grep` helper) because it needs the 13-entry pathspec exclusion list, which `_git_grep` does not support.
- Reuses the existing `_has_git_metadata()` and `_has_pathspec_magic()` skip-guards verbatim (Pitfall 5).
- Includes the 13-entry allowlist exactly as enumerated in `<interfaces>` (must match Plan 03's source-tree state).
- The regex `r"^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b"` uses `\bUser\b` word boundary so:
  - `import User` matches (trips the guard outside allowlist).
  - `import Role, User, UserRole` matches (trips the guard).
  - `import ApiKey, User` matches (trips the guard).
  - `import UserRole` (no standalone `User`) does NOT match (D-08 — `UserRole` stays concrete; not flagged).

After Edit 3, run `cd backend && uv run pytest tests/test_layering.py::test_cross_domain_does_not_import_user_from_auth_models -v --tb=short`. Expected: PASS (Plan 03 migrated all cross-domain User-imports; only the 18-file allowlist remains; allowlist matches the test's pathspec).

If the test FAILS at this stage:
- The failure message names the offending file(s). Cross-reference against the 18-file allowlist documented in `214-03-SUMMARY.md`. If a legitimate file was missed in Plan 03, fix-forward in Plan 03 (migrate the file's imports/annotations); the test will pass on the next run.
- If the offending file is one of the 13 explicit allowlist entries, the pathspec entry is misspelled or has a typo. Check `:!backend/app/modules/...` exactly matches the file path returned by git grep.

**Edit 4 — Verify the existing 3 tests are UNTOUCHED.**

Tests that stay verbatim:
- `test_app_settings_imports_only_via_core_db_models` (Phase 212-03 deleted-path regression — KEPT)
- `test_no_imports_from_auth_visibility` (Phase 213-03)
- `test_no_auth_visibility_module_referenced` (Phase 213-03)

Run `git diff backend/tests/test_layering.py` and confirm the diff:
- ADDS the new docstring (lines 1-21).
- REPLACES the function name `test_core_does_not_import_from_settings_module` with `test_core_does_not_import_from_any_module` and updates the regex.
- ADDS a new function `test_cross_domain_does_not_import_user_from_auth_models` at end of file.
- Leaves the 3 existing tests entirely untouched.

**Edit 5 — Run all 5 architecture tests:**

```bash
cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short
```

Expected output: `5 passed` on the host (with `.git/` present); `5 skipped` inside containers (Pitfall 5 — `_has_git_metadata()` skips, NOT a regression). The host run is the authoritative gate.

**Edit 6 — Verify the architecture marker is registered (no change needed):**

```bash
grep -A5 "markers = " backend/pyproject.toml | head -10
```

Expected: `architecture` is in the markers list (registered by Phase 212-03). No change required.

**Edit 7 — Run the full pytest suite as a regression check:**

```bash
cd backend && uv run pytest -m 'not perf' --tb=short -q 2>&1 | tail -10
```

Expected: ≥2003 passed (post-Phase-214 floor: 1999 baseline + 3 new test_extensions tests + 1 new test_layering test).
  </action>
  <verify>
    <automated>cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short && bash -c 'grep -c "@pytest.mark.architecture" tests/test_layering.py | grep -E "^[5-9]$|^[0-9][0-9]$"' && bash -c 'count=$(grep -cE "^def test_" tests/test_layering.py); test "$count" -ge "5"' && bash -c 'grep -q "test_core_does_not_import_from_any_module" tests/test_layering.py' && bash -c 'grep -q "test_cross_domain_does_not_import_user_from_auth_models" tests/test_layering.py' && bash -c 'grep -q ":!backend/app/modules/audit/service.py" tests/test_layering.py' && bash -c 'grep -q ":!backend/app/modules/catalog/maps/service.py" tests/test_layering.py' && uv run ruff check tests/test_layering.py && uv run ruff format --check tests/test_layering.py</automated>
  </verify>
  <acceptance_criteria>
    - `backend/tests/test_layering.py` contains a function `test_core_does_not_import_from_any_module` (verify with `grep -c "^def test_core_does_not_import_from_any_module" backend/tests/test_layering.py` equals 1).
    - `backend/tests/test_layering.py` does NOT contain `test_core_does_not_import_from_settings_module` (verify with `grep -c "^def test_core_does_not_import_from_settings_module" backend/tests/test_layering.py` equals 0 — replaced per CONTEXT.md "Claude's Discretion" default).
    - `backend/tests/test_layering.py` contains a function `test_cross_domain_does_not_import_user_from_auth_models` (verify with `grep -c "^def test_cross_domain_does_not_import_user_from_auth_models" backend/tests/test_layering.py` equals 1).
    - The file contains exactly 5 `@pytest.mark.architecture` decorators (verify with `grep -c "^@pytest.mark.architecture" backend/tests/test_layering.py` equals 5).
    - The file contains exactly 5 `def test_*` functions (verify with `grep -cE "^def test_" backend/tests/test_layering.py` equals 5).
    - The 13 pathspec exclusions are present in `test_cross_domain_does_not_import_user_from_auth_models` (verify with `grep -c '":!backend/' backend/tests/test_layering.py` ≥ 13; allows for the existing `:!backend/tests/test_layering.py` exclusion in `test_no_auth_visibility_module_referenced` to count toward a higher number).
    - Critical individual pathspec entries verified: `:!backend/app/modules/auth/` (catches all auth/**), `:!backend/app/modules/admin/` (catches all admin/**), `:!backend/app/modules/audit/service.py` (Pitfall 1 reconciliation), `:!backend/app/modules/catalog/maps/service.py`, `:!backend/app/modules/catalog/collections/router.py`, `:!backend/app/modules/catalog/datasets/api/router_export.py`, `:!backend/app/modules/catalog/datasets/domain/helpers.py`, `:!backend/app/modules/catalog/search/service.py`, `:!backend/app/modules/embed_tokens/service.py`, `:!backend/app/modules/audit/models.py`, `:!backend/app/api/main.py`, `:!backend/app/processing/ingest/tasks_raster.py`, `:!backend/tests/`. Verify each: `grep -q ":!backend/app/modules/auth/" backend/tests/test_layering.py && grep -q ":!backend/app/modules/admin/" backend/tests/test_layering.py && grep -q ":!backend/app/modules/audit/service.py" backend/tests/test_layering.py && grep -q ":!backend/app/modules/catalog/maps/service.py" backend/tests/test_layering.py && grep -q ":!backend/app/modules/catalog/collections/router.py" backend/tests/test_layering.py && grep -q ":!backend/app/modules/catalog/datasets/api/router_export.py" backend/tests/test_layering.py && grep -q ":!backend/app/modules/catalog/datasets/domain/helpers.py" backend/tests/test_layering.py && grep -q ":!backend/app/modules/catalog/search/service.py" backend/tests/test_layering.py && grep -q ":!backend/app/modules/embed_tokens/service.py" backend/tests/test_layering.py && grep -q ":!backend/app/modules/audit/models.py" backend/tests/test_layering.py && grep -q ":!backend/app/api/main.py" backend/tests/test_layering.py && grep -q ":!backend/app/processing/ingest/tasks_raster.py" backend/tests/test_layering.py && grep -q ":!backend/tests/" backend/tests/test_layering.py`.
    - The module docstring credits Phase 214 (verify with `head -25 backend/tests/test_layering.py | grep -q "Phase 214"`).
    - The module docstring credits Phases 212, 213, AND 214 (verify with `head -25 backend/tests/test_layering.py | grep -E "Phase 212|Phase 213|Phase 214" | wc -l` ≥ 3).
    - The 3 unchanged tests (`test_app_settings_imports_only_via_core_db_models`, `test_no_imports_from_auth_visibility`, `test_no_auth_visibility_module_referenced`) are still present (verify with `grep -c "^def test_app_settings_imports_only_via_core_db_models\|^def test_no_imports_from_auth_visibility\|^def test_no_auth_visibility_module_referenced" backend/tests/test_layering.py` equals 3).
    - The architecture-guard standalone run passes: `cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short` exits 0 with `5 passed` (host) OR `5 skipped` (container — Pitfall 5).
    - Ruff lint and format pass on the file.
    - The reconciliation note from `<planning_context>` is honored: the test 2 pathspec includes `:!backend/app/modules/audit/service.py` per RESEARCH § Pitfall 1.
  </acceptance_criteria>
  <done>
    `backend/tests/test_layering.py` is extended with two new architecture tests: `test_core_does_not_import_from_any_module` (broadens Phase 212-03's settings-only guard to all `app.modules.*` per IDENT-01) and `test_cross_domain_does_not_import_user_from_auth_models` (closes IDENT-02 with the 13-entry pathspec allowlist reflecting Plan 03's source-tree state). The narrow Phase 212 test is replaced (not duplicated). The module docstring credits Phase 214. All 5 architecture tests pass on the host; no regression in the existing pytest corpus. The architecture-guard regression seal is in place.
  </done>
</task>

<task type="auto">
  <name>Task 04-02: Run phase verification gate and capture evidence to 214-04-SUMMARY.md</name>
  <files>.planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md</files>
  <read_first>
    - .planning/phases/214-identity-protocol-extract/214-VALIDATION.md (Sampling Rate / Phase gate; Per-Task Verification Map rows 214-04-01 through 214-04-05)
    - .planning/phases/214-identity-protocol-extract/214-RESEARCH.md (lines 1114-1150 — Verification commands; Pitfall 4 — pre-existing alembic procrastinate drift; Pitfall 5 — architecture tests SKIP inside container)
    - .planning/ROADMAP.md (Phase 214 Success Criteria — 5 conditions)
    - .planning/phases/214-identity-protocol-extract/214-CONTEXT.md (D-23 alembic, D-24 full pytest, D-25 SC#5 soft, D-26 frontend untouched)
    - .planning/phases/213-catalog-authz-relocate/213-04-SUMMARY.md (the template — read end-to-end so this SUMMARY mirrors its structure 1:1 with only SC list and grep targets swapped)
    - .planning/phases/212-core-settings-decouple/212-04-SUMMARY.md (companion template — read for the alembic Pitfall 4 documentation pattern)
    - .planning/phases/214-identity-protocol-extract/214-01-SUMMARY.md (confirm Plan 01 produced the new file + extension fallback)
    - .planning/phases/214-identity-protocol-extract/214-02-SUMMARY.md (confirm Plan 02 retyped deps + duplicated wire-in)
    - .planning/phases/214-identity-protocol-extract/214-03-SUMMARY.md (confirm Plan 03 migrated 33 caller files + 18-file allowlist documented)
  </read_first>
  <action>
Run each verification command in order. Capture the exit code and a brief excerpt of stdout/stderr. If ANY command exits non-zero, STOP and fix-forward in the appropriate plan; do not paper over a failure.

**Step 1 — Alembic schema-drift check (D-23, ROADMAP SC supporting evidence):**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run alembic check
```

Expected: exit 0, "No new upgrade operations." OR pre-existing procrastinate / raw-SQL drift documented in 212-04-SUMMARY.md and 213-04-SUMMARY.md. Per Pitfall 4: any drift mentioning `users`, `roles`, `user_roles`, `api_keys`, `refresh_tokens`, or other auth-domain tables is a regression — STOP and investigate.

**Step 2 — Full backend test suite (D-24, ROADMAP SC#4):**

```bash
docker compose exec api uv run pytest -m 'not perf' --tb=short -q 2>&1 | tee /tmp/214-04-pytest.log
```

If `docker compose` is not available, fall back to host: `cd backend && uv run pytest -m 'not perf' --tb=short -q`.

Expected: exit 0, summary line shows `≥2003 passed` (post-Phase-214 floor: 1999 baseline + 3 new test_extensions + 1 new test_layering test). Inside the container, the 5 architecture tests SKIP (Pitfall 5 — `.git/` excluded by `.dockerignore`); summary line is `≥1998 passed, 5 skipped` (1999 - 5 arch tests + 4 net-new = 1998 passed in container; the 5 skipped includes the 4 architecture tests + 0 others since architecture is the only marker that skips inside container).

Wait — recompute. Pre-Phase-214 baseline (per VALIDATION row Test floor) is 1999 tests passing. Of those, 4 are architecture tests (which skip in container per Pitfall 5). So inside container, baseline is 1995 passed + 4 skipped. Phase 214 adds 3 new test_extensions tests + 1 new test_layering test (architecture, skips in container). Post-Phase-214 in container: 1998 passed + 5 skipped. Post-Phase-214 on host: 2003 passed. Capture EXACT summary line.

If any test fails, classify by failure mode:
- `ImportError: cannot import name 'Identity' from 'app.core.identity'` → Plan 01 failed; re-run Plan 01.
- `AttributeError: type object 'IdentityProtocol' has no attribute 'X'` → Plan 03 accidentally rewrote a SQL InstrumentedAttribute to use `Identity` instead of `User`. Identify the file, restore the concrete `User` reference, add the file to the allowlist if not already, and re-run Plan 04 Task 04-01.
- `TypeError: object NoneType can't be used in 'await' expression` → Plan 01 Pitfall 8: `DefaultIdentityExtension.resolve_identity_from_token` is sync, must be async. Fix in Plan 01.
- `NameError: name 'User' is not defined` → Plan 03 missed an annotation rewrite (import was swapped, but a `user: User` annotation was left behind). Find with `grep -nE '\buser:\s*User\b' backend/app/` excluding allowlist, fix-forward in Plan 03.

**Step 3 — Ruff lint and format check:**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run ruff check .
cd /Users/ishiland/Code/geolens/backend && uv run ruff format --check .
```

Both must exit 0.

**Step 4 — ROADMAP SC#1 specific gate (`core/identity.py` defines IdentityProtocol with the 6-field surface; concrete `User` satisfies it):**

```bash
cd /Users/ishiland/Code/geolens/backend && python -c "
from app.core.identity import IdentityProtocol, RoleProtocol, IdentityExtension, Identity
from app.modules.auth.models import User, Role

# Verify IdentityProtocol exposes the 6-field surface
import typing
hints = typing.get_type_hints(IdentityProtocol)
expected_fields = {'id', 'username', 'email', 'is_active', 'roles', 'created_at'}
actual_fields = set(hints.keys())
assert expected_fields == actual_fields, f'Surface drift: expected {expected_fields}, got {actual_fields}'

# Verify alias
assert IdentityProtocol is Identity, 'Identity alias broken'

# Structural conformance is verified end-to-end by Plan 02's auth-affected test slice;
# this gate just verifies the symbols exist and the surface matches D-01.
print('SC#1 ok')
"
```

Expected: exit 0 with `SC#1 ok`.

**Step 5 — ROADMAP SC#2 specific gate (cross-domain `User` import outside allowlist):**

```bash
cd /Users/ishiland/Code/geolens
git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b" -- backend/ \
  ':!backend/app/modules/auth/' ':!backend/app/modules/admin/' \
  ':!backend/app/modules/audit/models.py' ':!backend/app/modules/audit/service.py' \
  ':!backend/app/api/main.py' ':!backend/app/processing/ingest/tasks_raster.py' \
  ':!backend/app/modules/embed_tokens/service.py' \
  ':!backend/app/modules/catalog/maps/service.py' \
  ':!backend/app/modules/catalog/collections/router.py' \
  ':!backend/app/modules/catalog/datasets/api/router_export.py' \
  ':!backend/app/modules/catalog/datasets/domain/helpers.py' \
  ':!backend/app/modules/catalog/search/service.py' \
  ':!backend/tests/' ; test $? -eq 1
```

Expected: exit 0 (the `test $? -eq 1` idiom inverts git grep's "no matches" exit-1 into success-exit-0). Zero matches means ROADMAP SC#2 satisfied.

**Step 6 — ROADMAP SC#3 specific gate (`get_identity_extension()` typed accessor exists and falls back to default):**

```bash
cd /Users/ishiland/Code/geolens/backend && python -c "
from app.platform.extensions import get_identity_extension, get_branding_extension, get_audit_extension, get_auth_extension
from app.platform.extensions.defaults import DefaultIdentityExtension

# Verify the new accessor exists and falls back to default
ext = get_identity_extension()
assert isinstance(ext, DefaultIdentityExtension), f'Default fallback broken: got {type(ext)}'

# Verify all four typed accessors are exported (Phase 214 mirrors the existing trio)
import asyncio
result = asyncio.run(ext.resolve_identity_from_token('any-token', None, None))
assert result is None, f'Default impl should return None, got {result}'

print('SC#3 ok')
"
```

Expected: exit 0 with `SC#3 ok`.

**Step 7 — Architecture guard standalone (5 tests after Plan 04):**

```bash
cd /Users/ishiland/Code/geolens/backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short
```

Expected: `5 passed` on host, `5 skipped` in container. Capture the count.

**Step 8 — Frontend untouched (D-26, ROADMAP SC supporting evidence):**

```bash
cd /Users/ishiland/Code/geolens
git diff --name-only $(git merge-base HEAD origin/main 2>/dev/null || git rev-parse HEAD~5)..HEAD -- frontend/
```

Expected: zero output (no frontend files modified across Phase 214's 4 plans). The fallback `HEAD~5` covers the commits this phase produced (1 per plan = 4 commits, with possible intermediate fix-forward commits).

**Step 9 — ROADMAP SC#5 soft gate (optional pyright spot-check per D-25):**

```bash
cd /Users/ishiland/Code/geolens
npx --yes pyright backend/app/core/identity.py backend/app/modules/auth/dependencies.py 2>&1 | tail -20
```

Expected: 0 NEW errors introduced by Phase 214 edits. Pre-existing pyright errors elsewhere in the codebase are not blockers (D-25). If pyright reports errors:
- Errors in `core/identity.py` → likely a typo in the Protocol declaration; fix in Plan 01.
- Errors in `auth/dependencies.py` → likely a missing `Identity` import or a missed annotation; fix in Plan 02.
- Errors in unrelated files (e.g., `processing/ai/llm_loop.py`) → pre-existing, document and ignore.

This step is OPTIONAL per D-25 — if `npx pyright` is unavailable or rate-limited, skip and document in SUMMARY as "skipped per D-25 soft interpretation."

**Step 10 — Capture evidence to SUMMARY.**

Create `.planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md` with the following structure (substitute real values; mirror 213-04-SUMMARY.md formatting 1:1):

````markdown
# Phase 214 - Plan 04 Verification Gate Evidence

**Run date:** {ISO timestamp}
**Result:** PASS / FAIL

## Verification Commands

| # | Command | Exit | Key output |
|---|---------|------|------------|
| 1 | `cd backend && uv run alembic check` | 0 | "No new upgrade operations." (or pre-existing procrastinate-only drift documented in 212-04 / 213-04 SUMMARY) |
| 2 | `docker compose exec api uv run pytest -m 'not perf' --tb=short -q` | 0 | "{N} passed, {M} skipped in {T}s" — N≥2003 host / N≥1998 container, M includes 5 architecture tests skipped inside container |
| 3a | `cd backend && uv run ruff check .` | 0 | "All checks passed!" |
| 3b | `cd backend && uv run ruff format --check .` | 0 | "{N} files already formatted" |
| 4 | SC#1 import + 6-field surface gate | 0 | "SC#1 ok" |
| 5 | SC#2 cross-domain User-import gate (with 13-entry allowlist) | 1 (no matches) | (empty) |
| 6 | SC#3 get_identity_extension() default-fallback gate | 0 | "SC#3 ok" |
| 7 | `cd backend && uv run pytest tests/test_layering.py -v -m architecture` | 0 | "5 passed" (host-run; `.git/` present) |
| 8 | `git diff --name-only ... -- frontend/` | 0 (zero output) | (no frontend files modified) |
| 9 | `npx pyright backend/app/core/identity.py backend/app/modules/auth/dependencies.py` | 0 | "0 errors" (or skipped per D-25) |

## ROADMAP Phase 214 Success Criteria - Status

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | `backend/app/core/identity.py` defines `IdentityProtocol` capturing the surface 51 cross-domain call sites depend on (id, email, role, tenant context, etc.); the concrete `User` ORM model satisfies it | PASS | Step 4 (file exists, 6-field surface verified, Identity alias present); Step 2 (full pytest passes — concrete `User` structurally satisfies `IdentityProtocol` exercised end-to-end by 2003+ tests) |
| 2 | All 51 cross-domain `User` import sites across the 11 domains type against `IdentityProtocol` (or an alias of it), not the concrete SQLAlchemy class | PASS | Step 5 (zero matches outside the 18-file allowlist) + Step 7 (architecture-guard test 2 asserts the same invariant programmatically) |
| 3 | The extension system exposes a registration hook (typed accessor + entry_point seam, mirroring `get_branding_extension()` / `get_audit_extension()`) so an enterprise overlay can supply an alternate identity backend without core changes | PASS | Step 6 (`get_identity_extension()` exists, returns `DefaultIdentityExtension` fallback, default impl returns None preserving JWT path); the entry_point seam mirrors `geolens.extensions` group used by branding/audit/auth extensions |
| 4 | Existing JWT, OAuth/OIDC, API key, and refresh-token flows operate unchanged against the concrete model; the 1965-test backend baseline stays green | PASS | Step 2 (≥2003 passed; auth + OAuth + API-key + refresh-token slices all green) |
| 5 | `pyright`/`mypy` (per project convention) reports no new typing regressions introduced by the Protocol migration | PASS (soft per D-25) | Step 9 (optional pyright spot-check on the two phase-touched files; project does not run pyright/mypy in CI per D-25) |

## Manual-Only Verifications

VALIDATION.md "Manual-Only Verifications" lists two items:

1. **`pyright` spot-check on retyped deps (SC#5 soft)** — covered by Step 9 above.
2. **Manual smoke of admin Settings UI (sanity)** — performed: `docker compose up -d --build api && curl -fsS http://localhost:8000/health` returned 200; admin Settings tab loads cleanly; no auth regression. (If executor cannot perform this manually, note in SUMMARY as "deferred to /gsd-verify-work UAT step.")

## Notes

- pyright/mypy NOT run in CI because the project does not include a static type checker in its dev dependencies (`backend/pyproject.toml` `[dependency-groups].dev` has only ruff + pytest + coverage); ruff (Step 3) is the canonical static check. Same as Phase 212-04 and 213-04. Step 9 ran pyright ad-hoc per D-25 soft interpretation.
- The architecture guard test scope now covers Phase 212 LAYER-01 (`from app.modules.settings.models`), Phase 213 LAYER-02 (`auth.visibility` import + broader reference), AND Phase 214 IDENT-01..02 (broadened core/* + cross-domain User-import allowlist). Phase 218 will revisit if any layering finding remains.
- Pitfall 5 noted: the 5 architecture tests SKIP inside the container (Step 2) and PASS on the host (Step 7) — designed-in fallback behavior, not a regression.
- Pitfall 4 noted: any procrastinate / raw-SQL drift in Step 1 is pre-existing (documented in 212-04-SUMMARY.md), not introduced by Phase 214. Phase 214 is pure-Python type-system refactor; no catalog-domain table changed.
- Reconciliation note honored: RESEARCH § Pitfall 1 (`audit/service.py:24` is on the architecture-guard allowlist, not migrated) — verified by Step 5 pathspec including `:!backend/app/modules/audit/service.py` and Step 7 test passing.
- Reconciliation note honored: RESEARCH § Pitfall 9 (extension wire-in duplicated across `get_optional_user` and `get_current_user` to preserve expired-token UX) — verified by Plan 02-SUMMARY's grep gate showing `count == 2`.
- Phase 214 is a hard prerequisite for Phase 217 (auth-saml-enterprise). Phase 217's SAML overlay will register an `IdentityExtension` under the `geolens.extensions` entry-point group with key `"identity"`, and `get_identity_extension()` will return it on subsequent requests without any further core changes.
- The Phase 218 audit re-run (`/oc-audit`) will measure Boundary B → A− improvement: Phase 214 contributes by removing 33 cross-domain `core ⇆ modules.auth.User` coupling edges and adding the IdentityExtension seam.
````

**Hard constraints:**

- This task modifies ZERO source files. The only artifact is the SUMMARY at `.planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md`.
- If any verification command exits non-zero, stop and fix-forward in Plan 01, 02, 03, or 04 Task 04-01 as appropriate. Do NOT mark this plan PASS with a failure carried over.
- Do NOT skip Step 7 (host-only architecture run) just because Step 2 includes the same tests — Step 2's container run SKIPs them, so Step 7 is the only place they actually execute.
- Do NOT skip Step 8 (frontend-untouched check) — D-26 is explicit and verifiable.
- Step 9 (pyright) is OPTIONAL per D-25; if skipped, document the skip rationale in SUMMARY.
  </action>
  <verify>
    <automated>(cd backend && uv run alembic check) && (cd backend && uv run ruff check .) && (cd backend && uv run ruff format --check .) && (cd backend && python -c "from app.core.identity import IdentityProtocol, RoleProtocol, IdentityExtension, Identity; import typing; hints = typing.get_type_hints(IdentityProtocol); assert {'id','username','email','is_active','roles','created_at'} == set(hints.keys()); assert IdentityProtocol is Identity; print('SC1 ok')") && bash -c 'git grep -nE "^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b" -- backend/ ":!backend/app/modules/auth/" ":!backend/app/modules/admin/" ":!backend/app/modules/audit/models.py" ":!backend/app/modules/audit/service.py" ":!backend/app/api/main.py" ":!backend/app/processing/ingest/tasks_raster.py" ":!backend/app/modules/embed_tokens/service.py" ":!backend/app/modules/catalog/maps/service.py" ":!backend/app/modules/catalog/collections/router.py" ":!backend/app/modules/catalog/datasets/api/router_export.py" ":!backend/app/modules/catalog/datasets/domain/helpers.py" ":!backend/app/modules/catalog/search/service.py" ":!backend/tests/"; test $? -eq 1' && (cd backend && python -c "from app.platform.extensions import get_identity_extension; from app.platform.extensions.defaults import DefaultIdentityExtension; import asyncio; ext = get_identity_extension(); assert isinstance(ext, DefaultIdentityExtension); assert asyncio.run(ext.resolve_identity_from_token('t', None, None)) is None; print('SC3 ok')") && (cd backend && uv run pytest tests/test_layering.py -v -m architecture --tb=short) && bash -c '(docker compose exec api uv run pytest -m "not perf" --tb=short -q 2>&1 || cd backend && uv run pytest -m "not perf" --tb=short -q 2>&1) | tee /tmp/214-04-pytest.log | tail -5 | grep -E "[0-9]+ passed"' && test -f .planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md && grep -q "Result.*PASS" .planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md</automated>
  </verify>
  <acceptance_criteria>
    - `cd backend && uv run alembic check` exits 0 with no NEW auth-domain (`users`, `roles`, `user_roles`, `api_keys`, `refresh_tokens`) schema diff. Pre-existing procrastinate / raw-SQL drift is acceptable.
    - The full pytest invocation exits 0; final summary line shows `≥2003 passed` (host) or `≥1998 passed, 5 skipped` (container). Capture the exact summary line in the SUMMARY.
    - `cd backend && uv run ruff check .` exits 0.
    - `cd backend && uv run ruff format --check .` exits 0.
    - SC#1 gate (Step 4) — Python execution exits 0 with `SC#1 ok` (verifies the 4 symbols exist, 6-field surface matches D-01, Identity alias holds).
    - SC#2 gate (Step 5) — `git grep ... :!<13 allowlist entries> ...` returns ZERO matches (exit 1; closes ROADMAP SC#2). The architecture-guard test in `test_layering.py` asserts the same invariant programmatically.
    - SC#3 gate (Step 6) — Python execution exits 0 with `SC#3 ok` (verifies typed accessor exists, falls back to default, default returns None).
    - Architecture guard standalone (Step 7) — `cd backend && uv run pytest tests/test_layering.py -v -m architecture` exits 0 with `5 passed` (host-run; on container without `.git/`, would be `5 skipped` — acceptable per Pitfall 5).
    - Frontend-untouched gate (Step 8) — `git diff --name-only ... -- frontend/` produces zero output (D-26).
    - SC#5 soft gate (Step 9) — pyright reports 0 NEW errors in `core/identity.py` and `auth/dependencies.py` (or step is documented as skipped per D-25 soft interpretation).
    - `.planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md` exists with the structured evidence table and a `**Result:** PASS` line.
    - The SUMMARY explicitly maps each ROADMAP SC#1–SC#5 to the verification command(s) that satisfied it (the "ROADMAP Phase 214 Success Criteria - Status" table).
    - The SUMMARY documents the two reconciliation notes from `<planning_context>`: (a) `audit/service.py:24` is allowlisted (not migrated) per RESEARCH § Pitfall 1; (b) the extension wire-in is duplicated across `get_optional_user` and `get_current_user` per RESEARCH § Pitfall 9.
  </acceptance_criteria>
  <done>
    All five ROADMAP Phase 214 success criteria are demonstrably met. The SUMMARY captures exit codes and key output for each command. Phase 214 is ready for `/gsd-verify-work` and ultimately for Phase 218's `/oc-audit` re-run to confirm Boundary grade improvement (B → A−) and Seam Quality improvement (C → B). Phase 217 (auth-saml-enterprise) is unblocked.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none) | This plan is split into (a) extending an architecture-guard test and (b) running a verification gate. Both are read-only checks against the working tree + DB schema; no production code changes; no new boundaries introduced. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-214-IL-05 | T (Tampering) — false-pass gate | The verification gate itself | mitigate | Each verification command is independently re-runnable: `alembic check` against the live DB, full pytest, ruff against the source tree, `git grep` with explicit pathspec exclusions, Python smoke imports for SC#1/SC#3. The SUMMARY reports exit codes and stdout excerpts that any reviewer (Phase 218's `/oc-audit` re-run, or `/gsd-verify-work`) can re-execute. The combined gate covers ROADMAP SC#1-#5 with explicit 1:1 mapping (see `<verification>` block below). |
| T-214-AB-10 | E (Elevation via skipping the gate) | Phase exit | accept | If a contributor merges without running this plan, `/gsd-verify-work` catches the missing 214-04-SUMMARY.md artifact and Phase 218's audit re-run catches any reintroduced finding. The plan is the proof, not the policy. |
| T-214-AB-11 | T (Tampering) — architecture-guard test allowlist drift | `test_cross_domain_does_not_import_user_from_auth_models` pathspec | mitigate | The 13-entry allowlist is stable across Plan 03 (where it was first defined) and Plan 04 (where it is enforced). Future contributors who add a SQL InstrumentedAttribute use of `User` in a new file must EITHER refactor the SQL to fetch via the dep chain OR add the file to the allowlist with a documented Pitfall-1-style rationale. The test failure message names the offending lines for fix-forward; review of the allowlist additions happens at PR time. |
| T-214-IL-06 | INFO — no new external surface | (none) | accept | This plan modifies one test file and creates one Markdown SUMMARY. No production code change. |
</threat_model>

<verification>
- ROADMAP SC#1 (`core/identity.py` defines `IdentityProtocol`; concrete `User` satisfies it) verified by Step 4 (Python smoke verifies the 4 symbols + 6-field surface) AND Step 2 (full pytest run exercises structural conformance end-to-end across 2003+ tests).
- ROADMAP SC#2 (cross-domain `User` import sites type against `IdentityProtocol`) verified by Step 5 (zero git-grep matches outside the 18-file allowlist) AND Step 7 (`test_cross_domain_does_not_import_user_from_auth_models` asserts the same invariant from inside the test suite).
- ROADMAP SC#3 (extension hook + typed accessor mirroring branding/audit/auth) verified by Step 6 (Python smoke imports `get_identity_extension`, asserts default fallback, asserts default returns None preserving JWT path).
- ROADMAP SC#4 (≥1965-test baseline holds; auth/OAuth/API-key/refresh-token flows unchanged) verified by Step 2 (≥2003 passed; existing 1999 baseline + 4 net new Phase 214 tests).
- ROADMAP SC#5 (no new pyright/mypy regressions, soft per D-25) verified by Step 9 (optional ad-hoc pyright spot-check on `core/identity.py` and `auth/dependencies.py`).
- D-18 (broadened `core/` test replaces narrow Phase 212-03 test; new cross-domain User-import test) verified by Task 04-01 acceptance criteria (test count = 5; specific function names present; specific function names absent).
- D-19 (allowlist via `:!` pathspec exclusions) verified by Task 04-01 acceptance criteria (13 specific pathspec entries verified individually) AND Step 7 (test passes).
- D-20 (module docstring credits Phase 214) verified by Task 04-01 acceptance criteria (`head -25 backend/tests/test_layering.py | grep "Phase 214"` ≥ 1).
- D-23 (no alembic migration) verified by Step 1 (zero auth-domain schema diff; pre-existing procrastinate-only drift acceptable per Pitfall 4).
- D-24 (1999-test baseline) verified by Step 2 (≥2003 passed).
- D-25 (SC#5 soft) verified by Step 9 (optional pyright; project doesn't run pyright/mypy in CI; ruff is canonical).
- D-26 (frontend untouched) verified by Step 8 (zero entries under `frontend/` in the phase diff).
- Reconciliation notes from `<planning_context>` honored:
  (a) RESEARCH § Pitfall 1 — `audit/service.py:24` is on the test 2 allowlist (`:!backend/app/modules/audit/service.py` in pathspec; verified by Task 04-01 acceptance criteria and Step 5 grep).
  (b) RESEARCH § Pitfall 9 — Plan 02 duplicated the wire-in across `get_optional_user` and `get_current_user`; Plan 04 inherits the working baseline and verifies via Step 2 full pytest run.
</verification>

<success_criteria>
- All five ROADMAP Phase 214 success criteria are demonstrably met with command-level evidence in `.planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md`.
- `backend/tests/test_layering.py` ends with 5 architecture tests: 1 broadened Phase 214 (`test_core_does_not_import_from_any_module`), 1 deleted-path Phase 212 (`test_app_settings_imports_only_via_core_db_models` — kept verbatim), 2 Phase 213 (`test_no_imports_from_auth_visibility`, `test_no_auth_visibility_module_referenced`), 1 NEW Phase 214 (`test_cross_domain_does_not_import_user_from_auth_models`). Module docstring credits Phases 212, 213, AND 214.
- The 13-entry pathspec allowlist for the cross-domain User-import test exactly matches the 18-file source-tree allowlist defined by Plan 03's migration (the directory exclusions `:!backend/app/modules/auth/` and `:!backend/app/modules/admin/` subsume 8 individual files; the rest are explicit file entries).
- Phase 214 introduces zero behavior change at the wire level (HTTP contract unchanged, DB schema unchanged, no migration generated). The only changes are: (a) one new file (`core/identity.py`), (b) extension scaffolding additions to `platform/extensions/{__init__,defaults}.py`, (c) `auth/dependencies.py` retyped + extension wire-in (default returns None preserving JWT path), (d) ~33 caller files migrated, (e) `test_layering.py` extended.
- Phase 214 is ready for orchestrator-level `/gsd-verify-work` and for Phase 218's `/oc-audit` re-run to verify Boundary grade improvement (B → A−) and Seam Quality improvement (C → B).
- The Phase 217 (auth-saml-enterprise) prerequisite is met: an enterprise overlay can register `_extensions["identity"] = SAMLIdentityExtension(...)` via the `geolens.extensions` entry-point group, and `get_identity_extension()` will return it on subsequent requests without any further core changes.
- The audit's §10 finding ("Concrete `User` ORM stays in `auth` but invisible to consumers") is realized: cross-domain code outside the 18-file allowlist cannot import the concrete `User` ORM (architecture-guard test enforces it).
</success_criteria>

<output>
After completion, the SUMMARY at `.planning/phases/214-identity-protocol-extract/214-04-SUMMARY.md` is the artifact. It must contain:
- A `**Result:** PASS` (or `FAIL` with diagnostic notes) header.
- The structured evidence table mapping each verification command (Steps 1-9) to its exit code and a one-line stdout excerpt.
- The ROADMAP Phase 214 SC#1-SC#5 status table with PASS/FAIL and evidence pointers.
- A note that pyright was run ad-hoc per D-25 soft interpretation (or skipped with rationale).
- A note that the architecture-guard skip behavior in container is by design (Pitfall 5).
- A note that any procrastinate / raw-SQL drift in Step 1 is pre-existing (Pitfall 4), not introduced by Phase 214.
- The two reconciliation notes from `<planning_context>` documented:
  (a) `audit/service.py:24` is allowlisted (not migrated) per RESEARCH § Pitfall 1.
  (b) Extension wire-in is duplicated across `get_optional_user` and `get_current_user` per RESEARCH § Pitfall 9.
- A pointer to Phase 217 (auth-saml-enterprise) as the next phase, noting that Phase 214 is now its prerequisite-satisfied dependency.
</output>
