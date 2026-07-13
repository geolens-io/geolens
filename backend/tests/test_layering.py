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
  datasets/api/router_export,datasets/domain/helpers,search/service_semantic}.py, and
  tests/)

Phase 218 will re-run `/oc-audit` to verify Boundary B -> A-, Seam Quality
C -> B, OSS Surface D -> C grade improvements.

Markers:
- `@pytest.mark.architecture` - opt-out locally with `pytest -m 'not architecture'`
  (Phase 212-03 D-07). Runs by default in CI because `addopts` does not exclude it.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest


def _discover_repo_roots() -> tuple[Path, Path]:
    """Return (repo_root, backend_root) for host and backend-container layouts."""
    test_file = Path(__file__).resolve()
    for candidate in test_file.parents:
        if (candidate / "backend/app").is_dir():
            return candidate, candidate / "backend"
        if (candidate / "app").is_dir() and (candidate / "tests").is_dir():
            return candidate.parent, candidate
    # Fallback for the historical backend/tests/test_layering.py layout.
    return test_file.parents[2], test_file.parents[1]


REPO_ROOT, BACKEND_ROOT = _discover_repo_roots()


def _backend_path(rel: str) -> Path:
    """Resolve a path relative to backend/ in both host and container runs."""
    return BACKEND_ROOT / rel


def _repo_style_rel(path: Path) -> str:
    """Render paths with the repository's backend/... prefix for stable messages."""
    try:
        return f"backend/{path.relative_to(BACKEND_ROOT).as_posix()}"
    except ValueError:
        return path.relative_to(REPO_ROOT).as_posix()


def _repo_style_path(rel: str) -> Path:
    """Resolve repository-style relative paths in host and backend-container runs."""
    if rel.startswith("backend/"):
        return _backend_path(rel.removeprefix("backend/"))
    return REPO_ROOT / rel


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
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    if result.returncode != 0:
        return False
    # `git version 2.X.Y` -> extract minor X
    match = re.search(r"git version 2\.(\d+)", result.stdout)
    return match is not None and int(match.group(1)) >= 13


# Module-level evaluation of git availability (Phase 278 TEST-09).
# Cached once at import time so @pytest.mark.skipif decorators can reference
# it. Both checks are pure (no side effects beyond a single subprocess call
# to `git --version`); wrapped in try/except above to never raise at import.
_GIT_METADATA_AVAILABLE: bool = _has_git_metadata()
_PATHSPEC_MAGIC_AVAILABLE: bool = _has_pathspec_magic()
_GIT_METADATA_REASON = "git metadata unavailable; arch test only runs on full clones"
_PATHSPEC_MAGIC_REASON_GENERIC = (
    "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce architecture "
    "invariant via grep-based guard"
)


def _git_grep(pattern: str, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "grep", "-n", "-E", pattern, "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _iter_backend_app_python_files() -> list[Path]:
    return sorted((BACKEND_ROOT / "app").rglob("*.py"))


def _normalized_import_root(name: str | None) -> str:
    if name is None:
        return ""
    if name.startswith("backend."):
        return name.removeprefix("backend.")
    return name


def _is_allowed_private_service_importer(path: Path, package_path: str) -> bool:
    rel = _repo_style_rel(path)
    return rel == f"{package_path}/service.py" or (
        rel.startswith(f"{package_path}/service_") and rel.endswith(".py")
    )


def _private_service_import_offenders(
    *,
    package: str,
    package_path: str,
    private_modules: set[str],
) -> list[str]:
    offenders: list[str] = []
    normalized_package = _normalized_import_root(package)

    for path in _iter_backend_app_python_files():
        if _is_allowed_private_service_importer(path, package_path):
            continue

        rel = _repo_style_rel(path)
        try:
            tree = ast.parse(path.read_text(), filename=rel)
        except SyntaxError as exc:
            pytest.fail(f"Could not parse {rel}: {exc}")

        lines = path.read_text().splitlines()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported = _normalized_import_root(alias.name)
                    if any(
                        imported == f"{normalized_package}.{module}"
                        or imported.startswith(f"{normalized_package}.{module}.")
                        for module in private_modules
                    ):
                        offenders.append(
                            f"{rel}:{node.lineno}:{lines[node.lineno - 1].strip()}"
                        )
            elif isinstance(node, ast.ImportFrom):
                imported_from = _normalized_import_root(node.module)
                if imported_from in {
                    f"{normalized_package}.{module}" for module in private_modules
                }:
                    offenders.append(
                        f"{rel}:{node.lineno}:{lines[node.lineno - 1].strip()}"
                    )
                    continue
                if imported_from == normalized_package:
                    imported_names = {alias.name for alias in node.names}
                    if imported_names.intersection(private_modules):
                        offenders.append(
                            f"{rel}:{node.lineno}:{lines[node.lineno - 1].strip()}"
                        )

    return offenders


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
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
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
def test_app_settings_imports_only_via_core_db_models() -> None:
    """`AppSetting` must only be imported from `app.core.db.models`.

    Catches reintroduction of the deleted `app.modules.settings.models` path
    (Phase 212 D-05). Anywhere across `backend/` that still names that module
    is a regression.
    """
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
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
def test_no_imports_from_auth_visibility() -> None:
    """`auth.visibility` import path must not appear anywhere under `backend/`.

    Closes Phase 213 LAYER-02: the deleted `app.modules.auth.visibility` path
    becomes a hard ModuleNotFoundError after this phase - any surviving import
    is a migration miss. Maps directly to ROADMAP SC#4.
    """
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
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
@pytest.mark.skipif(
    not _PATHSPEC_MAGIC_AVAILABLE,
    reason=(
        "git < 2.13 lacks `:!` pathspec exclusion; rely on the import-shaped "
        "guard above (test_no_imports_from_auth_visibility) instead"
    ),
)
def test_no_auth_visibility_module_referenced() -> None:
    """Broader guard: `auth.visibility` string must not appear as a module reference.

    Catches re-exports in `__init__.py` files or indirect references that the
    import-shaped guard above would miss. Excludes this test file itself via
    a `:!` pathspec so the regex literal in the guard does not produce a
    self-positive (Phase 212-03 bug, commit b0bd0c2c — fixed there with an
    import-anchor; here we use the broader regex deliberately and rely on the
    pathspec exclusion instead).
    """
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
    auth_path = _backend_path("app/modules/auth/dependencies.py")
    catalog_path = _backend_path("app/modules/catalog/authorization.py")

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
            f"{_repo_style_rel(auth_path)}."
        )

    apply_visibility_idx = catalog_source.find("def apply_visibility_filter")
    get_roles_idx = catalog_source.find("async def get_user_roles")
    if apply_visibility_idx == -1 or get_roles_idx == -1:
        pytest.fail(
            "catalog apply_visibility_filter()/get_user_roles boundary not found"
        )
    apply_visibility_block = catalog_source[apply_visibility_idx:get_roles_idx]
    if (
        "get_permission_extension()" not in apply_visibility_block
        or ".filter_visible(" not in apply_visibility_block
    ):
        pytest.fail(
            "Phase 232 PERM-05 invariant violated: apply_visibility_filter() "
            "must delegate query filtering to PermissionExtension. Expected "
            "get_permission_extension().filter_visible(...) in "
            f"{_repo_style_rel(catalog_path)}."
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
            f"{_repo_style_rel(catalog_path)}."
        )


