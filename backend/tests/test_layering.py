"""Layering rules across Phases 212, 213, 214, 222, 223, 224, 225, 226, 230, 231, 232, and 233.

Enforces open-core boundaries closed by:
- Phase 212 LAYER-01 - core/ must not depend on modules/settings/.
- Phase 213 LAYER-02 - modules/auth/visibility.py is gone; catalog authorization
  lives at app.modules.catalog.authorization.
- Phase 214 IDENT-01..03 - core/ broadened: must not depend on ANY app.modules.*.
  Cross-domain code does not import the concrete `User` ORM from
  `app.modules.auth.models` outside the 18-file allowlist (auth/**, admin/**,
  plus 7 specific files where `User` is used as a SQLAlchemy InstrumentedAttribute
  holder for SQL queries).
- Phase 225 PROCESS-02/04 - processing/ must not import from app.modules.catalog.*;
  all catalog access goes through ProcessingPort (app.core.processing_port).
- Phase 230 CATPORT-02/04 - catalog/ must not have module-level imports from
  app.processing.*; all processing access goes through CatalogPort
  (app.core.catalog_port).
- Phase 226 AIEXT-03/05 - processing/ai/ must not contain hardcoded
  `if provider == "anthropic"/"openai_compatible"` dispatch; all provider
  dispatch goes through `get_ai_provider(name).complete(...)` from
  `app.platform.extensions`. Pathspec excludes `streaming.py` and
  `metadata_service.py` per RESEARCH.md Open Questions 1 & 2 (true
  LLM-token streaming and structured-output APIs are deferred-scope
  follow-up phases).
- Phase 231 EMBPROV-04 - the Phase-226 architecture guard
  test_no_module_level_provider_sdk_imports_in_processing_ai is RENAMED
  to test_no_module_level_provider_sdk_imports_in_processing, pathspec
  broadened from backend/app/processing/ai/ to backend/app/processing/,
  and the embeddings carve-out paragraph removed from the docstring.
- Phase 232 PERM-05 - known permission/visibility chokepoints must route
  through PermissionExtension: require_permission(), apply_visibility_filter(),
  and dataset detail access helpers.
- Phase 233 WORK-05 - known dataset publication transition chokepoints must
  route through WorkflowExtension: /status/, /target-status/, and metadata
  PATCH record_status writes.

If a test in this file fails, a forbidden import was reintroduced - the failure
message names the offending lines for fix-forward.

Scope:
- `from app.modules.*` under `backend/app/core/` (Phase 214 IDENT-01 - broadens
  Phase 212's settings-only guard)
- `from app.modules.settings.models` anywhere under `backend/` (Phase 212 D-05
  deleted-path regression)
- `from app.modules.auth.visibility` anywhere under `backend/` (Phase 213 LAYER-02)
- Broader `auth.visibility` reference catch (Phase 213 LAYER-02)
- PermissionExtension chokepoint delegation (Phase 232 PERM-05)
- WorkflowExtension publication chokepoint delegation (Phase 233 WORK-05)
- `from app.modules.auth.models import .*\\bUser\\b` outside the 18-file
  allowlist (Phase 214 IDENT-02 - pathspec excludes auth/**, admin/**,
  audit/{models,service}.py, api/main.py, processing/ingest/tasks_raster.py,
  embed_tokens/service.py, catalog/{maps/service,collections/router,
  datasets/api/router_export,datasets/domain/helpers,search/service}.py, and
  tests/)

Phase 218 will re-run `/oc-audit` to verify Boundary B -> A-, Seam Quality
C -> B, OSS Surface D -> C grade improvements.

Markers:
- `@pytest.mark.architecture` - opt-out locally with `pytest -m 'not architecture'`
  (Phase 212-03 D-07). Runs by default in CI because `addopts` does not exclude it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

# backend/tests/test_layering.py -> backend/tests -> backend -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]


def _has_git_metadata() -> bool:
    """Return True if `.git/` is present at the repo root.

    Subprocess-based `git grep` requires git metadata. Some container test
    invocations may exclude `.git/` via `.dockerignore`; in that case we skip
    rather than fail (RESEARCH.md Pitfall 4).
    """
    return (REPO_ROOT / ".git").exists()


def _has_pathspec_magic() -> bool:
    """Return True if git supports `:!` pathspec exclusion (git >= 2.13).

    Older git versions reject the `:!` exclusion syntax with a non-zero
    exit code that is not the standard "no matches" rc=1. In containers
    pinned to ancient git, fall back to skipping rather than failing.
    """
    result = subprocess.run(
        ["git", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    # `git version 2.X.Y` -> extract minor X
    match = re.search(r"git version 2\.(\d+)", result.stdout)
    return match is not None and int(match.group(1)) >= 13


def _git_grep(pattern: str, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "grep", "-n", "-E", pattern, "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.architecture
def test_core_does_not_import_from_any_module() -> None:
    """`backend/app/core/` must never import from `app.modules.*`.

    Closes Phase 214 IDENT-01 (broadens Phase 212-03's settings-only guard).
    The `core` layer is the lowest layer; modules (auth, catalog, audit,
    settings, ...) depend on core, never the reverse. Phase 214's
    `core/identity.py` is the first new file in `core/` since Phase 212;
    this test ensures it (and any future core/ files) respect the boundary.

    Subsumes Phase 212-03's `test_core_does_not_import_from_settings_module`
    - `app.modules.settings` is a subset of `app.modules.*`. The deleted-path
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


@pytest.mark.architecture
def test_app_settings_imports_only_via_core_db_models() -> None:
    """`AppSetting` must only be imported from `app.core.db.models`.

    Catches reintroduction of the deleted `app.modules.settings.models` path
    (Phase 212 D-05). Anywhere across `backend/` that still names that module
    is a regression.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    # Match only import-shaped lines so docstrings/error messages in this
    # file that reference the deleted path do not trigger a self-positive.
    result = _git_grep(
        r"^\s*(from|import)\s+app\.modules\.settings\.models",
        "backend/",
    )

    if result.returncode == 0:
        pytest.fail(
            "Regression: a deleted import path is referenced. Use "
            "`app.core.db.models` instead. Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_no_imports_from_auth_visibility() -> None:
    """`auth.visibility` import path must not appear anywhere under `backend/`.

    Closes Phase 213 LAYER-02: the deleted `app.modules.auth.visibility` path
    becomes a hard ModuleNotFoundError after this phase - any surviving import
    is a migration miss. Maps directly to ROADMAP SC#4.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = _git_grep(
        r"^\s*(from|import)\s+app\.modules\.auth\.visibility",
        "backend/",
    )

    if result.returncode == 0:
        pytest.fail(
            "Regression: deleted import path `app.modules.auth.visibility` is still "
            "referenced. Migrate to `app.modules.catalog.authorization`. "
            "Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_no_auth_visibility_module_referenced() -> None:
    """Broader guard: `auth.visibility` string must not appear as a module reference.

    Catches re-exports in `__init__.py` files or indirect references that the
    import-shaped guard above would miss. Excludes this test file itself via
    a `:!` pathspec so the regex literal in the guard does not produce a
    self-positive (Phase 212-03 bug, commit b0bd0c2c — fixed there with an
    import-anchor; here we use the broader regex deliberately and rely on the
    pathspec exclusion instead).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; rely on the import-shaped "
            "guard above (test_no_imports_from_auth_visibility) instead"
        )

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"app\.modules\.auth\.visibility|auth\.visibility",
            "--",
            "backend/",
            ":!backend/tests/test_layering.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Regression: `auth.visibility` is referenced outside test_layering.py. "
            "Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_permission_chokepoints_use_extension() -> None:
    """Phase 232 PERM-05: known permission chokepoints must use PermissionExtension.

    This guard is intentionally narrow. It seals the two Phase 232 surfaces
    from the roadmap instead of scanning every auth/catalog file:
    - ``require_permission()`` delegates capability decisions.
    - catalog visibility helpers delegate list filtering and detail access.
    """
    auth_path = REPO_ROOT / "backend/app/modules/auth/dependencies.py"
    catalog_path = REPO_ROOT / "backend/app/modules/catalog/authorization.py"

    auth_source = auth_path.read_text()
    catalog_source = catalog_path.read_text()

    require_permission_idx = auth_source.find("def require_permission")
    if require_permission_idx == -1:
        pytest.fail("require_permission() not found in auth dependencies")
    require_permission_block = auth_source[require_permission_idx:]
    if (
        "get_permission_extension()" not in require_permission_block
        or ".check_permission(" not in require_permission_block
    ):
        pytest.fail(
            "Phase 232 PERM-05 invariant violated: require_permission() must "
            "delegate capability decisions to PermissionExtension. Expected "
            "get_permission_extension().check_permission(...) in "
            f"{auth_path.relative_to(REPO_ROOT)}."
        )

    apply_visibility_idx = catalog_source.find("def apply_visibility_filter")
    get_roles_idx = catalog_source.find("async def get_user_roles")
    if apply_visibility_idx == -1 or get_roles_idx == -1:
        pytest.fail("catalog apply_visibility_filter()/get_user_roles boundary not found")
    apply_visibility_block = catalog_source[apply_visibility_idx:get_roles_idx]
    if (
        "get_permission_extension()" not in apply_visibility_block
        or ".filter_visible(" not in apply_visibility_block
    ):
        pytest.fail(
            "Phase 232 PERM-05 invariant violated: apply_visibility_filter() "
            "must delegate query filtering to PermissionExtension. Expected "
            "get_permission_extension().filter_visible(...) in "
            f"{catalog_path.relative_to(REPO_ROOT)}."
        )

    access_idx = catalog_source.find("async def check_dataset_access_or_anonymous")
    if access_idx == -1:
        pytest.fail("catalog dataset-access helpers not found")
    access_block = catalog_source[access_idx:]
    if (
        "get_permission_extension()" not in access_block
        or ".can_access_dataset(" not in access_block
    ):
        pytest.fail(
            "Phase 232 PERM-05 invariant violated: dataset detail access must "
            "delegate access decisions to PermissionExtension. Expected "
            "get_permission_extension().can_access_dataset(...) in "
            f"{catalog_path.relative_to(REPO_ROOT)}."
        )


@pytest.mark.architecture
def test_workflow_publication_chokepoints_use_extension() -> None:
    """Phase 233 WORK-05: known publication transitions use WorkflowExtension.

    This guard is intentionally narrow. It checks the two publication endpoints
    plus the metadata PATCH record_status helper, and it does not scan seed,
    ingest, or factory paths that assign initial record_status values.
    """
    router_path = REPO_ROOT / "backend/app/modules/catalog/datasets/api/router_data.py"
    metadata_path = (
        REPO_ROOT / "backend/app/modules/catalog/datasets/domain/service_metadata.py"
    )

    router_source = router_path.read_text()
    metadata_source = metadata_path.read_text()

    status_idx = router_source.find("async def update_publication_status")
    target_idx = router_source.find("async def set_target_status")
    if status_idx == -1 or target_idx == -1:
        pytest.fail("publication status endpoint boundary not found in router_data.py")
    status_block = router_source[status_idx:target_idx]
    target_block = router_source[target_idx:]

    for label, block, mode in (
        ("/status/", status_block, 'mode="status"'),
        ("/target-status/", target_block, 'mode="target_status"'),
    ):
        if (
            "get_workflow_extension()" not in block
            or "WorkflowTransitionContext(" not in block
            or ".allowed_transitions(" not in block
            or ".on_transition(" not in block
            or mode not in block
        ):
            pytest.fail(
                "Phase 233 WORK-05 invariant violated: "
                f"{label} must delegate publication transitions to "
                "WorkflowExtension. Expected get_workflow_extension(), "
                "WorkflowTransitionContext, allowed_transitions(...), "
                f"on_transition(...), and {mode} in "
                f"{router_path.relative_to(REPO_ROOT)}."
            )

    metadata_idx = metadata_source.find("async def _apply_record_status_change")
    is_dem_idx = metadata_source.find("async def _apply_is_dem")
    if metadata_idx == -1 or is_dem_idx == -1:
        pytest.fail("metadata record_status helper boundary not found")
    metadata_block = metadata_source[metadata_idx:is_dem_idx]
    if (
        "get_workflow_extension()" not in metadata_block
        or "WorkflowTransitionContext(" not in metadata_block
        or ".allowed_transitions(" not in metadata_block
        or ".on_transition(" not in metadata_block
        or 'mode="metadata_patch"' not in metadata_block
    ):
        pytest.fail(
            "Phase 233 WORK-05 invariant violated: metadata PATCH record_status "
            "writes must delegate to WorkflowExtension. Expected "
            "get_workflow_extension(), WorkflowTransitionContext, "
            "allowed_transitions(...), on_transition(...), and "
            "mode=\"metadata_patch\" in "
            f"{metadata_path.relative_to(REPO_ROOT)}."
        )


@pytest.mark.architecture
def test_cross_domain_does_not_import_user_from_auth_models() -> None:
    """`from app.modules.auth.models import .*User` must only appear in the allowlist.

    Closes Phase 214 IDENT-02. The concrete `User` SQLAlchemy ORM stays
    inside `auth/`; cross-domain code (catalog, audit, processing, platform,
    standards) types against `app.core.identity.Identity` (the Protocol
    alias) instead. Allowlist (D-09 + Pitfall 1 reconciliation):

    - `auth/**`         - owns the model
    - `admin/**`        - admin endpoints CRUD User rows; read sensitive
                          fields (password_hash, auth_provider, etc.) NOT
                          on the Identity Protocol
    - `audit/models.py` - `Mapped["User"]` relationship (TYPE_CHECKING)
    - `audit/service.py`- function-scope `select(User.id)` SQL filter
                          (Pitfall 1 reconciliation - InstrumentedAttribute
                          use, not parameter annotation)
    - `api/main.py`     - Base.metadata registration for Alembic discovery
    - `processing/ingest/tasks_raster.py`
                          - Procrastinate worker `Base.metadata` registration
    - `embed_tokens/service.py` - function-scope `select(...User.username...)`
                                   for admin embed-token list (Pitfall 1)
    - `catalog/maps/service.py` - `User.username.label()` in JOINs/SELECTs
                                   for owner display (Pitfall 1)
    - `catalog/collections/router.py` - `select(User).where(User.id.in_(actor_ids))`
                                         for actor enrichment (Pitfall 1)
    - `catalog/datasets/api/router_export.py` - `select(User).where(User.id == ...)`
                                                for export header personalization (Pitfall 1)
    - `catalog/datasets/domain/helpers.py` - `select(User).where(User.id.in_(ids))`
                                              for batched user resolution (Pitfall 1)
    - `catalog/search/service.py` - `select(User).where(User.id.in_(actor_ids))`
                                     for search-result enrichment (Pitfall 1)
    - `tests/`          - fixtures construct `User(...)` directly; structurally
                          valid as Identity at the call site

    The `\\bUser\\b` word-boundary ensures `import UserRole` (no standalone
    `User`) does NOT trip the guard - `UserRole` stays concrete per D-08.
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


@pytest.mark.architecture
def test_no_external_imports_of_dataset_domain_submodules() -> None:
    """Phase 224 DECOUPLE-04: no external module imports the catalog/datasets/
    domain/service_X sub-modules directly. All consumers must go through the
    ``app.modules.catalog.datasets.domain.service`` façade.

    Phase 224 split the 1407-LOC ``service.py`` god-module into 5 cohesive
    sub-modules (service_create, service_query, service_lifecycle,
    service_metadata, service_relationships) behind a thin re-export façade.
    DECOUPLE-01 preserved zero call-site churn — the 22 consumer files in
    ``backend/app/`` still import from ``service``. This guard fails CI if
    any module under ``backend/app/`` (excluding the 5 sub-modules + service.py
    + this test file) starts importing from a sub-module directly,
    re-introducing the bypass that DECOUPLE-04 forbids.

    Cross-imports BETWEEN the 5 sub-modules are PERMITTED (D-05) — e.g.,
    ``service_create.py`` imports ``_safe_table_ref`` from
    ``service_lifecycle`` and ``auto_detect_relationships`` from
    ``service_relationships``. The sub-modules collaborate as a domain
    package; only external bypasses are forbidden.

    Allowlist (files allowed to reference service_X paths directly):
      - The 5 sub-modules themselves (service_create.py, service_query.py,
        service_lifecycle.py, service_metadata.py, service_relationships.py)
      - The service.py façade (it re-exports from each sub-module)
      - This test file (it documents and enforces the invariant)

    Maps to Phase 224 ROADMAP DECOUPLE-04 close gate. Mirrors AUDIT-02
    (Phase 222) and BILLING-02 (Phase 223) architecture guards.
    See ``oc-separation-audit-20260430-b.md`` §5 + §7 P0 #1.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    # Pattern matches any of the 5 sub-modules OR the _sql_safety helper.
    # _sql_safety is an internal module (underscore prefix) holding shared
    # SQL-injection-prevention regexes; external callers must reach
    # _safe_table_ref through the service.py façade re-export, not directly.
    pattern = (
        r"from app\.modules\.catalog\.datasets\.domain\."
        r"(service_(create|query|lifecycle|metadata|relationships)|_sql_safety)"
    )

    result = _git_grep(pattern, "backend/app/")

    # Allowlisted paths — these MAY reference the sub-modules / _sql_safety.
    # The 5 sub-modules cross-import each other (D-05) and import shared
    # regexes from _sql_safety; service.py re-exports from all of them;
    # the test file references the path strings in this docstring.
    allowlist_prefixes = {
        "backend/app/modules/catalog/datasets/domain/service.py",
        "backend/app/modules/catalog/datasets/domain/service_create.py",
        "backend/app/modules/catalog/datasets/domain/service_query.py",
        "backend/app/modules/catalog/datasets/domain/service_lifecycle.py",
        "backend/app/modules/catalog/datasets/domain/service_metadata.py",
        "backend/app/modules/catalog/datasets/domain/service_relationships.py",
        "backend/app/modules/catalog/datasets/domain/_sql_safety.py",
    }

    # git grep exit codes: 0 = matches found, 1 = no matches, >1 = error
    if result.returncode == 1:
        # No matches at all — vacuously passes.
        return
    if result.returncode != 0:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )

    offenders: list[str] = []
    for line in result.stdout.splitlines():
        # git grep -n output: "<path>:<lineno>:<content>"
        path = line.split(":", 1)[0]
        if path in allowlist_prefixes:
            continue
        offenders.append(line)

    if offenders:
        pytest.fail(
            "Phase 224 DECOUPLE-04 invariant violated: external module "
            "imports from a catalog/datasets/domain/service_X sub-module "
            "directly. All consumers must go through the "
            "`app.modules.catalog.datasets.domain.service` façade. "
            "Cross-imports between the 5 sub-modules themselves are "
            "permitted (D-05) — only external bypasses are forbidden.\n"
            "Offending lines:\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_no_log_action_calls_outside_audit_service() -> None:
    """Phase 222 AUDIT-02: ``log_action()`` is called only by ``DefaultAuditSink.emit()``.

    All 65 historical call sites must route through ``audit_emit()`` instead.
    Closes the +242% ``log_action`` decentralization regression flagged in
    ``docs-internal/audits/oc-separation-audit-20260430.md`` §5 (line 224).

    Excluded paths:
      - ``backend/app/modules/audit/service.py`` — defines ``log_action()``;
        this is the only application-side caller permitted post-Phase-222.
      - ``backend/app/platform/extensions/defaults.py`` — ``DefaultAuditSink.emit()``
        calls ``log_action()`` via deferred import (Phase 222 D-04 / option a
        from AUDIT-02). The community-edition default sink is the SOLE
        consumer of the preserved helper.
      - ``backend/tests/`` — test seeds (e.g., ``test_lifecycle.py:421, 687``)
        may construct audit_logs rows directly via ``log_action()`` for
        deterministic fixture setup. Tests are exempt from the production-code
        invariant (RESEARCH.md Open Question 3 (b)).

    Pattern matched: ``await log_action(`` — the call shape used by every
    historical site. The ``await`` anchor avoids tripping on the function's
    own definition (``async def log_action(``) and on attribute references
    like ``log_action_helper``.

    Maps directly to Phase 222 ROADMAP SC#4 ("No call site in backend/app/
    calls log_action() directly — all 65 sites route through
    get_audit_sink().emit()") — implementation is via the ``audit_emit()``
    facade introduced in Plan 02.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 222 AUDIT-02 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"\bawait log_action\(",
            "--",
            "backend/app/",
            ":!backend/app/modules/audit/service.py",
            ":!backend/app/platform/extensions/defaults.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 222 AUDIT-02 invariant violated: log_action() is called "
            "outside backend/app/modules/audit/service.py and "
            "backend/app/platform/extensions/defaults.py. All 65 historical "
            "sites must use audit_emit(session, AuditEvent(...)) instead.\n"
            f"Offending lines:\n{result.stdout}"
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_no_core_marketplace_import() -> None:
    """Phase 223 BILLING-02: ``app.core.marketplace`` does not exist after Phase 223.

    Asserts that:
      (a) ``import app.core.marketplace`` raises ImportError — the module file
          ``backend/app/core/marketplace.py`` was deleted in Plan 03 (D-02).
      (b) No surviving ``from app.core.marketplace`` reference exists anywhere
          in ``backend/app/`` — the lifespan startup at ``api/main.py:184-203``
          was rewritten to dispatch through ``BillingExtension.on_startup`` in
          Plan 02; the import line at ``api/main.py:20`` was deleted in Plan 02.

    The 30-line ``register_marketplace_usage`` function was relocated to the
    enterprise overlay (geolens-enterprise/geolens_enterprise/billing/__init__.py
    in Plan 05). The community core has zero AWS Marketplace business logic
    after this phase.

    Negative-control: any future regression that re-creates the file or
    re-introduces a ``from app.core.marketplace`` import fails this test
    immediately at CI time.
    """
    import importlib

    # (a) Importing the module must fail
    try:
        importlib.import_module("app.core.marketplace")
        pytest.fail(
            "Phase 223 BILLING-02 invariant violated: app.core.marketplace was "
            "importable. The module file backend/app/core/marketplace.py must be "
            "deleted (Plan 03 / D-02). The 30-line register_marketplace_usage "
            "function was relocated to the enterprise overlay's "
            "MarketplaceBillingExtension class (Plan 05)."
        )
    except ImportError:
        pass  # Expected: module was deleted

    # (b) No surviving import of app.core.marketplace anywhere in backend/app/
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 223 BILLING-02 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"from app\.core\.marketplace|import app\.core\.marketplace",
            "--",
            "backend/app/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 223 BILLING-02 invariant violated: backend/app/ still "
            "contains a `from app.core.marketplace` or `import app.core.marketplace` "
            "reference. The lifespan dispatch in api/main.py must use "
            "`get_billing_extensions()` and the AWS Marketplace business logic "
            "lives ONLY in the enterprise overlay's MarketplaceBillingExtension. "
            "Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_billing_dispatch_uses_hardcoded_timeout() -> None:
    """Phase 223 BILLING-04 / D-11: the production dispatch loop hardcodes timeout=10.0.

    D-11 deliberately rejects making the timeout configurable (no
    ``BILLING_STARTUP_TIMEOUT_SECONDS`` env var, no per-extension override).
    Today's value is hardcoded; preserving that as a constant in core's
    dispatch loop is the smallest-diff option and matches the pre-phase-223
    behavior at the now-deleted line 191 of api/main.py.

    Test fixtures (test_billing_extension.py::_dispatch) accept a parameterized
    ``timeout`` argument for fast tests, but the PRODUCTION dispatch loop in
    api/main.py MUST use the literal ``timeout=10.0``. This test catches drift
    between the two.

    Negative-control: any change that wraps the timeout in a settings field
    or env-var lookup will fail this test (the literal will be missing).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"asyncio\.wait_for\(ext\.on_startup\(app\), timeout=10\.0\)",
            "--",
            "backend/app/api/main.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 1:
        pytest.fail(
            "Phase 223 BILLING-04 / D-11 invariant violated: backend/app/api/main.py "
            "does NOT contain the production BillingExtension dispatch loop with "
            "literal `asyncio.wait_for(ext.on_startup(app), timeout=10.0)`. The "
            "10-second timeout MUST be hardcoded (D-11 — YAGNI for env-var "
            "configuration). Either the dispatch loop is missing entirely (Plan 02 "
            "incomplete) or the literal timeout was changed."
        )
    if result.returncode not in (0,):
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_no_processing_imports_catalog() -> None:
    """Phase 225 PROCESS-02/04: backend/app/processing/ must not have module-level imports from app.modules.catalog.*.

    All catalog access must go through ProcessingPort (app.core.processing_port).
    Strict zero-hit for module-level (top-level, unindented) imports — no allowlist
    for processing/* (D-23).

    Excluded paths:
      - backend/tests/ — test fixtures construct catalog ORM objects directly,
        structurally satisfying the Protocols (the scan target backend/app/processing/
        is already disjoint from backend/tests/, so no explicit pathspec exclusion
        is needed).

    Scope: this guard catches module-level imports (lines starting at column 0
    with ``from app.modules.catalog`` or ``import app.modules.catalog``).
    Function-scope lazy imports (indented, e.g. inside async def bodies in
    tiles/router.py, ai/service.py, ai/router.py, ai/metadata_service.py,
    export/router.py) are a separate migration target and are out of scope for
    this guard. The guard prevents any NEW module-level catalog import edges
    from being introduced.

    The pattern ``^(from|import) app.modules.catalog`` (literal space, no backslash-s
    metachar) is used because git grep's POSIX ERE does not recognize backslash-s as a
    whitespace class — the POSIX-compatible form would require ``[[:space:]]``, but
    a literal space is equivalent for well-formatted Python import statements and
    matches the intent of the guard.

    Maps to Phase 225 ROADMAP SC#2 / SC#3. Inlines former Phase 999.11
    (added in same phase as the inversion — guard before inversion fails CI).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 225 PROCESS-04 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"^(from|import) app\.modules\.catalog",
            "--",
            "backend/app/processing/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 225 PROCESS-02/04 invariant violated: backend/app/processing/ "
            "contains a module-level import from app.modules.catalog.*. All catalog "
            "access must go through ProcessingPort (app.core.processing_port). "
            f"Offending lines:\n{result.stdout}"
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_no_catalog_imports_processing() -> None:
    """Phase 230 CATPORT-02/04: catalog/ must not have module-level imports from app.processing.*.

    All processing-owned helper, task, schema, and ORM-class access from
    backend/app/modules/catalog/ must go through CatalogPort
    (app.core.catalog_port). Strict zero-hit for module-level imports.

    Scope: this guard catches top-level import lines starting at column 0:
    ``from app.processing``, ``import app.processing``, and the equivalent
    ``backend.app.processing`` forms. Function-local lazy imports are allowed by
    the phase context as deferred boundaries; new module-level edges are not.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 230 CATPORT-04 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"^(from|import) (backend\.)?app\.processing",
            "--",
            "backend/app/modules/catalog/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 230 CATPORT-02/04 invariant violated: "
            "backend/app/modules/catalog/ contains a module-level import from "
            "app.processing.*. All processing access must go through CatalogPort "
            "(app.core.catalog_port). Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_no_hardcoded_ai_provider_branches() -> None:
    """Phase 226 AIEXT-03/05: no hardcoded ``if provider ==`` dispatch in processing/ai/.

    SC#3 binding (ROADMAP §Phase 226): ``grep -RE "if .*provider *== *['\"]
    (anthropic|openai_compatible)" backend/app/processing/ai/`` returns zero
    hits after the Phase 226 migration. Replaces ten dispatch sites that
    previously branched on the provider name string (5 in scope after the
    migration; 4 in deferred-scope files documented below).

    Excluded paths:
      - ``backend/app/processing/ai/streaming.py`` — true LLM-token
        streaming via ``_stream_anthropic_chat`` / ``_stream_openai_chat``
        (~200 LOC each) is explicitly deferred per RESEARCH.md Open
        Question 1. CONTEXT.md §deferred lists "True LLM-token streaming"
        as a follow-up phase. The if/elif provider branches at
        ``streaming.py:516,531`` will migrate when the ``stream()`` Protocol
        method is implemented for real (current default raises
        NotImplementedError per D-03).
      - ``backend/app/processing/ai/metadata_service.py`` — structured-output
        APIs (``client.beta.chat.completions.parse`` for OpenAI Pydantic
        response_format; ``tool_choice={"type":"tool","name":"output"}``
        for Anthropic forced-tool-use) don't map to the wide ``complete()``
        Protocol shape, which returns ``ToolLoopResult`` (not a Pydantic
        model). RESEARCH.md Open Question 2: a future phase adds
        ``structured_complete(response_model, ...)`` to the Protocol; until
        then the dispatch at ``metadata_service.py:255,291`` is
        pathspec-excluded.

    Negative-control (D-14): temporarily reintroduce
    ``if provider == "anthropic":`` in ``processing/ai/sql_generator.py``,
    run this test, confirm it fails with the offending line surfaced.
    Revert. Run again, confirm green.

    Maps to AIEXT-03 + AIEXT-05 (REQUIREMENTS.md §Phase 226).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 226 AIEXT-03 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-P",
            r"if\s+.*provider\s*==\s*['\"](?:anthropic|openai_compatible)",
            "--",
            "backend/app/processing/",
            ":!backend/app/processing/ai/streaming.py",
            ":!backend/app/processing/ai/metadata_service.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 226 AIEXT-03 invariant violated: hardcoded AI provider "
            "dispatch (`if provider == 'anthropic'/'openai_compatible'`) found "
            "in backend/app/processing/. Replace with "
            "`get_ai_provider(name).complete(...)` from "
            "`app.platform.extensions`.\nOffending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
def test_no_module_level_provider_sdk_imports_in_processing() -> None:
    """oc-audit 2026-05-02 §5 + Phase 231: backend/app/processing/ must not have
    module-level imports of provider SDKs (anthropic, openai).

    Module-level provider-SDK imports inside ``processing/`` violate the
    open-core boundary: they couple the AI domain to specific SDK packages
    at import time, defeating the AIProviderExtension Protocol seam (Phase
    226). Move imports to function-local scope when needed (mirror Phase
    225's deferred-import discipline) or place them behind the Protocol in
    ``app/platform/extensions/defaults.py``.

    Negative-control (Phase 231 D-15): temporarily reintroduce
    ``from openai import OpenAI`` at the top of
    ``backend/app/processing/embeddings/helpers.py``, run this test,
    confirm it fails with the offending line surfaced. Revert.
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")

    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"^(from|import) (anthropic|openai)( |$)",
            "--",
            "backend/app/processing/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Module-level provider-SDK import found in backend/app/processing/. "
            "Move to function-local scope or behind the AIProviderExtension Protocol "
            "in app/platform/extensions/defaults.py. "
            f"Offending lines:\n{result.stdout}"
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