@pytest.mark.architecture
def test_workflow_publication_chokepoints_use_extension() -> None:
    """Phase 233 WORK-05: known publication transitions use WorkflowExtension.

    This guard is intentionally narrow. It checks the two publication endpoints
    plus the metadata PATCH record_status helper, and it does not scan seed,
    ingest, or factory paths that assign initial record_status values.
    """
    router_path = _backend_path("app/modules/catalog/datasets/api/router_data.py")
    metadata_path = _backend_path(
        "app/modules/catalog/datasets/domain/service_metadata.py"
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
                f"{_repo_style_rel(router_path)}."
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
            'mode="metadata_patch" in '
            f"{_repo_style_rel(metadata_path)}."
        )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
@pytest.mark.skipif(
    not _PATHSPEC_MAGIC_AVAILABLE,
    reason=(
        "git < 2.13 lacks `:!` pathspec exclusion; install a newer git "
        "or run this test from the host"
    ),
)
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
    - `catalog/maps/service_{shared,crud,public}.py`
                          - `User.username.label()` in JOINs/SELECTs
                            for owner display after maps service decomposition
                            (Pitfall 1)
    - `catalog/collections/router.py` - `select(User).where(User.id.in_(actor_ids))`
                                         for actor enrichment (Pitfall 1)
    - `catalog/datasets/api/router_export.py` - `select(User).where(User.id == ...)`
                                                for export header personalization (Pitfall 1)
    - `catalog/datasets/domain/helpers.py` - `select(User).where(User.id.in_(ids))`
                                              for batched user resolution (Pitfall 1)
    - `catalog/search/service_semantic.py` - `select(User).where(User.id.in_(actor_ids))`
                                              for search-result enrichment (Pitfall 1)
    - `tests/`          - fixtures construct `User(...)` directly; structurally
                          valid as Identity at the call site

    The `\\bUser\\b` word-boundary ensures `import UserRole` (no standalone
    `User`) does NOT trip the guard - `UserRole` stays concrete per D-08.
    `import Role, User, UserRole` and `import User` and `import ApiKey, User`
    all DO trip the guard outside the allowlist.

    Maps directly to ROADMAP Phase 214 SC#2.
    """
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
            ":!backend/app/modules/catalog/maps/service_shared.py",
            ":!backend/app/modules/catalog/maps/service_crud.py",
            ":!backend/app/modules/catalog/maps/service_public.py",
            ":!backend/app/modules/catalog/collections/router.py",
            ":!backend/app/modules/catalog/datasets/api/router_export.py",
            ":!backend/app/modules/catalog/datasets/domain/helpers.py",
            ":!backend/app/modules/catalog/search/service_semantic.py",
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
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
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
def test_no_external_imports_of_maps_private_service_modules() -> None:
    """Phase 238 BOUND-01: maps callers must use the public service façade.

    Phases 236 and 238 keep `app.modules.catalog.maps.service` as the stable
    import surface. Focused private modules may collaborate with each other and
    the façade may re-export them, but production modules outside the service
    split must not import service_shared/service_crud/service_layers/
    service_public directly.
    """
    private_modules = {
        "service_shared",
        "service_crud",
        "service_diff",
        "service_layers",
        "service_public",
    }
    offenders = _private_service_import_offenders(
        package="app.modules.catalog.maps",
        package_path="backend/app/modules/catalog/maps",
        private_modules=private_modules,
    )

    if offenders:
        pytest.fail(
            "Phase 238 BOUND-01 invariant violated: production code imports "
            "maps private service modules directly. External callers must "
            "import from `app.modules.catalog.maps.service`; only the maps "
            "facade and maps service_*.py modules may import private service "
            "modules directly.\nOffending lines:\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_no_external_imports_of_search_private_service_modules() -> None:
    """Phase 238 BOUND-01: search callers must use the public service façade."""
    private_modules = {
        "service_filters",
        "service_facets",
        "service_collections",
        "service_semantic",
        "service_datasets",
        "service_records",
    }
    offenders = _private_service_import_offenders(
        package="app.modules.catalog.search",
        package_path="backend/app/modules/catalog/search",
        private_modules=private_modules,
    )

    if offenders:
        pytest.fail(
            "Phase 238 BOUND-01 invariant violated: production code imports "
            "search private service modules directly. External callers must "
            "import from `app.modules.catalog.search.service`; only the search "
            "facade and search service_*.py modules may import private service "
            "modules directly.\nOffending lines:\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_decomposed_service_modules_stay_within_size_budgets() -> None:
    """Phase 238 BOUND-02 + Phase 269 H-05 + Phase 276 CODE-02: decomposed splits stay bounded.

    Originally introduced as the maps/search size-budget guard in Phase 238
    BOUND-02. Phase 269 (v13.12 H-05) extended coverage to the Phase 224
    dataset-domain split (`datasets/domain/service_*.py`), which previously
    had a private-import guard but no companion size cap. Phase 276 CODE-02
    added processing/ai/chat_*.py coverage when chat_service.py was split
    into a facade + sub-modules.
    """
    facade_line_budgets = {
        "backend/app/modules/catalog/maps/service.py": 100,
        "backend/app/modules/catalog/search/service.py": 80,
        "backend/app/modules/catalog/datasets/domain/service.py": 110,
        # Phase 276 CODE-02 — chat_service.py is now a facade re-exporting
        # from chat_*.py sub-modules. 400 was the established Phase-226 cap
        # for facade modules that retain a meaty orchestrator + system-prompt
        # builder.
        # builder-audit follow-up (read-only AI access model): +36 LOC —
        # build_chat_system_prompt gains a can_edit read-only directive, and
        # chat_edit_map gains the per-turn allowed-tool guard on the tool
        # executor + action collector (so a view-only caller cannot execute or
        # collect a mutating tool). Cap raised 400 -> 440 (~4 LOC headroom).
        "backend/app/processing/ai/chat_service.py": 440,
    }
    private_service_default_line_budget = 350
    private_service_line_budget_allowlist = {
        "backend/app/modules/catalog/maps/service_crud.py": 550,
        # fix(#474, #475): localized ranking/eager loading plus the OGC
        # ids/externalIds filters cross the default by nine lines. Keep the
        # carve-out exact so further growth requires another review.
        "backend/app/modules/catalog/search/service_datasets.py": 359,
        # Phase 1062 CR-04: +13 lines from non-expiring embed-token CSP fix
        # (or_ IS NULL predicate, _create_non_expiring_embed_token helper).
        # Cap raised from 575 → 600 to allow ~12 lines of headroom above 588.
        # Phase 1176 SEC-024: +20 lines for _redact_terrain_config (strip the
        # private DEM source_dataset_id from shared/public map responses when the
        # DEM is not a visible layer). Cap raised 600 → 625 (~5 LOC headroom).
        # #347 (ADM-01): +24 lines — the admin "Published Maps" listing re-keys
        # on Map (visibility=public) LEFT JOINed to the latest share token per
        # map (DISTINCT ON) so every published map appears, not just shared ones.
        # Cap raised 625 → 660 (~11 LOC headroom).
        # fix(#394) SH-01/B-023: +31 lines — get_shared_map unions embed-token
        # scoped layers into the visibility-filtered set (SEC-022 capability
        # parity with the tile path) + tile_version threading. Cap raised
        # 660 → 720 (~29 LOC headroom).
        "backend/app/modules/catalog/maps/service_public.py": 720,
        "backend/app/modules/catalog/search/service_records.py": 500,
        # fix(#448): +~40 LOC — query-embedding hot-path deadline (asyncio.wait_for
        # wrapper) + the gated/approximated vector-only match COUNT in
        # _run_rrf_merge (perf audit 2026-07-10 §2d). Cap 350 → 390
        # (~19 LOC headroom above 371).
        "backend/app/modules/catalog/search/service_semantic.py": 390,
        # fix(#430 V-14): _replace_layers now reconciles layers by id (update-in-place
        # + create/delete) instead of delete-all-then-recreate, so a PUT preserves
        # layer UUIDs. +~35 LOC over the 350 default. Cap → 400 (~34 headroom).
        "backend/app/modules/catalog/maps/service_diff.py": 400,
        # fix(#430 V-17): DatasetMeta/LayerRow now carry dataset visibility+status so the
        # builder can badge layers hidden from a public map's audience. +~10 LOC
        # over the 350 default (BA-21 tie-break comment adds a couple more).
        "backend/app/modules/catalog/maps/service_shared.py": 400,
        # Phase 269 H-05: dataset-domain modules over the 350 default at audit
        # time. Caps set ~20-30 LOC above current size to allow modest growth
        # while still tripping CI on substantial regrowth back toward the
        # original 1407-LOC god module.
        # Security fix (relationship target authz): +83 LOC for target-visibility
        # filtering in list_relationships, the get_relationship_datasets loader,
        # source/target binding in get_related_records, and the public-source
        # auto-detect guard. Cap raised 480 -> 580 for ~30 LOC headroom.
        # Phase 1191 GAP-033: +new list_relationships_with_total for the list-envelope
        # contract ({relationships,total}); list_relationships DRY'd to delegate +
        # _visible_relationships extracted (shared, fail-closed). Cap 580 -> 595 (~7 LOC headroom).
        # Smoke-check backlog (#315): +source/target Dataset.id resolution so the
        # list response returns dereferenceable ids. Smoke-residual follow-up (#315):
        # +try/except (ProgrammingError->503) around get_related_records table
        # queries (raster/missing-table guard). Cap 595 -> 620 (~3 LOC headroom).
        "backend/app/modules/catalog/datasets/domain/service_relationships.py": 620,
        # fix(#474): reject primary-language updates that collide with a
        # translated variant. Cap 460 -> 480 (~9 LOC headroom above 471).
        "backend/app/modules/catalog/datasets/domain/service_metadata.py": 480,
        # fix(#435 codex r1): +6 LOC in get_dataset_rows to probe schema existence
        # before degrading a 42P01 to an empty page. Postgres reports a missing
        # tenant data schema with the same code as a raster dataset's synthetic
        # table, so the code alone cannot tell provisioning drift from normal
        # emptiness. Cap 390 -> 396, no headroom.
        "backend/app/modules/catalog/datasets/domain/service_query.py": 396,
        # Phase 276 CODE-02: chat_*.py sub-modules are all under the 350
        # default (largest is chat_actions.py at ~245 LOC). No explicit
        # per-file overrides needed; default applies.
        # fix(#394) CH-02: +~35 lines — set_label column validation against the
        # target layer schema (error feedback to the model), the CSS-colorish
        # sanitizer, and the collector error gate. Cap 350 → 400 (~19 headroom).
        "backend/app/processing/ai/chat_actions.py": 400,
    }

    files_to_check = list(facade_line_budgets)
    files_to_check.extend(
        _repo_style_rel(path)
        for root in (
            _backend_path("app/modules/catalog/maps"),
            _backend_path("app/modules/catalog/search"),
            _backend_path("app/modules/catalog/datasets/domain"),
        )
        for path in sorted(root.glob("service_*.py"))
    )
    # Phase 276 CODE-02: extend discovery to processing/ai/chat_*.py sub-modules
    # (the chat_service.py facade is already covered via facade_line_budgets).
    files_to_check.extend(
        _repo_style_rel(path)
        for path in sorted(_backend_path("app/processing/ai").glob("chat_*.py"))
        if path.name != "chat_service.py"
    )

    violations: list[str] = []
    for rel in sorted(set(files_to_check)):
        line_count = len(_repo_style_path(rel).read_text().splitlines())
        if rel in facade_line_budgets:
            cap = facade_line_budgets[rel]
        else:
            cap = private_service_line_budget_allowlist.get(
                rel, private_service_default_line_budget
            )
        if line_count > cap:
            violations.append(f"{rel}: {line_count} lines > cap {cap}")

    if violations:
        pytest.fail(
            "Phase 238 BOUND-02 / Phase 269 H-05 / Phase 276 CODE-02 "
            "invariant violated: decomposed service modules "
            "(maps / search / datasets-domain / processing/ai/chat_*) "
            "exceeded their line-count budgets. Split the module or add a "
            "reviewed explicit cap only when growth is intentional.\n"
            + "\n".join(violations)
        )


# fix(#435): each cap equals the file's current LOC, so these files can only shrink.
# Every cap here used to carry 3-7% headroom, and each time a file grew into its cap
# the cap was raised (five documented raises for tiles/router.py alone). That is how
# "decomposition is queued" stayed true for a year while the routers grew past 2,000
# lines.
#
# To add lines to a ratcheted file: remove lines from it, or decompose it into
# sub-routers (per Phase 226 / Phase 238) and lower its cap in the same commit.
# Lowering a cap is always fine. Raising one needs a written carve-out here.
#
# History of the previous caps, kept because it records why each file is large:
#   maps/router.py    1610 → 1700 → 1800 → 1900. Phase 1047 bulk-delete, then PR #118
#     builder polish took it to 2107; extracting _router_helpers.py brought it back.
#     Splitting share/media/layers into sub-routers is the remaining work.
#   search/router.py  1515 → 1600 → 1640 → 1700. OGC record metadata (#315), then the
#     record_type/sort_by allowlist + to_filters() chokepoint (#317 A2). The OGC
#     Records array-query contract and explicit GeoJSON response schemas add the
#     final 21 lines after protocol helpers were extracted to records_protocol.py.
#   standards/stac/router.py entered the allowlist at 1547 for the virtual
#     unassigned Collection, deterministic multi-membership selection, and HTTP
#     Link parity required by the 2026-07-12 compliance remediation.
#   tiles/router.py   1500 → 1660 → 1850 → 1920 → 2050 → 2090. Raster meta TTLCache
#     (1176 PERF-002), SET LOCAL ROLE binding (1209-03 DP-02), cloud fairness/metering
#     seams (1213-06), the cold-tier seam (1214-04), terrainrgb nodata (#186), and
#     empty-tile Cache-Control (#430 V-03). NOTE: `_check_cold_rehydrate` is pinned to
#     this module by the overlay's 1214-05 static AST proof, so the tile_seams.py split
#     must update the overlay in lockstep.
_ROUTER_LOC_CAPS: dict[str, int] = {
    "backend/app/modules/catalog/maps/router.py": 1884,
    # fix(#474): thread negotiated languages through catalog search, cache keys,
    # and OGC record serialization; fix(#475) adds the Records array-query
    # contract and response-header parity. The ratchet remains exact.
    "backend/app/modules/catalog/search/router.py": 1706,
    # fix(#474): negotiate localized STAC record text; fix(#475) adds the
    # unassigned Collection and matching HTTP Link navigation.
    "backend/app/standards/stac/router.py": 1584,
    "backend/app/processing/tiles/router.py": 2077,
}


@pytest.mark.architecture
def test_router_loc_caps_have_no_headroom() -> None:
    """Every ratchet must equal its file's current LOC.

    A cap above the current size is permission to grow. The audit found 13, 3, and 29
    spare lines in the three largest routers — each one the seed of the next
    "cap raised to N, decomposition queued" comment.

    Shrinking a file fails this too. Lower the cap in the same commit.
    """
    drift: list[str] = []
    for rel, cap in sorted(_ROUTER_LOC_CAPS.items()):
        actual = len(_repo_style_path(rel).read_text().splitlines())
        if actual != cap:
            verb = "shrank below" if actual < cap else "exceeds"
            drift.append(f"{rel}: {actual} lines {verb} its cap of {cap}")

    if drift:
        pytest.fail(
            "Router LOC ratchets are out of sync with the files they track. Set each "
            "cap to the file's current line count.\n" + "\n".join(drift)
        )


@pytest.mark.architecture
def test_router_orchestrator_modules_stay_within_loc_cap() -> None:
    """Phase 276 CODE-01: router and orchestrator modules stay <= 1500 LOC.

    Catches regrowth of large API-edge modules toward the size cliff that
    triggered the Phase 226 / Phase 238 / Phase 252 decompositions.
    Allowlisted modules are ratcheted at their current size (see _ROUTER_LOC_CAPS).

    Scope: ``backend/app/**/router.py`` (all module + standards routers).
    Decomposed service modules (``service_*.py``) are covered separately by
    ``test_decomposed_service_modules_stay_within_size_budgets``.
    """
    DEFAULT_CAP = 1500
    allowlist = _ROUTER_LOC_CAPS

    violations: list[str] = []
    for path in sorted((BACKEND_ROOT / "app").rglob("router.py")):
        rel = _repo_style_rel(path)
        line_count = len(path.read_text().splitlines())
        cap = allowlist.get(rel, DEFAULT_CAP)
        if line_count > cap:
            violations.append(f"{rel}: {line_count} lines > cap {cap}")

    if violations:
        pytest.fail(
            "Phase 276 CODE-01 invariant violated: router modules exceeded "
            "their LOC cap. Either decompose the module (preferred — split "
            "into a facade + cohesive sub-modules per Phase 226 / Phase 238 "
            "patterns) or, if growth is intentional, raise the explicit "
            "allowlist entry with a code review.\n" + "\n".join(violations)
        )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
@pytest.mark.skipif(
    not _PATHSPEC_MAGIC_AVAILABLE,
    reason=(
        "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
        "Phase 222 AUDIT-02 invariant via grep-based guard"
    ),
)
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
    # pytest.skip kept inline: must run AFTER the importlib check above (a),
    # which is the test's primary assertion; a top-level skipif decorator
    # would skip the importlib check too and miss regressions.
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    # pytest.skip kept inline: same reason as the git-metadata guard above —
    # must follow part (a) of the test, not skip the entire function.
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
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
def test_billing_dispatch_uses_hardcoded_timeout() -> None:
    """Phase 223 BILLING-04 / D-11: the production dispatch loop hardcodes timeout=10.0.

    D-11 deliberately rejects making the timeout configurable (no
    ``BILLING_STARTUP_TIMEOUT_SECONDS`` env var, no per-extension override).
    Today's value is hardcoded; preserving that as a constant in core's
    dispatch loop is the smallest-diff option and matches the pre-phase-223
    behavior at the now-deleted line 191 of api/main.py.

    Test fixtures (test_billing_extension.py::_dispatch) accept a parameterized
    ``timeout`` argument for fast tests, but the PRODUCTION dispatch loop (in the
    shared ``bootstrap()`` helper since Phase 1206 WORK-01 — formerly api/main.py)
    MUST use the literal ``timeout=10.0``. This test catches drift between the two.

    Negative-control: any change that wraps the timeout in a settings field
    or env-var lookup will fail this test (the literal will be missing).
    """
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"asyncio\.wait_for\(ext\.on_startup\(app\), timeout=10\.0\)",
            "--",
            # Phase 1206 (WORK-01) collapsed the API lifespan + worker bootstrap
            # into one shared bootstrap() helper, which is where the billing
            # dispatch loop now lives (moved from the now-deleted api/main.py site).
            "backend/app/platform/extensions/bootstrap.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 1:
        pytest.fail(
            "Phase 223 BILLING-04 / D-11 invariant violated: "
            "backend/app/platform/extensions/bootstrap.py does NOT contain the "
            "production BillingExtension dispatch loop with literal "
            "`asyncio.wait_for(ext.on_startup(app), timeout=10.0)`. The "
            "10-second timeout MUST be hardcoded (D-11 — YAGNI for env-var "
            "configuration). Either the dispatch loop is missing entirely or the "
            "literal timeout was changed. (Phase 1206 moved this from api/main.py "
            "into the shared bootstrap() helper.)"
        )
    if result.returncode not in (0,):
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


# fix(#435): burn-down list of function-local `app.modules.catalog` imports inside
# `backend/app/processing/`. Every entry is a place where processing reaches past
# ProcessingPort, so an Enterprise/Cloud overlay cannot observe or intercept the call.
#
# The list may SHRINK, never grow. Adding an entry means adding a new port bypass —
# route the behavior through `app.core.processing_port` instead. See
# `_authorize_metadata_dataset` in `processing/ai/router.py`, migrated to the port's
# existing `get_dataset` / `check_dataset_access` methods.
_PROCESSING_CATALOG_IMPORT_BURNDOWN: dict[str, set[str]] = {
    "ai/chat_validation.py": {"app.modules.catalog.maps.filter_grammar"},
    "ai/router.py": {
        # Private cross-domain helpers. Needs behavior-level ProcessingPort methods
        # (check_map_read_access, can_edit_map) before this edge can go.
        "app.modules.catalog.maps._router_helpers",
        "app.modules.catalog.maps.models",
    },
    "ai/service.py": {
        "app.modules.catalog.datasets.domain.models",
        "app.modules.catalog.search.service",
    },
    "export/router.py": {
        "app.modules.catalog.authorization",
        "app.modules.catalog.features.service",
    },
    "ingest/manifest_service.py": {
        "app.modules.catalog.authorization",
        # Rule 2 (AGENTS.md): SSRF redirect revalidation must use make_safe_client.
        "app.modules.catalog.sources.security",
    },
    "ingest/manifest_sources.py": {"app.modules.catalog.sources"},
    "ingest/router.py": {
        "app.modules.catalog.authorization",
        "app.modules.catalog.datasets.domain.service",
        "app.modules.catalog.sources.security",
    },
    "ingest/service.py": {
        "app.modules.catalog.authorization",
        "app.modules.catalog.datasets.domain.service",
    },
    "ingest/tasks_reupload.py": {"app.modules.catalog.sources.security"},
    "ingest/tasks_vector.py": {
        "app.modules.catalog.sources.adapters.arcgis",
        "app.modules.catalog.sources.security",
    },
    "tiles/router.py": {"app.modules.catalog.datasets.domain.models"},
}

_PROCESSING_DIR = REPO_ROOT / "backend" / "app" / "processing"


def _catalog_import_edges() -> dict[str, set[str]]:
    """Every `app.modules.catalog.*` import under processing/, at ANY scope."""
    import ast

    edges: dict[str, set[str]] = {}
    for path in sorted(_PROCESSING_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if module.startswith("app.modules.catalog"):
                    key = str(path.relative_to(_PROCESSING_DIR))
                    edges.setdefault(key, set()).add(module)
    return edges


@pytest.mark.architecture
def test_no_processing_imports_catalog() -> None:
    """Phase 225 PROCESS-02/04: processing/ reaches catalog only through ProcessingPort.

    fix(#435): this guard was a `git grep` for imports starting at column 0, so moving
    an import inside a function body satisfied it while still bypassing the overlay
    seam. An AST scan found 30 such function-local imports across 11 files, one
    reaching into private router helpers and another bypassing the port for dataset
    authorization. The guard now walks every scope, and the surviving edges are an
    explicit burn-down list rather than an invisible exemption.
    """
    offenders: list[str] = []
    for file, modules in sorted(_catalog_import_edges().items()):
        allowed = _PROCESSING_CATALOG_IMPORT_BURNDOWN.get(file, set())
        for module in sorted(modules - allowed):
            offenders.append(f"  backend/app/processing/{file}: {module}")

    if offenders:
        pytest.fail(
            "Phase 225 PROCESS-02/04 invariant violated: backend/app/processing/ "
            "imports app.modules.catalog.* outside the burn-down allowlist. Route the "
            "behavior through ProcessingPort (app.core.processing_port) instead of "
            "adding an entry to _PROCESSING_CATALOG_IMPORT_BURNDOWN.\n"
            + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_processing_catalog_import_allowlist_is_current() -> None:
    """The burn-down list must shrink as edges are migrated — no stale entries.

    A stale entry is a silent licence to reintroduce the bypass later.
    """
    edges = _catalog_import_edges()
    stale: list[str] = []
    for file, modules in sorted(_PROCESSING_CATALOG_IMPORT_BURNDOWN.items()):
        for module in sorted(modules - edges.get(file, set())):
            stale.append(f"  {file}: {module}")

    if stale:
        pytest.fail(
            "_PROCESSING_CATALOG_IMPORT_BURNDOWN lists edges that no longer exist. "
            "Delete them — the list only shrinks.\n" + "\n".join(stale)
        )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
@pytest.mark.skipif(
    not _PATHSPEC_MAGIC_AVAILABLE,
    reason=(
        "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
        "Phase 230 CATPORT-04 invariant via grep-based guard"
    ),
)
def test_no_catalog_imports_processing() -> None:
    """Phase 230 CATPORT-02/04: catalog/ must not import app.processing.*.

    All processing-owned helper, task, schema, and ORM-class access from
    backend/app/modules/catalog/ must go through CatalogPort
    (app.core.catalog_port). Strict zero-hit across module-level imports
    and function-local imports. Pure `#` comment lines are skipped — code
    comments may legitimately mention the module name for documentation.
    """
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"(backend\.)?app\.processing",
            "--",
            "backend/app/modules/catalog/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        # Filter out pure comment lines (line starts with optional whitespace + `#`).
        # Format of git-grep -n is "path:lineno:content".
        offending = [
            line
            for line in result.stdout.splitlines()
            if (parts := line.split(":", 2))
            and len(parts) == 3
            and not parts[2].lstrip().startswith("#")
        ]
        if offending:
            pytest.fail(
                "Phase 230 CATPORT-02/04 invariant violated: "
                "backend/app/modules/catalog/ contains a direct reference to "
                "app.processing.*. All processing access must go through "
                "CatalogPort (app.core.catalog_port). Offending lines:\n"
                + "\n".join(offending)
            )
        return  # All hits were comment lines — pass.
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
@pytest.mark.skipif(
    not _PATHSPEC_MAGIC_AVAILABLE,
    reason=(
        "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
        "Phase 226 AIEXT-03 invariant via grep-based guard"
    ),
)
def test_no_hardcoded_ai_provider_branches() -> None:
    """Phase 226 AIEXT-03/05: no hardcoded ``if provider ==`` dispatch in processing/ai/.

    SC#3 binding (ROADMAP §Phase 226): ``grep -RE "if .*provider *== *['\"]
    (anthropic|openai_compatible)" backend/app/processing/ai/`` returns zero
    hits after the provider-seam migration. Streaming chat now dispatches
    through ``AIProviderExtension.stream_chat_events(...)`` and metadata
    drafts use ``AIProviderExtension.structured_complete(...)``.

    Negative-control (D-14): temporarily reintroduce
    ``if provider == "anthropic":`` in ``processing/ai/sql_generator.py``,
    run this test, confirm it fails with the offending line surfaced.
    Revert. Run again, confirm green.

    Maps to AIEXT-03 + AIEXT-05 (REQUIREMENTS.md §Phase 226).
    """
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-P",
            r"if\s+.*provider\s*==\s*['\"](?:anthropic|openai_compatible)",
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
            "Phase 226 AIEXT-03 invariant violated: hardcoded AI provider "
            "dispatch (`if provider == 'anthropic'/'openai_compatible'`) found "
            "in backend/app/processing/. Replace with "
            "`get_ai_provider(name)` dispatch from "
            "`app.platform.extensions`.\nOffending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
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


def _manifest_backend_files() -> list[Path]:
    manifest_dir = _backend_path("app/processing/ingest")
    return sorted(manifest_dir.glob("manifest_*.py"))


def _iter_imported_modules(tree: ast.AST) -> list[tuple[str, int]]:
    modules: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append((node.module, node.lineno))
    return modules


def _is_forbidden_manifest_import(module: str) -> bool:
    normalized = _normalized_import_root(module)
    forbidden_roots = {
        "app_enterprise",
        "cli",
        "geolens",
        "geolens_cli",
        "geolens_sdk",
        "geolens_enterprise",
        "sdks",
    }
    if any(
        normalized == root or normalized.startswith(f"{root}.")
        for root in forbidden_roots
    ):
        return True
    return "enterprise" in normalized.split(".")


@pytest.mark.architecture
def test_manifest_apply_backend_has_no_cli_sdk_or_enterprise_imports() -> None:
    """Phase 243 INGEST-03: backend manifest apply stays backend-local.

    The backend apply path must not import CLI internals, generated SDK clients,
    or Enterprise-only modules. Community extension ports such as
    ``app.platform.extensions`` remain allowed.
    """

    offenders: list[str] = []
    for path in _manifest_backend_files():
        rel = _repo_style_rel(path)
        source = path.read_text()
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError as exc:
            pytest.fail(f"Could not parse {rel}: {exc}")

        lines = source.splitlines()
        for module, lineno in _iter_imported_modules(tree):
            if _is_forbidden_manifest_import(module):
                offenders.append(f"{rel}:{lineno}:{lines[lineno - 1].strip()}")

    if offenders:
        pytest.fail(
            "Phase 243 INGEST-03 invariant violated: backend manifest apply "
            "imports CLI, generated SDK, or Enterprise-only modules directly. "
            "Keep manifest apply backend-local and use existing community "
            "extension ports. Offending lines:\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_manifest_apply_router_uses_upload_permission() -> None:
    """Phase 243 INGEST-03: manifest apply reuses the existing upload permission."""

    router_path = _backend_path("app/processing/ingest/manifest_router.py")
    source = router_path.read_text()
    tree = ast.parse(source, filename=_repo_style_rel(router_path))

    permissions: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "require_permission":
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            pytest.fail("manifest_router.py uses non-literal require_permission().")
        permissions.append(str(node.args[0].value))

    assert permissions == ["upload"]


@pytest.mark.architecture
def test_upload_thumbnail_route_uses_json_body() -> None:
    """Phase 254 SDK-02: PUT /maps/{map_id}/thumbnail/ must use a JSON body
    (Pydantic model), not a text/plain body.

    openapi-python-client rejects ``text/plain`` request bodies and silently
    drops the endpoint from the generated Python SDK (emitting
    ``WARNING parsing PUT /maps/{map_id}/thumbnail/``). Phase 254 Plan 01
    switched the route to a JSON body backed by ``ThumbnailUploadRequest``.
    This guard prevents silent regression: any future change that switches
    the route back to a non-JSON body shape fails this test BEFORE
    ``make sdks`` runs.

    Companion gate: the ``Makefile`` ``sdks:`` target also fails on any
    ``^WARNING parsing`` line from openapi-python-client (Phase 254 Plan 02
    Task 1). This source-shape guard fires earlier in the loop, on every
    ``pytest tests/test_layering.py`` invocation.
    """
    router_path = _backend_path("app/modules/catalog/maps/router.py")
    if not router_path.exists():
        # Test runs from monorepo root; if path is relative-broken, skip
        # rather than false-fail on environment misconfiguration.
        # pytest.skip kept inline: reason interpolates router_path which is
        # computed via _backend_path() — the resolved value depends on the
        # test runtime layout (host vs container), so a static decorator
        # reason cannot capture the actual missing path.
        pytest.skip(f"router file not found at {router_path}")

    source = router_path.read_text(encoding="utf-8")

    # Locate the upload_thumbnail function definition. Use AST so we
    # don't false-positive on docstrings or other strings that mention
    # the function name.
    tree = ast.parse(source)
    upload_fn: ast.AsyncFunctionDef | ast.FunctionDef | None = None
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == "upload_thumbnail"
        ):
            upload_fn = node
            break

    if upload_fn is None:
        pytest.fail(
            "Phase 254 SDK-02 invariant violated: function "
            "'upload_thumbnail' not found in "
            "backend/app/modules/catalog/maps/router.py. The route was "
            "renamed or removed; update this guard or restore the route."
        )

    # Inspect the parameter list. The route must NOT have any parameter
    # whose default is a Body(...) call with a `media_type` keyword arg
    # set to a non-JSON content type (typically "text/plain").
    #
    # Phase 254 WR-01: walk both positional defaults AND kwonly defaults,
    # so a regression that switches `upload_thumbnail` to FastAPI's
    # keyword-only style (e.g., `*, data_uri: str = Body(..., media_type=...)`)
    # is also caught. Without this, kwonly args land in
    # `fn.args.kwonlyargs` / `fn.args.kw_defaults` and slip past the guard.
    args = upload_fn.args.args
    defaults = upload_fn.args.defaults
    default_idx = len(args) - len(defaults)
    positional_pairs: list[tuple[ast.arg, ast.expr]] = [
        (arg, defaults[arg_pos - default_idx])
        for arg_pos, arg in enumerate(args)
        if arg_pos >= default_idx
    ]
    # `kw_defaults` is parallel to `kwonlyargs`; entries are `None` when
    # a kwonly arg has no default. Filter those out so `(arg, default)`
    # below is always (ast.arg, ast.expr).
    kwonly_pairs: list[tuple[ast.arg, ast.expr]] = [
        (arg, default)
        for arg, default in zip(
            upload_fn.args.kwonlyargs,
            upload_fn.args.kw_defaults,
            strict=True,
        )
        if default is not None
    ]
    for arg, default in (*positional_pairs, *kwonly_pairs):
        if not isinstance(default, ast.Call):
            continue
        func = default.func
        func_name = (
            func.attr
            if isinstance(func, ast.Attribute)
            else func.id
            if isinstance(func, ast.Name)
            else None
        )
        if func_name != "Body":
            continue
        for kw in default.keywords:
            if (
                kw.arg == "media_type"
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
                and kw.value.value != "application/json"
            ):
                pytest.fail(
                    "Phase 254 SDK-02 invariant violated: parameter "
                    f"'{arg.arg}' on upload_thumbnail uses "
                    f"Body(..., media_type='{kw.value.value}'). "
                    "openapi-python-client cannot parse non-JSON request "
                    "bodies and will silently drop the endpoint from the "
                    "Python SDK. Switch to a Pydantic JSON body model "
                    "(e.g., ThumbnailUploadRequest) per Phase 254 Plan 01."
                )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
@pytest.mark.skipif(
    not _PATHSPEC_MAGIC_AVAILABLE,
    reason=(
        "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
        "Phase 276 CODE-08 invariant via grep-based guard"
    ),
)
def test_no_unjustified_broad_except_sites() -> None:
    """Phase 276 CODE-08: every ``except Exception:`` site under backend/app/
    must justify itself with ``# broad: <reason>`` or
    ``# noqa: BLE001 <reason>`` on the SAME line.

    Catches new unjustified broad-except sites at PR time. The intent is
    not to forbid broad catches — they are sometimes the correct safety
    net (audit sinks, cache decoders, optional-dependency probes,
    third-party SDK boundaries) — but to require a one-line justification
    at the catch site so reviewers can confirm the broad catch is
    intentional and not accidental swallowing of a real bug.

    Two acceptable styles (both already used in the codebase):
        except Exception:  # broad: <reason>
        except Exception:  # noqa: BLE001 <reason>

    Pattern A (``# broad:``) is preferred for new annotations and matches
    the dominant style across ~138 of 139 sites. Pattern B
    (``# noqa: BLE001``) is reserved for sites where ruff would otherwise
    complain about BLE001 (e.g., audit sinks).

    The comment must appear on the SAME line as the ``except`` so this
    grep-based check can find it via line-by-line scanning. Multi-line
    comments above the except do NOT satisfy the guard.

    Out of scope: ``backend/tests/`` (test code may swallow exceptions
    for structural reasons unrelated to production safety) and
    ``backend/app/processing/ai/router.py`` is NOT exempted — it has
    its own justified sites.

    Negative-control: temporarily reintroduce ``except Exception:`` (no
    comment) into a sandbox file under ``backend/app/``, run this test,
    confirm it fails with the offending line surfaced. Revert.

    Maps to CODE-08 (REQUIREMENTS.md §Phase 276).
    """
    # Match `except Exception:` and `except Exception as foo:` lines
    # under backend/app/ only (tests/ is out of scope).
    # Use `[ \t]+` instead of `\s+` for portable ERE — macOS (Apple Git)
    # git grep -E does not treat `\s` as a whitespace character class.
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"except Exception([ \t]+as[ \t]+\w+)?:",
            "--",
            "backend/app/",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    # rc=1 means "no matches" (and our codebase is expected to have
    # matches). rc=0 means matches found — we then filter them.
    if result.returncode not in (0, 1):
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )

    violations: list[str] = []
    for line in result.stdout.splitlines():
        # Each match is "<path>:<lineno>:<source>".
        if "# broad:" in line or "# noqa: BLE001" in line:
            continue
        violations.append(line)

    if violations:
        pytest.fail(
            "Phase 276 CODE-08 invariant violated: unjustified broad-except "
            "sites found. Add `# broad: <reason>` (or `# noqa: BLE001 "
            "<reason>`) on the SAME line as the `except`, OR tighten the "
            "catch to a specific exception class.\n"
            "Offending lines:\n" + "\n".join(violations)
        )


# fix(#435): `platform/` is the shared layer beneath `modules/`, but four files import
# upward into product domains at module scope. Each edge means a product-layer refactor
# can break platform imports at runtime, so they are enumerated rather than tolerated
# silently. The list may SHRINK, never grow.
#
# Deferred (function-local) imports are out of scope: they are the established D-17
# discipline for breaking these cycles, and `platform/extensions/defaults.py` is built
# on them by design.
_PLATFORM_MODULE_IMPORT_BURNDOWN: dict[str, set[str]] = {
    # Bootstrap adapters: FastAPI dependency callables must be imported to be used as
    # route dependencies. Resolvable by moving these routers under modules/.
    "config_ops/router.py": {"app.modules.auth.dependencies"},
    "jobs/router.py": {"app.modules.auth.dependencies"},
    # Config import/export validates product schemas. Resolvable by moving config_ops
    # under modules/settings/, or by passing validated DTOs across a settings port.
    "config_ops/service.py": {
        "app.modules.auth.oauth.schemas",
        "app.modules.auth.permissions",
        "app.modules.settings.schemas",
    },
    # The SQL sandbox enforces catalog visibility. Resolvable via CatalogPort.
    "sandbox/validator.py": {
        "app.modules.catalog.authorization",
        "app.modules.catalog.datasets.domain.models",
    },
}

_PLATFORM_DIR = REPO_ROOT / "backend" / "app" / "platform"


def _platform_module_level_edges() -> dict[str, set[str]]:
    """Module-level (column 0) `app.modules.*` imports under platform/."""
    import ast

    edges: dict[str, set[str]] = {}
    for path in sorted(_PLATFORM_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            if node.col_offset != 0:
                continue
            for module in modules:
                if module.startswith("app.modules"):
                    key = str(path.relative_to(_PLATFORM_DIR))
                    edges.setdefault(key, set()).add(module)
    return edges


@pytest.mark.architecture
def test_platform_does_not_import_modules() -> None:
    """The shared platform layer must not depend upward on product domains.

    fix(#435): `platform/config_ops/service.py` reached into `modules.settings.router`
    for the private `_ENTERPRISE_ONLY_TABS`. That constant now lives beside the
    persistent-config registry that defines `PersistentConfig.tab`, so edition policy
    has a stable owner and decomposing the settings router cannot break config import.
    """
    offenders: list[str] = []
    for file, modules in sorted(_platform_module_level_edges().items()):
        allowed = _PLATFORM_MODULE_IMPORT_BURNDOWN.get(file, set())
        for module in sorted(modules - allowed):
            offenders.append(f"  backend/app/platform/{file}: {module}")

    if offenders:
        pytest.fail(
            "platform/ imports upward into app.modules.* at module scope. Depend on a "
            "core port or DTO, or defer the import (D-17), rather than adding an entry "
            "to _PLATFORM_MODULE_IMPORT_BURNDOWN.\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_platform_does_not_import_private_module_names() -> None:
    """No `from app.modules.… import _private` anywhere in platform/, at any scope.

    A leading underscore says the name can move or vanish without notice.
    `platform/config_ops` imported the settings router's `_ENTERPRISE_ONLY_TABS`, so any
    refactor of that router became a runtime break here.
    """
    import ast

    offenders: list[str] = []
    for path in sorted(_PLATFORM_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("app.modules"):
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    rel = path.relative_to(_PLATFORM_DIR)
                    offenders.append(
                        f"  backend/app/platform/{rel}: {node.module}.{alias.name}"
                    )

    if offenders:
        pytest.fail(
            "platform/ imports a private name from a product module. Promote it to a "
            "public home (core registry, port, or DTO) instead.\n"
            + "\n".join(offenders)
        )
