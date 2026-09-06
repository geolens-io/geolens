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
- fix(#1438 F6/F7/F17/F24) - four import-boundary guards broadened past their
  original scope: processing/'s app.modules.* ban now covers every domain, not
  just catalog (test_no_processing_imports_other_domains); the private-name/
  private-module ban covers processing/ and standards/, not just platform/
  (test_no_private_module_imports_from_app_modules); standards/ carries a
  frozen, shrink-only (non-zero) app.modules.* surface
  (test_standards_module_import_surface_does_not_grow), complementing the
  zero-tolerance app.processing guard in the sibling
  backend/tests/test_standards_layering.py (added by #1438); and the
  router-module import ban applies package-wide at module scope, not only
  inside platform/ (test_no_cross_package_router_imports_at_module_scope).

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
import importlib
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
    # fix(#1182): `-P` (PCRE), never `-E`. POSIX ERE has no `\s`/`\b`/`\w`;
    # glibc accepts them as GNU extensions but macOS does not, so an `-E`
    # pattern using them matches nothing there — and a forbidden-pattern
    # guard reads a universal non-match as a clean pass.
    return subprocess.run(
        ["git", "grep", "-n", "-P", pattern, "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
def test_git_grep_guards_use_pcre_and_gnu_escapes_are_live() -> None:
    """The grep-based guards in this file must be able to fail on this host.

    fix(#1182): two halves, because either one alone passes vacuously.

    1. No `git grep` argv in this file may use `-E`. Nearly every guard pattern
       here relies on `\\s`, `\\b` or `\\w`, which POSIX ERE does not define;
       under `-E` on macOS they match nothing and the guard is permanently,
       silently green.
    2. Those escapes must actually match under the flag we do use, asserted
       against a line known to exist rather than assumed from the flag name.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    offenders: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.List):
            continue
        items = [
            e.value
            for e in node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if items[:2] == ["git", "grep"] and "-E" in items:
            offenders.append(node.lineno)
    if offenders:
        pytest.fail(
            "git grep guard uses `-E`; POSIX ERE has no \\s/\\b/\\w, so the "
            "pattern matches nothing on macOS and the guard cannot fail "
            "locally. Use `-P`. Offending argv at line(s): "
            + ", ".join(str(n) for n in offenders)
        )

    # Liveness: this import line exists, and the pattern reaching it needs all
    # three escapes. A non-match means the regex engine, not the codebase.
    probe = _git_grep(
        r"^\s*from\s+pathlib\s+import\s+\bPath\b\w*",
        "backend/tests/test_layering.py",
    )
    if probe.returncode != 0:
        pytest.fail(
            "git grep found no match for a pattern whose target line is known "
            f"to exist (rc={probe.returncode}). The \\s/\\b/\\w escapes are "
            "not being honored — grep-based guards in this file are vacuous. "
            f"stderr: {probe.stderr}"
        )


def _resolve_relative_import(path: Path, node: ast.ImportFrom) -> str | None:
    """Resolve an `ImportFrom` node's target to an absolute dotted module name.

    fix(#1438 codex review): `node.module` is only the absolute spelling for a
    LEVEL-0 (non-relative) import. A relative import — ``from . import X``,
    ``from ..pkg.mod import X`` — stores the leading dots as `node.level` and
    `node.module` as whatever follows them (``None`` for a bare ``from .
    import``), so a guard that reads `node.module` directly sees
    ``"platform.jobs.router"`` (or nothing at all) for what is actually
    ``app.platform.jobs.router`` — invisible to any check anchored on the
    ``app.`` prefix. Climbing `node.level - 1` steps up from the FILE's own
    package and appending `node.module` reconstructs the real target.
    Equivalent to ``test_standards_layering.py::_absolute_module`` — kept as a
    separate copy rather than a cross-file import, since test modules are not
    meant to import each other's internals.
    """
    if node.level == 0:
        return node.module
    package = path.parent.relative_to(BACKEND_ROOT).parts
    trimmed = package[: len(package) - (node.level - 1)]
    if not trimmed:
        # Climbs past the `app` package root — not a resolvable target.
        return None
    parts = [*trimmed, *(node.module.split(".") if node.module else [])]
    return ".".join(parts)


def _iter_backend_app_python_files() -> list[Path]:
    return sorted((BACKEND_ROOT / "app").rglob("*.py"))


@pytest.mark.architecture
def test_public_core_does_not_import_private_overlay_packages() -> None:
    """Public application code must depend on extension contracts, not overlays.

    The AST walk covers imports at every scope. Function-local imports still
    couple the Apache-licensed package to a private namespace and bypass the
    typed extension registry, even when they happen to be guarded at runtime.
    """

    private_roots = {"app_enterprise", "geolens_cloud", "geolens_enterprise"}
    offenders: list[str] = []

    for path in _iter_backend_app_python_files():
        rel = _repo_style_rel(path)
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        lines = source.splitlines()

        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.append(node.module)
            else:
                continue

            if any(
                module.split(".", 1)[0] in private_roots for module in imported_modules
            ):
                offenders.append(
                    f"{rel}:{node.lineno}:{lines[node.lineno - 1].strip()}"
                )

    if offenders:
        pytest.fail(
            "Public core imports a private overlay package. Define a typed Protocol "
            "in app.platform.extensions and register the private implementation via "
            "the geolens.extensions entry-point instead.\nOffending lines:\n"
            + "\n".join(offenders)
        )


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
            "-P",
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
    - `catalog/records/inherited.py` - `record_audience` predicate target
                                        (the ORM class the audience predicate
                                        is written against) plus the
                                        `select(User.id)` audience-difference
                                        query (Pitfall 1, feat #1070) — the
                                        same InstrumentedAttribute use the
                                        maps service entries above cover
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
            "-P",
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
            ":!backend/app/modules/catalog/records/inherited.py",
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
        r"(service_(analysis|create|query|lifecycle|metadata|relationships)"
        r"|_sql_safety)"
    )

    result = _git_grep(pattern, "backend/app/")

    # Allowlisted paths — these MAY reference the sub-modules / _sql_safety.
    # The 5 sub-modules cross-import each other (D-05) and import shared
    # regexes from _sql_safety; service.py re-exports from all of them;
    # the test file references the path strings in this docstring.
    allowlist_prefixes = {
        "backend/app/modules/catalog/datasets/domain/service.py",
        "backend/app/modules/catalog/datasets/domain/service_analysis.py",
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
        "service_candidates",
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


_ANALYSIS_SQL_PACKAGE = "app.platform.analysis_sql"
_ANALYSIS_SQL_FAMILIES = frozenset(
    {"measure", "overlay", "shared", "spatial_join", "transform"}
)

# How many times to re-walk a file propagating `sql = analysis_sql` rebinds.
# Three covers any chain a reviewer would let through; the loop exits early
# when nothing new binds, so this is a ceiling rather than a cost.
_BINDING_REBIND_ROUNDS = 3

# The eight modules that legitimately consume the façade. Named so the
# both-directions test can prove the guard still LETS THEM THROUGH — a refusal
# assertion cannot notice that a correct import started being rejected.
#
# fix(#1589): buffer_marker.py joins them. It renders the geodesic buffer the
# NL->SQL prompt used to embed, which is why sql_generator.py is still on the
# list too — it keeps MAX_BUFFER_METERS, so the distance ceiling the prompt
# quotes is the one the expander enforces.
_ANALYSIS_SQL_CALLERS = (
    "app/modules/catalog/datasets/api/router_analysis.py",
    "app/modules/catalog/datasets/domain/schemas.py",
    "app/modules/catalog/datasets/domain/service_analysis.py",
    "app/platform/extensions/defaults_processing_port.py",
    "app/platform/sandbox/validator.py",
    "app/processing/ai/buffer_marker.py",
    "app/processing/ai/sql_generator.py",
    "app/processing/analysis/tasks.py",
)


def _dotted_name(node: ast.expr) -> str:
    """Flatten an attribute chain to ``a.b.c``; ``""`` when it is not one."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else ""
    if isinstance(node, ast.NamedExpr):
        # A walrus EVALUATES to its value, so `(sql := analysis_sql).overlay`
        # reaches the family through the assignment expression itself rather
        # than through the name it binds. Seeing through it is the semantics,
        # not a special case for that spelling.
        return _dotted_name(node.value)
    return ""


def _reaches_analysis_sql_family(dotted: str) -> str:
    """The family a dotted path reaches (``…analysis_sql.overlay``), else ``""``.

    Segment-wise so a RELATIVE ``from .analysis_sql.overlay import …`` is seen
    too: the ast node carries that as ``analysis_sql.overlay``, with no package
    prefix to anchor a string match on.
    """
    parts = dotted.split(".")
    for parent, child in zip(parts, parts[1:]):
        if parent == "analysis_sql" and child in _ANALYSIS_SQL_FAMILIES:
            return child
    return ""


def _is_analysis_sql_package(dotted: str) -> bool:
    """True for the façade spelled out in full, absolute or relative.

    A LITERAL test, and only a fallback — ``_analysis_sql_facade_bindings``
    below is what actually decides whether an expression denotes the façade.
    This still earns its place for a handle re-exposed as an attribute
    (``self.analysis_sql.overlay``), which no import-binding pass can see.
    """
    return bool(dotted) and dotted.split(".")[-1] == "analysis_sql"


def _analysis_sql_facade_bindings(tree: ast.Module) -> set[str]:
    """Expressions denoting the façade PACKAGE in this file, alias included.

    refactor(#1089 review r2): the structural half of the fix. Round 1 compared
    an attribute chain's base against the literal string ``analysis_sql``, so
    ``from app.platform import analysis_sql as sql`` then ``sql.overlay.…``
    walked past it. Chasing that as a missing case is unwinnable — every alias
    spelling is a new literal and there are infinitely many. Resolving the name
    to what it is BOUND to closes the class instead, which is why round 2's
    table adds aliased twins and they need no new branches.

    Bindings are collected FILE-WIDE rather than per scope, so a function-local
    ``import … as sql`` is seen. That over-approximates: a name bound to the
    façade in one function makes ``<name>.overlay`` suspicious anywhere in the
    file. Deliberate — the error direction for a guard is to flag too much, and
    the alternative silently under-reports.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _is_analysis_sql_package(alias.name):
                    continue
                # `import a.b.analysis_sql` binds `a`, and the module is reached
                # through the whole chain, so the chain is the expression to
                # record. `… as sql` binds `sql` to the module directly.
                bound.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                # `from app.platform import analysis_sql [as sql]`, and the
                # relative `from . import analysis_sql [as sql]`. The package
                # name is unique in this tree, so not resolving the relative
                # level over-approximates rather than misses.
                if alias.name == "analysis_sql":
                    bound.add(alias.asname or alias.name)

    # One more hop: `sql = analysis_sql` is two characters from `import … as
    # sql` and binds exactly the same thing. Iterated because rebinding can
    # chain; bounded because a fixpoint over a file's assignments is not worth
    # an unbounded loop in a test.
    #
    # fix(#1089 review r3): the rebind pass read ``ast.Assign`` only, so the
    # ANNOTATED form ``sql: object = analysis_sql`` bound nothing — a
    # statically resolvable path, so the contract below was overstating.
    # Closed as a form-space rather than a case: every node that pairs a
    # target with a value is handled, which is Assign, AnnAssign, the walrus,
    # and element-wise tuple/list unpacking. Attribute targets fall out for
    # free, so ``self.sql = analysis_sql`` then ``self.sql.overlay`` is seen.
    for _ in range(_BINDING_REBIND_ROUNDS):
        grew = False
        for node in ast.walk(tree):
            for target, value in _binding_pairs(node):
                if _dotted_name(value) not in bound:
                    continue
                name = _dotted_name(target)
                if name and name not in bound:
                    bound.add(name)
                    grew = True
        if not grew:
            break
    return bound


def _binding_pairs(node: ast.AST) -> list[tuple[ast.expr, ast.expr]]:
    """``(target, value)`` pairs a node binds, for the forms worth modelling.

    Handled: ``x = v``, ``x: T = v``, ``(x := v)``, and ``a, b = v1, v2``
    element-wise when both sides are literal sequences of the same length.

    NOT handled, and these are residue rather than oversights:

    - ``for sql in (analysis_sql,)`` and ``with cm(analysis_sql) as sql``.
      Both bind through a PROTOCOL — iteration, and ``__enter__`` — whose
      result is only knowable for a literal container or a context manager
      that happens to return its argument. A branch would be right for the
      contrived literal and wrong for everything else, which is the kind of
      coverage that reads as more than it is.
    - a parameter default, ``def build(sql=analysis_sql)``. The default is
      evaluated where the module is already bound, so the import itself is
      visible; only the indirect use inside the body escapes, and pairing
      defaults to arguments is index arithmetic in service of a shape nobody
      writes.

    Neither appears anywhere under ``backend/app/``.
    """
    if isinstance(node, ast.Assign):
        pairs: list[tuple[ast.expr, ast.expr]] = []
        for target in node.targets:
            pairs.extend(_unpack_pair(target, node.value))
        return pairs
    if isinstance(node, ast.AnnAssign) and node.value is not None:
        return _unpack_pair(node.target, node.value)
    if isinstance(node, ast.NamedExpr):
        return _unpack_pair(node.target, node.value)
    return []


def _unpack_pair(target: ast.expr, value: ast.expr) -> list[tuple[ast.expr, ast.expr]]:
    """One pair, or the element-wise pairs of a same-length sequence unpack."""
    if (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
    ):
        return list(zip(target.elts, value.elts))
    return [(target, value)]


def _analysis_sql_family_bypasses(source: str, rel: str) -> list[str]:
    """Every reference reaching a family module, as ``rel:lineno: detail``.

    THE CONTRACT: this catches every path to a family module that is
    STATICALLY RESOLVABLE. It is not, and cannot be, "catches everything" —
    see the residue at the bottom.

    Two review rounds shaped it, and both were the same mistake at different
    depths: comparing literal text where a name had to be resolved.

    - r1 matched ``node.module`` alone, so ``from app.platform.analysis_sql
      import overlay`` walked past — the module IS the façade (allowed) and the
      imported NAME was never read. That import succeeds at runtime, because
      the façade imports its submodules and they become package attributes.
    - r2 matched an attribute chain's base against the literal ``analysis_sql``,
      so ``from app.platform import analysis_sql as sql`` then
      ``sql.overlay.…`` walked past. Fixed by resolving bindings
      (``_analysis_sql_facade_bindings``) rather than by adding alias cases,
      because the set of spellings is unbounded.

    What is checked, in three passes over one parse:

    1. an import whose dotted path traverses a family — ``import
       …analysis_sql.overlay``, ``from …analysis_sql.overlay import x``,
       aliased or not, absolute or relative;
    2. an import FROM the façade whose imported NAME is a family — ``from
       …analysis_sql import overlay [as ov]``, mixed freely with real exports;
    3. an attribute chain ``<expr>.<family>`` where ``<expr>`` is bound to the
       façade in this file — under any alias, through a plain assignment, and
       from a function-local import.

    STRUCTURALLY OUT OF REACH, so the next review round can be answered by
    pointing here instead of re-litigating. No static import analysis sees
    these, and a branch for the spelled-out case would read as coverage it does
    not provide:

    - ``getattr(analysis_sql, name)`` — the attribute is a value, not a node.
    - ``importlib.import_module(path)`` — likewise, and the argument need not
      be a literal.
    - anything reached through a data flow this does not model (a family module
      returned from a function, stashed in a dict, passed as a parameter, or
      bound by a ``for``/``with`` target — see ``_binding_pairs`` for why those
      last two stay out).

    Nothing under ``backend/app/`` loads a platform module any of those ways.

    One shape looks like residue and is not: ``from …analysis_sql import *``
    cannot reach a family at all, because ``__init__`` declares ``__all__`` and
    no family name is in it. That is a property of the FAÇADE rather than of
    this matcher, so it is pinned where it is decided — see the ``__all__``
    assertion in ``test_analysis_sql_facade_guard_sees_every_bypass_shape``.
    """
    tree = ast.parse(source)
    facade = _analysis_sql_facade_bindings(tree)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _reaches_analysis_sql_family(alias.name):
                    offenders.append(f"  {rel}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _reaches_analysis_sql_family(module):
                offenders.append(f"  {rel}:{node.lineno}: from {module} import …")
            elif _is_analysis_sql_package(module):
                for alias in node.names:
                    if alias.name in _ANALYSIS_SQL_FAMILIES:
                        offenders.append(
                            f"  {rel}:{node.lineno}: from {module} import {alias.name}"
                        )
        elif isinstance(node, ast.Attribute) and node.attr in _ANALYSIS_SQL_FAMILIES:
            # `sql.overlay.render_clip(…)` after a perfectly legal
            # `from app.platform import analysis_sql as sql`. No import
            # statement names the family; the caller holds it just the same.
            base = _dotted_name(node.value)
            if base and (base in facade or _is_analysis_sql_package(base)):
                offenders.append(f"  {rel}:{node.lineno}: {base}.{node.attr}")
    return sorted(set(offenders))


def _analysis_sql_facade_all_names() -> set[str]:
    """``__all__`` from the façade, read statically so no app import is needed."""
    source = _backend_path("app/platform/analysis_sql/__init__.py")
    for node in ast.parse(source.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            return {
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant)
            }
    pytest.fail("analysis_sql/__init__.py no longer declares __all__")


@pytest.mark.architecture
def test_no_external_imports_of_analysis_sql_family_modules() -> None:
    """refactor(#1089): analysis_sql's family modules are reached via the façade.

    ``app.platform.analysis_sql`` exists so the catalog preview path
    (``datasets/domain/service_analysis.py``) and the processing materialize
    worker (``processing/analysis/tasks.py``) render IDENTICAL SQL. Catalog
    cannot import processing and processing cannot import catalog, so before
    the module existed each path carried its own copy of every statement and
    they drifted: an approved preview and the dataset it saved could disagree
    about what the operation meant.

    #1089 split it by operation family — overlay, measure, spatial_join,
    transform, over a shared core. That is safe only while the façade stays the
    single import surface. The moment a caller reaches past it, "which renderer
    does this path use" becomes a per-caller question again, which is the same
    failure in a new shape. Cross-imports BETWEEN family modules are fine (they
    are one package and reach each other relatively); only external bypasses
    are forbidden.

    Walks the tree rather than git-grepping, so an untracked new file is
    covered on the run that introduces it.
    """
    package_dir = _backend_path("app/platform/analysis_sql")

    offenders: list[str] = []
    for path in sorted(_backend_path("app").rglob("*.py")):
        if package_dir in path.parents:
            continue
        offenders.extend(
            _analysis_sql_family_bypasses(
                path.read_text(encoding="utf-8"), _repo_style_rel(path)
            )
        )

    if offenders:
        pytest.fail(
            "A module outside the analysis_sql package reaches one of its "
            f"operation-family modules directly. Use `{_ANALYSIS_SQL_PACKAGE}` "
            "instead — it re-exports every renderer, and keeping it the single "
            "import surface is what stops the preview path and the materialize "
            "worker from drifting apart on what SQL they run (#1089).\n"
            + "\n".join(offenders)
        )


# Public attributes the façade is allowed to carry without declaring them in
# __all__, each with the reason it cannot simply be made private.
_ANALYSIS_SQL_SURFACE_EXEMPT = {
    # Importing a submodule binds it on the parent package. Unavoidable for a
    # package, and it is what `test_no_external_imports_of_analysis_sql_family_
    # modules` exists to police instead.
    **{
        family: "submodule bound by the import machinery"
        for family in ("measure", "overlay", "shared", "spatial_join", "transform")
    },
    "annotations": "`from __future__ import annotations`",
    "Any": "typing import used in render_geometry_expr's signature",
}


@pytest.mark.architecture
def test_analysis_sql_facade_surface_matches_its_declared_api() -> None:
    """The IMPORTABLE surface equals __all__, exemptions named one by one.

    fix(#1089 review r3): #1089 added six per-family `render_*_expr` helpers so
    each family owns the branch that renders it, kept them out of `__all__`,
    and imported them publicly anyway. `from app.platform.analysis_sql import
    render_clip_expr` therefore worked on the branch and failed on main — an
    API expansion the PR was simultaneously claiming not to make.

    `__all__` was honest and irrelevant: it governs `import *` and states
    intent, while callers bind to ATTRIBUTES. Nothing was comparing the two,
    which is how the surface drifted twice without a failing test. This is that
    comparison. It imports the façade, which is cheap and needs no database —
    `app.core.geo` pulls only shapely and sqlalchemy.

    The comparison is EXACT, and the exemptions are named one by one with a
    reason. Resist relaxing it into a predicate — "ignore short names",
    "ignore anything not callable" — because its whole value is that the next
    accidental promotion has nowhere to land. An exemption forces someone to
    write down why; a predicate quietly absorbs the thing it was meant to
    catch.

    THIS CHECK IS HALF OF THE INVARIANT. Python binds a submodule on its
    parent package at import, so `analysis_sql.overlay` is a public attribute
    no matter what this module does — it is exempt here because it is
    unavoidable, not because it is harmless. What makes it harmless is
    ``test_no_external_imports_of_analysis_sql_family_modules``, which fails
    the build if anything outside the package reaches through it. So: this
    test keeps the DECLARED surface honest, that one keeps the UNAVOIDABLE
    surface unused, and "the façade is the only import surface" is true
    because both hold. Neither is sufficient alone, and deleting either one
    leaves a claim the remaining test does not support.
    """
    facade = importlib.import_module(_ANALYSIS_SQL_PACKAGE)

    public = {name for name in dir(facade) if not name.startswith("_")}
    declared = set(facade.__all__)
    unexpected = public - declared - set(_ANALYSIS_SQL_SURFACE_EXEMPT)
    assert not unexpected, (
        "these names are importable from the façade but are not in __all__ and "
        "are not exempt. Either add them to __all__ deliberately — which grows "
        "the public API and needs to be stated as such — or bind them under a "
        f"_-prefixed name: {sorted(unexpected)}"
    )

    missing = declared - public
    assert not missing, (
        f"__all__ promises names the façade does not bind: {sorted(missing)}"
    )

    # The exemptions must stay live, or the list becomes a place stale entries
    # hide and the next real expansion slips in behind one.
    stale = set(_ANALYSIS_SQL_SURFACE_EXEMPT) - public
    assert not stale, (
        f"these surface exemptions no longer apply and should go: {sorted(stale)}"
    )


@pytest.mark.architecture
def test_analysis_sql_facade_guard_sees_every_bypass_shape() -> None:
    """The guard above, pinned in BOTH directions.

    A refusal assertion is half a test: it cannot notice that a legitimate
    import started being rejected, and a guard nobody has fed a bypass to is
    indistinguishable from one that matches nothing. So every shape that must
    fail is listed beside every shape that must pass, and the near-miss cases
    are in the table on purpose — ``spatial_join_output_columns`` is a real
    export whose name starts with a family name, and ``from app.platform
    import analysis_sql`` is how a caller legitimately holds the façade.
    """
    must_fail = {
        "from-submodule": (
            f"from {_ANALYSIS_SQL_PACKAGE}.overlay import render_clip_layer_join"
        ),
        "from-submodule aliased": (
            f"from {_ANALYSIS_SQL_PACKAGE}.transform import render_geodesic_buffer as b"
        ),
        "from-package import family": f"from {_ANALYSIS_SQL_PACKAGE} import overlay",
        "from-package import family aliased": (
            f"from {_ANALYSIS_SQL_PACKAGE} import measure as m"
        ),
        "from-package mixed with a real export": (
            f"from {_ANALYSIS_SQL_PACKAGE} import render_geometry_expr, shared"
        ),
        "plain dotted import": f"import {_ANALYSIS_SQL_PACKAGE}.spatial_join",
        "plain dotted import aliased": f"import {_ANALYSIS_SQL_PACKAGE}.overlay as ov",
        "relative from-submodule": (
            "from .analysis_sql.overlay import render_intersect_pairs"
        ),
        "relative from-package import family": "from .analysis_sql import shared",
        "attribute chain off the façade": (
            "from app.platform import analysis_sql\n"
            "x = analysis_sql.overlay.render_clip_layer_join('t', src='s')"
        ),
        "attribute chain, relative façade": (
            "from . import analysis_sql\nx = analysis_sql.shared.MAX_SOURCE_FEATURES"
        ),
        "attribute chain off the full path": (
            f"import {_ANALYSIS_SQL_PACKAGE}\n"
            f"x = {_ANALYSIS_SQL_PACKAGE}.transform.render_geodesic_buffer('g', 1.0)"
        ),
        # --- r2: the aliased twin of every chain above. Each one is a fresh
        # literal and a fresh miss for a text matcher; none needs a branch of
        # its own once the base is resolved to its binding.
        "attribute chain, from-import ALIAS": (
            "from app.platform import analysis_sql as sql\n"
            "x = sql.overlay.render_clip_layer_join('t', src='s')"
        ),
        "attribute chain, plain-import ALIAS": (
            f"import {_ANALYSIS_SQL_PACKAGE} as sql\n"
            "x = sql.overlay.render_clip_layer_join('t', src='s')"
        ),
        "attribute chain, relative ALIAS": (
            "from . import analysis_sql as sql\nx = sql.shared.MAX_SOURCE_FEATURES"
        ),
        "attribute chain, underscore ALIAS": (
            "from app.platform import analysis_sql as _s\n"
            "x = _s.transform.render_geodesic_buffer('g', 1.0)"
        ),
        "attribute chain via plain rebind": (
            "from app.platform import analysis_sql\n"
            "sql = analysis_sql\n"
            "x = sql.overlay.render_clip_layer_join('t', src='s')"
        ),
        "attribute chain, function-local ALIAS": (
            "def build():\n"
            "    from app.platform import analysis_sql as sql\n"
            "    return sql.measure.render_measure_columns()"
        ),
        "attribute chain off a re-exposed handle": (
            "class Renderer:\n"
            "    def build(self):\n"
            "        return self.analysis_sql.overlay.render_clip_layer_join(\n"
            "            't', src='s'\n"
            "        )"
        ),
        "aliased façade plus a family import": (
            f"import {_ANALYSIS_SQL_PACKAGE} as sql\n"
            f"from {_ANALYSIS_SQL_PACKAGE} import shared"
        ),
        # --- r3: the binding FORMS, not just the binding names.
        "attribute chain via ANNOTATED rebind": (
            "from app.platform import analysis_sql\n"
            "sql: object = analysis_sql\n"
            "x = sql.overlay.render_clip_layer_join('t', src='s')"
        ),
        "attribute chain via walrus": (
            "from app.platform import analysis_sql\n"
            "x = (sql := analysis_sql).overlay.render_clip_layer_join('t', src='s')"
        ),
        "attribute chain via tuple unpack": (
            "from app.platform import analysis_sql\n"
            "sql, other = analysis_sql, 1\n"
            "x = sql.shared.MAX_SOURCE_FEATURES"
        ),
        "attribute chain via an instance attribute": (
            "from app.platform import analysis_sql\n"
            "class R:\n"
            "    def bind(self):\n"
            "        self.sql = analysis_sql\n"
            "    def build(self):\n"
            "        return self.sql.transform.render_geodesic_buffer('g', 1.0)"
        ),
    }
    must_pass = {
        "façade renderer": f"from {_ANALYSIS_SQL_PACKAGE} import render_clip_layer_join",
        "façade constants": (
            f"from {_ANALYSIS_SQL_PACKAGE} import MAX_SOURCE_FEATURES, "
            "render_geometry_expr"
        ),
        "export whose name starts with a family name": (
            f"from {_ANALYSIS_SQL_PACKAGE} import spatial_join_output_columns"
        ),
        "façade held as a module": "from app.platform import analysis_sql",
        "façade held relatively": "from . import analysis_sql",
        "plain façade import": f"import {_ANALYSIS_SQL_PACKAGE}",
        "attribute off the façade, not a family": (
            "from app.platform import analysis_sql\n"
            "x = analysis_sql.render_geometry_expr('centroid')"
        ),
        "a family NAME on an unrelated package": (
            "from app.platform.cache import shared"
        ),
        # --- r2: the must-pass twins. These are what prove the fix resolves
        # BINDINGS rather than blacklisting whatever the alias happened to be
        # called in the reported instance.
        "ALIASED façade, ordinary renderer": (
            "from app.platform import analysis_sql as sql\n"
            "x = sql.render_geometry_expr('centroid')"
        ),
        "ALIASED façade, ordinary constant": (
            f"import {_ANALYSIS_SQL_PACKAGE} as sql\nx = sql.MAX_SOURCE_FEATURES"
        ),
        # The discriminator: same alias, different module. A guard that had
        # merely learned the word `sql` would flag this.
        "a DIFFERENT module under the same alias": (
            "from app.platform import cache as sql\nx = sql.shared"
        ),
        "an unrelated handle that happens to be sql": (
            "import sqlalchemy\nsql = sqlalchemy.text('select 1')\nx = sql.compile()"
        ),
    }

    missed = [
        label
        for label, source in sorted(must_fail.items())
        if not _analysis_sql_family_bypasses(source, "probe.py")
    ]
    assert not missed, (
        "these bypass shapes reach a family module and the guard let them "
        f"through: {missed}"
    )

    rejected = {
        label: found
        for label, source in sorted(must_pass.items())
        if (found := _analysis_sql_family_bypasses(source, "probe.py"))
    }
    assert not rejected, f"the guard rejected legitimate façade usage: {rejected}"

    # The eight real consumers, checked as themselves rather than as snippets:
    # each must still reference the façade (so this is not vacuous) and none
    # may trip the guard.
    for rel in _ANALYSIS_SQL_CALLERS:
        source = _backend_path(rel).read_text(encoding="utf-8")
        assert _ANALYSIS_SQL_PACKAGE in source, (
            f"{rel} no longer references {_ANALYSIS_SQL_PACKAGE}; either it "
            "stopped being a caller or this list is stale"
        )
        assert not _analysis_sql_family_bypasses(source, rel)

    # What makes `from … import *` safe, pinned where it is actually decided.
    # Without __all__ the star would bind the submodules the façade imports,
    # and no import-shape matcher could see it happen.
    exported = _analysis_sql_facade_all_names()
    assert exported, "the façade's __all__ is empty"
    assert exported.isdisjoint(_ANALYSIS_SQL_FAMILIES), (
        "a family module name is exported in the façade's __all__, so "
        f"`from {_ANALYSIS_SQL_PACKAGE} import *` now reaches a family: "
        f"{sorted(exported & _ANALYSIS_SQL_FAMILIES)}"
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
        # fix(#1847): +2, sample_example_values re-exported. Cap 110 -> 112, exact.
        "backend/app/modules/catalog/datasets/domain/service.py": 112,
        # Phase 276 CODE-02 — chat_service.py is now a facade re-exporting
        # from chat_*.py sub-modules. 400 was the established Phase-226 cap
        # for facade modules that retain a meaty orchestrator + system-prompt
        # builder.
        # builder-audit follow-up (read-only AI access model): +36 LOC —
        # build_chat_system_prompt gains a can_edit read-only directive, and
        # chat_edit_map gains the per-turn allowed-tool guard on the tool
        # executor + action collector (so a view-only caller cannot execute or
        # collect a mutating tool). Cap raised 400 -> 440 (~4 LOC headroom).
        # fix(#525 B-037): +2 LOC — chat_edit_map builds ChatActions per-item
        # via _build_chat_actions (re-exported here for streaming.py) so one
        # invalid action drops with a note instead of failing the whole turn.
        # Cap raised 440 -> 446 (~4 LOC headroom).
        # fix(#549): +9 LOC — the system prompt now owns verb classification
        # outright, reading the request's OBJECT (catalog / layer / data / map
        # appearance) before its verb, so the tool descriptions stop
        # re-litigating which phrasing wins. Cap raised 446 -> 456.
        # feat(#1242): +29 LOC — build_chat_system_prompt gains the
        # can_edit-gated filter_offer_note (offer, never apply, a persistent
        # set_filter after a query_data result that reads as a simple row
        # predicate) plus the doc/comment explaining why it is gated and why
        # it lives here rather than in tools.py. Cap raised 456 -> 485, exact.
        # fix(#1778): +28 - the provider call is wrapped so a tool loop that
        # exhausts still records what it spent, and the layer block in the
        # system prompt now scrubs column names and sample values and is fenced
        # in an explicit trust boundary the model is told to read as data.
        # Cap 485 -> 513, exact.
        # fix(#1778 round 1): +3 - the layer block is fenced by the shared
        # helper instead of interpolating the marker tags here, so a layer id
        # or a serialized filter cannot forge a closing tag either.
        # Cap 513 -> 516, exact.
        # fix(#1778 round 3): +3 - safe_rows re-exported through the facade
        # alongside _safe_value, per the module's import contract.
        # Cap 516 -> 519, exact.
        "backend/app/processing/ai/chat_service.py": 519,
        # fix(#836): defaults.py is the facade over the extensions-defaults
        # split (defaults_*.py sub-modules discovered below). Pure re-exports —
        # a new Default* class costs a few lines here.
        # fix(#873 review r4): +10 — the two incidental pre-split helper
        # bindings (defer_async_with_tenant, model_safe_tool_result) restored
        # as redundant-alias re-exports. Cap 60 -> 70, exact.
        # fix(#873 review r5): +5 — both helpers added to __all__ so the
        # pre-split wildcard surface survives too. Cap 70 -> 75, exact.
        "backend/app/platform/extensions/defaults.py": 75,
    }
    private_service_default_line_budget = 350
    private_service_line_budget_allowlist = {
        # M4 phase-2 grew this from three analysis operations to seven
        # (#953 spatial_join, #954 measure, #955 select_by_location, #956
        # intersect). Every rendered statement was pushed down into
        # app.platform.analysis_sql as it landed, so what remains here is the
        # preview ORCHESTRATION — which branch feeds which renderer, and how the
        # positional rows become properties — not SQL. Two folds during the
        # wave (#955's count builder, #956's preview projection) each bought
        # one more operation's worth of room before it stopped fitting.
        # 310 on main + 144 for the four operations = 454, then +9 for the
        # #1097-review note on why intersect's match_count seeds to 0 rather
        # than None (an empty overlay is an ANSWER; None is reserved for a
        # count that could not be computed, and the panel renders those
        # differently). The per-operation dispatch is now the majority of the
        # file, so an eighth operation should split that out rather than raise
        # this again.
        # Then +12 for the #1097-review fix that moves the exact-count query
        # inside the preview semaphore: 6 lines of code and the note explaining
        # that BOTH statements open a sandbox connection, so releasing the slot
        # between them let a finished preview admit the next caller while still
        # holding one — the bound stopped bounding the thing it exists for.
        # This budget is a ceiling rather than an exact ratchet, so a stale
        # higher number would still pass. Set to the measured value anyway:
        # the spare line is what the no-headroom rule on _MODULE_LOC_CAPS
        # calls the seed of the next raise.
        #
        # Then +19 for the #1097-review preview-serialization fixes: _json_safe
        # (a transferred bytea value reaches Pydantic as raw bytes and raises;
        # encode as to_jsonb's hex form so both endpoints serve the same
        # representation) and linearizing the select-by-location layer-path
        # identity lateral, the one pass-through geometry this module renders
        # itself rather than through render_geometry_expr.
        #
        # Then +12 making _json_safe recursive: a bytea[] column comes back as
        # a LIST of bytes, which the scalar check waved through to the same
        # 500 (round-14 review). to_jsonb renders that as an array of hex
        # strings, so recursing with the same scalar encoding keeps the two
        # endpoints byte-identical.
        #
        # fix(#1104): -1 — the select-by-location identity lateral reads the
        # bare column again; geom_4326 is linearized at ingest now, so the
        # per-read ST_CurveToLine wrap is gone. Budget 506 -> 505, exact.
        #
        # fix(#727): +89 for viewport-scoped previews — resolve_source_
        # feature_count's bbox-scoped sibling (_resolve_bbox_source_count),
        # the bbox predicate threaded through build_preview_sql's WHERE
        # composition, the intersect-branch scope-decision comment, and the
        # docstring updates on run_analysis_preview explaining both. Budget
        # 505 -> 594.
        #
        # fix(#727 codex P1/P2 round 1): +14 — the bbox count moved from a
        # bare db.execute before the preview semaphore to execute_safe
        # inside it (a concurrent-preview pool-exhaustion finding), which
        # also made it degrade to None on SandboxError instead of exposing a
        # LIMIT-capped count as an exact total (a second, related finding —
        # see _resolve_bbox_source_count's docstring for both). Budget
        # 594 -> 608, exact.
        #
        # fix(#727 codex round 2): +2 — the intersect branch now passes
        # request.bbox through to render_intersect_preview instead of
        # discarding it (a second review round found the discard left one
        # operation still clustering previews in gid order despite the
        # frontend sending bbox uniformly). Budget 608 -> 610, exact.
        #
        # fix(#727 codex round 5): +2 — the spatial_join match_count call
        # site now passes bbox=request.bbox through to
        # render_spatial_join_match_count, matching intersect's fix (a
        # third review round found spatial_join's count was the one
        # remaining place a bbox-scoped source_feature_count was paired
        # with a whole-dataset match_count). Budget 610 -> 612, exact.
        "backend/app/modules/catalog/datasets/domain/service_analysis.py": 612,
        # fix(#1778): +56 over the reviewed 550. The gallery listing's
        # page-scoped layer counts, and the asset-object lifecycle the maps
        # module had none of: the row lock that serializes one map's thumbnail
        # and OG-image replacements, the post-commit re-read that refuses to
        # delete a key the row still points at, and the best-effort discard the
        # delete endpoint and both upload handlers share. Most of the growth is
        # the two docstrings, which carry the part a later reader would
        # otherwise simplify away: a row lock cannot outlive the commit that
        # releases it, so the lock and the re-read are two halves of one fix and
        # neither is redundant. Cap 550 -> 606, exact.
        # fix(#1778 round 3): +44. new_map_asset_key, whose docstring is the
        # argument for it: the row lock ends at the commit, so the cleanup that
        # follows re-reads the row and can still be descheduled between that
        # read and the delete. A key that is never reused closes that window by
        # construction rather than by timing. The locked read also moved from
        # the Map entity to its two columns, and the reason is recorded because
        # it is easy to undo: every caller has already loaded the map, so an
        # entity select returns the identity-mapped instance and reads back the
        # keys from before the wait on the lock. Cap 606 -> 650, exact.
        # fix(#1778 round 4): +58. The post-commit liveness read moved inside
        # the best-effort boundary, because it is a database call made after the
        # caller already committed and a blip in it was turning a durable delete
        # into a 500. And map_asset_publication, the rollback scope the three
        # object writers in this package share. Most of it is the two rationales
        # a later reader would otherwise undo: why skipping the deletes is the
        # safe side of a failed liveness read, and why the ledger records
        # physical keys rather than logical ones (map images resolve into the
        # tenant prefix, sprite icons are deliberately global).
        # Cap 650 -> 708, exact.
        # fix(#1778 round 5): +33 — the ledger became MapAssetPublication, whose
        # settled() moves the rollback boundary onto the commit. Keying it on
        # "did the block raise" answered a different question from "did the row
        # commit", so the icon route's post-commit refresh could delete an
        # object the committed row referenced. The class docstring carries that,
        # and record() carries the physical-vs-logical rule the two writers
        # depend on. Cap 708 -> 741, exact.
        # fix(#1778 round 6): +42 — committing() and outcome_unknown, the mark
        # that makes an indeterminate commit non-destructive. A connection lost
        # between PostgreSQL making the commit durable and the acknowledgement
        # arriving raises for a transaction that DID commit, so the rollback
        # would delete an object the committed row references. Most of the lines
        # are the docstring recording the trade, and why the alternative of
        # verifying from an independent session before deleting was refused: it
        # is a database call on an error path, over a connection that has just
        # proven unreliable, to decide a deletion. Cap 741 -> 783, exact.
        # fix(#1778 round 7): +11 — record()'s docstring now states the ordering
        # as a rule rather than an aside, including the provider evidence that
        # deleting a never-written key is a no-op everywhere (local, S3, Azure),
        # which is what makes recording before the write free.
        # Cap 783 -> 794, exact.
        # fix(#1778 round 8): +56 — lock_map_for_asset_write now runs
        # under SET LOCAL lock_timeout = '2s' and maps a lost race (55P03) to a
        # 409 instead of hanging, plus the _is_lock_timeout_error helper that
        # detects it across asyncpg and SQLAlchemy wrapping. Most of the growth
        # is the docstring addition explaining why an unbounded wait here was a
        # real problem once the row lock started spanning an object-storage
        # PUT with minute-scale S3 timeouts. Cap 794 -> 850, exact.
        "backend/app/modules/catalog/maps/service_crud.py": 850,
        # fix(#474, #475): localized ranking/eager loading plus the OGC
        # ids/externalIds filters cross the default by nine lines. Keep the
        # carve-out exact so further growth requires another review.
        # fix(#1855): -78. The search-only filters and the count moved into
        # service_candidates.py, the selection facets now share. Cap 359 -> 281.
        "backend/app/modules/catalog/search/service_datasets.py": 281,
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
        # Hosted opaque-share isolation joins every token operation through
        # its RLS-visible Map/User parent (+9 LOC). Cap 720 -> 735 leaves
        # only six lines before the next required split review.
        # fix(#931): +32. find_public_maps_using_dataset became
        # find_maps_broken_by_dataset_visibility: an internal map using the
        # dataset was matched by neither the old query nor its caller's gate,
        # so the flip succeeded and every signed-in viewer of that map lost
        # the layer in silence. #930 made the rule a matrix, so the helper
        # compares the before and after audiences instead of listing
        # forbidden target values. Cap 735 -> 918, exact.
        # fix(#1111 review): +19 — precision defers to the conservative
        # refusal whenever a non-default PermissionExtension is registered:
        # the stranded-viewer query mirrors only the default's grants+ladder,
        # so an additive overlay's viewers are invisible to it (#1068 tracks
        # the seam-aware answer). Cap 918 -> 937, exact.
        # feat(#1068): -36. The rank table, its per-map reach function and the
        # three named cut slices are gone: the audience seam answers "who could
        # read this before, and who can after" directly, and a rank drop was
        # only ever a proxy for that difference being non-empty. The guard is
        # shorter than it was before #1111's stopgap and now asks the
        # authority rather than restating the community ladder at it.
        # Cap 937 -> 901, exact.
        # fix(#1126 codex P2): +13 — an unchanged visibility returns before the
        # authority is asked at all. The rank comparison used to absorb the
        # no-op (`X < X` is false); without it the fallback named every shared
        # map, and the seam-answering branch reported an account the overlay
        # could not classify as stranded by a move that did not happen. Most of
        # the lines are why it sits above the branch rather than inside one.
        # Cap 901 -> 914, exact.
        # fix(#1204): +66 — sortable column headers on the admin Published Maps
        # table need list_share_tokens to order by more than the map's
        # created_at. Most of the lines are _share_token_ordering: the sort
        # allowlist, the NULLS LAST pinning for creator/expires_at (an outer
        # join makes every linkless map null there), and why the embed count is
        # ordered by the COALESCE'd expression the cell renders rather than the
        # raw aggregate (which is NULL, not 0, for a map with no ACTIVE embed
        # token — and the count never exceeds 1, per the partial unique index).
        # Cap 914 -> 983, exact.
        # fix(#1372): +4 — the shared-layer raster tile template carries
        # ?v=<tile_cache_version>, the segment nginx's raster cache keys on.
        "backend/app/modules/catalog/maps/service_public.py": 987,
        # fix(#1290 review): +5 — PUBLIC_ASSET_KEYS and the guard that reads it.
        # _build_stac_assets published every dataset_assets row it was handed,
        # so the first INTERNAL key (archived_original, the pre-conversion
        # upload kept after a lossy conversion) would have been advertised as a
        # downloadable asset — a presigned URL on published S3. An allowlist
        # rather than a skip-list so the next internal key is private by
        # default. Cap 500 -> 505, exact.
        # feat(#1281): +7 — project origin health and freshness timestamps
        # through the visibility-filtered OGC search representation, including
        # JSON-safe datetime serialization for the OGC and STAC response paths.
        # Cap 505 -> 512, exact.
        # fix(#1372 codex r2): +7 — the advertised raster_tiles asset carries
        # ?v=<tile_cache_version> like every rendered raster template.
        # fix(#1469): +5 — properties.distributions no longer republishes the
        # raster/VRT ingest tails' object-storage-key row (unresolvable, and it
        # exposes the storage layout). One is_publishable_url guard plus the
        # comment saying why this profile drops the row instead of replacing it
        # — build_assets already advertises raster access here. Cap 519 -> 524.
        # feat(#1681): +1 — FlatGeobuf joined _FORMAT_MEDIA alongside every
        # other export format. Cap 524 -> 525, exact.
        # feat(export/pmtiles): +1 — PMTiles joined _FORMAT_MEDIA the same
        # way. Cap 525 -> 526, exact.
        # fix(#1805 review round 4 P2): +13 — a band whose own stats lack a
        # nodata key but whose asset-level RasterAsset.nodata column is None
        # now emits an explicit nodata: null, so the client can tell
        # "confirmed absent" from "genuinely unavailable" (the latter keeps
        # the key missing). Cap 526 -> 539, exact.
        # fix(#1805 review round 5): +9 — res_x/res_y are now surfaced
        # alongside the lossy gsd (min(abs(res_x), abs(res_y))), so a
        # client-side grid-alignment check can compare each axis
        # independently, matching the backend's _check_grid_alignment.
        # Cap 539 -> 548, exact.
        # fix(#1778): +11, rebased onto the above rather than the 526 baseline
        # it was originally measured against. The band array now builds
        # through the shared `app.core.raster_bands` normalisers, so this
        # representation stops dropping the colour-interpretation name of
        # every locally ingested raster (it read a `name` key no producer
        # writes) and stops emitting empty band entries for a remotely
        # described COG, while keeping the round-4-P2 explicit-null case
        # above (moved to sit beside the normaliser call it now depends on).
        # Cap 548 -> 559, exact.
        "backend/app/modules/catalog/search/service_records.py": 559,
        # fix(#448): +~40 LOC — query-embedding hot-path deadline (asyncio.wait_for
        # wrapper) + the gated/approximated vector-only match COUNT in
        # _run_rrf_merge (perf audit 2026-07-10 §2d). Cap 350 → 390
        # (~19 LOC headroom above 371). That headroom is now spent (386 LOC).
        # fix(#625): +9 LOC — the _MIN_SEMANTIC_QUERY_LEN gate that drops
        # typeahead prefixes before they reach the provider, plus its rationale
        # comment. Cap 390 → 395, exact: the next addition needs its own review.
        # fix(#1546): +61 — stored rows now carry the identity of the
        # configuration that produced them and the vector arm filters on it.
        # Around fifteen lines are mechanism: `_live_embedding_identity`,
        # resolving it once below the has_embeddings gate and handing it back
        # out of `_get_vector_ranks` so the counts filter on what the ranks were
        # taken under, the query-embedding cache key, and `usable_by_config` at
        # the three filter sites. The rest is why the cache key had to change
        # with them — the memoized query vector is a third independent reader of
        # the configuration, and filtering rows by the live one while serving a
        # vector made under the previous one moves the bug rather than fixing
        # it. Cap 395 -> 456.
        # fix(#1546 review r1, codex P1/P2): +26 — the resolved configuration is
        # now handed to the PROVIDER as well as used for the filter and the
        # cache key, so a settings change inside one request cannot produce the
        # query vector under a configuration the rows are not ranked under; and
        # the resolution moved inside the FTS fallback guard, where a raising
        # persistent-config read degrades instead of failing the search. Most of
        # the lines are the two rationales, including why verify-after-the-fact
        # was rejected. Cap 456 -> 482, exact.
        # fix(#1855): -84. The vector arm is resolved once into SemanticArm and
        # counted through the shared candidate set. Cap 482 -> 398, exact.
        "backend/app/modules/catalog/search/service_semantic.py": 398,
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
        # fix(#1104): +8 — _fetch_target_rows projects the row before to_jsonb
        # (via live_property_columns) so the curved source `geom` column never
        # reaches the geometry→jsonb cast, which raises on curves. Cap
        # 620 -> 628, exact.
        # fix(#1113 review r10): +7 — the FK match moved inside the projection
        # against the base table (a relationship may target a column the
        # projection drops), with the identifier colon-escaped for text().
        # Cap 628 -> 635, exact.
        # fix(#1580): +18 — the related-items seed is the anchor ROW now, not a
        # bare vector, and the pair travels from it into the scoring call. A
        # list of floats does not say which model or endpoint produced it, so
        # without carrying the identity this layer could select neighbours in
        # one vector space and print similarities measured in another. Most of
        # the lines are the two docstrings saying why the anchor's own pair is
        # the question here, where both sides are stored rows, rather than the
        # live configuration's. Cap 635 -> 653, exact.
        # fix(#1580 review r2): +4 — the anchor read is handed into the
        # neighbour selection rather than left to be taken again. Two reads of
        # one record under READ COMMITTED can straddle a commit, and then the
        # ranking is anchored on a row the scoring never saw. Cap 653 -> 657.
        "backend/app/modules/catalog/datasets/domain/service_relationships.py": 657,
        # fix(#474): reject primary-language updates that collide with a
        # translated variant. Cap 460 -> 480 (~9 LOC headroom above 471).
        # fix(#931): +7. _apply_visibility_change no longer carries its own
        # `new != public and old == public` gate — that gate is what hid the
        # internal-map case — and delegates the whole before/after audience
        # comparison to the maps helper. Cap 480 -> 489, exact.
        # feat(#1068): +1 — the guard call passes record_id, so the permission
        # authority can key an audience on the record and not only its dataset.
        # Cap 489 -> 490, exact.
        # fix(#1170): -37 — delete the dead update_auto_metadata, the one
        # geometry_type writer that never probed for geom_4326 (refs #1020).
        # Cap 490 -> 453, exact.
        # feat(#1070): +30 — the inherited-keyword disclosure warning at the
        # metadata chokepoint: after visibility/record_status resolve, one
        # check of the resolved state warns (never blocks) when keywords
        # inherited from the analysis source reach beyond that source's
        # audience. Cap 453 -> 483, exact.
        # fix(#1178 review): -5 — the check body moved into the shared
        # inherited_keyword_disclosure_warning helper so the publication
        # status endpoints run it too. Cap 483 -> 478, exact.
        # feat(#1472): +1 — the `attribution` entry in _RECORD_FIELD_MAP, which
        # is all the PATCH needs: the field is a plain scalar on the record, so
        # _apply_simple_field_assignments already gives it PATCH semantics and
        # explicit-null clearing. Cap 478 -> 479, exact.
        # fix(#1746 B2b review r24): +9. `row_count_delta` is null when either
        # count is unknown rather than a subtraction against a coerced zero,
        # which invented a delta the size of whichever side was known. The
        # case that reaches it is a service preview whose collection size the
        # service never published.
        # fix(#1847): +31. `sample_example_values` reads the data table on its
        # own and `reset_attribute` takes the sample as an argument, so the
        # reset samples before it takes the pair. Cap 488 -> 519, exact.
        "backend/app/modules/catalog/datasets/domain/service_metadata.py": 519,
        # fix(#435 codex r1): +6 LOC in get_dataset_rows to probe schema existence
        # before degrading a 42P01 to an empty page. Postgres reports a missing
        # tenant data schema with the same code as a raster dataset's synthetic
        # table, so the code alone cannot tell provisioning drift from normal
        # emptiness. Cap 390 -> 396, no headroom.
        # fix(#836): +1 for the RASTER_FAMILY_RECORD_TYPES import. Cap 397,
        # still no headroom.
        # feat(#765): +7 — the detail response resolves derived_from through
        # visible_derived_from, so a private source is never disclosed via a
        # derived dataset. Cap 397 -> 404, still no headroom.
        # fix(#1103): +15 — the same treatment for the PROSE. Both builders in
        # this module now resolve lineage_summary through
        # visible_lineage_summary(ies), which is what stops a derived dataset
        # from naming a source or mask layer the requester cannot open. The
        # list builder takes the batch form deliberately: one visibility query
        # for the page rather than one per row. Cap 404 -> 419, no headroom.
        # fix(#1290 review): +7 — the public-asset-key boundary. Rows are
        # filtered where they are FETCHED so an internal key never enters a
        # payload structure; `GET /datasets/{id}` had been building its assets
        # straight off the ORM rows and leaked the archived original's href and
        # filename to every viewer. Cap 419 -> 426, exact.
        # feat(#1316): +12 — the list and detail builders each now resolve
        # can_view_dataset_provenance(record, user, user_roles) and pass it
        # into dataset_to_response, so origin_uri/origin_ref are nulled for
        # every reader but the owner or an admin. Cap 426 -> 438, exact.
        # fix(#1436): +5 — the raster asset, VRT source-count, and dataset-asset
        # fetches each open their own async_session() instead of gathering on
        # the shared `db` (which asyncpg silently serialized despite the old
        # "in parallel" comment). Cap 438 -> 443, exact.
        # fix(#1436 codex r1): -14 — reverted to sequential fetches on the
        # caller's own session. Per-branch async_session() traded the
        # serialization bug for a nested pool checkout while the caller's own
        # connection is held for the rest of the request; per codex, ~13
        # concurrent raster/VRT detail requests exhaust the default (10 + 3)
        # pool this way. Three fast point lookups aren't worth that risk.
        # Cap 443 -> 429, exact.
        # fix(#1778): +10 — the row browser emits quoted column identifiers.
        # A column named after a SQL keyword (``desc``, ``order``, ``user`` —
        # ogr2ogr's DBF output, and nothing renames them on ingest) made every
        # SELECT and every ILIKE filter a 42601 syntax error, which is in none
        # of the sqlstate sets this module degrades on, so the endpoint 5xx'd
        # for that dataset forever. The lines are the import, the two call
        # sites and the docstring note saying membership is decided on the bare
        # name so quoting happens at emission. Cap 429 -> 439, exact.
        "backend/app/modules/catalog/datasets/domain/service_query.py": 439,
        # fix(#1452): first explicit cap for this module — it sat under the
        # 350 default until the detach landed. +65 over the pre-change 350:
        # _reap_managed_storage (the reap loop both branches had inline,
        # extracted when the new conditional pushed delete_dataset past
        # ruff C901), _relation_exists (the pg_class probe that decides
        # whether a detach freed the name), and the two decisions delete now
        # makes with the reasoning behind them: drop-vs-detach, and the
        # GH-1443 retirement that follows the relation rather than the
        # dataset. Cap 350 -> 415, exact.
        # fix(#1456): +36 — the tombstone now carries the freed relation's oid
        # and the dataset's prior owner. _relation_exists became _relation_oid
        # (same one probe, now returning the identity), the probe moved ahead
        # of the drop-vs-detach branch so the DROP path can capture an oid
        # before the relation is gone, and the two new tombstone fields carry
        # the reasoning for why they are captured here and nowhere else
        # (both sources die in this transaction) plus the oid's
        # one-cluster-lifetime caveat. Cap 415 -> 451, exact.
        # fix(#1456 codex round 1): +32 — the identity was being collected
        # everywhere EXCEPT the surviving-detach path, which is the one
        # GH-1456's window 1 is about. That path now writes a DetachedRelation
        # instead of discarding what it probed, in a sibling table rather than
        # the retirement set (whose whole API is set membership), with the
        # reasoning for the split and for the belt-and-braces oid guard.
        # Cap 451 -> 483, exact.
        # fix(#1847): the lock order, its gate and its 409 mapping, and the
        # job rows ahead of the cascade. Cap 513, exact.
        "backend/app/modules/catalog/datasets/domain/service_lifecycle.py": 513,
        # Phase 276 CODE-02: chat_*.py sub-modules are all under the 350
        # default (largest is chat_actions.py at ~245 LOC). No explicit
        # per-file overrides needed; default applies.
        # fix(#394) CH-02: +~35 lines — set_label column validation against the
        # target layer schema (error feedback to the model), the CSS-colorish
        # sanitizer, and the collector error gate. Cap 350 → 400 (~19 headroom).
        # fix(#544): +~14 lines — deterministic geom_4326 append before
        # execution and WKB-column strip after geojson extraction in
        # _handle_query_data. Cap 400 → 425 (~11 headroom).
        # fix(#556 review P2): +~8 lines — overlay-row-budget fetch cap when
        # geometry is appended (constant + conditional row_limit). Cap
        # 425 → 445 (~12 headroom).
        # fix(#556 review P2, round 7): +~15 lines — geometry-free COUNT
        # recovery so the transfer cap doesn't corrupt the documented total
        # row_count. Cap 445 → 470 (~18 headroom).
        # fix(#560): +~44 lines — _geom_4326_missing_note helper + graceful
        # degrade (clean note instead of a generic failure) at both the
        # model-written and append-retry failure points when a legacy geom-only
        # table lacks geom_4326. Cap 470 → 530 (~16 headroom).
        # M4 Phase 5 (run_analysis chat tool): +~11 lines — the dispatch branch,
        # the collector branch, and the chat_analysis import. The handler itself
        # was split into the new chat_analysis.py sibling (auto-discovered by the
        # chat_*.py glob below, ~142 lines under the 350 default) rather than
        # grown here. Cap 530 → 550 (~14 headroom).
        # fix(#1778): +31 - the _SANDBOX_BOUNDS table and the comment
        # enumerating what query_data now passes to the sandbox and, for the
        # statement timeout and the output-amplification denylist, why it
        # deliberately does not. Both surfaces sit behind the same
        # use_ai_chat permission, so the omissions were opt-out by asking the
        # chatbot. Cap 550 -> 581, exact.
        # fix(#1778 round 3): +6 - safe_rows on the tabular half of the
        # query_data payload, at the one point it is handed to a frame, plus
        # the note saying why it runs after geometry detection and not before.
        # Cap 581 -> 587, exact.
        "backend/app/processing/ai/chat_actions.py": 587,
        # feat(#1241): +18 over the 350 default — _safe_value now emits
        # integers outside JavaScript's safe range as strings (constant, the
        # int branch, and the docstring explaining why), so a bigint id
        # survives the browser's JSON.parse intact instead of arriving rounded
        # and being written that way into a saved chat-preview snapshot.
        # Cap 350 → 370 (~17 headroom).
        # fix(#1778): +50 — non-finite floats now become null and an all-EMPTY
        # result returns no bbox instead of [inf, inf, -inf, -inf], either of
        # which used to make the actions frame unparseable (the browser dropped
        # it silently; the non-streaming endpoint returned 500). Two helpers
        # were split out to keep _extract_geojson under the complexity gate:
        # _parse_row_geometry (the per-row parse) and _row_properties (the
        # property build plus its non-finite count, which feeds one warning per
        # result rather than one per cell). Cap 370 -> 420, exact.
        # fix(#1778 round 3): +17 - safe_rows, the tabular sibling of
        # _safe_value. Round 0 normalized only the GeoJSON property copy, so a
        # NaN in an ordinary column still reached the SSE frame as a bare token
        # and the browser dropped the whole frame. Cap 420 -> 437, exact.
        # fix(#1891): +3. The geometry append folds both table parts through
        # the sandbox's folded_identifier before comparing. Cap 437 -> 440, exact.
        "backend/app/processing/ai/chat_geojson.py": 440,
        # fix(#836): extensions-defaults sub-modules over the 350 default at
        # split time. Caps exact (zero headroom): each class moved verbatim
        # from the 1815-LOC defaults.py, and regrowth toward another god
        # module should get its own review.
        # fix(#1590): +48 — stream and stream_chat_events pinned to explicit
        # keyword-only signatures matching AIProviderExtension instead of a
        # bare **kwargs shim, so a missing keyword surfaces at the port
        # boundary rather than inside _stream_openai_chat. Cap 444 -> 492,
        # exact.
        # fix(#1778): +10 - each of the three ToolLoopExhaustedError raise
        # sites now carries the running token totals, so the caller can bill an
        # exhausted loop to the daily cap instead of losing it. Cap 492 -> 502,
        # exact.
        # fix(#1778 round 1): +18 - the loop is wrapped so EVERY exit stamps
        # its running token totals, not only the three exhaustion raises. After
        # round one the provider has been billed, so a later request failure, a
        # tool executor that raises, or a cancellation must still reach the
        # daily quota. Cap 502 -> 520, exact.
        "backend/app/platform/extensions/defaults_ai_openai.py": 520,
        # fix(#1778 round 1): first explicit cap, over the 350 default. The
        # loop is wrapped so every exit stamps its running token totals, and
        # _run_tool_use_blocks was split out of complete() because that wrapper
        # pushed it over the complexity gate. Cap 350 -> 372, exact.
        "backend/app/platform/extensions/defaults_ai_anthropic.py": 372,
        # fix(#1207): +15 — three delegations for the shared presigned-completion
        # helpers (lock/assemble-check/finalize) the reupload door reaches through
        # the port. Three lines each, matching the existing entries.
        # fix(#1213 review r3): +7 — the completability guard's delegation.
        # fix(#1235 review r3): +5 — the remaining-lifetime delegation, which
        # the reupload door reaches through the port like every other
        # processing helper it uses.
        # fix(#1235 review r8): +5 — the sign-with-deadline delegation. The
        # reupload door hands this to a worker thread, so the whole callable
        # has to cross the port rather than just the lifetime number.
        # feat(#1221): +5 — the raster-replace task delegation, same three-line
        # shape as its reupload_file/reupload_service siblings. The reupload
        # commit door picks the executor by record type and reaches all three
        # through the port.
        # feat(#1265): +5 — the registered-PostGIS refresh task delegation,
        # same three-line shape again. The refresh door now picks its executor
        # by origin kind and reaches this one the same way it reaches
        # reupload_service.
        # feat(#1266): +5 — the STAC re-resolution task delegation, the third
        # instance of that same three-line shape. Cap 440 -> 445.
        # refactor(stac): +5 — fetch_raster_meta_bulk_without_vrt, the narrower
        # reading of the raster-meta query the STAC item surface takes. Same
        # deferred-import shape as its sibling; a separate method rather than a
        # keyword because widening a port signature is an
        # EXTENSION_API_VERSION bump. Cap 445 -> 450.
        # fix(#1546): +11 — resolve_embedding_config_fingerprint, the answer
        # semantic search needs to tell a stored vector from one made under
        # another endpoint. Same deferred-import shape as its neighbours;
        # `modules/catalog/` may not import `app.processing.*`, so it crosses
        # here. Cap 450 -> 461.
        # fix(#1546 review r1, codex P1): +17 — the port answers the whole live
        # configuration rather than its fingerprint alone, and generate_embedding
        # takes a pinned triple. The comment carries why that is ONE optional
        # argument and not three keyword ones: `None` is a legitimate resolved
        # endpoint, so three None defaults could not tell "not pinned" from
        # "pinned to the client default". Cap 461 -> 478, exact.
        # fix(#1580): +13, and the code shrank — get_record_embedding stopped
        # spelling its own query and now shares `get_anchor_embedding_row` with
        # the ranking helper, so "which row is the anchor" has one answer
        # instead of two `LIMIT 1` reads that could disagree. The lines are the
        # two comments: why the anchor's identity travels with its vector, and
        # why scoping the selection without scoping the distances would have
        # moved the defect one layer out rather than closing it.
        # Cap 478 -> 491, exact.
        # fix(#1580 review r2): +18 — get_nearest_record_ids takes the caller's
        # anchor as a required keyword, and both queries move to
        # usable_by_stored_anchor. The lines are the two comments saying why the
        # stored-vs-stored predicate does not grandfather an unstamped row where
        # search's does: on the catalog that distinction matters for, a partial
        # re-embed, the rows still carrying NULL are the old space.
        # Cap 491 -> 509, exact.
        # fix(#1590): +60 — pin abort_presigned_multipart_upload,
        # verify_completed_presigned_upload, and finalize_presigned_object to
        # CatalogPort's explicit keyword-only signatures instead of a bare
        # **kwargs shim, so a missing keyword surfaces at the port boundary
        # rather than deep in the service call.
        # verify_completed_presigned_upload and finalize_presigned_object
        # also keep accepting replacing_dataset_id: uuid.UUID | None = None,
        # a structural superset the Protocol does not declare yet (see the
        # comments on both methods in core/catalog_port.py — adding it there
        # is a version bump, not a cleanup). Cap 509 -> 569, exact.
        "backend/app/platform/extensions/defaults_catalog_port.py": 569,
        # feat(#683): +58 — run_analysis_preview carries a clip mask DATASET
        # now, which costs a widened signature (one param per line once ruff
        # wraps it) plus the mask's shape and size gates. Those live here on
        # purpose: they are the rails router_analysis._load_mask_dataset
        # applies, and putting them at the port gives every caller the same
        # refusal instead of an empty preview or an unbounded mask subdivide.
        # Cap 406 → 470 (~6 headroom).
        # feat(#1266): +11 — resolve_stac_binding. The STAC refresh strategy
        # re-reads the item document its asset was published in, and every
        # byte of that goes through Rule 2's safe client and the #1222 health
        # classifier, both of which live in the catalog domain. Routing the
        # ANSWER across the port is what keeps processing/ from importing
        # catalog for it (the burn-down list's own instruction) and leaves the
        # worker holding no HTTP client at all. Cap 470 -> 481.
        # fix(#1266 review round 9): +1 — the resolution takes the item's
        # recorded id as well, so a catalog whose URLs state no identity can
        # still have an answer checked against the binding. Cap 481 -> 482.
        # fix(#1314): +12 — reconcile_distributions, the seam the refresh and
        # reupload paths cross to bring auto-generated distribution rows in
        # line with a modality that changed under them. Cap 482 -> 494.
        # fix(#1443): +5 — get_retired_table_name_orm_class. The retired-name
        # probe runs inside generate_table_name, which lives in processing/ and
        # so cannot import the catalog model it needs; this is the same
        # ORM-class accessor shape as its five neighbours. Cap 494 -> 499,
        # exact.
        # fix(#1506): +38 — get_records_without_embeddings became model-aware.
        # Six lines are the NOT EXISTS and the model resolution; the rest is
        # the pair of rationales a future reader needs to not undo it: why
        # "missing" means "missing under THIS model", and why an unresolvable
        # model returns nothing here while the same sentinel is allowed to
        # read as zero coverage in admin's stats. Cap 499 -> 537, exact.
        # fix(#1546): +27 — "missing" narrows once more, from "no vector this
        # MODEL can use" to "no vector this CONFIGURATION can use", so a row
        # written against another endpoint is picked up instead of reading as
        # coverage the search cannot use. Six lines are the fingerprint
        # resolution and its fail-closed branch; the rest records why an
        # UNSTAMPED row still counts as covering the record, which is the only
        # thing keeping an upgrade from turning the next Generate Missing into
        # a catalog-wide re-embed. Cap 537 -> 564, exact.
        # fix(#1590): +4 — compute_schema_diff's parameters renamed to match
        # ProcessingPort's old_feature_count/new_feature_count so a keyword
        # caller fails against the Protocol, not just the default. Cap
        # 564 -> 568, exact.
        "backend/app/platform/extensions/defaults_processing_port.py": 568,
        # fix(#929): +2 over the 350 default — the creator exemption on the
        # restricted branch of filter_visible/can_access_dataset plus its
        # rationale comments. fix(#930): +20 — the internal branch on the same
        # two functions, whose comments carry why the obvious stricter variant
        # is wrong (it hides an owner's own draft from the owner). Cap exact,
        # zero headroom.
        # feat(#1068): +61 — record_audience, the audience-shaped reading of
        # the same ladder filter_visible applies per user. Roughly half the
        # lines are the mapping between the two: which condition over there
        # each branch here inverts, so the pair can be kept in step by reading
        # rather than by running the equivalence suite. Cap 372 -> 433, exact.
        "backend/app/platform/extensions/defaults_extensions.py": 433,
        # fix(#1778): +16 over the 350 default -- _apply_common_filters'
        # datetime block replaces two bare `.is_(None)` OR-arms (which
        # unconditionally matched every null-temporal record for ANY
        # datetime filter) with the same null_temporal & created_at
        # fallback comparison the already-fixed STAC peer uses, while
        # preserving the existing open-ended reading for records that do
        # have one bound set. Cap 350 -> 366, exact.
        "backend/app/modules/catalog/search/service_filters.py": 366,
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
    # fix(#836): extend discovery to the platform/extensions defaults split
    # (the defaults.py facade is already covered via facade_line_budgets).
    files_to_check.extend(
        _repo_style_rel(path)
        for path in sorted(
            _backend_path("app/platform/extensions").glob("defaults_*.py")
        )
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


# fix(#958): lifted to module scope from
# test_open_core_decomposition_boundaries_stay_clean so the inclusion rule below
# can ask whether a ceiling gate already watches a module. Plain ceilings, not
# exact ratchets: these files may shrink freely. Where an entry below says its
# ratchet "stays exact", that is the author setting the cap flush with the
# file's current LOC as a convention — no test here enforces the equality.
_OPEN_CORE_SIZE_CAPS: dict[str, int] = {
    # fix(#526 B-044): per-layer minzoom/maxzoom in style.json export,
    # propagated to companion layers.
    # fix(#527 B-054/S-05+LB-04): symbol icon-opacity + allow-overlap parity.
    # fix(v1.6.0 audit): hypso_reversed flows into the color-relief
    # companion so exported ramps match the builder's Reverse toggle.
    # fix(#836): +1 for the RASTER_FAMILY_RECORD_TYPES import.
    # fix(#917): +85 — builtin fill patterns are stripped at export and fall back
    # to a solid colour. Plain strings only: composites are left as authored,
    # because MapLibre skips a missing pattern and exposes styleimagemissing to
    # repair it, while stripping a working expression is unrecoverable (#1069).
    # Ratchet stays exact.
    # fix(#910): +37 — the extrusion companion resolves its colour from the
    # fillColorSaved stash, and the export seeds that stash into `fill-color`
    # BEFORE #917's strip runs, so a builder-patterned polygon exports the colour
    # the user chose instead of brand blue (EDIT-05 means paint never carries one).
    # fix(#910, codex P2): +5 — the seed accepts an explicit `fill-color: null` too.
    # fix(#1069): +56 — the read-side bound on malformed stored style values.
    # Writes are shape-checked now, but that does nothing about the rows already
    # in the database, and a serializer that descends into one of them 500s the
    # SHARED style endpoint from stored data rather than from the request. Two
    # guards, because the two stages that read stored paint are separate: the
    # per-layer serialize loop in `build_maplibre_style`, and the emitted-layer
    # pass now split out as `_validate_emitted_layer` — which is where #1054's
    # intermediate revision actually walked `fill-pattern` composites. Roughly
    # half the lines are the write-up of why the catch is a named data-shape
    # tuple and not `Exception`: `_tile_url_for_layer` raises RuntimeError with
    # no tenant context, and swallowing that would turn a fail-closed refusal
    # into a quietly missing layer in a hosted export.
    # fix(#1372): +5 — exported raster/DEM sources carry ?v=<tile_cache_version>
    # so external MapLibre consumers roll the shared nginx cache on replace.
    # fix(#1472 review): +9 — dataset_attribution on exported sources. Placed on
    # _source_for_layer's common tail rather than in each branch, so vector,
    # raster, and raster-dem carry it and a fourth source type cannot be added
    # without it. Cap 1620 -> 1629, exact.
    # fix(#1472 review): +12 — HTML-escape the exported credit. The style spec's
    # `attribution` is an HTML string the consuming application renders, so this
    # export hands a third party a context we do not control; the lines are
    # mostly the note recording that the write guard already keeps `<`/`>` out,
    # which leaves this escaping the ampersand and covering a value written
    # before that guard existed. Cap 1629 -> 1641, exact.
    # fix(#1626): +53 — `_fold_master_opacity` applies `layer.opacity` to the
    # primary fill/line layer on export. Mostly its docstring: it records why the
    # export multiplies instead of emitting the v6 `-layer-opacity` keys (they
    # abort the style load on maplibre-gl < 6, verified against 5.24.0) and the
    # metadata handshake that keeps a GeoLens round trip lossless. Plus the
    # allowlist note saying the two keys are left out on purpose, and (#1631
    # review) the note on the pre-existing absent-at-master-1 divergence the
    # fold deliberately leaves alone. Cap 1641 -> 1703.
    # fix(#1778): +7 — `_layer_metadata` emits popup_config, which had no export
    # at all, so a map's popup configuration was dropped by any export/import
    # cycle and the import side had nothing to read. Cap 1703 -> 1710.
    # fix(#1778 round 3): +9 — the export's zoom no-op conditions read the
    # shared BUILDER_MIN_ZOOM / BUILDER_MAX_ZOOM instead of repeating 0 and 22,
    # so the two directions of the round trip cannot drift. Cap 1710 -> 1719.
    "backend/app/modules/catalog/maps/style_json.py": 1719,
    # fix(#1626): +50 — `_restore_master_opacity` undoes the export fold from
    # `metadata.geolens.feature_opacity` and maps a v6 `-layer-opacity` key onto
    # `layer.opacity` (number) or drops it with a warning (expression); plus
    # (#1631 review) BUILDER_FEATURE_OPACITY_DEFAULTS, the mirror of the
    # frontend's OPACITY_DEFAULTS the fold starts from when paint has none.
    # Cap 450 -> 500.
    # fix(#1778): +6 — the master-opacity read goes through finite_number so a
    # stored 0.0 survives import, plus the comment saying what the truthiness
    # read cost (the folded paint key was popped in the same pass, so the
    # document's own record of the 0 went with it). Cap 500 -> 506.
    # fix(#1778): +49 — `_restore_zoom_range` reads the spec minzoom/maxzoom the
    # export promotes from the builder-private layout keys, and
    # `_popup_config_from_import` reads back the popup settings the export half
    # of this fix started emitting. Most of it is the two docstrings: why the
    # 0/22 no-ops must not be written back as explicit keys, and why a
    # malformed popup config is dropped rather than raised on (MapLayerInput
    # would 400 the whole document over one layer). Cap 506 -> 555.
    # fix(#1778 round 1): +25 — MapStyleImportLayerLimitError and the per-map
    # limit applied to the layers that will become rows, which is the count
    # apply_layer_diff later compares against, so the import door and the save
    # path refuse at the same number. Cap 555 -> 580, exact.
    # fix(#1778 round 3): +57 — BUILDER_MIN_ZOOM / BUILDER_MAX_ZOOM mirrored
    # from map-sync.ts and shared with the export, plus the clamp that keeps a
    # restored minimum below the maximum the builder can render. Most of it is
    # the docstring: MapLibre hides a layer at zoom >= maxzoom, so a minimum at
    # or above the substituted 22 imported cleanly into a layer that could never
    # be drawn, and clamping is the only repair the builder can honour.
    # Cap 580 -> 637, exact.
    "backend/app/modules/catalog/maps/style_import.py": 637,
    "backend/app/modules/catalog/maps/style_sanitizers.py": 200,
    # fix(getgeolens.com#86 review): +6 — the icon-asset and sprite-index GETs
    # gained per-route `responses={403: FORBIDDEN_RESPONSE}` overrides; they
    # are read-gated (icon asset) or unauthenticated (sprite index), so the
    # router's inherited write-flavored 403 misdescribed their actual cause.
    # Cap 126 -> 132, exact.
    # fix(#1440): +10 — the sprite-index override above only reworded the 403; the
    # sprite JSON and PNG routes take no auth at all, so no 401/403/409 can
    # occur regardless of description. FastAPI's router `responses=` merge is
    # additive along the whole include chain (an ancestor's key always shows
    # through unless a route sets that same key itself), so a same-file
    # sibling router nested under the maps router's ERROR_RESPONSES_WRITE
    # would still leak those keys. All four sprite routes moved to
    # `sprites_router`, mounted with ERROR_RESPONSES_PUBLIC directly on
    # api_router (api/router.py) as a sibling of the maps router rather than
    # a descendant. Cap 132 -> 142, exact.
    # fix(#1778 round 4): +7 — the icon upload publishes the object and its row
    # inside one rollback scope. It is the third write-object-then-commit-row
    # site in the package and the only one whose write and commit sit in
    # different functions, so the comment records why the ledger is threaded
    # through create_icon_asset. Cap 142 -> 149.
    # fix(#1778 round 5): +4 — the publication settles on the commit and the
    # refresh moved below the scope, which is the case that found the boundary
    # bug. Cap 149 -> 153.
    # fix(#1778 round 6): +3 — the icon commit is marked before it is awaited,
    # the same as the two image handlers. Cap 153 -> 156.
    "backend/app/modules/catalog/maps/router_assets.py": 156,
    # fix(#526 B-048): the card-route SPA-redirect fallback shell.
    # fix(#819): visibility-check owner-or-admin gate + rationale docstring.
    # fix(#1518 codex P2 round 3): 398 -> 404. +6 to apply the rule once, ahead
    # of all three arms. It had run only after a SUCCESSFUL unpack, so a missing
    # (404) or revoked (410) link answered a caller whose credential was dead
    # without ever telling them.
    # fix(#1518): 387 -> 398. +11 for the CAPABILITY obligation on the shared-map
    # endpoint: it takes the deferring dependency so the embed token is judged
    # first, unpacks the capability verdict get_shared_map now reports, and
    # re-applies the fail-closed rule when nothing was authorized by it. The
    # verdict comes from the service because that is where the scope is
    # resolved; re-deriving it here would be a second lookup that could
    # disagree with the first.
    # fix(#1672): +32 — the style.json export route's 200 response is now
    # documented in the decorator: an open object schema pointing at the
    # MapLibre style spec plus the sprite array-form guarantee, replacing the
    # empty {} schema a generated client could misread (sprite string vs
    # array). Deliberately description-heavy, zero logic added. Then +4
    # (codex r1): additionalProperties: true, or openapi-typescript closes
    # the open object to Record<string, never>. Cap 436 -> 440, exact.
    "backend/app/modules/catalog/maps/router_sharing.py": 440,
    "backend/app/modules/catalog/search/query_params.py": 225,
    "backend/app/modules/catalog/search/router_saved.py": 100,
    # fix(#821): +14 lines — admin key mint accepts expires_at (audit
    # detail + response) and maps the inactive-owner mint refusal to 409.
    # fix(#875): +7 lines — admin key mint accepts scope, and surfaces it
    # in the audit detail, the create response, and the list item.
    # fix(#1204): +20 lines — the published-maps listing takes sort/order as
    # closed enums, with the descriptions that say which columns are absent
    # (link status) and why.
    # fix(#1778): +4 lines — POST /admin/api-keys/
    # documents the 409 it raises for a pending/suspended/deactivated
    # target user, closing a gap the repaired OpenAPI-contract gate surfaced.
    # fix(#1778): +4 lines — GET /admin/api-keys/ orders by created_at desc so
    # the LIMIT-capped page is deterministic across refetches.
    # fix(#1805 review round 4 P2): +5 lines — created_at DESC alone ties on
    # equal timestamps and each page is a separate query; id DESC added as a
    # secondary key for a total, reproducible order across pages.
    "backend/app/modules/admin/router_operations.py": 329,
    # PRIV-1: +7 lines — GET /settings/branding/ also resolves and returns
    # PRIVACY_URL, so the login/register privacy-policy link is admin
    # configurable instead of a hardcoded getgeolens.com URL.
    # PRIV-1 (pre-review): +18 — the reader re-checks a stored/env privacy_url
    # against the shape rule and drops (+ logs) an unsafe one instead of
    # serving it as a login-page <a href>; a stored value can predate the
    # check or bypass PersistentConfig.set()'s validation entirely.
    # feat(#1691): +2 — restrict_public_visibility rides the public
    # feature-flags bundle so the UI can hide the Public option for
    # non-admins. Cap 175 -> 177.
    "backend/app/modules/settings/router_public.py": 177,
}


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
# fix(#836): the dict is keyed by PATH, not filename, and no longer holds routers
# only. The router-glob gate below scans `**/router.py`, so the largest backend
# modules — ingest/metadata.py, ingest/tasks_common.py, maps/schemas.py,
# api/main.py — were ungated simply because of their names, and ingest/router.py
# sat a few lines under the 1500 default cliff where the next feature would trip
# a gate its author had never seen. All five are now ratcheted exact.
#
# History of the previous caps, kept because it records why each file is large:
#   maps/router.py    1610 → 1700 → 1800 → 1900. Phase 1047 bulk-delete, then PR #118
#     builder polish took it to 2107; extracting _router_helpers.py brought it back.
#     Icon/sprite assets and public sharing/export now live in composed sub-routers;
#     media/layer mutation routes remain in the main router.
#   search/router.py  1515 → 1600 → 1640 → 1700. OGC record metadata (#315), then the
#     record_type/sort_by allowlist + to_filters() chokepoint (#317 A2). The OGC
#     Records array-query contract and explicit GeoJSON response schemas add the
#     final 21 lines after protocol helpers were extracted to records_protocol.py.
#   standards/stac/router.py entered the allowlist at 1547 for the virtual
#     unassigned Collection, deterministic multi-membership selection, and HTTP
#     Link parity required by the 2026-07-12 compliance remediation.
#   tiles/router.py   1500 → 1660 → 1850 → 1920 → 2050 → 2090 → 2329. fix(#1429) bought
#     the generation dimension in the tile cache key: `_generation_table_key`, the
#     dataset-id parameter threaded through `_cluster_cache_table_key`, and
#     `_evict_dataset_meta` plus its listener registration, which is what stops a
#     freed table name from serving its successor under the deleted dataset's
#     visibility. Raster meta TTLCache
#     (1176 PERF-002), SET LOCAL ROLE binding (1209-03 DP-02), cloud fairness/metering
#     seams (1213-06), the cold-tier seam (1214-04), terrainrgb nodata (#186), and
#     empty-tile Cache-Control (#430 V-03). NOTE: `_check_cold_rehydrate` is pinned to
#     this module by the overlay's 1214-05 static AST proof, so the tile_seams.py split
#     must update the overlay in lockstep.
#   api/main.py 1846 -> 1883. fix(#1778 codex r2): +37 for
#     `install_api_query_deadline` and the note under it. The query deadline
#     moved off the `get_db` dependency onto the engine this process owns,
#     because handlers open request-scoped sessions directly through
#     `async_session()` in more than twenty modules -- `GET /stac/collections`
#     runs three aggregates that way -- and a per-dependency binding covered
#     none of them. Most of the addition is why it runs at import rather than
#     in the lifespan (`do_connect` only fires for connections opened after
#     registration), why the engine is late-bound (fix(#909)), and why the
#     worker, which never imports this module, must stay excluded.
#   api/main.py 1796 -> 1846. fix(#1778): +50 across two audit findings. The
#     /health/live route (liveness, no dependency probes) and the paragraph
#     saying why the container healthcheck and the frontend's depends_on had to
#     stop targeting /health: it probes the cache, which the API is built to
#     survive, so a Valkey outage marked the container unhealthy and took the
#     UI down with it. The rest is the note on _rate_limit_handler explaining
#     why it must stay a plain def -- slowapi's synchronous middleware silently
#     discards a coroutine handler and answers the global rate limit with a
#     bare {"error": ...} and no Retry-After, which is unreachable from any
#     test that drives a decorated route.
#   api/main.py 1635 -> 1750. fix(#1666): +115 for three OpenAPI post-processing
#     passes, joining the four already here. `_normalize_validation_error_contract`
#     replaces FastAPI's `HTTPValidationError` at every 422 with the problem+json
#     `ProblemDetail` the app-wide handler actually returns, and
#     `_drop_unreferenced_validation_models` removes the models once nothing
#     references them — checked rather than popped, since a dangling `$ref`
#     breaks SDK generation. `_repair_depends_bound_query_model` republishes the
#     two `SearchQueryParams` fields that do not survive `Depends()` binding on
#     `collection_items` (`keywords`, which FastAPI reads as a GET request body,
#     and the `filter-lang` alias, which pydantic cannot name), copying them from
#     the sibling operation that declares the same model correctly rather than
#     restating them. Most of the addition is the rationale for why that route
#     cannot use the query-parameter-model form the other one now does. The last
#     13 are the codex P2 round: the reference scan excludes only the candidate,
#     never both models, so a retained `HTTPValidationError` cannot take the
#     `ValidationError` it points at down with it.
#   search/router.py 1468 -> 1483. fix(#1666): +15. `search_datasets_endpoint`
#     moved to `Annotated[SearchQueryParams, Query()]`, which binds `keywords`
#     and `filter-lang` natively and retired its raw-query-string reads; the
#     shared `_checked_filter_lang` that replaced the two duplicated checks costs
#     more lines than it saves, because the reason the field stays a bare `str`
#     (a `Literal` would answer 422 where both routes contract to 400) has to be
#     written down or the next reader tightens it. 1483 -> 1494 for the codex
#     P2 round: `_resolve_filter_lang` reads the wire instead of the bound value,
#     because neither binding form sees both accepted spellings, and it keeps
#     honouring `cql2_filter_lang` — the name the PRE-FIX contract published, so
#     the only one older generated SDKs send. Plus `_legacy_keywords_body`, which
#     honours the GET-body `keywords` the pre-fix contract declared and older
#     generated clients still send — accepted, never republished, since a request
#     body on a GET is the defect being fixed.
#   api/main.py 1499 -> 1558. fix(#1518 codex P2): +59 for
#     `_document_unresolvable_credential_401`, which publishes the 401 that
#     #1518 made normal runtime behaviour on every credential-aware anonymous
#     operation. Most of it is the docstring explaining why it targets all
#     THREE optional dependencies while `_normalize_security_contract` targets
#     two: a 401 RESPONSE is not a security REQUIREMENT, so the no-security-
#     schema STAC operations must gain the status without gaining the auth
#     markers #430 removed.
#   api/main.py 1558 -> 1573. fix(#1518 codex P2 round 4): +15 of `info.description`
#     prose. The docs promised a 401 for every unresolvable credential while the
#     capability lanes deliberately serve one, so the published contract was
#     wrong about behaviour that is right. It states the three exceptions
#     instead: logout, a capability that authorized on its own, and a shared-map
#     link that no credential could have opened.
#   tiles/router.py 2557 -> 2590. fix(#1518 codex P2 round 4): +33 for
#     `_resolve_dataset_meta_for_serving`, which routes the vector tile lookup's
#     404 through `capability_declined`, and for moving the clusterable gate
#     below authorization. Both ran BEFORE `_authorize_vector_tile_request` —
#     the tile URL carries a table NAME, so the id the capability needs does not
#     exist until the lookup returns — and both answered a resource code to a
#     caller whose credential was dead, while the raster route already answered
#     401 for the same request shape.
#   tiles/router.py 2528 -> 2557. fix(#1518 codex P2 round 3): +29 for routing
#     every capability DECLINE through `capability_declined` instead of a bare
#     raise, plus wrapping the raster meta lookup. The rule had been applied at
#     one exit point per handler while each has several no-capability paths, so
#     an invalid embed token and a missing signed template both answered 403
#     with the credential rule never running. Going through the helper makes the
#     ordering structural rather than positional, which is also what lets
#     test_capability_declines_route_through_the_helper check it statically.
#   tiles/router.py 2505 -> 2528. fix(#1518 codex P2): +23 for the post-loop
#     capability pass in the batch token handler. The flag it replaces was only
#     set on the fallback arm, so a batch of PUBLIC datasets never consulted the
#     embed token at all and a valid capability was rejected. The pass runs only
#     when nothing has already established the capability and stops at the first
#     covered id, so it costs one cached validation on exactly the requests that
#     need it and nothing on the ones that sent no token.
#   tiles/router.py 2468 -> 2505. fix(#1518): +37 for the CAPABILITY obligation.
#     `_authorize_vector_tile_request` and `_resolve_raster_access` are the two
#     centralised decision points for the six tile handlers, so the rule is
#     applied there rather than six times; most of the cost is re-indenting the
#     raster auth arms under an explicit `else` so the control flow SHOWS that
#     the rule fires only when neither capability authorized, instead of leaving
#     a reader to infer it from an elif chain. The rest is the batch handler's
#     post-loop application, which cannot be hoisted because the embed token
#     authorizes a scope and the loop is what resolves it.
#   tiles/router.py 2341 -> 2468. fix(#1451): +127 for `_assert_dataset_still_registered`
#     and its single call site in `_acquire_and_serve_tile`. GH-1443 closed the
#     half a caller could reach; direct DDL on the `data` schema can still put a
#     relation under a deleted dataset's name, and the schema-wide default
#     privilege makes it readable by the tile role with no grant of its own. The
#     cached authorization is what would carry it, and the #1441 eviction is
#     process-local, so the catalog gets asked once per tile the pool actually has
#     to build — never on a cache hit, which is the round-trip _dataset_cache
#     exists to avoid. Most of the lines are the docstring recording why the check
#     sits on the pool path and not in _resolve_dataset_meta, since that placement
#     is the whole difference between this and the option #1451 ruled out. The
#     codex rounds added the placement itself, which took four and is now the bulk
#     of the lines. The check sits in each endpoint on the first line past the
#     byte-cache short-circuit: earlier and the hot path pays for it, later and it
#     is below the COLD-02 seam (which would wake storage for a deleted dataset)
#     and below the three bounded resources a tile request takes in order — an
#     API-pool connection, a FAIR-01 permit, a tile-pool connection — where every
#     position inverts a pair against a metadata-cache miss and stalls both paths.
#     Every rejected position is recorded in the docstring, since re-deriving them
#     is what the four rounds were.
#   tiles/router.py 2329 -> 2341. fix(#1444): +12 of comment, no code. Both
#     docstrings that GH-1429 left stating "a freed table name is immediately
#     redrawable" as a live precondition now say GH-1443 removed it, and each
#     says why its own mechanism stays anyway (the eviction buys freshness; the
#     generation key is what keeps a name safe independently of how names are
#     generated). Leaving them was the worse option — a reader who trusts a
#     stale precondition unwinds the wrong defence.
_MODULE_LOC_CAPS: dict[str, int] = {
    # fix(#1814): first entry. The lines bought the reserve/stage/bind split of
    # one create-and-queue function, its two fenced settlement exits, the quota
    # preflight, the staging deadline, and the reset-and-retry settlement.
    # fix(#1888): +16. The staged-entry settlement reads the row's status on
    # its own transaction and reaps the staged copy once a committed attempt
    # left the row failed, best effort. Cap 1130 -> 1146, exact.
    "backend/app/processing/ingest/manifest_service.py": 1146,
    # fix(#1770 round 43 P1): crossed _RATCHET_INCLUSION_LOC on the XML
    # streaming preflight (`_xml_preflight`, `MAX_DOCUMENT_ATTRIBUTES`,
    # `MAX_DOCUMENT_DEPTH`) that closes the attribute-bomb/deep-nesting-bomb/
    # text-bomb class `structural_elements`'s per-element byte-scan could not
    # see -- a single tag carrying an enormous number of attributes, or a
    # document nested one element inside another thousands of times over,
    # both stayed under the element budget while costing real memory or
    # real recursion. Most of the added lines are the docstring explaining
    # why the byte-scan stays as a cheap first pass rather than being
    # replaced outright, and why the preflight has to refuse an entity
    # declaration itself (it runs on raw `expat`, before `defusedxml`'s own
    # `forbid_dtd` ever gets a turn).
    # fix(#1770 round 44 P2): +13. `_parsed_json` now also catches
    # `RecursionError` (a JSON depth bomb raises that, not `ValueError`, and
    # was escaping every except chain that named only the latter). Cap
    # 1042 -> 1055, exact.
    # fix(#1770 round 46 P2): +61. `_OGCAPI_OPERATION_RELS` split into
    # `_LANDING_RELS`/`_COLLECTION_RELS`, `_ogcapi_link_hrefs` gained a
    # `rels` parameter, and the four `_check_ogcapi` call sites gained a
    # `# fix` comment each explaining which document type they scope to.
    # Most of the added lines are the docstring tracing which document type
    # dereferences which rel, and why a collections listing page/entry
    # dereference neither. Cap 1055 -> 1116, exact.
    # fix(#1770 round 46b): +29. The pre-trigger audit's four fixes: the
    # module comment correcting which paths actually reach `_COLLECTION_
    # RELS` (none of preview/worker do; only the probe, which never passes
    # a collection), naming the actual structural tests that now guard the
    # rel scoping, and a one-line "deliberate no-op" comment at each of the
    # two `frozenset()` call sites. Cap 1116 -> 1145, exact.
    # fix(#1770 round 47): +113. Three closed classes: `bounded_service_url`/
    # `bounded_parse_qsl`/`MAX_SERVICE_HREF_BYTES`/`MAX_QUERY_FIELDS` (the P1
    # advertised-href/query-field-count bound, wired into `_next_page` and
    # `_assert_same_origin`), `_wfs_operation_hrefs`'s walk made iterative
    # (no depth of its own to exceed) with a `RecursionError` last line of
    # defense in `_check_wfs`, and `MAX_DOCUMENT_DEPTH` lowered 1,000 -> 256
    # with a comment correcting round 43's own claim. Most of the added
    # lines are the docstrings recording why each bound is the number it is.
    # Cap 1145 -> 1258, exact.
    # fix(#1770 round 47b): +52. The pre-trigger audit's P1 (`HrefTooLongError`,
    # a `ValueError` subclass so the length refusal gets its own wording at
    # every catch site with no new except clause required at the ones that
    # don't bother) and the low-priority fixes: a warning on `_next_page`'s
    # silent stop, and a docstring note on `_wfs_operation_hrefs`'s own
    # O(breadth) stack-memory tradeoff. Cap 1258 -> 1310, exact.
    # fix(#1770 round 47c): +6. `_capabilities_url` moved from
    # `max_num_fields=` back to `# parse_qs: unbounded` -- see the
    # function's own docstring for why round 47b's bound here was wrong.
    # Net growth is the corrected, longer docstring. Cap 1310 -> 1316,
    # exact.
    # fix(#1770 rebase audit nit): +1. The marker line sat at exactly 88
    # chars; split the `parse_qs` call onto its own line so the trailing
    # `# parse_qs: unbounded` comment has room. Cap 1316 -> 1317, exact.
    # fix(#1770 rebase audit nit): +2. `_capabilities_url`'s docstring now
    # distinguishes `/probe`'s fresh schema field from preview/the worker's
    # persisted `origin_ref["url"]`, the same fix `adapters/wfs.py::build_
    # capabilities_url`'s docstring already got. Cap 1317 -> 1319, exact.
    # fix(#1770 round 49 P3): +11. Corrected the `_check_ogcapi` listing-walk
    # comment that claimed the probe's own `/collections` pagination is
    # "credential-free exploration" -- it is not; `_check_ogcapi` shares the
    # caller's real `headers`, and the soft stop is safe because `_next_page`
    # itself refuses a cross-origin/unparseable `next`, not because the
    # pages are anonymous. Cap 1319 -> 1330, exact.
    # fix(#1828): +551. `_check_wfs` reads the layer's DescribeFeatureType,
    # built byte for byte as the driver builds it, and refuses a schema
    # `include` off the origin; `require_wfs_layer` at the spawn points. 1881.
    "backend/app/platform/service_endpoints.py": 1881,
    # fix(#1770 round 42): first entry, crossed _RATCHET_INCLUSION_LOC on the
    # completeness-predicate unification. `_page_proves_complete` is the one
    # function round 41's full-walk-only proof and round 42's sampled-preview
    # mirror of it both call now, and `_end_of_chain`/`_sample_truncated` are
    # the extractions that keep `_walk_pages` itself under ruff's C901
    # ceiling rather than adding another exemption (the same reason
    # `_resolve_conformance` was pulled out of `probe_ogcapi` in #1746).
    # Most of the added lines are the docstrings recording the round 38-42
    # history so a future reader does not re-derive it from the diff.
    # fix(#1770 round 44 P2): +8. The items-page JSON parse also catches
    # `RecursionError` now, same reasoning as `service_endpoints.py::
    # _parsed_json`. Cap 1033 -> 1041, exact.
    # fix(#1770 round 47): +49. Two closed classes: every advertised-href
    # site (`_advertised_items_href`/`_with_page_size`/`_next_href`) now
    # runs through `bounded_service_url`/`bounded_parse_qsl`, and
    # `_walk_pages`'s per-feature re-serialisation catches `UnicodeEncode
    # Error` from an unpaired JSON surrogate escape rather than letting it
    # escape as an internal exception. Cap 1041 -> 1090, exact (`ruff
    # format` wrapped one `urljoin(base, bounded_service_url(...))` call
    # onto three lines after the round-47 diff landed).
    # fix(#1770 round 47b): +16. `HrefTooLongError` handling at the three
    # `bounded_service_url` catch sites, each getting its own wording
    # distinct from the generic "unparseable" refusal. Cap 1090 -> 1106,
    # exact.
    "backend/app/platform/service_items.py": 1106,
    # fix(#1758): the ArcGIS sign-in protocol, which crossed 1000 lines over
    # nine review rounds. What the growth bought, in order: the two-phase
    # split that resolves WHERE a password would go before any lock or budget
    # is taken (r7), host canonicalization so two spellings of one destination
    # are one bucket rather than two (r5), the delegate bound that stops a
    # discovery document redirecting the credential to an unrelated host (r9),
    # and the no-redirect rules on both the discovery GET and the credential
    # POST (r4, r9). Roughly a third of the file is the comments explaining
    # those, which is deliberate: every one of them is a security property a
    # future reader would otherwise "simplify" away.
    #
    # Kept as one module because it is one protocol and the phases share the
    # error vocabulary. The clean split when it next grows is the host cluster
    # (_numeric_ipv4, canonical_host, canonical_portal_host, portal_host,
    # _is_trusted_delegate), which would need to raise ValueError and let this
    # module map it, since ArcGISSignInError lives here.
    # fix(#1758 codex r10/r11): +62 lines. The two-phase split gained a per-phase
    # deadline so the caller's ledger insert and audit commit sit outside any
    # cancellation scope, and the identity the limits key on became the
    # token service's authority AND web-adaptor path, because two Enterprise
    # portals can share a hostname and be separate account stores.
    # fix(#1758 codex r12-r17): +149 lines. One httpx.URL is now the single normalized
    # form the scope, the delegate check and the POST destination all read,
    # because urlsplit kept dot segments that httpx removes, and a URL that
    # still argues with itself after normalization is refused rather than
    # repaired, and every URL in the module now takes that one road. r14
    # added the decompression-bomb refusal: identity encoding asked for, raw
    # transport bytes capped, a compressed answer refused unread. r15 refused
    # port zero, which is falsey and so aliased the real :443 budget. r16
    # made a redirect the SSRF hook rejects during DISCOVERY fall back rather
    # than refuse, since the hook fires on every 3xx whether or not it is
    # followed. r17 decodes to a fixed point instead of for four passes, and
    # refuses a stable form still carrying an encoded separator.
    # fix(#1775): +40. `signin_user_key`, the keyed digest that carries the
    # per-caller budget now that it is counted from the ledger rather than
    # from audit_logs (reserve-then-settle commits the attempt before the
    # credential POST and writes the audit row after it, so a cancelled
    # request leaves no audit row to count), and AUDIT_CANCELLED, the outcome
    # of an attempt whose POST was interrupted. Cap 1253 -> 1293, exact.
    # fix(#1775 audit): +8. AUDIT_CANCELLED's comment now says which external
    # cancellation actually reaches the route and which does not — a worker
    # shutdown does, a client disconnect does not, because it arrives as an
    # `http.disconnect` message a non-streaming route never reads and the one
    # `cancel()` in BaseHTTPMiddleware ends a sibling wait rather than the
    # downstream coroutine — and why the reservation makes the path safe
    # whichever it is. An earlier revision of this comment asserted the
    # opposite, which is why it now cites the line it was checked against.
    # Cap 1293 -> 1301, exact.
    # fix(#1858): +11. The capped read's JSON parse also catches
    # `RecursionError` now (a depth bomb fits inside `_MAX_RESPONSE_BYTES`,
    # and the decoder gives up on a stack overflow rather than a
    # `ValueError`), with the arithmetic recorded so nobody re-derives which
    # of the two bounds actually holds. A duplicated, unreachable copy of the
    # same try/except is deleted in the same edit, which is why the net is
    # smaller than the comment. Cap 1301 -> 1312, exact.
    "backend/app/modules/catalog/sources/arcgis_signin.py": 1312,
    # feat(C2) / fix(#1840): crossed _RATCHET_INCLUSION_LOC when the ArcGIS
    # credential moved out of the request URL and into a header. What the
    # growth bought, in one list: the version gate Esri's own `currentVersion`
    # spelling needs (`parse_arcgis_current_version`, where 10.5.1 reports as
    # `10.51` and a float comparison gets two releases the wrong way round),
    # the one transport chooser (`arcgis_request_auth`) so no read decides for
    # itself where the credential goes, one bounded reader
    # (`read_arcgis_json`) with the two query-form fallbacks a real deployment
    # needs -- a pre-10.5.1 server's 499 envelope and a Web Adaptor's 401/403
    # before ArcGIS is ever reached -- plus `build_arcgis_layer_info_url` and
    # the fold of the third hand-rolled count query into
    # `build_arcgis_count_query_url` (#1755 item 14). Most of the added lines
    # are the comments carrying the measurements those decisions rest on;
    # without them the next reader re-derives the Esri version encoding and
    # the web-tier case from scratch. Cap set at 1015, exact.
    # fix(#1858): +33. `_arcgis_parsed_json` is the one place both of this
    # module's remote-body parses go through, so a JSON depth bomb becomes
    # the `EndpointCheckFailedError` every caller already handles instead of
    # a `RecursionError` no caller catches. Most of the lines are the
    # docstring recording why `ValueError` is deliberately left alone.
    # Cap 1015 -> 1048, exact.
    # fix(#1858 audit P2-2): +26. Comments only. Four best-effort clauses
    # here catch `ValueError` and therefore `SSRFError`, and each now says
    # why a refused hop stays a degrade rather than being raised: the read
    # establishes one optional fact and the adapter answers without it. The
    # rule and its converse are stated once at `_fetch_count` and referred to
    # from the other three. Cap 1048 -> 1074, exact.
    "backend/app/modules/catalog/sources/adapters/arcgis.py": 1074,
    # feat(#1746 B2b): first explicit entry for this file, which rode the 1500
    # default until the service-auth wave. #1758 added the ArcGIS sign-in
    # endpoint and its rate-limit wiring, and this lane added the credential
    # conversion at the probe and preview doors, the CRS fallback's own
    # credential handling, and the cross-origin endpoint check after detection
    # (review r13). Ratcheted rather than decomposed because the split that
    # pays here is connector-versus-service, which is #1755 item 13's queue
    # and bigger than any one lane. Cap 1500 -> 1528, exact.
    # fix(#1746 B2b review r14): +33. `_probe_credential_line` composes the
    # line the endpoint check sends, bound to the format detection just
    # established, because reading a protected service's description
    # anonymously learned nothing and approved it. The rest is the second
    # refusal code on the same handler and the note on why the log line reads
    # `origin` defensively. Cap 1528 -> 1561, exact.
    # fix(#1746 B2b review r24): +9. `/probe` passes a monotonic deadline to
    # the endpoint check. It had omitted one, so the check ran unbounded and a
    # description delivered slowly but steadily across up to twenty listing
    # pages held an API request open for as long as the service liked.
    # fix(#1746 B2b review r27): +9. The door no longer decides from the URL
    # text whether a credential's method can be carried; it binds by method
    # alone and `service_carries_method` answers the transport question after
    # detection. The lines are the comment recording why reading the URL there
    # was wrong, since `/FeatureServer/wfs` is a WFS and the door had refused
    # it a credential it supports.
    # fix(#1770 round 40 P2): +4. The credentialed CRS fallback fetch's
    # `error=str(exc)` becomes `error=redact_exception_text(exc)`, plus the
    # new import. Cap 1579 -> 1583, exact.
    # fix(#1770 round 43 P1): +28. `_fetch_ogcapi_collection_srid` now reads
    # through `bounded_probe_read` under `DEFAULT_CHECK_TIMEOUT` instead of a
    # bare `client.get`, the same shape round 41 already gave the four probe
    # adapters -- new imports (`json`, `urlencode`, `bounded_probe_read`,
    # `OGC_JSON_ACCEPT`), the query folded into the URL since the helper
    # takes no `params=`, the `asyncio.timeout` wrapper, and a widened except
    # clause plus its comment. Cap 1583 -> 1611, exact.
    # fix(#1770 round 44 P1/P2): +18. The ArcGIS layer-preview except clause
    # widened for `EndpointCheckFailedError`/`TimeoutError` (P1, ArcGIS
    # reads now bounded), the CRS-fallback except clause gained
    # `RecursionError` (P2, JSON depth bomb), plus their comments. Cap
    # 1611 -> 1629, exact.
    # fix(#1770 rebase onto main, post-#1820/#1821): re-pinned by direct
    # `wc -l` measurement of the post-rebase file, not arithmetic on either
    # side's number. #1820 (merged first) removed 28 lines from this file
    # reserving the ArcGIS sign-in attempt before the mint; this lane's own
    # rounds 45 through 47c added lines back on top through the normal
    # ArcGIS-bound/non-dict-guard/conformance-seed fixes. Net: 1629 -> 1625,
    # exact.
    # fix(#1770 round 49 P3): +14. The mid-probe `SSRFError` handler no
    # longer reflects `SSRFResolutionError`'s interpolated redirect-target
    # hostname into the 400 body or the persisted audit reason -- both now
    # carry a fixed policy string; the raw text stays in the server-side log
    # line only. Cap 1625 -> 1639, exact.
    # fix(#1755 item 9): +141. `_preview_refusal_response` and
    # `_run_service_preview_or_refuse` map every typed refusal
    # `run_service_preview` and its callees can raise to a coded 4xx before
    # `preview_service_layer`'s broad `except Exception`, so a future edit
    # that breaks one of those callees' "raises only HTTPException" contracts
    # degrades to a coded 4xx instead of a 500. Cap 1639 -> 1780, exact.
    # fix(#1840 audit round 1): +11. `_probe_credential_line` gates on
    # `requires_header_token_policy` rather than on `build_credential_header`
    # answering None, plus the import and the docstring paragraph saying why
    # the two stopped being equivalent when lane C2 taught the builder to
    # compose an ArcGIS header for the httpx transport. Cap 1780 -> 1791,
    # exact.
    # fix(#1858 audit P2-1): +40. `_refuse_preview` is extracted from
    # `_run_service_preview_or_refuse` so the ArcGIS preview branch, which
    # never went through that function, answers a refused redirect hop the
    # way the WFS and OGC API branches of the same door already do, instead
    # of reporting `ogrinfo_failed` for a tool that never ran. The extraction
    # is net-neutral; the lines are the helper's own docstring and the new
    # clause's comment. Cap 1791 -> 1831, exact.
    # fix(#1848): +18. Both doors hand the pooled connection back before their
    # network work, which costs the release itself, its comment and the
    # `user_id` local the rollback's expiry makes necessary. Codex round 1
    # moved each release above `validate_url_for_ssrf`, whose `getaddrinfo`
    # wait is the first of the two waits, and the preview needs a second
    # release because its duplicate-source query re-acquires in between.
    # Cap 1831 -> 1849, exact.
    # fix(#1825): +52. A cancellation clause on both settlement writes, and
    # the reservation id threaded to all three finaliser call sites.
    # Cap 1849 -> 1901, exact.
    "backend/app/modules/catalog/sources/router.py": 1901,
    # fix(#998): the DDL ported from migration 0019 so tenant-ownership adoption
    # is reachable forward-only at head. Almost all of it is SQL text, and it is
    # one artifact on purpose — the module is reviewed line-by-line against
    # 0019_tenant_provisioning_boundary.py, which splitting the blocks across
    # files would make harder, not easier. The Python that drives it and the
    # report types already live in tenant_adoption.py and
    # tenant_adoption_report.py.
    # fix(#998 codex r44/r45): +200 — refuse creator-shaped memberships
    # retained by other logins (an ADMIN-only edge can re-arm itself), refuse
    # boundary-function and provisioner grant-option ACL entries a foreign
    # grantor issued (unrevokable by the repair, which would otherwise
    # silently no-op every run), count foreign grantors in the early-return
    # guard so canonical-but-foreign tenants reach the refusal, and render
    # the default-privilege remedy one statement per object kind.
    # fix(#998 codex r46-r49): +268 — extended statistics and collations transferred, the six rarer owned kinds refused, so no owned object kind in a tenant schema is unhandled — generated multiranges excluded on all
    # three type surfaces; schema-less default privileges counted in the
    # fast-path guard and refused cluster-wide for the provisioner (the
    # per-tenant pass never runs with zero tenants).
    "backend/app/core/db/tenant_adoption_sql.py": 2102,
    # fix(#998): the tool the DDL above serves — the catalog reads that decide
    # whether anything is left to do, the steps that close the gap, and the
    # operator CLI. Already decomposed three ways (report types and the success
    # predicate in tenant_adoption_report.py, the ported DDL in
    # tenant_adoption_sql.py); the remainder is one read per object the adoption
    # boundary covers, and each is a single SQL statement that has to see the
    # whole object at once.
    # fix(#998 codex r45-r49): +130 — read side mirrors every apply-side ownership surface — run the provisioner grant-option guard
    # before the plain revokes it protects; mirror the multirange and
    # schema-less default-privilege refusals on the read side so the dry run
    # cannot call adopted what --apply stops on.
    "backend/app/core/db/tenant_adoption.py": 1303,
    # fix(#836): the five path-gated additions. Caps are exact (zero headroom),
    # matching the #435 convention: growth needs a reviewed carve-out here,
    # shrinking must lower the cap in the same commit.
    # fix(#1240, #651): +4 — import shutdown_worker_metrics and call it in the
    # lifespan shutdown block so a recycled uvicorn worker drops its
    # prometheus_client multiprocess mmap files instead of leaving a stale
    # series for the next scrape to keep summing. Cap 1292 -> 1296, exact.
    # fix(#1240, #651 review round 2): +9 — start/cancel metrics_sweep_task
    # (sweep_dead_worker_metrics) alongside the existing pool/memory
    # background tasks, so an OOM-killed/SIGKILLed worker's multiprocess
    # gauge files get reaped even though its own graceful shutdown hook
    # never ran. Cap 1296 -> 1305, exact.
    # feat(#1268): +8 — start and cancel the refresh-metrics loop beside the
    # existing pool/memory/sweep tasks. Half the lines are the comment saying
    # why the refresh lifecycle is observed in the API at all when the worker
    # is what executes it: the worker serves no /metrics endpoint, so a
    # counter incremented there is written to a file nothing reads.
    # Cap 1305 -> 1313, exact.
    # fix(#1277 review round 2): +24 — the stale-jobs sweeper also re-arms
    # refresh credentials whose task is still queued. Round 1 tried to bound
    # the credential lifetime with a constant derived from JOB_TIMEOUT_SECONDS;
    # the heartbeat means no constant bounds a healthy long import, so the
    # bound is now renewal and this loop is what drives it. Most of the lines
    # are the comment explaining why the interval constant is imported from the
    # credential module (the TTL arithmetic depends on it, so there is one of
    # it) and why the renewal needs no try of its own. Cap 1313 -> 1337, exact.
    # fix(#1277 review round 3): the tenant-scoped renewal landed here first.
    # fix(#1277 review round 4): -58 — and moved straight back out to
    # platform/refresh/credentials.py, because the worker has to host the same
    # renewal and cannot import the API app module. main.py is a thin caller
    # again, so the cap drops below where round 3 left it.
    # Cap 1390 -> 1332, exact.
    # fix(#1315): -2 — init_tile_cache() and its import move into the shared
    # bootstrap(). The lifespan owning a second copy is how the API and the
    # worker ended up with different tile-cache states in the first place.
    # Cap 1332 -> 1330, exact.
    # +20 — the periodic _stale_jobs_sweeper loop now also sweeps exports/ on
    # every cycle, not just once at boot: export residue from a hard process
    # death (SIGKILL, OOM) used to sit until the next restart. The sweep +
    # conditional log live in a small top-level _sweep_orphaned_exports_and_log
    # helper (with the Path import it needs) rather than inline in the loop,
    # so the extra branch does not push lifespan's McCabe complexity past its
    # gate. Cap 1330 -> 1350, exact.
    # fix(#1435 codex round 1): +12 — the periodic sweep runs continuously
    # rather than only at a restart, so it needs a wider age threshold than
    # the boot-time callers (a directory's mtime does not advance while
    # ogr2ogr keeps writing the file inside it or a client keeps streaming it
    # out) — otherwise any export whose total lifetime exceeds 1 hour gets
    # deleted out from under it on the next 5-minute cycle, guaranteed.
    # Cap 1350 -> 1362, exact.
    # fix(#1435 codex round 5): +24 — sweep_orphaned_exports does synchronous
    # directory traversal + shutil.rmtree; unlike the boot-time callers,
    # which run before the event loop serves traffic, the periodic caller
    # runs on a live server every few minutes and was calling it inline,
    # stalling request handling for the duration. Now runs via
    # run_in_thread_draining through a small positional-only wrapper
    # (age_threshold_seconds is keyword-only on sweep_orphaned_exports, and
    # the helper only forwards *args). Cap 1362 -> 1386, exact.
    # +3 — one-line comment at the periodic call site stating why the two
    # boot-time callers deliberately stay synchronous, so a future review
    # round reads the asymmetry as intentional rather than a missed sibling.
    # Cap 1386 -> 1389, exact.
    # fix(#1470): +77 — _register_standards_head_routes, the derived-route pass
    # that makes HEAD answer wherever the CORS preflight advertises it, and
    # _clone_api_route, the ~25-kwarg route copy it now shares with
    # _add_trailing_slash_aliases (which previously spelled that list inline).
    # HEAD was 405 on all 48 standards GET routes; deriving both surfaces from
    # standards_api_path is what stops them drifting again, and is why this is
    # one pass here rather than 48 decorator edits across five routers.
    # Cap 1389 -> 1466, exact.
    # fix(#1485): +4 — the boot-time setup_logging() call gains
    # production=settings.is_production, which selects the plain traceback
    # formatter so an exception cannot pin the event loop rendering frame
    # locals with rich. Over 88 columns as one line, hence four.
    # Cap 1466 -> 1470, exact.
    # fix(#1518): +29 — 23 lines of API description telling a client what a
    # rejected credential does, and 6 in _normalize_security_contract for the
    # second optional-identity dependency. The description is the only in-repo
    # home for that contract (it is `info.description` in the committed
    # openapi.json and the rendered /docs page), and the answer could not be
    # written down before #1518 because it depended on which router you hit.
    # Cap 1470 -> 1499, exact.
    # fix(#1540 review P2): +20 — image/tiff joins starlette's default gzip
    # exclusions, and the comment says why it is a correctness fix rather than a
    # CPU one: the middleware compresses a 200 and skips a 206, so one strong
    # ETag named gzip bytes on the full download and raw bytes on every range,
    # and a client resuming the encoded representation could splice raw bytes at
    # encoded offsets. Cap 1573 -> 1593, exact.
    # fix(#1532 review r7): +15 — the periodic staging sweeper also reclaims
    # atomic-write scratch files now. `LocalStorageProvider.put` writes through
    # `<name>.<hex>.tmp` and renames, so a process killed mid-write leaves one
    # under whatever prefix it was writing: COGs, originals, VRTs, map assets.
    # This sweeper is the right home because it already walks the staging tree
    # on a schedule and needs no `init_storage`, unlike anything storage-backed.
    # Cap 1593 -> 1608, exact.
    # fix(#1532 review r9): +14 — the export route stops being gzipped. #1532
    # made it sliceable under a strong ETag naming the RAW bytes, so a
    # compressed 200 beside a raw 206 is the splice fix(#1540) already closed
    # for COGs.
    # fix(#1532 review r11): +4 net. That exclusion was by MEDIA TYPE, which
    # also silenced compression on feature GeoJSON and the admin and audit CSV
    # streams — endpoints that serve one representation and never a range, so it
    # bought no safety and cost real bandwidth. It is scoped to the export PATH
    # now, through a middleware in its own module; `image/tiff` stays a
    # media-type exclusion because there the type and the route are the same
    # set. Cap 1622 -> 1626, exact.
    # fix(#1532 review r14): +2 — the scratch reclaimer now rides this loop's
    # 300 s cadence but keeps its own, so a replica walks the whole staging root
    # once per horizon instead of every five minutes. Two lines of docstring say
    # why the two passes on this line differ; the guard itself lives beside the
    # function it guards, in staging.py. Cap 1626 -> 1628, exact.
    # fix(#1596): +7 of comment, no code. The anonymous CORS wildcard now has a
    # second surface (catalog search), which the derived-HEAD pass keyed on
    # standards_api_path does not cover. Five lines in that function's docstring
    # say the omission is deliberate and why it does not reopen #1470 — the
    # middleware advertises GET, OPTIONS there, so nothing promises a HEAD no
    # route registers. The other two widen the production CORS warning, which
    # told an operator only standards reads were open to any browser origin.
    # Cap 1628 -> 1635, exact.
    # fix(#1746): +13 — the boot-time and periodic sweeps now also call
    # sweep_stale_gdal_header_files, reclaiming the GDAL bearer-header
    # tempfile ogr.py's finally block misses on a SIGKILL/OOM. Cap 1757 ->
    # 1770, exact.
    # fix(#1746 codex r1): +19 — `sweep_stale_jobs_once` runs the terminal-row
    # token purge ONCE per pass, in its own bare session with its own
    # best-effort handler, instead of once per tenant inside the loop below.
    # Mostly the comment recording why the queue table is not a tenant's.
    # Re-measured on the rebase across #1751, which raised the same cap.
    # Cap 1770 -> 1789, exact.
    # fix(#1746 codex r2): +7 — both of those sweeps now default to the
    # container tmpfs rather than taking the staging volume. The lines are the
    # comments recording why: staging is persistent and backup-entrypoint.sh
    # tars it every cycle, so a crash-orphaned Authorization header there can
    # reach a backup, while /tmp is a per-container 512m tmpfs. Re-baselined on
    # the rebase across #1753, which raised the same cap for the token purge.
    # Cap 1789 -> 1796, exact.
    # fix(#1770 round 44 P2): +14. `CredentialScrubASGIMiddleware` registered
    # as the innermost middleware, plus the import and the comment on why it
    # has to be registered first and be a plain ASGI callable. Cap
    # 1883 -> 1897, exact.
    # fix(#1845): +6. The published description of the deprecated `?api_key=`
    # lane now states the read-only restriction the resolver enforces, in both
    # places a client reads it: the auth section of the API description and
    # the ApiKeyQuery security scheme. Cap 1897 -> 1903, exact.
    # fix(#1856 item 2): +9 for the conformance list in the API description.
    # It claimed the OAS 3.0 classes while the served document is OpenAPI 3.1,
    # and named three of the five families /api/conformance advertises. Cap
    # 1903 -> 1912, exact.
    # fix(#1847): the lock order, its gate and its 409 mapping. Cap 1962, exact.
    # fix(#1847): the handler docstring states its contract. Cap 1962 -> 1959.
    "backend/app/api/main.py": 1959,
    # fix(#1005): +4 — MapSummaryResponse gains thumbnail_updated_at, the
    # thumbnail cache version split out of updated_at. Ratchet stays exact.
    # fix(#910): +1 on top of that, the fillColorSaved entry in the authoritative
    # builder camelCase->snake_case table.
    # fix(#1069): +62 — the write-time shape check on `paint`/`layout`. Those
    # fields were bounded by serialized size alone, so `{"fill-pattern":
    # {"stops": 1}}` persisted and waited to raise inside whatever serializer
    # next descended into it. Only `stops` is checked, because it is the one
    # shape checkable without a per-property paint table (per-property
    # validation is the raster paint-key-allowlist problem, tracked separately).
    # Most of the lines are the docstring recording that scope decision and why
    # `style_config` is deliberately excluded — the builder writes its own
    # `stops` there in a different shape, so checking it would 422 every
    # line-gradient save. Ratchet stays exact.
    # fix(#1109 review): -10 — the nested-dict walker is gone; the check reads
    # direct property values only, because a `stops` key inside an expression
    # operand is data, not a legacy function. Cap 1379 -> 1369, still exact.
    # feat(#1472): +8 — dataset_attribution on the three layer read models
    # (DatasetMetaKwargs, MapLayerResponse, SharedLayerResponse) plus the notes
    # recording that the shared/embed response carries it deliberately: that is
    # the surface a source's display obligation most needs to reach, because it
    # is the one shown to people outside the instance. Cap 1369 -> 1377, exact.
    # fix(#1672): +19 — MapSpriteEntry model and the sprite union
    # (str | list[MapSpriteEntry]), so exported styles (which always emit the
    # array form) round-trip through /maps/import instead of 422ing.
    # Cap 1377 -> 1396, exact.
    # fix(#1778): +28 — `filter` picks up the byte cap the other open JSONB
    # columns carry. The byte check moved into `_reject_oversize_json` so the
    # dict and list callers share one policy, and `_validate_filter_field`
    # records the ordering that matters: the grammar validator carries the
    # nesting bound and has to run first, because `json.dumps` recurses and a
    # RecursionError is not something Pydantic turns into a 422.
    # Cap 1396 -> 1424, exact.
    # fix(#1778): +27 — the style-import door picks up `max_length=
    # _MAX_LAYERS_PER_MAP` like its three siblings, with the comment saying
    # what its absence cost (an over-cap imported map that apply_layer_diff
    # then refused to save), and MapStyleImportSummary gains add_warning plus
    # the truncation counter, because one warning per unmatched source over an
    # unbounded `sources` object put the whole list in the 201 response.
    # Cap 1424 -> 1451, exact.
    # fix(#1778 round 1): +14 — _MAX_STYLE_DOCUMENT_LAYERS replaces the per-map
    # cap on the raw `layers` array, which counted the companions an export
    # emits and so refused valid GeoLens documents from about 50 polygons up.
    # The lines are the derivation: four style layers per logical layer, worst
    # case, measured, times the per-map cap, plus headroom for the layers an
    # import skips. Cap 1451 -> 1465, exact.
    "backend/app/modules/catalog/maps/schemas.py": 1465,
    # fix(#1042): decomposed. The file reached 2151 lines with five carve-outs
    # on this cap, each one a correctness fix that had to argue for its lines:
    # #888 (+117, shift a 0..360 source instead of clipping it, plus the clip
    # accounting), #899 codex r1 (+23, the angular-unit half of that guard —
    # 14 stock SRIDs are GEOGCS in grads, where -360 is not a whole turn),
    # #906 (+83, the degenerate-envelope guard: 4415 of 8500 stock SRIDs
    # collapse the safe envelope under ST_Transform and the clip then emptied
    # the table silently), #934 (+52, the seam-aware extent-producer override),
    # #961 review (+29, the anchor on `_GEOGRAPHIC_SRTEXT_RE` documented as
    # load-bearing), and then #1104/#1113's eight rounds (+124, the
    # geom_4326-is-always-linear invariant and its BYO-column enforcement).
    # #958 named the pattern — the ratchet taxing correctness work on a module
    # nobody had time to split — and filed #1042 to split it.
    #
    # Every one of those clusters now has its own file, so the next carve-out
    # argues against a few hundred lines instead of two thousand:
    # metadata_sql (60), metadata_quality (190), metadata_projection (266),
    # metadata_attributes (352), metadata_mercator (361), metadata_geometry
    # (424), metadata_extent (633). None is near the 1000-line inclusion
    # threshold, so none needs an entry here yet. What is left below is the
    # re-export façade every existing importer and mock.patch target resolves
    # against. Cap 2151 -> 144, exact.
    # fix(#1738): +10 — the re-exports the repair path resolves against
    # (rederive_geom_4326, the Geom4326Repair it returns, and its three
    # outcome constants) plus their __all__ entries. Cap 144 -> 154, exact.
    # fix(#1738 round 1): +4 — probe_geom_4326 and the Geom4326State it
    # returns, split out so the caller can tell a non-spatial table from a
    # repairable one BEFORE resolving the SRID. Cap 154 -> 158, exact.
    "backend/app/processing/ingest/metadata.py": 158,
    # ingest/router.py is also scanned by the router-glob gate; this exact
    # ratchet overrides its 1500 default so the remaining runway to the cliff
    # cannot be spent silently.
    # fix(#1186): -20 — _stamp_raster_metadata gave up its download-and-
    # validate half. It exists to set the `file_type` discriminator, and
    # bundling a full-object CRS download into that is what kept
    # complete_presigned_upload from calling it at all. `crs_missing` is
    # derived in ingest_raster now, from metadata that task already reads.
    # Cap 1493 -> 1473, still exact.
    # fix(#1202): +74 — _validate_presigned_content, so the presigned door
    # enforces the same content contract as the direct one. Most of it is the
    # docstring recording WHICH bytes the probe carries and why that is
    # faithful: the header window the magic-byte branch reads, plus the
    # trailing PAR1 magic for .parquet. That reasoning is the load-bearing
    # part — a check added to validate_file_content that reads the middle of a
    # file would pass vacuously here. Cap 1473 -> 1547, exact.
    # fix(#1202 review): +62 — freeze-first. Validating the staging key was a
    # TOCTOU: the client keeps a working presigned PUT URL for it until expiry,
    # so checked bytes could be swapped for garbage before preview read them.
    # Completion now snapshots to a key no presign endpoint ever issued a URL
    # for and judges THAT (_frozen_staging_key plus the copy/verify/validate
    # ordering). The lines are mostly the two comments recording why the ORDER
    # is the fix and which object each failure branch may delete — get either
    # wrong and the race is back with the guard still apparently in place.
    # Cap 1547 -> 1609, exact.
    # fix(#1202 review r2): +45 — three findings, all the same shape as the
    # first two rounds (client-writable state re-entering after a check).
    # One-shot completion keyed off `file_path`; a pre-copy size fast path so
    # an oversize object is not copied just to be rejected; and draining the
    # freeze copy so a disconnect cannot abandon the SDK thread mid-write.
    # The comments carry which of the three is the security boundary (only
    # the post-copy verify) — deleting the wrong one reads as a cleanup.
    # Cap 1609 -> 1654, exact.
    # fix(#1202 review r3): +18 — both findings were "the failure path leaves
    # state the retry path cannot proceed from". Multipart assembly is skipped
    # when the staging object already exists (for S3 that is an iff for
    # CompleteMultipartUpload having succeeded, so a retry no longer presents a
    # spent upload id), and the staging delete moved after the commit so a
    # rolled-back commit does not strand the retry with the bytes gone. Both
    # comments carry the invariant, not the mechanic. Cap 1654 -> 1672, exact.
    # fix(#1202 review r5): +26 — the one-shot guard was an UNLOCKED read, so
    # two overlapping completions both passed it and raced over the same
    # deterministic frozen key, letting the loser's refusal delete state the
    # winner had already accepted. Completion now re-fetches the row FOR
    # UPDATE before reading anything the guard depends on. The rest is the
    # comment explaining why get_job_or_404 deliberately stays unlocked.
    # Cap 1672 -> 1698, exact.
    # fix(#1202 review r5b): +5 — the sweep comment named its reapers and went
    # stale the moment the raster tail was added. It now points at
    # `owned_presigned_staging_key` as the grep-able registry and records that
    # the stale purge is a backstop only (it exempts the newest complete job
    # per dataset). Cap 1698 -> 1703, exact.
    # fix(#1202 review r9): +14 — the locked re-fetch became
    # `lock_presigned_job`, whose docstring records that the property is
    # TWO-part: the SELECT must lock AND the read must be fresh. Without
    # populate_existing the lock serialized without informing, and the r5 test
    # pinned only the first half, which is why the second survived four
    # rounds. Extracting it also stops a test reimplementing the call and
    # passing while the handler diverges. Cap 1703 -> 1717, exact.
    # fix(#1207): -194 — the completion sequence moved to presigned.py so the
    # reupload door could share it. Ratchet DOWN in the same commit, per the
    # no-headroom rule. Cap 1717 -> 1523, exact.
    # fix(#1213 review r3): -8 — the one-shot block became a call to the
    # shared require_completable_presigned_job, which owns both facts.
    # fix(#1233): +7 — the cancel branch no longer deletes the assembled
    # object, and the comment records why: the upload id is already spent, so
    # that object is the only record assembly succeeded and the retry's only
    # way past it.
    # fix(#1235 review r3): +10 — both signing sites anchor their expiration
    # to the job deadline, with the comment recording why the part loop
    # computes it once (later parts inherit the earlier deadline, which is
    # conservative in the right direction).
    # fix(#1235 review r4): +1 — the TTL call moved above the multipart branch
    # so a job with no usable lifetime left is refused before an upload id is
    # ever initiated, which trades two in-branch computations for one hoisted
    # one plus the comment saying why the placement matters.
    # fix(#1235 review r5): +9 — the part loop recomputes the TTL per
    # signature (once-before-the-loop expired later parts PAST the deadline),
    # and the multipart except block re-raises HTTPException so the lifetime
    # refusal survives as a 409 instead of being reported as a storage outage.
    # fix(#1235 review r8): -2 — signing moved behind sign_url_with_deadline,
    # which took the per-site reasoning comments with it into presigned.py.
    # Ratchet DOWN in the same commit, per the no-headroom rule.
    # fix(#1235 review r9): +8 — the single-PUT branch re-raises HTTPException
    # so the in-thread lifetime refusal stays a 409 there too, as it already
    # did on the other three signing paths.
    # fix(#1327): -15 — add_vrt_source/remove_vrt_source stage their intended
    # member set on the VrtGeneration row instead of writing vrt_source_links,
    # so the MAX(position) lookup, both link INSERT/DELETE statements, the
    # separate COUNT(*) and position reads, and the two compensating rollback
    # statements are all gone; the endpoints gained the fix(#1327) notes that
    # say where the member set now lives, kept out of the docstrings because
    # FastAPI publishes those into openapi.json. Ratchet DOWN in the same
    # commit, per the no-headroom rule. Cap 1548 -> 1537, exact.
    # fix(#1327 codex P1): +8 — both staged dispatch sites say why they defer
    # the staged task name rather than the legacy one. Cap 1537 -> 1545, exact.
    # fix(getgeolens.com#86 review): +5 — get_upload_config gained a per-route
    # `responses={403: FORBIDDEN_RESPONSE}` override; it only requires
    # authentication, not the router's write-flavored default. Cap 1545 ->
    # 1550, exact.
    # Collapsed the add/remove VRT-source defer-rollback closures onto the
    # shared make_vrt_regeneration_failed_rollback factory in defer_guard.py
    # instead of hand-rolling the same eight-field revert twice with only
    # comment/statement-order differences between them (-7 net). Landed
    # concurrently with the responses={403:...} addition above; recounted
    # after merge rather than picking either side's number. Cap 1550 ->
    # 1543, exact.
    # fix(#1682 codex r3): +4 — the DB-failure fallback for allowed upload
    # extensions became a function reading settings.allowed_extensions_list
    # instead of an eight-entry literal that had drifted two formats behind.
    # Most of the growth is the docstring recording why a narrower fallback is
    # not a safer one. Cap 1543 -> 1547, exact.
    # feat(#1691): +37 — the check_public_visibility_allowed gate at the five
    # visibility-writing handlers (commit, fan-out, register, bulk register,
    # VRT create), each a local import (PROCESS-02/04) plus one call and the
    # comment saying which surface it closes. Cap 1547 -> 1584, exact.
    # fix(#1709 review r2 P1): +16 — commit_fan_out's terminal transition is
    # a fenced CAS via finalize_fan_out_parent instead of a blind attribute
    # write, keyed on the attempt id captured with the pending check; the
    # all-failed branch no longer writes 'pending' back. The lines are the
    # capture, the call, and the comments recording why the blind writes
    # could overwrite a committed cancel. Cap 1584 -> 1600, exact.
    # fix(#1709 review r5 P1): +17 — the terminal transition moved BEFORE the
    # dispatch loop (claim_fan_out_parent) so it is the mutex for the whole
    # fan-out: a cancel either wins before any child exists or 409s against
    # the terminal parent, closing the fast-child window the round-2
    # post-loop shape left open. The lines are the claim call, its 409
    # rendering, and the comment carrying the two-serialization argument.
    # Cap 1600 -> 1617, exact.
    # feat(#1705): +189 — upload_from_url, the URL variant of POST
    # /ingest/upload. The handler lives here rather than a sibling module
    # because the PROCESS-02/04 burndowns (auth.dependencies, quota.service)
    # may only shrink; the fetch mechanics themselves are in url_fetch.py.
    # The lines are the Rule 2 sequencing — SSRF gate, safe-client fetch,
    # streamed size cap, staged-file sniff — plus the same cleanup-ownership
    # comments the direct upload path carries. #1705 and #1709 both raised
    # this cap from the same 1584 baseline in parallel, so the value is
    # measured off the MERGED file rather than taken from either lane (the
    # two lanes' import-region edits overlap, so the deltas do not simply
    # add). Cap 1617 -> 1808, exact.
    # fix(#1708 codex P1/P2): +40 — the pre-fetch commit that releases the
    # pool connection for the download's lifetime (plus the failed-fetch
    # stamping that replaces the rollback it gave up), the byte-clamp on the
    # override filename, and the codeql[py/path-injection] markers at the
    # staging open/unlink sites. Cap 1775 -> 1815, exact.
    # fix(#1708 codex r2): +86 — the download now rides the RUNNING lease
    # (status='running' + started_at before the pre-fetch commit) so the
    # stale-pending sweep cannot fail an in-progress fetch at a legal 61s
    # pending_job_timeout_seconds; both post-fetch transitions became
    # guarded CAS UPDATEs from 'running' only, with the zero-row case
    # surfaced as a 409; filename derivation moved into _url_import_filename
    # inside the guarded path (urlparse ValueError on malformed authorities
    # was an unhandled 500); _raster_stamped_metadata split out pure so the
    # CAS can persist the same stamp without dirtying the ORM row. Cap
    # 1815 -> 1908, exact.
    # fix(#1708 codex r4): +20 — the SSRF gate moved above the handler's DB
    # work AND the dependency-phase transaction is committed first, so the
    # validator's unbounded getaddrinfo never overlaps a checked-out pool
    # connection (auth deps query on the same request-cached session, so a
    # reorder alone released nothing). Cap 1908 -> 1928, exact.
    # fix(#1708 codex r5): +45 — control characters (NUL/C0/DEL) refused at
    # filename derivation before any job row exists, and the failure path
    # extracted into _settle_failed_url_import so a raising cleanup can
    # never preempt the failure CAS (the stuck-running shape, not just the
    # NUL instance); the post-success unlink went best-effort for the same
    # reason. Cap 1928 -> 1973, exact.
    # fix(#1708 codex r6): +12 — the completion CAS stamps
    # user_metadata.staged_at so stale_pending_clauses restarts the pending
    # review window at staging completion instead of letting the download
    # time eat it. Cap 1973 -> 1985, exact.
    # fix(#1708 codex r7): +84 — the S3-mode completions of both families:
    # the staging put moved into _put_staging_object/_stage_put_bounded (a
    # bounded WAIT with abandonment, since the drained boto3 thread absorbs
    # cancellation and an asyncio.timeout would not bound wall time) with
    # _abandoned_put_reaper deleting a late-landing object, and the byte-
    # quota check moved below the put so the post-stage transaction holds a
    # connection only for quota reads + CAS + commit. Cap 1985 -> 2069,
    # exact.
    # fix(#1708 codex r8): +40 — the stage clock now starts BEFORE the
    # preflight SSRF DNS, which is bounded at the call site with wait_for
    # (the one long operation still outside every deadline), and
    # _stage_put_bounded installs the abandonment reaper on ANY exit that
    # leaves the put task running — including the waiter itself being
    # cancelled mid-wait, which previously escaped before the timeout
    # branch installed it. Cap 2069 -> 2109, exact.
    # fix(#1708 codex r9): +14 — staging-path setup hoisted ABOVE the
    # running-commit (a read-only parent used to raise between the commit
    # and the settlement guard, stranding a running row for the lease), and
    # the INVARIANT comment at the seam: nothing executable may sit between
    # the running-commit and the guarded try. Cap 2109 -> 2123, exact.
    # fix(#1708 codex r10): +45 — _effective_stream_cap: the fetch's byte
    # cap becomes min(instance upload max, caller's remaining core byte
    # quota), refusing at submission when nothing remains and threading a
    # quota-shaped refusal detail through fetch_url_to_path so both cap
    # sites (declared Content-Length and mid-stream count) name the quota
    # when the quota is what is capping. The post-stage byte-charged check
    # stays authoritative. Cap 2123 -> 2168, exact.
    # fix(#1708 codex r11): +73 — the ambiguous-commit reconciliation: the
    # final running->pending commit goes through the _commit_staged_
    # transition seam, and _settle_failed_url_import probes a FRESH session
    # first (_url_import_transition_landed) — when the commit durably landed
    # despite a raised acknowledgement, settlement stands down instead of
    # deleting bytes a live pending row points at. Probe failure errs
    # toward standing down: orphaned bytes are sweepable, deleted catalog
    # data is not. Cap 2168 -> 2241, exact.
    # fix(#1708 codex r12): +54 — the last unbounded operation on the
    # request path, on the failure route that fires when S3 is degraded.
    # An abandoned put raises _StagePutAbandoned, and settlement then skips
    # the synchronous remote delete entirely (the late-put reaper already
    # owns that key, and a delete issued now would race the in-flight
    # upload); every other failure bounds its delete by what remains of the
    # request budget. Cap 2241 -> 2295, exact.
    # fix(#1708 codex r13): +37 — the joint budget became genuinely joint.
    # The fetch's bound is now min(FETCH_MAX_SECONDS, stage_deadline - now)
    # via _remaining_fetch_budget, so time spent by auth, preflight DNS and
    # the config/quota transaction is deducted from it instead of the fetch
    # starting a fresh 480s clock; a budget already under the floor refuses
    # promptly rather than opening a doomed connection. Most of the growth
    # is the INVARIANT comment at the deadline's definition, which a future
    # phase added to this handler inherits. Cap 2295 -> 2332, exact.
    # fix(#1708 codex r14): +68 — the r11 ambiguous-commit probe was scoped
    # to EVERY post-staging failure, so ordinary rejections opened a second
    # session while still holding their own transaction (the r2/r7
    # connection family, reopened by a settlement path that grew) and
    # inherited the probe's deliberate assume-landed default, skipping
    # cleanup. Settlement now rolls back FIRST, and the probe fires only
    # for an exception carrying the marker _commit_staged_transition_
    # guarded stamps. A cancelled put task also reaches its deleter now
    # (task.exception() raises on a cancelled task). Cap 2332 -> 2400,
    # exact.
    # fix(#1708 codex r15): +26 — the landed stand-down deletes the LOCAL
    # copy when the row references an S3 key (nothing downstream can
    # discover a path no row names, so it leaked one file per ambiguous
    # commit) and keeps it when the row references the local file itself.
    # Most of the growth is the comment making that asymmetry read as
    # intent rather than an oversight. Cap 2400 -> 2426, exact.
    # fix(#1708 codex r16): +14 — the INVARIANT comment at the deadline's
    # initialization now states what the joint clock does NOT cover (auth
    # and dependency-phase work run before this handler body; the
    # post-stage transaction runs after the budget), replacing wording
    # that claimed auth time was deducted. A comment describing a
    # protection the code does not implement is the class AGENTS.md calls
    # out, so the correction is the point of the change. Cap 2426 -> 2440,
    # exact.
    # fix(#1708 codex r17): +1 — the stage budget is derived per request
    # from the configured db_pool_timeout (see stage_total_budget_seconds)
    # rather than hardcoded, so raising that operator-settable value
    # shrinks the budget instead of silently breaking the proxy invariant.
    # Cap 2440 -> 2441, exact.
    # fix(#1708 codex r18): +4 — the INVARIANT comment now enumerates the
    # request's THREE pool checkouts (auth, pre-fetch, post-stage) instead
    # of the two r17's derivation assumed, and points at the named constant
    # that carries the count so the arithmetic stays checkable against the
    # code. Cap 2441 -> 2445, exact.
    # fix(#1708 codex r19): +37 — _preflight_dns_budget, so the preflight
    # follows the INVARIANT's own rule (min(own ceiling, remaining)) rather
    # than a bare ceiling. Harmless while the budget is healthy, wrong in
    # the floored regime, where a 1s budget could still spend 30s resolving
    # before anything refused; an exhausted clock now refuses with the
    # budget's message before any job row exists. Cap 2445 -> 2482, exact.
    # fix(#1708 codex r20): +29 — comment only. The running-state commit is
    # deliberately NOT covered by the ambiguous-commit probe, and the
    # reasoning is recorded at the site: nothing is staged yet, the row
    # blocks nothing (checked against every active-job predicate: the
    # backfill unique index, the per-user analysis cap, the manifest
    # in-flight check, the reupload lookup, and quota), and the running
    # lease already owns it. An unexplained asymmetry is what invites the
    # next round, so the trade is written down with its expiry condition.
    # Cap 2482 -> 2511, exact.
    # RECONCILED at the #1708/#1709 merge: both PRs raised this cap in
    # parallel off the same 1584 baseline — #1709 to 1617 (the fan-out
    # parent claim moving before dispatch), #1708 to 2511 (everything
    # above). Neither number survives having both applied, so the cap is
    # measured off the merged file rather than composed from either lane's
    # arithmetic. 2511 + #1709's 33 = 2544, exact.
    # fix(#1708 CodeQL triage): +1 — the codeql[py/path-injection] marker on
    # _cleanup_saved_upload's Path branch. The URL flow reaches that shared
    # helper (from _settle_failed_url_import) with an S3 KEY STRING, which is
    # what made the pre-existing sink alert; the marker records that the Path
    # branch only ever receives a staging-rooted path. Cap 2544 -> 2545, exact.
    # fix(#1708 codex r25): +20 — the floored-budget refusal moved to
    # immediately after the deadline is derived, before preflight DNS and the
    # config/quota transaction. Deliberately the SAME _remaining_fetch_budget
    # call the pre-fetch check makes, so the two can never disagree about what
    # "too small to start" means; most of the lines are the comment recording
    # that the floor promised a PROMPT refusal the ordering did not deliver.
    # Cap 2545 -> 2565, exact.
    # fix(#1746 codex r1): +17 — the header-token check moved ahead of the
    # metadata write in commit_import. The refusal already existed one call
    # deeper, but `service_auth_required` was committed in between and
    # permanently blocks POST /jobs/{id}/retry, so a rejected token left a
    # still-pending job that could never be replayed. Most of the lines are the
    # comment recording that, and why `service_type` is readable before the
    # merge. Cap 2565 -> 2582, exact.
    # feat(#1746 B2b): +20 — `commit_import` converts the structured `auth`
    # object the way the other four doors do, judges it against the job's own
    # service format before the metadata write, and hands the resulting
    # credential to `queue_ingest_job` rather than a bare token. Most of the
    # lines are the comment saying why `auth` joins `token` in the model_dump
    # exclusion: user_metadata is a durable JSONB column and that dump is a
    # whitelist by omission. Cap 2582 -> 2602, exact.
    # fix(#1846, GHSA-hrf5-v3cq-frx5): +14. `preview_file` lets one refusal
    # class past the generic "may be malformed or unsupported" handler: the
    # schema check's message is server-authored, names what was refused and
    # says what to upload instead, and the preview is where a presigned upload
    # first meets a whole-file check. Cap 2602 -> 2616, exact.
    # fix(#1848): +50. `upload_file` commits the job before the spooled body
    # is staged and binds through a guarded UPDATE that stamps `staged_at`; the
    # lines are the guard helper, the two guarded writes and the 409. To 2666.
    "backend/app/processing/ingest/router.py": 2666,
    # fix(#888): +25 — the `mercator_clip` StagingResult field and the
    # `_append_mercator_clip_warning` emitter that keeps the three ingest call
    # sites a single statement each (`reupload_file` is already at the C901
    # complexity ceiling, so the branch cannot live inline). Ratchet stays exact.
    # fix(#1018): +40 — `_ingest_vector_into_staging` has no caller in `app/`;
    # every call site is a test. The added lines say so at the definition and
    # map what it mirrors, because silent drift is what makes a test-only copy
    # dangerous rather than merely unused. fix(#1018 review) corrected that
    # map and cost most of the lines: the staging steps are NOT forked here,
    # they are the real `_run_staging_pipeline` — but production reaches that
    # only on re-upload, while new vector ingest reruns the same eight steps
    # inline in `_finalize_ingest`, so the sequence has three sites. The same
    # correction fixes `_run_staging_pipeline`'s own docstring, which claimed
    # `_ingest_vector_into_staging` was the "new ingests" caller.
    # Ratchet stays exact.
    # fix(#1202 review r5b): +32 — `reap_presigned_staging_object`, the shared
    # sweep. The vector tail had it inline; raster needed the same block, and
    # two copies of a best-effort delete in a PR about doors that drifted
    # would have been the same mistake one level down. Cap 1671 -> 1703, exact.
    # fix(#1207): +4 — the terminal-status guard folded into
    # reap_presigned_staging_object from three identical copies in the task
    # tails, which also kept reupload_file under the complexity ceiling.
    # fix(#1213 review r2): +57 — reap_downloaded_staging_source, extracted
    # from the vector tail so the reupload tail could share it. That block
    # reaps the object the task DOWNLOADED from, which after a presigned
    # completion is the frozen copy; the reupload tail shipped without it.
    # fix(#1213 review r4): +9 — the reaper's guard keyed off the path rewrite,
    # which never happens when the download itself raises, so a terminal
    # failure skipped the sweep. The `staging/` prefix is the real
    # storage-key signal; the docstring records why the rewrite check was
    # wrong and why the prefix is sufficient.
    # fix(#1213 review r6): +23 — the failed-source retention semantics (an
    # ordinary import stays retryable while its source exists, so only the
    # reupload caller reaps on failure) plus draining both terminal reapers so
    # a cancellation cannot skip the sweep that follows. Most of it is the
    # docstring correcting r4's claim, which cited the wrong authority.
    # feat(#1218): +20 — IngestContext gains origin_ref (the typed per-origin
    # payload the finalize pipeline writes) and _finalize_ingest stamps the
    # system-managed origin pointer in the same transaction that creates the
    # dataset. Most of it is the field's comment recording why the caller
    # supplies the payload rather than this module inferring one.
    # Cap 1796 -> 1816, exact.
    # fix(#1218 review): +32 — _apply_reupload_swap restamps the origin
    # binding and last_refreshed_at, so the stored ref keeps describing where
    # the CURRENT bytes came from after a reupload changes the origin kind.
    # Most of it is the comment explaining why the kind is derived rather than
    # hardcoded to upload (a service reupload must stay a service origin) and
    # that #1220's executor takes both writes over, and why the timestamp is a
    # Python datetime rather than func.now() (a SQL expression leaves the
    # attribute expired, so the next read lazy-loads). Cap 1816 -> 1850, exact.
    # fix(#1222 review): +11 — the swap stamps last_checked_at for service and
    # STAC origins, because set_dataset_origin clears probe state on restamp
    # and this swap IS a contact with the origin. The comment carries why
    # source_health is NOT written here (the vocabulary belongs to the
    # probe's classifier). Cap 1850 -> 1861, exact. +7 more: first ingest
    # stamps the same contact for service/STAC origins — the import fetched
    # from the origin too, and a fresh service dataset otherwise reported
    # "never contacted" until manually probed. Cap 1861 -> 1868, exact.
    # feat(#1219): +6 — _apply_reupload_swap now RETURNS the DatasetVersion it
    # created, flushed so its id is populated, because the refresh run row
    # links to that id. Resolving it at the call site by (dataset_id,
    # version_number) instead would be a second way to name one row.
    # Cap 1868 -> 1874, exact. fix(#1274 review): +6 — the failure finalizer's
    # attempt fence now admits `pending`, because a failure BEFORE the claim
    # (the worker-time SSRF refusal) must still finalize the job it owns; the
    # comment carries why attempt-id equality, not status, is the fence.
    # Cap 1874 -> 1880, exact.
    # fix(#1277 review): +9 — the shared failure sink redacts before it
    # persists. This one function fans out to three sinks (the durable
    # error_message, the log record, the notification reason), so the comment
    # has to say why the redaction belongs here rather than at each of them,
    # and why the exception itself is left unmodified for callers that
    # dispatch on its type. Cap 1880 -> 1889, exact.
    # fix(#1290 review): +13 — _archive_original_file reports whether the
    # archive landed and accepts the uploaded filename. The raster tails call
    # it to satisfy ADR-002 Decision 7 when a conversion was lossy, so for them
    # the outcome is a decision input (do not delete the staged upload unless
    # the durable copy exists) rather than a breadcrumb, and `file_path` is a
    # temp download on object storage so the name had to come from the caller.
    # Cap 1889 -> 1902, exact.
    # feat(#1266): +66 — stamp_failed_origin_health, the guarded dataset-side
    # health write a failed refresh makes. It arrived with #1313 as a private
    # helper inside the registered-PostGIS strategy; the STAC strategy needs
    # precisely the same write, and a copy would have been a THIRD spelling of
    # the binding guard beside _record_failed_origin_contact in
    # tasks_reupload. Moved here rather than duplicated, so the two strategies
    # share one implementation and #1313's file shrank by the same lines.
    # Cap 1902 -> 1968, exact.
    # fix(#1314): +26 — _apply_reupload_swap reconciles the auto-generated
    # distribution rows when the swap changes the dataset's modality. Most of
    # the lines are the note recording what this deliberately does NOT fix on
    # this path (record_type, filed as #1361) so the asymmetry is a decision
    # rather than an oversight. Cap 1968 -> 1994, exact.
    # fix(#1314 review round 2): +28 — the demote needs positive evidence that
    # the relation is not spatial, because a spatial reupload of an empty file
    # measures None while its geom column is still there. Most of the lines are
    # the note saying why the sampled value is not that evidence, which is the
    # same trap #1313 fell into on the refresh path. Cap 1994 -> 2022, exact.
    # fix(#1373 x #1361): +97 — the effective-geometry precedence and the
    # record_type derivation MOVED here from tasks_postgis_refresh (which
    # already imports from this module, so the dependency runs the right way)
    # and _apply_reupload_swap now resolves both. Roughly half the lines are
    # the three helpers and their docstrings arriving intact — that file shrank
    # by 68 — and the rest is the swap's own note recording why the sampled
    # geometry type is not evidence about the COLUMN, and why record_type must
    # consume the RESOLVED value or an empty spatial reupload flips a still-
    # spatial dataset to `table`. Cap 2022 -> 2119, exact. +8 more: the note
    # recording what this swap still does NOT retire when it de-spatializes a
    # dataset (the synthetic `geom` attribute row, filed as #1380), so the
    # remaining asymmetry with the refresh path is a decision. Cap 2119 ->
    # 2127, exact. +12 more (#1382 review r1): a generic empty column over a
    # dataset nothing had ever measured resolved to None and classified a
    # spatial relation as tabular, so the precedence falls back to the generic
    # sentinel; the lines are the note recording that `GEOMETRY` is how the
    # rest of the codebase already spells "spatial, subtype unknown".
    # Cap 2127 -> 2139, exact. fix(#1380): +39 — the note above becomes the
    # thing it described. `_retire_geometry_attribute_row` MOVED here from
    # tasks_postgis_refresh (which shrank by 10) and both de-spatializing
    # paths call it, so the synthetic `geom` attribute row is retired once
    # rather than by whichever path remembered to. Most of the lines are the
    # docstring recording why `refresh_attribute_metadata` is right to leave
    # that row alone for every other caller, and why the null check lives
    # inside the helper. Cap 2139 -> 2178, exact.
    # feat(#1472): +29 — `apply_manifest_record_metadata`, the read-back for the
    # manifest metadata `manifest_job_metadata` had been writing into the job
    # ledger and nobody consumed. It lives here rather than in either tail
    # because the vector tail (below) and the raster tail (tasks_raster, which
    # already imports `_parse_temporal_fields` from this module) both need it
    # and would otherwise each grow their own copy. Most of the lines are the
    # docstring recording why only the manifest-namespaced keys are copied:
    # title/summary/visibility reach the record through create_dataset's own
    # arguments on every ingest path, so touching them here would change
    # non-manifest ingests, and why `record` is duck-typed rather than annotated
    # `Record` (the annotation would add the processing -> modules.catalog edge
    # ProcessingPort exists to keep out). Cap 2178 -> 2207, exact.
    #
    # fix(#1542): +4 — one `task_app.import_paths` entry for the queued admin
    # embedding backfill, plus the three-line comment saying why that task
    # module lives under modules/admin/ (it emits the run's audit events, which
    # processing/ may not import) rather than beside the backfill it runs.
    # Cap 2207 -> 2211, exact.
    # fix(#1675): +81 — run_paged_arcgis_service_fetch, the guarded
    # resultOffset paging loop extracted from tasks_vector so the refresh
    # executor pages large ArcGIS layers with the same no-progress guard
    # instead of trusting GDAL driver paging. Then +16 (codex r2): the
    # growth check became exact — a server capping responses below its
    # advertised page size returned SOME rows per page while the offset
    # skipped records, so positive growth alone could swap a truncated
    # copy. Cap 2211 -> 2308, exact.
    # fix(#1682 codex r1): +3 — the DBF field-name-truncation warning in the
    # shared reupload helper is keyed on the derived source_format instead of
    # the .zip suffix, plus the import and the comment saying why (a File
    # Geodatabase arrives in a .zip and has no DBF). Cap 2308 -> 2311, exact.
    # fix(#1746): +69 — the shared token purge both service tasks now run on
    # their terminal failure path: `purge_queued_job_token` (a best-effort
    # `args - 'token'` UPDATE against the task's own procrastinate row) and
    # the `purge_token_on_failure` decorator that absorbs the JobContext
    # procrastinate passes in so the tasks keep their existing signatures.
    # Two thirds of it is comments — why deleting the key is safe (retry=0,
    # so the first exception is the terminal one) and why the wrapper catches
    # Exception rather than BaseException. Cap 2311 -> 2380, exact.
    # fix(#1778): +14 — `_cleanup_staging_on_failure` skips the DROP when it is
    # handed an empty staging-table name, which is what makes it usable by the
    # raster and VRT tails that have no staging table. Most of it is the
    # docstring saying what the four hand-rolled copies were each missing (the
    # redaction backstop, the pending-inclusive fence, the ingest_failed
    # notification) and why an empty name skips rather than logs a cleanup
    # failure on every VRT build failure. Cap 2380 -> 2395, exact.
    # fix(#1778 codex r2): +31 — `_cleanup_staging_on_failure` writes and
    # commits the failure row BEFORE it attempts the staging DROP, and the drop
    # rolls back its own wreckage. A DDL error aborts the whole PostgreSQL
    # transaction, so with the drop first a lock or statement timeout took the
    # failure write down with it and the job sat `running` with no reason. Most
    # of the lines are the docstring and comment stating that the order is the
    # contract. Cap 2395 -> 2426, exact.
    # fix(#1778 codex r6): +21 — `_job_phase_session` takes an optional
    # `lock_and_statement_timeout_ms`, applied via `SET LOCAL` BEFORE its own
    # SELECT rather than leaving a caller to set it after entering the
    # context manager, where it could not protect that SELECT from stalling
    # behind a lock the row's own later write would never see (e.g. an
    # ACCESS EXCLUSIVE table lock). `None` by default, so every other caller
    # of this shared helper is unchanged. Cap 2426 -> 2447, exact.
    # fix(#1778 audit r11): +23, rebased onto the above rather than the 2426
    # baseline it was originally measured against. `_job_phase_session` also
    # gains `require_status`, an independent optional status predicate that
    # joins the attempt fence, addressing a coexisting gap: an (id, attempt)
    # -only match still admitted a row the stale sweep had already failed on
    # a heartbeat timeout, with no retry having rotated the attempt token
    # yet, so a worker only paused could resume and write whatever that
    # phase writes. The two parameters are independent and both now live on
    # the same signature. Almost all of the growth is the docstring stating
    # which phases must pass which. Cap 2447 -> 2470, exact.
    # fix(#1778 audit r12): +25. `require_status`'s SELECT now takes `FOR NO
    # KEY UPDATE`, closing the TOCTOU a plain status check left open: the
    # sweep could still fail a row in the window between the read and the
    # phase's first put, since a SELECT is not a lock. Most of the growth is
    # the docstring stating why `NO KEY UPDATE` over plain `UPDATE`, and
    # pointing at the sweep-side fixes that now have to contend with this
    # lock instead of racing past it. Cap 2470 -> 2495, exact.
    # fix(#1738 round 1): +38 — bump_tile_cache_version_atomic, the sibling of
    # Dataset.bump_tile_cache_version for a writer that holds no row lock.
    # Most of it is the docstring arguing why the lock is not the fix: the
    # feature-edit routers roll the counter through a plain read-modify-write
    # and never take one, so one side locking does not serialize a race the
    # other side is not playing. Cap 2495 -> 2533, exact.
    # fix(#1770 round 43 P2): +8. `_bind_task_log_context` now also resets
    # the credential-secret registry (`core/service_tokens.register_
    # credential_secret`) at the same boundary it already clears structlog's
    # own contextvars, so a re-used worker cannot scrub a later job's log
    # lines with an earlier job's secret. Cap 2533 -> 2541, exact.
    # fix(#1846, GHSA-hrf5-v3cq-frx5): +5. The upload-safety gauntlet gained
    # the SQLite schema check beside the archive checks, for the same reason:
    # what a file instructs is as much a property of the upload as its shape.
    # Cap 2541 -> 2546, exact.
    # fix(#1846 review round 4): +5. Same thread offload as the ogr.py sites,
    # with the comment saying why a linear walk still does not belong on the
    # loop. Cap 2546 -> 2551, exact.
    # fix(#1755 item 11): +30. `cleanup_step`, the one helper the seven ingest
    # task modules now route every `finally`-block cleanup step through, plus
    # the docstring stating the two things it must never do: replace the
    # exception the block is already propagating, and swallow the
    # `CancelledError` a worker shutdown delivers. It replaces two private
    # copies that had grown in tasks_vector.py and tasks_reupload.py, whose
    # bodies differed only in the task name in their docstrings.
    # Cap 2551 -> 2581, exact.
    # fix(#1847): the lock order, its gate and its 409 mapping. Cap 2601, exact.
    # fix(#1847): the cache-bump docstring states its contract. Cap 2601 -> 2596.
    # fix(#1902): the atomic bump moved to platform/catalog_locks. Cap 2596 -> 2559.
    "backend/app/processing/ingest/tasks_common.py": 2559,
    # --- entered by the inclusion rule, feat(#1219 x #1222) ---------------
    # tasks_reupload crossed 1000 when two independently-reviewed features
    # met in one file: #1222's failed-contact bookkeeping (spawn-armed
    # binding-guarded stamp, ~90 lines with its helper and comments) and
    # #1219's refresh-run integration (run claim on dispatch, run
    # finalization on both outcomes, the savepoint-scoped run row on the
    # failure path). Both sides earned their lines in their own reviews;
    # the sum simply tripped the inclusion threshold. Entered at its
    # measured size. fix(#1274 review): +4 — the fetch-time SSRF check moved
    # inside the handled region so its refusal finalizes the job and run
    # instead of stranding a pending run against the admission index.
    # Cap 1055 -> 1059, exact.
    # feat(#1220): +48 — the one-time credential handoff reaches the worker
    # here. Twenty of those lines are `_resolve_service_token`, extracted
    # rather than inlined because the claim is one `if` and inlining it
    # tripped the C901 ceiling on `reupload_service`; the rest is the
    # `credential_ref` parameter, the docstring paragraph saying which of the
    # two doors sends which credential shape and why the ref wins when both
    # are set, and the failure handler's `credential_expired` branch — the one
    # failure on this path whose fix is "start again with a fresh token"
    # rather than anything about the origin. Cap 1059 -> 1107, exact.
    # feat(#1220 self-review): +18 — `_service_refresh_error_code`, which
    # splits the credential failures into two codes instead of one. An
    # unreachable credential store is an operator's split-brain config (the
    # API accepted the token because IT could reach the store) and needs a
    # different answer than a spent token; the mapping lives in a named
    # function so a fourth case is an entry rather than another branch inside
    # the failure handler. Cap 1107 -> 1125, exact.
    # fix(#1277 review): +14 — the exact-value credential scrub at the top of
    # the broad handler. This task is the only place that knows the token's
    # literal value, which is what makes it the redaction an unrecognised echo
    # cannot evade; the comment records that, and why it mutates the exception
    # in place rather than raising a replacement (the class is load-bearing for
    # the error-code mapping below it). Cap 1125 -> 1139, exact.
    # fix(#1472 review): +12 — apply the manifest ledger's credit line on the
    # reupload swap. A manifest re-apply with a changed fingerprint classifies
    # as "update" and lands here rather than on either fresh-ingest tail, so
    # without it the swap installed new data under the previous manifest's
    # credit. Most of the lines are the comment recording why this path is the
    # only reupload one that needs it and why dataset.record is safe to touch
    # (joinedloaded by the SELECT above it). Cap 1139 -> 1151, exact.
    # fix: +5 — thread original_filename through _detect_reupload_crs and the
    # two run_ogrinfo/run_ogr2ogr call sites so a corrupt reupload gets the
    # same friendly "could not open" message as a fresh upload, instead of
    # leaking the staging path / GDAL driver dump. Cap 1151 -> 1156, exact.
    # fix(#1675): +79 — _fetch_service_layer_with_paging_guard: the paging
    # decision (page-info probe, criteria, paged-vs-single dispatch) for the
    # refresh executor, module-level so the branches stay out of
    # reupload_service's complexity budget. Then +10 (codex r1): arm the
    # origin-contact stamp when the probe's request begins — the probe is
    # the first outbound contact and can die before any subprocess spawns.
    # Cap 1156 -> 1245, exact.
    # feat(tier-1 vector import) + fix(#1682 codex r1): +2 — the source_format
    # derivation moved to the shared ingest/source_format.py (one import line),
    # and the DBF-truncation guard gained the comment recording that it is
    # keyed on the derived format, not the .zip suffix. Cap 1245 -> 1247, exact.
    # feat(#1676): -5 — `_resolve_service_token`'s body moved out to
    # platform/refresh/credentials.resolve_worker_credential so `ingest_service`
    # can redeem the same way. Neither task module may import the other
    # (tasks_reupload already reaches into tasks_vector at call time, so a
    # top-level edge back would close a cycle), which is what put the shared
    # copy in platform/. Ratchet DOWN in the same commit, per the no-headroom
    # rule. Cap 1247 -> 1242, exact.
    # fix(#1746): +9 — `reupload_service` takes `pass_context=True` (the only
    # way a task can learn its own queue-row id) and the
    # `purge_token_on_failure` wrapper, plus the comment saying what the
    # context is for. Cap 1242 -> 1251, exact.
    # fix(#1746): +27 — the auth_required marker on the service swap's
    # origin_ref (True or absent, never False, so a token-less pull stores the
    # pre-marker ref shape and no backfill is owed), plus door-aware
    # auth-failure copy. The old string said "Retry commit", which names a
    # door neither caller came through: this task serves the refresh endpoint
    # and the re-upload commit, and never a first import. Cap 1251 -> 1278,
    # exact.
    # fix(#1746 codex r1): +5 — the marker comment now states the claim
    # narrowly ("the last successful pull was MADE with a token"), because the
    # worker never sees a challenge on the happy path. Cap 1278 -> 1283, exact.
    # fix(#1778): +8. The pending -> running run transition is committed
    # before `resolve_file_path` instead of after it, plus the comment saying
    # why. Holding the `dataset_refresh_runs` row lock across the staging
    # download made every cancel in that window a 409 that also rolled back the
    # job cancellation it had already written. Cap 1283 -> 1291, exact.
    # fix(#1746 B2b review r1): +6 — rebased onto #1778 above. The worker's
    # authentication-failure copy names the `auth` object rather than the
    # deprecated `token` field, which always means a bearer credential and so
    # could not authenticate the basic or named-key origin that produced the
    # failure. Same finding as the refresh door's 422, one layer down; the
    # lines are the comment recording that the two messages have to agree.
    # Cap 1291 -> 1297, exact.
    # fix(#1755 item 11): +36. `reupload_service`'s `finally` block routes
    # both cleanup calls through the new shared `_finally_cleanup` helper, so
    # a heartbeat-stop or staging-drop failure logs (redacted, exc_info)
    # rather than replacing the ingest exception in flight; the #1753 token
    # purge still runs, since the helper never re-raises. Cap 1297 -> 1333,
    # exact.
    # fix(#1755 item 11, follow-up): -23. The private `_finally_cleanup` copy
    # moved to `tasks_common.cleanup_step` as a context manager, which is
    # shorter at every call site than passing a coroutine, and `reupload_file`
    # gained the same treatment its service sibling already had (5 steps).
    # Cap 1333 -> 1310, exact.
    "backend/app/processing/ingest/tasks_reupload.py": 1310,
    # --- entered by the inclusion rule, feat(#1266) -----------------------
    # The refresh door crossed 1000 when it gained its third execution
    # strategy. Two thirds of the addition is the STAC dispatcher, which is
    # the service door's ordering with the steps a remote ITEM does not need
    # removed (no credential, no prior-ingest settings) — the shape is
    # deliberately the same because the ordering is what keeps a re-upload
    # that commits mid-admission from having its rebind dispatched from a
    # pre-swap snapshot. The rest is _resolve_stac_origin and the binding
    # dataclass, whose comments carry the one asymmetry that decides this
    # strategy: the asset href says whether the COG is still there, and only
    # the ITEM href can say where the publisher moved it to. Entered at its
    # measured size.
    # fix(#1266 review round 9): +2 — the dispatched STAC binding carries the
    # item's recorded id, so a re-upload that rebinds mid-admission is caught
    # by the same equality check as every other field of it.
    # fix(#1266 review round 10): +28 — the door refuses a STAC binding whose
    # item identity cannot be verified at all (no recorded id, and item URLs
    # that state none), before a job or a run row exists. Most of the lines
    # are the refusal's wording and the comment saying why it is the door's
    # business: an unverified first answer would be both adopted and recorded
    # as durable truth, and a caller who learns that immediately can act on
    # it, where one who learns it from a failed run cannot. Cap 1091 -> 1119.
    # fix(#1746): +44 — the service_token_required 422, refusing a
    # credential-less refresh of an origin whose last successful pull needed a
    # token, before the SSRF resolve and before the run reservation. Extracted
    # into its own helper rather than three lines in the handler, because
    # refresh_dataset sits one branch under ruff's C901 ceiling and the repo's
    # answer to that is extraction. Most of the addition is the docstring
    # saying why the marker is not a permanent trap: the re-upload dialog with
    # no token is the path that clears it. Cap 1119 -> 1163, exact.
    # fix(#1746 codex r1): +37 — the marker records that a token was USED, not
    # that the origin demanded one, so refusing on it alone locks a user who
    # imported a public service while holding a token out of every token-less
    # refresh. The guard now runs ONE token-less probe (through the health
    # endpoint's own target and probe helpers, both lifted into origin_probe)
    # and refuses only on an auth challenge; every other outcome falls through
    # to the worker. Most of the addition is the docstring saying why it fails
    # open. Cap 1163 -> 1200, exact.
    # fix(#1746 codex r2): +82 — two corrections to the r1 guard. It probes
    # only ArcGIS, whose target IS the layer the worker reads; WFS and OGC API
    # are refused outright, because their probe target is GetCapabilities or
    # the landing page and a public one of those in front of a protected
    # GetFeature is an ordinary deployment, so a healthy answer would be
    # evidence of nothing. And the probe path now releases the session across
    # the outbound wait and re-reads after it, the way check_source_health
    # does, so concurrent marked refreshes against a slow origin cannot
    # exhaust the pool. Most of the addition is the docstring stating which
    # services can be asked and why, plus the caller contract for the
    # rollback. Cap 1200 -> 1282, exact.
    # fix(#1746 codex r3): +62 — the marker is re-checked after the
    # reservation. A token-less refresh could read an unmarked dataset, pass
    # the guard, and have an authenticated re-upload of the same origin mark it
    # inside the reservation window; the binding comparison there cannot see
    # that, because `_ServiceOrigin` is the worker's binding and the origin did
    # not move. Detects the TRANSITION rather than re-deciding, so a healthy
    # ArcGIS probe is not overturned with no new evidence. Most of the addition
    # is the docstring saying why it is not folded into the binding check and
    # why it does not probe. Cap 1282 -> 1344, exact.
    # feat(#1746): +9. The refresh body's structured `auth` object is converted
    # to one credential at the top of the handler, so every branch below reads
    # the same value and a method this build cannot carry is refused before any
    # origin is contacted. Two of the lines are the import and the rest is the
    # comment saying why the conversion is first. Cap 1344 -> 1353, exact.
    # feat(#1746 B2b): -8. The post-reservation charset check is now one call
    # to `wire_credential` against the binding that is actually going to be
    # dispatched, which both judges the inputs and composes the wire value, so
    # the hand-rolled refusal block it replaced is gone. Ratcheted down rather
    # than left with headroom. Cap 1353 -> 1345, exact.
    # fix(#1746 B2b review r1): +19. The credential is composed AFTER the
    # write-access gate, because it reads `dataset.source_format` and a refusal
    # ahead of the gate answered 422 for a dataset the caller may not touch
    # while a nonexistent one answered 404. And the `service_token_required`
    # message names the `auth` object rather than only the deprecated `token`,
    # which always means bearer and so could not authenticate the basic origin
    # that raised it. Most of the lines are the two comments recording those.
    # Cap 1345 -> 1364, exact.
    # fix(#1770 round 35): +10 — the refresh door judges header_auth_job_queue
    # on the composed credential line, before the store lease may swap it for
    # a reference, and configures the deferred task's queue with the verdict
    # so a worker from the release before this PR never dequeues a header
    # line its own validator cannot parse. Cap 1364 -> 1374, exact.
    # fix(#1755 item 15): +2 — corrected the `_require_service_token_if_marked`
    # docstring, which still described the ArcGIS probe reading the layer's
    # `?f=json`; since #1754 round 6 it reads `<layer>/query` via
    # `build_arcgis_count_query_url`. Cap 1374 -> 1376, exact.
    # chore(#1812): -9, the refresh door no longer judges a queue on the composed line
    # or configures the deferred task with it. Cap 1376 -> 1367, exact.
    "backend/app/modules/catalog/datasets/api/router_refresh.py": 1367,
    # fix(#1335): stac_resolve.py's 1040 lines were split along their natural
    # seams — verdict taxonomy, identity checks, the asset gate (SSRF + COG
    # probe), and the by-search fallback each moved into a sibling module,
    # leaving this file as the by-URL entry point plus the façade the split's
    # external callers and tests still import through. No entry needed below
    # 1000 lines; see stac_resolve_asset_gate.py etc. for the pieces that
    # carried the length.
    # --- entered by the inclusion rule, fix(#958) -------------------------
    # These five were the ungated modules at or above _RATCHET_INCLUSION_LOC
    # when the rule was written. They arrive at their measured size with no
    # carve-out history, because none of them has ever had to argue for a
    # line: that is the gap #958 was filed about. The next change to any of
    # them writes the first entry.
    # fix(#1543): +6 — config import applies the whole batch's post-commit side
    # effects through apply_side_effects_batch instead of a per-key loop, so its
    # cache eviction is one step. Four of the six are the widened import; the
    # other two say why the loop is gone, which matters most here: an import
    # touches far more keys than a settings PUT, so it held the widest version
    # of the mismatch window. Cap 1201 -> 1207, exact.
    "backend/app/platform/config_ops/service.py": 1207,
    # fix(#1335): jobs/router.py's 2047 lines carried the sweep SQL
    # constants and every stale-job recovery/sweep handler alongside the
    # plain CRUD routes. The two were split along that seam: the sweep
    # handlers (fail_stale_jobs, sweep_stale_vrt_assets, the presigned-
    # staging reapers) and their SQL constants moved to sweep.py, leaving
    # router.py under the router-glob gate's default 1500-line cap with no
    # entry needed here. The line-by-line growth history that used to live
    # on this entry (fix #1236, fix #1322 rounds 1-6, ...) is unchanged and
    # readable via `git log` on the pre-split file; sweep.py is entered
    # fresh at its measured size below.
    # fix(#1249): +9 — the object-driven staging reconciliation is wired in
    # after the two row-driven reapers, with the comment saying why it is not
    # folded into StaleCleanupOutcome (that dataclass is a published API and
    # audit shape). The pass itself lives in its own module,
    # platform/jobs/staging_reconcile.py, which is under the 1000-line
    # inclusion threshold and needs no entry. Cap 1366 -> 1375, exact.
    # fix(#1249 review r4): +4 — the retention purge's survivor query now reads
    # STATUSES_NEEDING_STAGED_INPUT from jobs/models.py instead of an inline
    # tuple, because the reconciliation asks the same question and two copies
    # of "which statuses still need the bytes" drift into a leak in one
    # direction and a deletion of live input in the other. The lines are the
    # multi-name import that replaced the single-name one. Cap 1375 -> 1379,
    # exact.
    # fix(#1249 review r6): +1 — STAGING_REAPED_FINAL_MARKER moved to
    # jobs/models.py too. Its presence is what tells the reconciliation the
    # post-expiry sweep is finished with a key, and a copy of the string in
    # each module is one rename away from a row that shields an object
    # forever. Cap 1379 -> 1380, exact.
    # fix(#1327): +23 — the composition-drift branch keeps its code and gains
    # the rationale for why it is now near-unreachable: source add/remove stage
    # their member set and apply it at the artifact swap, so the drift this
    # branch discriminates is no longer produced by live traffic. The comment
    # says what the branch still guards (pre-#1327 rows, any future writer of
    # the link table) so the next reader does not delete a check whose FALSE
    # side went quiet. Cap 1380 -> 1403, exact.
    # fix(#1550 review): +86 for `audit_settled_embedding_backfill` and its
    # three call sites. After a hard kill there is no worker process left to
    # close an embedding backfill's audit trail, so the actor that settles the
    # row — this sweep — is the only one that can, and it emits on the caller's
    # session so the status change and the audit entry commit as one. Most of
    # the lines are the docstring recording why the trail cannot be closed
    # anywhere else, and why `audit_emit_durable` would be the wrong tool here.
    # Cap 1403 -> 1522, exact. The second raise adds
    # `terminal_backfill_audit_exists`: one operation gets one terminal entry,
    # whoever writes it first, because three actors can legitimately close the
    # same run and two of them disagreeing is the defect.
    # fix(#1556): +77 — the unbound half of the pending sweep gained an ACTION
    # helper (`stale_pending_unbound_values`) to sit beside the existing clause
    # helper, so a presigned upload nobody ever bound bytes to settles
    # `cancelled` at all three sites that can reach it instead of `failed` at
    # whichever one got there first. Most of the lines are the two predicate
    # docstrings recording why the class is "presigned marker AND empty
    # file_path" and not "falsy file_path": a service import with a source_url
    # is also unbound, and `/jobs/{id}/retry` only offers a `failed` row, so
    # the broader rule would take a recoverable job's recovery away.
    # Cap 1522 -> 1599, exact.
    # fix(#1556 review, codex P2): +54 — the unbound UPDATE returns the status
    # its CASE chose, so `pending_failed` can stop counting the rows that were
    # cancelled. Without it the admin cleanup response, its audit event and the
    # sweeper's log line all still reported an abandoned upload as a failure,
    # which is the whole thing the split exists to stop. The lines are the new
    # field plus the docstrings recording why `total_cleaned` excludes
    # cancellations while `total_affected` includes them, and why the count
    # reaches the audit event but not the published response model.
    # Cap 1599 -> 1653, exact.
    # fix(#1709 review r7 A): +82 — the childless-fanned_out reconciliation:
    # the r5 early flip (the mutex that closed the fast-child cancel window)
    # regressed the crash recoverability the old late transition got from the
    # pending clause, so a parent that died between its flip commit and its
    # first child commit stranded terminal forever. The clause settles such
    # parents 'failed' (retry becomes available) behind a 5-minute grace and
    # a retention-horizon bound; most of the lines are the comment proving
    # childless-fanned_out is the crash signature and nothing else's, and why
    # parents past the retention horizon belong to the purge instead.
    # Cap 1653 -> 1735, exact.
    # fix(#1709 review r8 A): +17 — the recovery stops advertising a retry
    # flow that does not exist. The settle now stamps
    # FAN_OUT_INTERRUPTED_METADATA_KEY (which _retry_capability refuses on —
    # generic retry would re-queue the multi-layer parent as ONE
    # default-layer import) and the message names re-upload as the real
    # path. Cap 1735 -> 1752, exact.
    # fix(#1709 review r10): +11 — audit_settled_embedding_backfill takes an
    # optional `settled_by`, so the terminal event names whoever SETTLED the
    # run: the canceller when a person cancelled it (the arm-3/cross-user
    # case, matching job.cancel and refresh.cancelled in the same
    # transaction), and the requester when a sweep settles it, since a lease
    # expiry is nobody's click. Cap 1752 -> 1763, exact.
    # fix(#1708 codex r6): +29 — pending age in stale_pending_clauses is
    # measured from coalesce(user_metadata.staged_at, created_at), so a URL
    # import whose download consumed part of the configurable pending
    # timeout gets its full review window back at staging completion, while
    # every row without the key (all other flows) ages from created_at
    # exactly as before. Mostly the comment recording why this is a restart
    # and not an exemption. Cap 1653 -> 1682, exact.
    # RECONCILED at the #1708/#1709 merge: both raised this cap off the same
    # 1653 baseline — #1709 to 1763, #1708 to 1682 — so the cap is measured
    # off the merged file. 1763 + #1708's 29 = 1792, exact.
    # fix(#1746): +35 — `purge_terminal_job_tokens`, the backstop UPDATE that
    # strips a leftover `token` from every TERMINAL procrastinate row (the
    # attempts that never reached the task-side purge: worker killed mid-run,
    # rows deferred before the fix). Its own coroutine rather than a line in
    # `fail_stale_jobs`, because that runs once per TENANT in hosted mode and
    # the queue table has no tenant column — the docstring carries that and
    # the why-no-index note. Cap 1792 -> 1827, exact.
    # fix(#1744): +30. `abandoned_presigned_upload` became `abandoned_upload`,
    # which asks the row whether a dispatch was ever attempted
    # (`commit_attempted_at`) instead of inferring it from an empty
    # `file_path` plus a `presigned` marker. Almost all of the lines are the
    # docstring: why the shape-based carve-out missed the door the demo
    # actually uses (a direct upload binds an absolute staging path and stamps
    # no `presigned` marker, so four abandoned uploads reported `failed` with
    # "never queued"), why the absolute-path class no longer needs a branch of
    # its own, and why rows predating the stamp reclassify rather than get a
    # migration, plus the two residual gaps it records (the one-statement
    # window between a door's own commit and the stamp, and S3-mode direct
    # uploads landing in the bound half). Cap 1827 -> 1857, exact.
    # fix(#1778): +134. Two out-of-process reapers for artifacts a hard kill
    # used to strand forever. `unpublished_storage_keys_from_metadata` reads the
    # `rasters/`/`originals/` keys a raster tail named on its own job row before
    # writing them, and `unadopted_analysis_table_from_metadata` plus
    # `_reap_unadopted_analysis_outputs` do the same for an analysis output
    # table; both are collected in `fail_stale_jobs` and deleted only after its
    # commit, alongside the existing stale-generation keys. Roughly half of it
    # is the docstrings stating why the analysis reap takes its own session.
    # Cap 1857 -> 1991.
    # fix(#1778 codex r1): +86. The raster reap gained a survivor check that an
    # earlier revision argued it did not need: an identical re-upload derives
    # the same content hash, so a replace's intended keys can BE the live
    # asset's, and a crash then licensed deleting the raster the dataset was
    # serving. `_live_referenced_storage_keys` asks the four columns that name
    # an object, `reap_unpublished_storage_keys` refuses what they return and
    # deletes nothing at all when the query fails, and both stale-job passes
    # go through it. Cap 1991 -> 2077.
    # fix(#1778 codex r4): +23. The retention purge is the LAST actor holding a
    # pointer to a terminal job's unpublished keys and analysis output table,
    # so a job that failed on its own and whose best-effort cleanup then failed
    # once had nothing left looking at it. Its DELETE ... RETURNING already
    # carried `user_metadata`; the rows now feed the same two post-commit reaps
    # the running-row sweep feeds, survivor checks included. Cap 2077 -> 2100.
    # fix(#1778 codex r5): +152. Feeding the reap was not enough, because the
    # reap runs after the commit and can fail as a whole, and by then the
    # pointer is gone. The purge now refuses to delete a row that still names
    # an unreaped artifact, which makes the job row the durable pending-reap
    # record a retry needs without a new table, and both reapers clear that
    # record once they have a final answer (deleted, or refused because a live
    # row names it) so the next pass can purge the row. The survivor query also
    # went from four IN clauses to one shared array bind, because four binds
    # per key crossed asyncpg's 32767-argument ceiling at about 8192 keys and
    # the resulting failure skipped every delete. Cap 2100 -> 2252.
    # fix(#1778 codex r6): +36. Both arms that clear an artifact record now key
    # the settle off a NAMED outcome instead of off control flow. The analysis
    # arm was reading "the call returned" as success, but the callee catches
    # its own probe and DROP failures, so a failed cleanup stripped the table's
    # last durable name and orphaned it; the storage arm was correct only by
    # where a statement sat inside a try block. `STORAGE_KEY_FINAL_OUTCOMES`
    # and the try/else restructure are most of the growth. Cap 2252 -> 2288.
    # fix(#1778 codex r7): +14. The analysis reap is keyed on the owning JOB
    # rather than on a table name two jobs could hold in sequence: it carries
    # (job, table) pairs, hands the owner to the drop so it can refuse a table
    # that job did not create, and clears the record by row id. Cap 2288 ->
    # 2302.
    # fix(#1778 codex r9): +26. The storage-key record accumulates across
    # attempts now, so clearing it wholesale would forget keys the pass never
    # answered for. The clear removes the settled keys one by one and drops the
    # field only once nothing is owed on it, which is a correlated statement
    # rather than an operator, and the comment says why the binds are cast and
    # why it uses jsonb_exists_any over `?|`. Cap 2302 -> 2328, exact.
    # fix(#1778 codex r10): +46. The analysis output record now accumulates
    # across attempts too (same shape `unpublished_storage_keys` took in r9),
    # keyed and cleared by TABLE NAME rather than by job id, because a job
    # can now name more than one table. `unadopted_analysis_table_from_metadata`
    # became `unadopted_analysis_tables_from_metadata`, delegating to the
    # writer's own normaliser so the two cannot disagree about the shape. The
    # two artifact collections that used to run inside `fail_stale_jobs`
    # (running-row transitions, and the retention purge's exempted-rows
    # SELECT) are replaced by one unconditional SELECT after the retention
    # block, because both could miss a row that owed a reap -- a job that
    # failed on an earlier pass, or one whose dead attempt's keys were carried
    # over onto a row that is now its dataset's latest complete job and so
    # exempt from the purge. `_CLEAR_SETTLED_LIST_SQL` also gained an arm for
    # the field's pre-PR plain-string shape, which the array-only WHERE clause
    # had silently excluded from ever clearing. Cap 2328 -> 2374, exact.
    # fix(#1778 audit r12): +18. The running-jobs UPDATE now reads its
    # candidates through a `FOR UPDATE SKIP LOCKED` subquery instead of
    # matching them directly in the UPDATE's own WHERE clause, so a row a
    # live phase-2 transaction holds locked is excluded from the pass
    # instead of blocking it, or, if this were guarded by a `lock_timeout`
    # instead, aborting the entire batch on one busy row. Most of the growth
    # is the comment stating why a set-based UPDATE cannot use `lock_timeout`
    # the way a single-row write does. Cap 2374 -> 2392, exact.
    "backend/app/platform/jobs/sweep.py": 2392,
    # fix(#1709 review r8 B): first entry — crossed the 1000-line inclusion
    # threshold at 1010 when refresh.cancelled attribution was corrected to
    # name the CANCELLING user (cancel_active_run_for_job and
    # _emit_refresh_cancelled thread `cancelled_by` through; the run row's
    # immutable triggered_by mis-attributed exactly the arm-3 cross-user
    # cancel this PR added, and most of the growth is the docstring saying
    # why the dispatcher's identity belongs to refresh.dispatch instead).
    # The module also carries #1677's cancel machinery from earlier rounds:
    # USER_CANCELLED codes, _emit_refresh_cancelled, cancel_active_run_for_job.
    "backend/app/platform/refresh/service.py": 1010,
    # fix(second-opinion review on #1236 review r3): first entry — crossed
    # _RATCHET_INCLUSION_LOC while adding the belt-and-suspenders
    # `le=5120` bound on `presigned_multipart_threshold_mb` (the router-side
    # fixed margin in `_sweep_expired_presigned_staging` is what actually
    # closes the gap; this Field bound only stops a fresh boot from
    # configuring past S3's own single-PUT ceiling in the first place).
    # feat(#947): +52 — the opt-in single-tenant runtime DB role field is
    # normalized and validated as a safe PostgreSQL identifier, is restricted
    # to single-tenant mode, and must exactly match DATABASE_URL_OVERRIDE's
    # login/password. Those checks keep bootstrap/migration credentials
    # distinct and make a miswired Compose deployment fail before it opens a
    # pool. Cap 1004 -> 1056, exact.
    # fix(#1287 review): +35 — validate the explicit migration-object owner
    # against the migrate service's actual database URL login, so managed DB
    # reconciliation can install future-object defaults for the right role.
    # Cap 1056 -> 1091, exact.
    # fix(#1249): +13 — `staging_orphan_min_age_seconds`, the age an untracked
    # staging object must reach before the reconciliation sweep may delete it.
    # Most of the lines are the comment saying what the number is NOT (an
    # estimate of how long an upload takes — the tracking-row check is what
    # decides ownership), so nobody later "tunes" it as if it were a transfer
    # margin. Cap 1091 -> 1104, exact.
    # fix(#1485): +3 — ENVIRONMENT gained a third behavior (plain traceback
    # rendering), so the field comment and the `is_production` docstring that
    # enumerate what the setting controls say so. This setting exists because
    # security posture was once keyed off a flag documented as log-format only;
    # an under-documented coupling is the same mistake. Cap 1104 -> 1107, exact.
    # PRIV-1: +5 — a privacy_url Settings field (env-backed default for the
    # login/register privacy-policy link) plus its empty-string normalizer
    # entry. Cap 1107 -> 1112, exact.
    # PRIV-1 (pre-review): +49 — a shared validate_privacy_url_shape helper
    # (reused by the admin-write validator and the read-path defense in
    # modules/settings) plus the field_validator that fails boot on an unsafe
    # PRIVACY_URL. Both are large because they document why the check exists
    # and why it lives in core/config.py instead of core/public_urls.py
    # (avoiding a circular import). Cap 1112 -> 1161, exact.
    # PRIV-1 (r2 pre-review): +7 — hoisted the urlsplit import to module scope
    # and rejected embedded tab/newline/CR characters (a documented WHATWG
    # URL scheme-check bypass) in validate_privacy_url_shape.
    # Cap 1161 -> 1168, exact.
    # PRIV-1 (codex r1): +12 — validate_privacy_url_shape now rejects an empty
    # hostname (a netloc like ":443" passes the earlier netloc-truthy check
    # but resolves nowhere) and a malformed port (urlsplit leaves the junk
    # sitting in netloc instead of rejecting it; accessing .port is what
    # actually validates it, same pattern as validate_database_url_override
    # above). Cap 1168 -> 1180, exact.
    # PRIV-1 (codex r2): +28 — the whitespace check widened from tab/CR/LF
    # only to any whitespace character (a plain space inside a host is a
    # WHATWG-vs-urlsplit disagreement too), and a new _is_valid_privacy_url_host
    # allowlist (DNS labels or an IP literal) replaces trusting whatever
    # urlsplit left in .hostname. Deliberately not a call to
    # app.core.public_urls.canonical_host_error, which answers a
    # near-identical question, because that would be the same circular
    # import validate_privacy_url_shape's own docstring already rules out.
    # Cap 1180 -> 1208, exact.
    # PRIV-1 (codex r3): +21 — the DNS-label branch alone accepted a
    # numeric-last-label host ("999.999.999.999", "1.2.3.4.5", "192.168.1")
    # that a browser reads as an attempted (and often different-resolving)
    # IPv4 address, per the WHATWG "ends in a number" rule. That branch now
    # requires the exact canonical dotted-quad spelling instead of falling
    # through to the DNS-label check. Cap 1208 -> 1229, exact.
    # PRIV-1 (codex r4): +20 — the DNS-name branch (case 2) now IDNA-encodes
    # the hostname before applying the label regex, so a browser-valid
    # internationalized host like 例え.テスト is accepted rather than rejected
    # by an ASCII-only regex. Also rejects a label that starts with a
    # Unicode combining mark, which Python's stdlib "idna" codec (IDNA2003)
    # encodes without error even though no browser accepts it.
    # Cap 1229 -> 1249, exact.
    # PRIV-1 (codex r5): +30 — a label the operator spelled directly as
    # ACE/"xn--" punycode (not one this function IDNA-encoded itself) must
    # decode to a real IDN label. "xn--a" decodes to a bare C1 control byte
    # (U+0080) without raising and round-trips cleanly back to "a", so the
    # round-trip check alone does not catch it; also rejects a decoded
    # control/format/surrogate/private-use/unassigned character explicitly.
    # Cap 1249 -> 1279, exact.
    # PRIV-1 (codex r6): +44 — a bracketed authority ("[...]") is now
    # restricted to a plain, unscoped IPv6 literal rather than falling
    # through to the DNS-name or numeric-last-label branches once
    # `.hostname` strips the brackets, which otherwise accepted an
    # IPvFuture literal ([v1.foo]), an IPv4-in-brackets ([1.2.3.4]), and a
    # scoped IPv6 zone ID ([fe80::1%eth0]). Split into a small
    # _is_unscoped_ipv6_literal helper to stay under ruff's cyclomatic
    # complexity limit. Cap 1279 -> 1323, exact.
    # PRIV-1 (codex r7): +23 — unified the U-label combining-mark check and
    # the decoded-A-label control-character check into one _check_ulabel
    # function, called from both sites, so "xn--lsa" (the punycode spelling
    # of a bare combining mark, which only the A-label check saw) gets the
    # same verdict as its literal U-label form. Cap 1323 -> 1346, exact.
    # PRIV-1 (codex r8): -57 (SHRANK) — replaced the hand-rolled DNS-label
    # regex + _check_ulabel + manual punycode decode/round-trip with one
    # call to the `idna` package's UTS46 ToASCII (already a direct backend
    # dependency, pinned in pyproject.toml for a CVE), which enforces the
    # same rules plus the ones a hand-rolled check missed (U+FE47, which
    # UTS46 maps to "[" and then rejects). Cap 1346 -> 1289, exact.
    # PRIV-1 (codex r9): +18 — a single trailing DNS root dot is now
    # stripped before the numeric-last-label check: `rsplit(".", 1)[-1]`
    # on "192.168.1." returns "", which skipped the ends-in-a-number branch
    # entirely and let idna.encode() (DNS syntax only, no IPv4 opinion)
    # accept "999.999.999.999." and "192.168.1." as ordinary-looking DNS
    # names. Cap 1289 -> 1307, exact.
    # PRIV-1 (Ian's own review): +68 — the numeric-last-label check now
    # runs on the UTS46-mapped ASCII form (idna.encode's output), not the
    # raw hostname: an ideographic full stop (U+3002, "。") has no ASCII "."
    # for rsplit to find until mapped, and str.isdigit() is true for a
    # fullwidth digit ("１"), so the OLD raw-hostname check both missed
    # "999。999。999。999" (no split point) and wrongly rejected
    # "１２７.０.０.１" (handed the un-mapped string to IPv4Address). Also
    # added one docstring paragraph enumerating every place this check is
    # deliberately stricter than a browser, so a future "browser accepts,
    # we reject" report is read against that list first. Cap 1307 -> 1375,
    # exact.
    #
    # Ambient AWS credentials: four runtime-injected marker fields
    # (AWS_ROLE_ARN / AWS_WEB_IDENTITY_TOKEN_FILE and the two
    # AWS_CONTAINER_CREDENTIALS_* forms), the has_ambient_aws_credentials
    # property that reads them, and the rework of the s3 branch of
    # validate_provider_settings to accept EITHER a complete static key pair or
    # an ambient source while still rejecting a half-configured pair. Bought
    # keyless S3 on EKS (IRSA): the storage layer and derive_gdal_s3_env
    # already omitted unset keys, so this validator was the only thing forcing
    # long-lived IAM user keys into a Kubernetes Secret. Cap 1375 -> 1423,
    # exact.
    # ogr_connection_string now emits sslrootcert alongside sslmode, matching
    # the procrastinate_conninfo sibling it had drifted from. Bought working
    # vector ingest against a managed database under DATABASE_SSL_MODE=
    # verify-full: ogr2ogr goes through libpq, which cannot see the CA that
    # only ever reached asyncpg as an SSLContext. Most of the growth is the
    # comment recording that asymmetry.
    #
    # codex review on #1617 then added libpq_value(), which quotes and escapes
    # every interpolated value in BOTH DSN builders — an unescaped path or
    # password containing whitespace ends the keyword/value pair early and
    # yields a malformed DSN. Testing that turned up a second defect in the
    # same two functions: urlparse does not percent-decode, so they sent the
    # literal `pass%20word` while the API path (SQLAlchemy, which decodes)
    # authenticated fine — fixed with unquote() on user/password.
    # Cap 1423 -> 1501, exact.
    # fix(#1778): 1501 -> 1509 -> 1511 -> 1513. +12 for
    # DB_STATEMENT_TIMEOUT_SECONDS and the note saying why the deadline is
    # applied to the API process's engine rather than as a session default in
    # database_connect_args: the worker imports the same engine module and runs
    # single statements for minutes while indexing or reprojecting a freshly
    # ingested table. Two came from the codex r2 round, which moved it off the
    # get_db dependency because handlers open request-scoped sessions directly
    # in more than twenty modules and none of those were covered. The last two
    # are the r3 round: it is issued as SET LOCAL rather than as a startup
    # parameter, because standard PgBouncer rejects an unknown one and
    # DB_USE_EXTERNAL_POOLER=true is a supported topology.
    #
    # fix(#1778): +24 more for the boot-time GEOLENS_ADMIN_PASSWORD byte bound
    # and the BCRYPT_MAX_PASSWORD_BYTES constant it needs. core/ may not import
    # from app.modules.*, so the number is restated here rather than imported
    # from password_policy.py; tests/test_oversized_password_1778.py pins the
    # two together. Cap 1513 -> 1537, exact.
    # fix(#1770 round 35, rebased onto #1778 above): worker_queues' default
    # gains "ingest-auth-v2" beside the three original queues, so a worker
    # built from this release drains the header-auth jobs a rolling deploy's
    # upgraded API enqueues on it, alongside the comment recording why.
    # fix(#1770 round 36): the P1 finding was that the round-35 comment was
    # wrong: both compose files DO set WORKER_QUEUES (their own fallback value
    # shadows this class default entirely), so they needed the new queue too,
    # and the correction plus the pointer to the structural test that now
    # guards it is most of the growth. Re-measured with wc -l after all three
    # fixes landed together through the rebase. Cap 1537 -> 1562, exact.
    # fix(#1770 round 47b P2 class): +27. `# parse_qs: unbounded` at the
    # five `DATABASE_URL_OVERRIDE` `parse_qs` sites -- an operator-supplied
    # BOOT-TIME env var, never a runtime service-advertised value, so
    # exempted with a reason rather than bound (see
    # `test_every_parse_qsl_call_bounds_its_field_count`'s own docstring).
    # Cap 1562 -> 1589, exact.
    # fix(#1871): +70 for SECRET_ENCRYPTION_KEY and SECRET_ENCRYPTION_KEY_
    # PREVIOUS: the two fields, the KNOWN_PUBLIC_CREDENTIALS set the boot guard
    # checks them against, and the guard itself, which is most of it because
    # each of its four refusals has to say in its message what the operator got
    # wrong and how to generate a valid key. Cap 1589 -> 1659, exact.
    # fix(#1882 audit): +15 refusing SECRET_ENCRYPTION_KEY_PREVIOUS equal to
    # SECRET_ENCRYPTION_KEY. The chain would hold one key twice, so the
    # rotation script would report every row rewritten under the key they
    # already use and then say to retire it. Cap 1659 -> 1674, exact.
    # fix(#1812): -21. Production on ingest-auth-v2 stops; the default keeps it
    # as a consumer for one release and the two round comments go. 1674 -> 1653.
    "backend/app/core/config.py": 1653,
    # fix(#1543): first entry — crossed _RATCHET_INCLUSION_LOC on the change
    # that gave PersistentConfig a batch eviction. The code is small
    # (apply_side_effects_batch, plus splitting the process-local half of
    # apply_side_effects out into a synchronous _apply_local_side_effects so a
    # batch of them cannot interleave). Most of the lines are the docstring,
    # and deliberately: it records the two fixes that look right and are not —
    # reordering the deletes, which mismatches the other way, and evicting
    # before the commit, which lets a reader repopulate the cache with the
    # pre-commit value for a full TTL — and the limit of what a writer-side fix
    # can do, since a reader calling get() once per key still samples at two
    # instants and can straddle the whole step.
    # fix(#1543 follow-up): +11 recording which half of #1539's endpoint
    # residue this closes. #1543 is that residue's named owner, and the split
    # is not guessable from the code: the eviction span is fixed here, while
    # the cached-vs-uncached TTL lag that dominates it is not an eviction
    # problem at all and needs EmbeddingProviderExtension widened. Without the
    # note the next reader assumes an atomic eviction covered both.
    # Cap 1007 -> 1018, exact.
    # PRIV-1: +11 — a PRIVACY_URL PersistentConfig on the "general" tab (not
    # "branding", which ENTERPRISE_ONLY_TABS gates) for the login/register
    # privacy-policy link. Cap 1018 -> 1029, exact.
    # feat(#1691): +13 — the RESTRICT_PUBLIC_VISIBILITY flag (admins-only
    # `visibility: public`) plus the comment pointing at its shared gate in
    # catalog/authorization.py. Cap 1029 -> 1042, exact.
    # fix(#1746 codex r8): +5 — the runtime log-level setter now also calls
    # apply_http_logger_levels() (logging_config.py) after raising root's
    # level, so httpx/httpcore's WARNING floor tracks a LOG_LEVEL change made
    # through the admin settings UI, not just one made at boot.
    "backend/app/core/persistent_config.py": 1047,
    # fix(#1533): first entry — crossed _RATCHET_INCLUSION_LOC on the change
    # that made the run notice the embedding column moving under it. Two
    # guards, both small: _live_column_dims (one pg_attribute read, shared with
    # the pre-flight so a rebuild cannot land between two reads of the same
    # width) and _structural_width_mismatch (the width the provider ACTUALLY
    # returned, checked against the width the run pinned, before the insert).
    # Most of the lines are comment, and they are the part worth keeping. They
    # record why the baseline is the width the run OBSERVED rather than
    # EMBEDDING_DIMS — the two legitimately disagree at rest under
    # ENV_ONLY_CONFIG, so comparing them aborts a healthy run — and why the
    # column read sits ahead of the endpoint block, which returns None from its
    # except and would otherwise skip every check below it on exactly the
    # half-configured install where a column gets altered by hand. The third
    # note is the one a reader would otherwise re-derive: the obvious symmetry
    # of running the force path's pre-flight on the non-force path too costs a
    # provider call per run and breaks the #449 partial-success contract that
    # test_batch_errors_do_not_stop_backfill and
    # test_failed_batch_retries_per_record pin.
    # fix(#1544): the same file also carries the compact-error helpers, whose
    # docstrings record the ordering invariant two review rounds found the hard
    # way — the redactor runs first, on the raw string, because truncation and
    # whitespace collapse each break the pattern it matches on.
    # fix(#1533 review, codex P2): +55 separating a STRUCTURAL width mismatch
    # from an ISOLATED one. The first revision stopped the run on any
    # wrong-width vector, which broke the same #449 isolation the note above
    # defends: one anomalous vector abandoned every remaining record. The lines
    # are _AnomalousVectorWidth (counted by the per-record handler rather than
    # rethrown), the batch check reading agreement ACROSS inputs instead of the
    # first vector, and the retry check asking storage — one input carries no
    # agreement, so the evidence has to come from whether the column moved.
    # The comments carry the part that is not visible in the code: why the
    # retry-path read is paid at all when the drift check two lines up already
    # compares the same two widths. Cap 1013 -> 1068, exact.
    # fix(#1533 review r2, codex P2): +30 for the same lesson one batch size
    # further in. A single-record batch — any catalog sized 1 mod _BATCH_SIZE —
    # made "every vector agrees" vacuously true, so one anomalous vector in the
    # final batch stopped the run. _column_rejects_width splits the fit test
    # away from what a mismatch MEANS, so the batch rule can demand two vectors
    # while the retry rule keeps judging one, and the comment says why they
    # cannot share a predicate: the first attempt at this fix routed one vector
    # through the batch rule and silently disarmed the retry check.
    # Cap 1068 -> 1098, exact.
    # fix(#1533 review r3, codex P2): +37, almost entirely comment. The code is
    # a reorder — flush the pending rows, THEN run the pre-commit drift check,
    # THEN commit — on both the batch and the retry path. The check reads
    # pg_attribute, which locks nothing, so running it before the rows were sent
    # left a window for an ALTER TABLE to take ACCESS EXCLUSIVE and commit
    # unseen; widening to an unconstrained vector then let the old-width inserts
    # succeed and the run report success over a column that had moved. The
    # flush's RowExclusiveLock is what closes it, and the comment says so at the
    # call site because the reason a statement sits where it does is invisible
    # from the statement itself. Cap 1098 -> 1135, exact.
    # fix(#1533 review r4, codex P2): +10 net. The retry's width judgement asked
    # "does this vector fit" before "is the column still the pinned one", and
    # returned early when the vector matched — so a column that moved during the
    # provider call for the LAST retried record was counted as a bad record
    # rather than named as drift, there being no next record whose pre-call
    # check would catch it. It now runs the drift bracket first and reuses
    # _raise_on_pin_drift rather than phrasing the abort locally, so the module
    # keeps ONE author of "the column moved". Cap 1135 -> 1145, exact.
    # fix(#1546): +80. Rows carry the identity of the configuration that
    # produced them, so both write sites stamp `config_fingerprint` from the
    # run's PIN rather than from a read at write time, and both moved from an
    # ORM add to `INSERT ... ON CONFLICT DO UPDATE` — a record whose only row
    # for the active model came from another configuration is now offered as
    # missing, and a plain INSERT answers that with a unique violation instead
    # of a vector. `_upsert_embeddings` and its rationale are most of the
    # count; the rest is why the stamp comes from the pin, which is the whole
    # point of the column. Cap 1145 -> 1225, exact.
    # fix(#1549): +140. The bulk DELETE is gone; `_replace_embeddings` and
    # `_delete_embeddings_for` remove a batch's old rows inside the transaction
    # that writes their replacements, so an aborted force run leaves the records
    # it reached rewritten and the rest exactly as they were rather than leaving
    # an empty table. The comments carry the two things a reader cannot see from
    # the statements: why the delete must precede the write and share its
    # transaction, and why the COMMIT belongs to the caller rather than to that
    # function (#1579's drift check has to run while the write still holds its
    # lock). fix(#1581): the batch counts the rows it wrote rather than the
    # texts it was handed, and hands the unanswered tail to the per-record
    # retry. fix(#1549 review): +36 more — a strict zip, so a provider that
    # skips a middle input fails the batch into the alignment-safe per-record
    # retry instead of pairing a record with someone else's vector; and the
    # end-of-run reclamation bounded to rows that predate the run, so a vector
    # the ingest path wrote mid-run survives it. fix(#1583 review): +23 more —
    # writes stamp `updated_at` with `clock_timestamp()` on BOTH the insert and
    # the conflict branch, because `now()` is transaction-start time and a batch
    # that spends a provider call in its transaction would otherwise record a
    # time from before it asked, which #1583's `updated_at DESC` anchor reads as
    # the wrong row. fix(#1584 review r1): +9 more — the reclamation cutoff moves
    # ABOVE the record fetch, because the fetch is the observation it protects
    # and a cutoff taken after it leaves the whole materialisation window
    # unguarded. fix(#1584 review r3): +20 more — the reclamation stops asking a
    # CLOCK whether a row predates the run and asks whether the row is still the
    # version the run observed, as (record_id, updated_at) pairs. A cutoff got
    # this wrong in both directions: it deleted fresh vectors whose writer read
    # a different clock, and spared stale ones stamped ahead of the database by
    # a pre-release writer, which moving the writers to clock_timestamp() cannot
    # retroactively fix. The snapshot is narrowed to TITLELESS records, a
    # superset of what the reclamation can reach, so it is not a copy of the
    # embeddings table in worker memory. Cap 1225 -> 1475, exact. Then +5: the
    # one edge that narrowing gives up (a title cleared between the snapshot
    # and the fetch defers that record's reclamation to the next force run) is
    # stated where the narrowing is decided. Cap 1475 -> 1480, exact.
    # fix(#1584 review r4): +47 — an unchanged row is not proof of an unchanged
    # record. The ingest writer skips its write on an unchanged content hash, so
    # an editor restoring exactly the content a vector was computed from leaves
    # the row's version untouched, and version matching alone would reclaim a
    # vector that is valid again. The reclamation now re-reads each record it is
    # about to reclaim (`_records_still_empty`, through the port's real loader)
    # and spares those no longer empty; the content-field extraction the run
    # and the re-check share moved into `_content_fields`. Cap 1480 -> 1527,
    # exact.
    # fix(#1584 review r5): the re-read and the delete hold the record. They
    # were two statements with a gap, and an editor restoring content in it had
    # the writer skip on an unchanged hash before the delete took the row.
    # `_records_still_empty` now locks the chunk's records FOR UPDATE and
    # `_reclaim_observed_rows` runs re-check, delete and commit per chunk in
    # one transaction. Cap 1527 -> 1555, exact.
    # fix(#1709 review r6): +33 — the cooperative per-batch stop: an opaque
    # should_continue callback polled at each batch boundary before the
    # provider call, so a user cancel whose best-effort queue abort was lost
    # costs at most one batch of provider spend instead of the whole
    # remaining catalog racing a successor run. Kept opaque here (the queued
    # caller passes a fenced job-row read) because this module knows records
    # and vectors, not jobs. Cap 1555 -> 1588, exact.
    "backend/app/processing/embeddings/backfill.py": 1588,
    # feat(#1219): first entry — crossed _RATCHET_INCLUSION_LOC, exactly as
    # the inclusion rule's own comment predicted for this file ("watched by
    # nothing until they cross 1000. The threshold catches them then"). The
    # lines bought the refresh run row's creation at DISPATCH: the
    # create_pending_run call in reupload_commit, the origin-kind decision it
    # shares with the branch below it, and a defer-guard rollback that
    # finalizes the run as failed when the queue is unreachable, so a dispatch
    # that provably never happened does not read as `pending` for an hour.
    # feat(#1219 amendment): +22 — the dispatch door is now the admission
    # gate. `uq_refresh_runs_one_active` refuses a second active run per
    # dataset, and this handler turns that IntegrityError into ADR-002
    # Decision 5b's 409 `dataset_busy`. The lines are the try/except, the
    # rollback that keeps the refused job re-committable, and the comment
    # recording why admission belongs here rather than at the worker's
    # advisory lock. Cap 1005 -> 1027, exact.
    # fix(#1274 review): +19 — _require_reupload_source, the guard that
    # rejects a source-less commit BEFORE the run row reserves the dataset.
    # Its docstring carries the trap: a presigned job's file_path is an empty
    # STRING, which the queue-time is-None check cannot see, and the stale
    # reservation it left blocked every refresh for the bound-job timeout.
    # Cap 1027 -> 1046, exact.
    # feat(#1221): +79 — raster replace. The eligibility gate stops refusing
    # raster_dataset outright and instead constrains it to raster payloads
    # (plus a service-preview refusal, since nothing fetches a GeoTIFF from a
    # feature service); the schema-preview endpoint gains an explicit refusal
    # because a raster has no attribute schema and the ogrinfo call below it
    # would fail as if the upload were broken; and _dispatch_reupload_task
    # extracts the three-way defer out of reupload_commit, which the raster
    # branch pushed past the McCabe gate. Most of the added lines are the
    # extraction's docstring and the raster branch's comment on why it stays
    # off the priority queue. Cap 1046 -> 1125, exact.
    # fix(#1290 review): +10 — both doors swap the creation-shaped
    # check_upload_quota for check_replacement_quota, which needs the
    # dataset_id and gets a comment explaining that a replacement creates no
    # dataset, so refusing it at the count cap locked owners out of replacing
    # what they already own. Cap 1125 -> 1135, exact.
    # fix(#1290 review): +8 — both doors pass the dataset OWNER rather than the
    # requester to the replacement admission, which is the identity the worker
    # reserves against. Wrapped across lines by the formatter.
    # Cap 1135 -> 1143, exact.
    # fix(#1290 review): +6 — the presigned completion door names the dataset
    # it is replacing, so the finalizer runs replacement-aware admission. It was
    # the third admission point and still creation-shaped, so an owner at the
    # dataset-count cap passed the request-time door, uploaded the bytes, and
    # was refused at completion. Cap 1143 -> 1149, exact.
    # +2 — the uncommitted-source cleanup helper re-raises CancelledError
    # instead of swallowing it, mirroring the re-raise convention already used
    # by the other three CancelledError checks in this file. Cap 1149 -> 1151,
    # exact.
    # fix(#1682 codex r3): -7 — the presigned-reupload DB-failure fallback
    # dropped its nine-entry literal for settings.allowed_extensions_list, so
    # the two upload doors cannot answer differently. Ratchet DOWN in the same
    # commit, per the no-headroom rule. Cap 1151 -> 1144, exact.
    # feat(#1676): +50 — the re-upload commit door leases its service token
    # through the same one-use Valkey handoff the refresh door has used since
    # #1220, instead of dispatching it as a durable task argument. Most of the
    # lines are the staging block and its 503, placed before the commit for the
    # reason the refresh door places its own there (a store failure rolls the
    # whole request back rather than stranding a dispatch that can never
    # authenticate), plus the comment recording why a storeless install falls
    # back here and is refused at the refresh door. The rest is the discard
    # wrapper on the defer rollback and the extra dispatch argument.
    # Cap 1144 -> 1194, exact.
    # fix(#1709 review r4 P1): +50 — the commit fence in reupload_commit: a
    # same-value CAS on the job's (pending, attempt_id) pair executed in the
    # SAME transaction that flushes the DatasetRefreshRun, so a cancel that
    # lands between the handler's pending read and its commit rolls the run
    # back into a 409 instead of stranding a pending run bound to a
    # cancelled job (which held uq_refresh_runs_one_active against every
    # refresh until the stale-run sweep). Over half the lines are the
    # comment recording both serializations and why the lock order cannot
    # deadlock against the cancel endpoint. Cap 1194 -> 1244, exact.
    # fix(#1746): +38 — reupload_commit applies the strict header-token policy
    # before it reserves anything, so a WFS/OGC token outside the base64url
    # charset is refused with the same 422 the refresh door returns instead of
    # burning its single-use credential and dying in ogr2ogr. Most of the lines
    # are the comment saying why the check sits ahead of `create_pending_run`
    # (a token that cannot work must not take the one-active-run admission
    # slot) and why ArcGIS is exempt. Cap 1244 -> 1282, exact.
    # feat(#1746): +12. The commit body's structured `auth` object becomes one
    # credential at the top of the handler and is passed to
    # `resolve_dispatch_credential` as a credential rather than a bare token.
    # The rest is the note on why `auth` joins `token` in the model_dump
    # exclusion: user_metadata is a durable JSONB column and that dump is a
    # whitelist by omission. Cap 1282 -> 1294, exact.
    # feat(#1746 B2b): +12. `_service_format` and `_job_service_format` resolve
    # the origin's canonical format once for both service doors, the commit
    # door composes its wire value from it before anything is written or
    # reserved (replacing the hand-rolled charset block), and the service
    # preview door converts its own `auth` object the way the four siblings
    # do. Cap 1294 -> 1306, exact.
    # fix(#1768): +61. `_refuse_if_origin_changed` re-reads the dataset's
    # origin after the run row takes the one-active-run slot and refuses a
    # stale `expected_origin_kind` with 409 `origin_changed`. It is a helper
    # rather than an inline block because two more branches in the handler
    # crossed the McCabe gate, which is the same reason `_dispatch_reupload_task`
    # exists. Most of the lines are its docstring: which window the condition
    # closes, why the reservation is what makes the re-read decisive instead of
    # one more racing read, and why an absent value asserts nothing.
    # Cap 1306 -> 1367, exact.
    # fix(#1770 round 35): the reupload door judges header_auth_job_queue on
    # the composed line before the store lease, and _dispatch_reupload_task
    # grows a service_queue parameter so the verdict reaches the configure()
    # call that used to hardcode the task's own queue. Cap 1367 -> 1386,
    # exact.
    # fix(#1846 review round 4): +10. This handler wrapped the preview in
    # try/finally with no `except`, so a content refusal -- a deliberate 4xx
    # whose message names the fix -- reached the client as a 500 here while the
    # sibling `preview_file` mapped it to 422. The lines are that branch and
    # the comment saying which endpoint it is matching.
    # Cap 1386 -> 1396, exact.
    # fix(#1848): +43. Three doors release the pooled connection before their
    # network or GDAL work; the added lines are the releases, their comments,
    # and the locals read off the ORM instances the rollback expires. The
    # audit round added the two compare-and-set writes that keep the
    # commit-first door from binding onto a row the stale-pending sweep
    # reclaimed mid-upload, plus their refusal. Codex round 2 added the
    # `staged_at` stamp to the same bind, which restarts the pending window
    # for a local upload whose absolute path never reaches the sweep's
    # completion class. Codex round 3 added the dataset binding to both
    # guarded writes, because the early commit releases the foreign-key lock
    # and a dataset deleted mid-upload nulls the job's binding.
    # Cap 1396 -> 1455, exact.
    # fix(#1848): +51. The presigned door commits before storage is asked for
    # anything and binds through the guard; the guard, the refusal and the
    # bind are helpers the direct door now shares. Cap 1455 -> 1506, exact.
    # chore(#1812): -18, the reupload door and _dispatch_reupload_task lose the
    # service_queue verdict, its parameter and the configure() branch. Cap 1506 -> 1488, exact.
    "backend/app/modules/catalog/datasets/api/router_reupload.py": 1488,
    # fix(#1218 review): +5 — VRT assembly stamps last_refreshed_at like every
    # other creation path, so a post-migration VRT does not report null while
    # a backfilled one carries a timestamp, with a note on why it is a Python
    # datetime and not func.now(). Cap 1071 -> 1078, exact.
    # fix(#1290 review): +28 — `last_regenerated_at` is stamped with the instant
    # the member snapshot was READ rather than the instant the VRT was
    # published. Most of the added lines are the comment: the field names the
    # state the artifact was built FROM, so a member replaced during the build
    # now reports stale instead of being vouched for as healthy, and the
    # clock-authority finding (both sides are app-side UTC, so no DB round trip
    # is needed and moving one side alone would break it) has to be written
    # down where the next reader will look. Cap 1078 -> 1106, exact.
    # fix(#1290 review, round 10): +12 net — snapshot_member_sources extracted
    # so BOTH VRT tails read their members through one function that stamps
    # before it reads. The creation tail had no snapshot at all and the
    # regenerate tail captured one after its query; putting the order inside
    # the only function that does the read makes the wrong order unwritable
    # rather than merely discouraged. Cap 1106 -> 1118, exact.
    # fix(#1290 review, round 12): +22 — built_from_map plus its persistence in
    # both tails. Staleness stopped being a timestamp comparison and became a
    # state one: the published VRT records the member URIs it was assembled
    # from, and health compares what-is against what-was-built-from. Postgres
    # cannot stamp commit time from inside a transaction, so no clock scheme
    # could express "committed after my snapshot" — three rounds of timestamp
    # fixes each left a window. Cap 1118 -> 1140, exact.
    # feat(#1267): +10 — the dataset's last_refreshed_at is stamped at the
    # generation's own completed_at instant, in the same transaction as the
    # generation swap, so source_freshness (#1224) reads a live signal for a
    # VRT instead of the creation-time floor forever. Most of the lines are
    # the comment recording why it reuses generation.completed_at rather than
    # a fresh now() call. Cap 1140 -> 1150, exact.
    # fix(#1327): +150 — the compensable-links pattern lives here: two helpers
    # (staged_source_ids_or_none, apply_staged_source_links) plus the phase-1
    # switch to the staged member set, the member-still-exists check that fails
    # a run whose staged source vanished, and the apply inside the publish
    # transaction. Most of the lines are the reasoning: why NULL means "changes
    # no membership", why apply is an upsert rather than delete-and-insert, and
    # why the applied list is the one the build read. Cap 1150 -> 1300, exact.
    # fix(#1327 codex P1): +44 — a second registered task name,
    # `regenerate_vrt_staged`, that forwards to the same body. It is the
    # rolling-deploy gate: a pre-#1327 worker has no such task and fails the
    # job (procrastinate TaskNotFound) instead of rebuilding from the live
    # links and reporting success, which would silently drop an accepted add or
    # remove. Nearly all of the lines are the comment recording why a marker
    # KWARG could not do this (the old signature ends in `**kwargs`, so an
    # unknown keyword is swallowed) and where the refused delivery lands.
    # Cap 1300 -> 1344, exact.
    # fix(#1329 follow-up): +10 — bump tile_cache_version in the VRT swap
    # transaction; the third pointer-swap door finally rolls the version.
    # fix(#1778): +32 — both VRT tails guard their publishing COMMIT with the
    # shared `publish_commit_landed` probe and reap on what it observed rather
    # than on a flag set after the await returned, and `ingest_vrt`'s terminal
    # failure write moves to the shared `_cleanup_staging_on_failure` so a
    # failed build finally emits `ingest_failed`. The dead `final_status`
    # string both functions no longer read is gone. Cap 1354 -> 1386, exact.
    # fix(#1778 codex r1): +56 — both VRT tails STAND DOWN on an observed
    # publish (return instead of re-raising) and both failure handlers refuse
    # to run at all once the publish is durable, because the generation write
    # is not fenced the way the job and asset writes are and `get_vrt_status`
    # plus the stale-generation sweep read what it stamps. The generation
    # update also gained its own `status != 'completed'` fence, so the rule is
    # stated at the write and not only at the caller. Most of the lines are the
    # two handler comments naming the reader each false failure reaches.
    # Cap 1386 -> 1442, exact.
    # fix(#1778 codex r2): +38 — the superseded-generation reap is a named
    # helper called from both the success path and the stand-down, because it
    # is the only deletion of the previous generation's artifact and a
    # stand-down that skipped it stranded bytes no row references and no quota
    # counts. `ingest_vrt` records that it has nothing to reap on that path.
    # Cap 1442 -> 1480, exact.
    # fix(#1778): +16. The storage keys are registered before their puts
    # rather than after (a cancelled put can have completed), the two in-thread
    # source reads go through the safe-open-env wrappers in `raster/vrt.py`, and
    # `create_vrt_dataset` accepts a caller-chosen dataset id so the manifest
    # tail can name its object keys before phase 2 opens. Cap 1480 -> 1496.
    # fix(#1778 codex r3): +34. The two safe-env wrappers moved here from
    # `raster/vrt.py` and call `extract_raster_metadata` / `generate_quicklook`
    # through this module's globals. Those two names are patch targets for the
    # VRT integration and source-management suites, and putting the wrappers in
    # `raster/vrt.py` with function-level imports removed the attributes AND
    # would have made the patches no-ops once restored. The docstrings say so,
    # because the next reader will want to move them back. Cap 1496 -> 1530.
    # fix(#1778 codex r4): +38. `ingest_vrt` puts the VRT and its quicklooks
    # before the terminal commit and recorded nothing, so a kill in between
    # lost `written_storage_keys` with the process AND rolled back the dataset
    # id the keys embed. It now preselects that id and records the intended
    # keys on the job row first, the way `ingest_raster` does. Most of the
    # growth is the comment saying why the id is decided outside phase 2.
    # Cap 1530 -> 1568, exact.
    # fix(#1778 audit): +7. record_unpublished_storage_keys now reports a
    # confirmed fence miss rather than silently committing nothing, and this
    # call site checks it: a miss means a retry has already superseded this
    # attempt, so it returns before generating quicklooks or ever reaching
    # phase 2, instead of relying on phase 2's own attempt-fenced load to
    # catch it downstream. Cap 1568 -> 1575, exact.
    # fix(#1778 audit r11): +25. Neither of this file's two "phase 2" blocks
    # goes through `_job_phase_session` (they predate the helper and match
    # the fence by hand), so both gain `IngestJob.status == "running"`
    # directly in their own SELECT, matching the sibling tails. The
    # `ingest_vrt` one closes the same object-storage leak the other raster
    # tails' phase 2 does; the `regenerate_vrt` one closes a job-completion
    # race the existing `current_generation_id` check does not cover, since
    # that field lives on a different row than `ingest_jobs.status` and the
    # sweep never touches it. Cap 1575 -> 1600, exact.
    # fix(#1778 audit r12): +28. `ingest_vrt`'s hand-matched phase-2 SELECT
    # gains `.with_for_update(key_share=True)`, the same TOCTOU close as the
    # other two raster tails, since its puts sit inside this same session
    # exactly like theirs do. `regenerate_vrt`'s own phase-2 SELECT is
    # deliberately left unlocked -- most of the growth here is the comment
    # explaining why: it loads the job row before a RasterAsset row a few
    # lines down, and `cancel_job` locks those two in the opposite order for
    # a vrt_regenerate job specifically to avoid an AB-BA deadlock with this
    # worker, so locking the job row here first would reopen that cycle. Cap
    # 1600 -> 1628, exact.
    # fix(#1755 item 11): +12. Both task tails route every cleanup step
    # through `cleanup_step`: three in `ingest_vrt`, four in `regenerate_vrt`,
    # which stops two heartbeats. Cap 1628 -> 1640, exact.
    # fix(#1847): the lock order, its gate and its 409 mapping. Cap 1653, exact.
    # fix(#1847): the phase-2 job load locks the row and the lock-order
    # rationale left the source. Cap 1653 -> 1640, exact.
    "backend/app/processing/ingest/tasks_vrt.py": 1640,
    # fix(#1202 review r5): +29 — sweep the presigned staging key at job end.
    # A completed presigned job points file_path at its frozen copy, so this
    # reaper never touched the key the client's PUT URL can still recreate.
    # Ownership comes from owned_presigned_staging_key, which refuses a
    # fan-out child's inherited parent key. Cap 1058 -> 1087, exact.
    # fix(#1202 review r5b): -12 — that block moved to
    # `tasks_common.reap_presigned_staging_object` so the raster tail could
    # share it. Ratchet DOWN in the same commit, per the no-headroom rule.
    # Cap 1087 -> 1075, exact.
    # fix(#1207): +1 — the reap call gained the final_status keyword when the
    # terminal-status guard moved into the shared helper.
    # fix(#1213 review r2): -16 — the inline BA-09 block became a call to the
    # shared helper. Ratchet DOWN in the same commit.
    # fix(#1213 review r4): -1 — the now-dead file_path argument dropped from
    # the call. Ratchet DOWN in the same commit.
    # fix(#1213 review r6): +4 — the caller states its retry semantics.
    # feat(#1218): +11 — both finalize call sites now pass their origin_ref.
    # The service one keeps the base URL and layer id as separate keys so a
    # refresh can re-address the layer without re-parsing the enriched URI.
    # Cap 1063 -> 1074, exact.
    # fix(#1218 review r3): +16 — the service ref records the SERVICE-NATIVE
    # layer identifier via service_layer_identity, so WFS/OGC rows name their
    # typename instead of storing nothing. Most of it is the comment recording
    # that build_gdal_source makes id and name mutually exclusive per service,
    # which is why one key suffices. Cap 1074 -> 1090, exact.
    # fix: +3 — pass original_filename (job.source_filename) to run_ogrinfo
    # and run_ogr2ogr so a corrupt vector upload gets a friendly message
    # instead of GDAL's raw driver-enumeration stderr. Cap 1090 -> 1093, exact.
    # fix(#1675): -10 — the inline paged loop moved to tasks_common's shared
    # run_paged_arcgis_service_fetch. Cap 1093 -> 1083, exact.
    # feat(tier-1 vector import): +2 — source_format is resolved once, before
    # step 3b instead of after it, because the DBF field-name-truncation
    # warning is Shapefile-only and a File Geodatabase now arrives in a .zip
    # too. The derivation itself moved out to ingest/source_format.py, shared
    # with the reupload path. Cap 1083 -> 1085, exact.
    # feat(#1676): +32 — `ingest_service` accepts a `credential_ref` and
    # redeems it once. Nearly all of it is two comments: why the claim sits
    # AFTER phase 1 (the failure write below is fenced on `status == 'running'`,
    # which phase 1 is what sets, so claiming earlier would leave a
    # `credential_expired` failure unrecorded and the job pending until the
    # stale sweep), and why the failure handler now scrubs the claimed secret
    # by exact value the way `reupload_service` does — this task holds the
    # value now, and the pattern layers only match tokens shaped like URLs.
    # Cap 1085 -> 1117, exact.
    # fix(#1746): +9 — `ingest_service` takes `pass_context=True` (the only
    # way a task can learn its own queue-row id) and the
    # `purge_token_on_failure` wrapper, plus the comment saying what the
    # context is for. Cap 1117 -> 1126, exact.
    # fix(#1746): +8 — the auth_required marker on a first service import's
    # origin_ref, so a token-bearing import is refusable at the refresh door.
    # One key and the comment saying why the value is True-or-None: absent
    # means "not known to need auth", which is where every dataset imported
    # before the marker sits. Cap 1126 -> 1134, exact.
    # fix(#1746 codex r1): +9 — same narrowing of the marker comment, plus the
    # note that the refresh door treats the key as a gate and not a verdict.
    # Cap 1134 -> 1143, exact.
    # fix(#1778): +18 — the upload-safety exit stops unlinking the file (the
    # #1290 correction the two raster tails already carry), and both terminal
    # failure writes move to the shared `_cleanup_staging_on_failure`, so a
    # failed file or service import emits `ingest_failed` and persists a
    # redacted message. Net of two hand-rolled UPDATE blocks and two now-unused
    # IngestJob imports removed; the rest is the comment saying which exit owns
    # the unlink decision. Cap 1143 -> 1161, exact.
    # fix(#1778): +48 — `_heartbeat_service_import_progress`'s per-tick session
    # open/write/commit/close now runs under `asyncio.shield`, split into its
    # own `_service_import_heartbeat_tick` helper so the loop can shield the
    # whole thing. A `.cancel()` used to be able to land mid-connect or
    # mid-commit; asyncpg does not always finish tearing a connection down
    # cleanly when that happens, and the leftover surfaced later, against
    # unrelated work, as `ConnectionError: unexpected connection_lost() call`
    # (test_ingest_progress.py's service-worker-progress test, seen in the
    # merge queue). Cancellation can now only land at the `asyncio.sleep`
    # between ticks. Cap 1161 -> 1209, exact.
    # fix(#1778 codex r2): +36 — the shield alone bounded WHERE a cancel could
    # land, not HOW LONG draining one could take: a tick stuck on something
    # with no timeout of its own (another transaction's row lock inside
    # `session.commit()`) could hang the drain, and with it `ingest_service`'s
    # own `finally`, forever. `_SERVICE_IMPORT_HEARTBEAT_DRAIN_TIMEOUT_SECONDS`
    # bounds it; `asyncio.shield` still keeps the tick itself running in the
    # background on a timeout rather than cancelling it, so its connection
    # still gets to close cleanly. Cap 1209 -> 1245, exact.
    # fix(#1778 codex r3): +36 — round 2's drain deadline bounded how long the
    # caller would WAIT for a stuck tick, but the tick's own connection stayed
    # checked out and blocked until whatever held the lock let go, so
    # repeated stalls could still exhaust the pool. `_service_import_
    # heartbeat_tick` now sets `lock_timeout`/`statement_timeout` on its own
    # transaction, so a blocked commit fails INSIDE Postgres within a few
    # seconds and releases its connection the ordinary way; the drain deadline
    # survives only as a safety net for what a DB-side timeout cannot cover.
    # Cap 1245 -> 1281, exact.
    # fix(#1778 codex r6): +3 — the timeouts move into
    # `_job_phase_session(lock_and_statement_timeout_ms=...)` so they also
    # cover that helper's own initial SELECT, which used to run before this
    # function's own `SET LOCAL` calls and could stall behind a lock the row
    # never got far enough to hit. Cap 1281 -> 1284, exact.
    # fix(#1778 codex r11): +49 — the tick's own SELECT is a snapshot, not a
    # lock: if this shielded tick's connection stalls past the caller's
    # cancellation drain, the caller moves on while the tick is still alive,
    # and `_finalize_ingest` can commit status="complete"/progress=1.0 (or a
    # retry can rotate attempt_id) before the tick's own commit runs. An
    # unconditional ORM commit would then overwrite that finalized row by
    # primary key with a stale progress. The write is now a single UPDATE
    # gated on id + attempt_id + status="running" + current_step="ogr2ogr" +
    # progress still below what it is about to write, matching the
    # attempt-fenced shape `_finalize_ingest` already uses via
    # `require_ingest_job_update`; zero rows affected logs at debug and does
    # nothing. Cap 1284 -> 1333, exact.
    # fix(#1778 audit r11): +23, rebased onto the above rather than the 1161
    # baseline it was originally measured against. Both of this file's
    # "phase 2" call sites (`ingest_file`, `ingest_service`) gain
    # `require_status="running"` on their `_job_phase_session` load. Neither
    # writes an untracked storage object -- each phase's own terminal write
    # already fences on status via `require_ingest_job_update`, so a
    # fenced-out attempt cannot resurrect a failed row -- but this stops a
    # paused, not-dead worker from running the whole finalize pipeline
    # against a doomed row in the first place, for consistency with the
    # raster tails. Cap 1333 -> 1356, exact.
    # fix(#1755 item 11): +36. `ingest_service`'s `finally` block routes both
    # cleanup calls through the new shared `_finally_cleanup` helper, so a
    # heartbeat-stop or staging-drop failure logs (redacted, exc_info)
    # rather than replacing the ingest exception in flight; the #1753 token
    # purge still runs, since the helper never re-raises. Cap 1356 -> 1392,
    # exact.
    # fix(#1755 item 11, follow-up): -24. The private `_finally_cleanup` copy
    # moved to `tasks_common.cleanup_step`, and the two `finally` blocks the
    # first pass left bare are routed too: `ingest_file`'s five steps, and the
    # nested one that stops the service-import progress heartbeat, where
    # awaiting the cancelled task re-raises anything the heartbeat body itself
    # failed with. Cap 1392 -> 1368, exact.
    "backend/app/processing/ingest/tasks_vector.py": 1368,
    # --- entered by the inclusion rule ------------------------------------
    # Crossed 1000 lines adding the "unable to open datasource" friendly-
    # message mapping shared by run_ogrinfo and run_ogr2ogr: the pattern
    # regexes (GDAL's driver-enumeration line and SQLite's own "file is not
    # a database"), the per-extension format-label table, and the message
    # builder, plus the log-then-raise branch duplicated at both call sites'
    # failure handling (ogrinfo's text-fallback raise and ogr2ogr's raise).
    # Exact line count at entry.
    # fix(codex review, #1640): +16 — a third pattern, SQLite's "database
    # disk image is malformed" (a valid header with a corrupt interior
    # b-tree page — distinct from "file is not a database", which is a
    # corrupt header). Empirically confirmed against a real GPKG with a
    # byte-flipped leaf page. Cap 1073 -> 1089, exact.
    # fix(#1746): +7 — the GDAL bearer-header tempfile now pins dir=
    # settings.upload_staging_dir (plus an os.makedirs and a comment
    # explaining why) so it lands on the staging volume the stale-file
    # sweep can reach, instead of the system tempdir. Cap 1089 -> 1096, exact.
    # fix(#1746 codex r2): +8 — that dir is now gdal_header_dir(), the
    # container tmpfs, not the backed-up staging volume; the os.makedirs went
    # with it (the helper owns creating its own 0700 directory) and the rest is
    # the comment saying why a credential file does not belong on a volume
    # scripts/backup-entrypoint.sh archives. Cap 1096 -> 1104, exact.
    # feat(#1746 B2b): +74. `_sanitize_authorization_token` became a header
    # LINE validator, because under plan D9 what crosses the queue is the
    # finished line rather than a bare token: it checks the shape, the field
    # name and the value charset, and keeps the base64url charset and the
    # length floor on the bearer branch alone. Most of the lines are the three
    # policy constants (each a full sentence, none of them naming any part of
    # a credential) and the docstring recording which branch may still name an
    # offending character and why the other branches may not. The rest is the
    # writer dropping its own `Authorization: Bearer ` prefix and pinning the
    # Authorization redirect rule on the env that carries the header file.
    # Cap 1104 -> 1178, exact.
    # fix(#1746 B2b review r3): +57. A value with no separator is the
    # PRE-#1770 wire format, and a worker starting on a queue that already
    # holds authenticated jobs reads exactly that; refusing it would fail every
    # one of them deterministically at the next deploy and spend the
    # single-use credential before ogr2ogr started. `_legacy_bearer_line`
    # composes it through `build_credential_header`, so this module still
    # produces no header of its own, and the charset it accepts is the one the
    # previous version already enforced. Most of the lines are the two
    # docstrings recording that and the `service_format` parameter that keeps
    # the builder the authority on which formats may carry a header.
    # Cap 1178 -> 1235, exact.
    # fix(#1746 B2b review r4): +2. The redirect-rule comment at the header
    # file's env says which value is set and why it is IF_SAME_HOST rather
    # than NO: NO drops the credential on a same-host canonical redirect too,
    # which a protected service answers with a 401. Cap 1235 -> 1237, exact.
    # fix(#1746 B2b review r13): +14. Before the header file is written, the
    # source's own service description is checked for an operation endpoint on
    # another origin: GDAL applies the header file to whatever that document
    # advertises, and those are fresh requests no redirect rule can see. The
    # check itself is `platform/service_endpoints.py`, shared with the door,
    # because the two callers are in layers that may not import each other.
    # Cap 1237 -> 1251, exact.
    # fix(#1746 B2b review r14): +5. The endpoint check is handed the finished
    # header line rather than only the header NAME, because a protected
    # service answers an anonymous description read with a 401 and the check
    # then learned nothing, and it is scoped to the layer being imported so a
    # collection past the listing's first page is still the one checked.
    # Cap 1251 -> 1256, exact.
    # fix(#1746 B2b review r16): +36. A protected OGC API collection is read
    # in-process and handed to ogr2ogr as a local file, because GDAL applies a
    # header file to every request it makes and an items page names its own
    # successor, so the credential would follow a service-chosen `next` to any
    # origin. GDAL 3.10.3 has no per-origin header scope; that was measured.
    # The reader is `platform/service_items.py`; these lines are the branch,
    # the argv swap and the extract's cleanup. WFS is untouched.
    # Cap 1256 -> 1292, exact.
    # fix(#1746 B2b review r17): +22. One clock now covers the in-process page
    # walk and the subprocess, because the walk ran before `timeout` began and
    # the HTTP client's timeout is per inactivity, so a service answering
    # slowly forever held a worker and then still got the full half-hour. The
    # lines are the deadline, the remaining-budget arithmetic with its floor,
    # and arming the origin-contact callback at the first page rather than at a
    # spawn that no longer happens first.
    # Cap 1292 -> 1314, exact.
    # fix(#1746 B2b review r23): +26. The WFS capabilities preflight
    # authenticates against the origin before the subprocess exists, so it now
    # arms the origin-contact callback and runs under the caller's deadline;
    # a 401, malformed XML or cross-origin endpoint used to leave
    # `last_checked_at` stale. One `fire_once` callback is shared by the page
    # walk, the preflight and the spawn, so no site has to assume another one
    # fired it, and the remaining-budget arithmetic moved to just before the
    # spawn where it accounts for both preflights.
    # Cap 1314 -> 1340, exact.
    # fix(#1746 B2b review r24): +2. The materialiser returns a described
    # extract rather than a bare path, so the preview can report the
    # collection's own size instead of the sample it was handed.
    # Cap 1340 -> 1342, exact.
    # fix(#1770 round 49 P3): +12. `_sanitize_authorization_token`'s D9
    # (separator-present) branch now calls `register_credential_secret`
    # on the validated value before returning it -- previously only
    # `_legacy_bearer_line`'s bare-token branch reached `build_credential_
    # header`, the registry's only other producer, so the exact-value scrub
    # pass was inert for the whole worker service-import path on the
    # format every current job actually uses. Cap 1342 -> 1354, exact.
    # fix(#1840 audit round 1): +12. `_legacy_bearer_line` asks
    # `requires_header_token_policy` itself before reaching the builder,
    # instead of inferring "this format carries no header line" from the
    # builder answering None -- which stopped being true when lane C2 taught
    # it to compose an ArcGIS header for the httpx transport. Both call sites
    # already gate on the same two formats; this is the trust-boundary copy
    # AGENTS.md requires, and the comment is the argument for keeping both.
    # Cap 1354 -> 1366, exact.
    # fix(#1840 audit round 2): +5. That gate moved up to
    # `_sanitize_authorization_token`'s own entry, because inside
    # `_legacy_bearer_line` it covered only the BARE-token branch -- a
    # finished `Authorization: Bearer <tok>` line arriving for an ArcGIS job
    # walked straight through to the header file. Both shapes refused now, and
    # the comment at each end says which half it is. Cap 1366 -> 1371, exact.
    # fix(#1844): +11. `_sanitize_authorization_token` registers the header
    # LINE rather than the value it carries. `_secret_variants` derives the
    # bare token, the basic blob and the decoded cleartext only from a secret
    # containing `": "`, so registering `Bearer <tok>` expanded to nothing and
    # the worker could not exact-scrub what an origin echoes back. The added
    # lines are the comment saying why the earlier reasoning (keep the header
    # NAME out of the registry) is still satisfied by the line.
    # Cap 1371 -> 1382, exact.
    # fix(#1844 codex r1): +10. The bearer length and charset checks moved
    # above the registration, so a line this function REFUSES no longer seeds
    # the exact-value registry -- `Authorization: Bearer e` used to register
    # the variant `e` and turn every later log line into redaction markers.
    # The lines are the guarded branch plus the comment saying which failure
    # the ordering prevents.
    # Cap 1382 -> 1392, exact.
    # fix(#1846, GHSA-hrf5-v3cq-frx5): +25. Every vector GDAL subprocess in
    # this module now names which drivers may open its source and which may
    # never be registered, instead of handing a caller-supplied file to the
    # whole driver set. The lines are the two helper calls per entry point, the
    # argv restructure that puts the `-if` pairs before the source, and the
    # comments saying what each clamp is for and why the local and service
    # variants differ. Cap 1392 -> 1417, exact (rebased onto #1844, which took
    # the same file 1371 -> 1392; the two changes touch different functions).
    # fix(#1846 audit round 1): +11. GPKG and SQLite are pointer-following
    # drivers too, and neither clamp can exclude them, because a GeoPackage is
    # the primary supported upload format and the file really is one. So the
    # three staged-upload entry points also read the schema and refuse a
    # database that names a source outside itself, here rather than only at the
    # doors, because the preview runs before the door that validates a
    # presigned upload's whole body. Cap 1417 -> 1428, exact.
    # fix(#1846 review round 4): +5. The three staged-upload call sites run the
    # content check through `run_in_thread_draining` instead of inline, so a
    # schema walk cannot sit on the event loop of the request that uploaded the
    # file. Cap 1428 -> 1433, exact.
    # fix(#1828): +6. `run_ogr2ogr_service` refuses a credentialed WFS that
    # names no layer before the origin check and the spawn. Cap 1433 -> 1439.
    "backend/app/processing/ingest/ogr.py": 1441,
    # fix(#1846, GHSA-hrf5-v3cq-frx5): first entry. This module crossed the
    # 1000-line threshold when the content check landed: the SQLite schema
    # reader, the archive member walk that identifies members by their bytes
    # rather than their names, and the shared decompression budget the walk
    # spends. The comments are most of it, because the two facts that make the
    # code correct (GDAL identifies on content, and it finds a VRT root by
    # substring) are the two a future reader would otherwise re-learn the hard
    # way. Cap set at the exact current count.
    # fix(#1846 audit round 3): +36. Reading a member to its end makes zipfile
    # verify the CRC, so a damaged upload raised BadZipFile -- not a
    # ValueError, which is the shape the upload gauntlet promises and
    # `tasks_vector` catches. The lines are the conversion at both member
    # reads, the restored guard on the archive open, and the comment saying
    # why `validate_zip_safety` could not have caught it on the way past (it
    # never reads member data). Cap 1016 -> 1052, exact.
    # fix(#1846 review round 4): +63. The comment strip became a single
    # left-to-right walk instead of a lazy regex that was quadratic on text
    # holding many `/*` with no `*/` -- uploader-chosen through a valid schema,
    # 64 KB was 3.6 s. Most of the lines are the comment recording that the
    # "standard linear block comment" pattern does NOT fix it, since it looks
    # like it should. The rest is the schema byte cap and the two
    # archive-member error classes (password-protected, unsupported method)
    # that were escaping uncaught. Cap 1052 -> 1115, exact.
    "backend/app/processing/ingest/validation.py": 1115,
    # fix(#1778): +157 for two audit findings that both land in JIT
    # provisioning. One is the REGISTRATION_ENABLED gate plus its exception
    # class, so enabling a provider stops being a way to reopen signup while
    # the Settings screen still reads "off". The other is
    # _reconcile_mapped_role, which re-applies group_role_mapping on a
    # returning user's login -- the mapping used to run only on the login that
    # created the account, so it could grant a role and never revoke one. Most
    # of the lines are the docstring on that helper stating its four
    # preconditions, each of which is what stops a login from taking away a
    # role the IdP said nothing about. Cap 1031 -> 1188, exact.
    # fix(#1778 codex r1): +61 for three round-1 P1s in the same function. The
    # role change now goes through AdminService.set_role_from_identity_provider,
    # so it inherits the last-admin invariant and the key_epoch bump instead of
    # assigning user.roles directly; a refused demotion writes its own audit row
    # and the login continues. The verified-email linking branch gets the same
    # reconciliation the subject-link branch had, and the function docstring
    # enumerates all three return paths so the next one added cannot miss it.
    # Cap 1188 -> 1249, exact.
    # fix(#1778 codex r5): +12. The audit event now fires only on a real change
    # and carries the previous roles the role update actually started from,
    # rather than a snapshot this coroutine took before waiting for the lock.
    # Cap 1249 -> 1261, exact.
    "backend/app/modules/auth/oauth/service.py": 1261,
    # fix(#1778 codex r1): first entry, crossed _RATCHET_INCLUSION_LOC on the
    # change that added set_role_from_identity_provider, the public seam the
    # OAuth group-role reconciliation applies a mapped role through. It exists
    # so that path is the SAME role change the admin router makes rather than a
    # second, weaker copy: the admin-lifecycle advisory lock, the last-admin
    # rule and the key_epoch bump all come from _ensure_not_last_admin and
    # _update_user_role, which stay private. Most of the lines are the docstring
    # saying which invariants were missing and why a refusal is not an error for
    # an IdP-driven caller. 992 -> 1036, exact.
    # fix(#1778 codex r4): +19. The advisory lock now covers the PROMOTION
    # branch too. Skipping it was justified by "a promotion cannot threaten the
    # last-admin invariant", which is true and beside the point: two OAuth
    # callbacks for one account both entered it unserialized, and
    # _update_user_role's delete-then-insert collided on the (user_id, role_id)
    # primary key, failing an otherwise valid login. Cap 1036 -> 1055, exact.
    # fix(#1778 codex r5): +43 for IdentityRoleOutcome and its docstring.
    # set_role_from_identity_provider returned a bare bool, so a caller could
    # not tell "applied" from "was already correct", and the loser of two
    # concurrent promotions reported a change it had not made. It now reports
    # applied/changed plus the previous roles read UNDER the lock, which is what
    # lets the caller audit only a real transition. Cap 1055 -> 1098, exact.
    "backend/app/modules/admin/service.py": 1098,
    # fix(#1113 review): +15 — register_existing_table linearizes a
    # pre-existing geom_4326 (savepoint + error contract mirroring the
    # add_4326_column branch beside it); see linearize_existing_4326.
    # Cap 1017 -> 1032, still exact.
    # fix(#1114): +12 — register_existing_table docstring records the
    # registered-table linear-geometry contract (linearize once at
    # registration, no post-registration policing). Cap 1032 -> 1044.
    # feat(#1218): +7 — register_existing_table stamps the postgis origin
    # pointer (schema-qualified table, no connection detail: gate 2 keeps
    # external federation out of v1). The URI and the ref's table_name are two
    # spellings of one fact, so set_postgis_origin composes both and this call
    # site stays one line. Cap 1044 -> 1051, exact.
    # fix(#1218 review r2): +8 — the call site passes the _schema it resolved
    # from the active tenant context instead of dataset.tenant_id, which is
    # NULL on the ORM instance because the insert trigger fills that column in
    # the database. The comment records why, so nobody "simplifies" it back to
    # reading the row. Cap 1051 -> 1059, exact.
    # fix(#1290 review): +14 — safe_upload_basename, extracted from the two
    # inline `Path(x).name` copies inside save_upload_file so the
    # archived-original key derives from the SAME normalization the upload path
    # applies. Deriving from the raw filename split the key: the logical URI
    # kept a path component the write stripped, so the counted row pointed at
    # nothing. Cap 1059 -> 1073, exact.
    # fix(#1359): +4 — register_existing_table now derives metadata for every
    # table it registers instead of only the spatial ones, so a non-spatial
    # registration stops landing with column_info and feature_count NULL. The
    # added lines are the comment explaining why the branch is gone.
    # Cap 1073 -> 1077, exact.
    # fix(#1443): +21 — generate_table_name gains a third collision probe,
    # against the retired-names table. The two it already had ask what exists
    # NOW, and a delete clears both, so a deleted dataset's table name was
    # handed straight to its successor while a tile worker could still be
    # holding the predecessor's authorization snapshot under that name. Most of
    # the added lines are the comment carrying that reasoning plus why the
    # probe is unscoped by tenant (it has to agree with the catalog probe
    # beside it, and over-collision only costs a suffix). Cap 1077 -> 1098,
    # exact.
    # fix(#1444 review): +21 — the same probe repeated in
    # register_existing_table, which is the one path that takes a table name
    # from the caller instead of generating it. Without it the whole guarantee
    # is bypassable through the front door: recreate a physical table under a
    # deleted public dataset's name, register it as private, and a worker still
    # holding the predecessor's metadata authorizes anonymously against
    # `public` while querying the successor's rows. The comment carries why it
    # refuses rather than renaming the caller's own table. Cap 1098 -> 1119,
    # exact.
    # fix(#1444 review round 2): +47 — the suffix walk now keeps every candidate
    # inside PostgreSQL's 63-byte identifier limit. Retired names accumulate
    # forever, so a 60-char base genuinely reaches `_100`, which is 64 bytes;
    # Postgres truncates that onto the same relation as `_10` while the catalog
    # keeps both untruncated strings, putting two logical names on one table.
    # The lines are `_with_collision_suffix`, three constants, the bound that
    # refuses an exhausted namespace instead of emitting a truncatable name,
    # and the probe prefix that has to be short enough to match a candidate
    # whose base was trimmed — plus the comments tying those last two together,
    # because they are only correct as a pair. Cap 1119 -> 1166, exact.
    # fix(#1444 review round 3): +33 — the retirement probes are tenant-scoped,
    # mirroring migration 0020's per-tenant uniqueness on datasets.table_name.
    # Unscoped, one tenant's deletions cost every other tenant suffixes, and
    # once the round-2 bound landed they could exhaust a shared budget and
    # refuse a title outright. `_retired_tenant_scope` (own tenant plus the NULL
    # scope, with the string->UUID coercion made explicit because a
    # never-matching comparison reads as "nothing is retired") is applied at
    # both probe sites. The comments carry why NULL binds everywhere: it is the
    # single-tenant namespace, and where a row retired before a single -> multi
    # transition sits, since nothing back-stamps this table. Cap 1166 -> 1199,
    # exact.
    # fix(#1452): +12 — the `managed` keyword and the docstring paragraph that
    # says why it is an explicit argument rather than a guess. Registration is
    # called both by an operator handing over a table they own and by the
    # analysis materialize path handing over one it just CTAS'd, and delete now
    # drops only the second; the caller is the only place that knows which.
    # Cap 1199 -> 1211, exact.
    # feat(#1676): +48 — `queue_ingest_job`'s service branch leases the token
    # rather than dispatching it. The 503 branch is the bulk: unlike the two
    # doors that stage before their commit, this runs after `commit_import` has
    # already committed the job, so an unreachable store has to finalize the
    # job row itself before raising or it strands a pending row until the stale
    # sweep. The rest is the discard on the defer rollback and the comment
    # saying the state-1/state-3 choice is not this door's to make.
    # Cap 1211 -> 1259, exact.
    # fix(#1689 codex r1): +25 — the rolling-deploy skew note. A worker from
    # the previous generation takes `credential_ref` through `**kwargs` and
    # discards it, and the review asked for a versioned task name to gate that.
    # The comment records why the gate is the worse option (Procrastinate fails
    # its own job on TaskNotFound but nothing writes the ingest_jobs row, so the
    # user sees a hang instead of a retryable failure) and why the window is
    # narrower here than at the refresh door, where #1220 accepted the same
    # trade. Written down so the next review lands on the decision rather than
    # re-deriving it. Cap 1259 -> 1284, exact.
    # fix(#1709 review r2 P1): +133 — finalize_fan_out_parent: the fenced
    # pending->fanned_out CAS, and the lost-CAS reconciliation that cancels
    # the children this request queued (guarded status CAS, best-effort
    # queue aborts, per-layer results rewritten to failed) so a cancel that
    # beat the fan-out mid-loop cannot leave every child importing. Roughly
    # a third of the lines are the docstring recording why the loser, not
    # the cancel endpoint, owns that reconciliation — only this side knows
    # the full child set. Cap 1284 -> 1417, exact.
    # fix(#1709 review r5 P1): -41 — finalize_fan_out_parent's post-loop
    # loser-reconciliation is DELETED, not kept as defense-in-depth: with
    # the flip preceding every child (claim_fan_out_parent), the window it
    # compensated — children existing while the parent CAS loses — is
    # unreachable, and dead compensation code reads as a live invariant.
    # Replaced by the smaller claim/restore pair, restore being the fenced
    # CR-02 retry contract. Cap 1417 -> 1376, exact.
    # fix(#1737): +26 for the geometry-column-name probe in
    # register_existing_table. A spatial table whose geometry is not named
    # `geom` used to register silently as a non-spatial attribute table; the
    # probe tells that case apart from the deliberate no-geometry path (#1359)
    # and refuses with the offending column name. Cap 1376 -> 1402, exact.
    # fix(#1746): +48 — `_assert_header_token_dispatchable`, called by
    # `queue_ingest_job` before it stashes anything, so a WFS/OGC token outside
    # the base64url charset is refused with the same 422 the refresh door
    # returns instead of burning its single-use credential and dying in
    # ogr2ogr. It is a named helper rather than an inline block because inline
    # pushed `queue_ingest_job` past ruff's C901 ceiling; most of the lines are
    # its docstring, recording the failure it closes and why ArcGIS is exempt.
    # Cap 1402 -> 1450, exact.
    # feat(#1746): +15. `queue_ingest_job` takes a `ServiceCredential` in its
    # own right, so a caller with no HTTP layer can queue an authenticated
    # ingest without assembling a request body for a door to take apart (plan
    # D2). Most of the lines are the docstring paragraph recording that, and
    # why an unsupported method is refused here rather than dispatched as an
    # anonymous fetch. Cap 1450 -> 1465, exact.
    # fix(#1744): +17. One `job=` argument at each of this module's five
    # `defer_with_orphan_guard` call sites, so the guard can stamp
    # `commit_attempted_at` on the row before the task exists. The kwarg is
    # required rather than optional precisely so a new dispatch site cannot be
    # written past it, plus `create_fan_out_jobs` putting the same stamp in
    # the metadata it commits for each child: that door runs inside a worker
    # task and its child cannot be recreated by repeating a user action, so it
    # is the one place the commit-to-dispatch window is worth closing
    # outright. Cap 1465 -> 1482, exact.
    # fix(#1774 review, codex P2): +18. `create_fan_out_jobs` resets the
    # session in its per-layer failure handler. That commit now carries the
    # child's dispatch marker as well as its row, and a transactional failure
    # there left the session refusing every later statement, so one layer's
    # deadlock failed every sibling and stranded the parent `fanned_out` with
    # no child importing. Cap 1482 -> 1500, exact.
    # fix(#1774 review r2, codex P2): +13. That reset expires the parent, and
    # both the next layer and `restore_fan_out_parent_pending` read attributes
    # off the same instance, so a synchronous read would raise MissingGreenlet
    # and turn one layer's failure into a 500. The parent is reloaded in the
    # same breath, and the log line reads a snapshotted id rather than the
    # instance it just expired. Cap 1500 -> 1513, exact.
    # feat(#1746 B2b): +25. `job_service_format` is extracted so the queue-time
    # check and the composition read the same answer, and `queue_ingest_job`
    # composes the wire value (plan D9) from whichever spelling its caller
    # used: the structured credential of plan D2, or the flat bearer token the
    # import-commit door still carries because `ServiceCommitRequest` has no
    # `auth` object yet. Cap 1465 -> 1490, exact.
    # fix(#1746 B2b review r1): +9. The legacy-token pre-check runs only when
    # the flat token is the credential being dispatched: the signature promises
    # the structured one wins when both are given, and the check judged the
    # losing one, so a stale legacy token refused a valid credential. Most of
    # the lines are the comment saying which value is judged where.
    # Cap 1490 -> 1499, exact.
    # Rebased across #1774: that branch's three raises (1465 -> 1482 -> 1500
    # -> 1513) and this one's two (1465 -> 1490 -> 1499) are edits to
    # different parts of the module, so the merged file carries both. Measured
    # rather than added up. Cap 1513 -> 1547, exact.
    # fix(#1770 round 35): +13 — the import door judges header_auth_job_queue
    # on the line job_service_format/wire_credential just composed, before
    # the credential-store lease may swap it for a reference, and configures
    # ingest_service's queue with the verdict. Cap 1547 -> 1560, exact.
    # fix(#1738): +8 of docstring, no code. register_existing_table's stated
    # contract was "linearize once, do not police the table afterward", which
    # a reader could take as "the owner's writes are picked up somehow". They
    # are not: they are picked up by Refresh, which now re-derives geom_4326.
    # The paragraph says which writes go stale and what recovers them, so the
    # next reader does not have to find that out from a broken dataset.
    # Cap 1560 -> 1568, exact.
    # fix(#1858): +30. Table discovery and registration now read one
    # expression for "this is an import staging table", where discovery's
    # `NOT LIKE '%\\_staging'` matched neither shape
    # `attempt_scoped_staging_table` produces. The lines are the refusal
    # itself, its bound parameter, and the comment saying why only the
    # attempt-scoped shape is refused rather than every `_staging`/`_old`
    # name, since `generate_table_name` can produce those from a title.
    # Cap 1568 -> 1598, exact.
    # chore(#1812): -8, the import door no longer judges a queue on the composed line
    # or configures ingest_service with it. Cap 1598 -> 1590, exact.
    "backend/app/processing/ingest/service.py": 1590,
    # fix(#1738): first entry, crossed _RATCHET_INCLUSION_LOC (842 -> 1019) on
    # the change that gave this task a repair phase. What the growth bought:
    # `geom_4326` on a registered table was written once, at registration, and
    # never re-derived, so an `UPDATE geom`, a DELETE+INSERT reload, or an
    # `ogr2ogr -overwrite` left rows that every reader filters out — silently
    # invisible, because `NULL && <envelope>` is NULL. Phase 1.5 re-applies
    # the invariant from outside the table, which is the only shape that
    # survives -overwrite dropping it. Most of the added lines are the
    # docstring and the constant comments carrying the two properties a later
    # reader would otherwise simplify away: the phase runs BEFORE the
    # read-only measurement (which declares postgresql_readonly=True precisely
    # so a write from it fails), and it installs its own statement deadline
    # because `install_api_statement_timeout` is an API-process concern and a
    # worker UPDATE on a customer's relation would otherwise be unbounded.
    # The second bound is the one measurement forced: ADD COLUMN takes ACCESS
    # EXCLUSIVE, a QUEUED lock request already blocks every reader behind it,
    # and the first version of this phase sat on that queue for the full five
    # minutes in a test. `_REPAIR_LOCK_TIMEOUT_MS` gives the position back
    # after five seconds instead. Cap 842 -> 1061, exact.
    # fix(#1738 round 1): +43 for two review findings and the defect the first
    # of them uncovered. The reader GRANT is now re-issued whatever the
    # geometry turned out to be — it is the third thing -overwrite destroys
    # and losing it does not depend on the render column needing a rewrite, so
    # gating it on the re-derive let a recreated table with a generated
    # geom_4326 pass a refresh unreadable. Probing the columns before
    # resolving the SRID is what that exposed: Find_SRID RAISES for a table
    # with no geometry, so every refresh of a registered non-spatial dataset
    # was a logged repair failure that also skipped the grant. And the version
    # bump moved to the atomic helper, because this transaction holds no row
    # lock. Cap 1061 -> 1104, exact.
    # fix(#1738 round 2): +24 — the GiST index restore moves onto the same
    # rule as the grant: every outcome where the column exists, not only the
    # one where it had to be rewritten. `rederive_geom_4326` was the only
    # caller of the index helper, so an overwrite that recreated the table
    # with a valid STORED GENERATED `geom_4326` left the dataset with no
    # spatial index and every `geom_4326 && <envelope>` predicate the readers
    # issue fell back to a sequential scan. Cap 1104 -> 1128, exact.
    # fix(#1755 item 11): +2. The `finally` block's heartbeat stop routes
    # through `cleanup_step`, so a failure in it logs instead of replacing the
    # refresh exception being propagated. Cap 1128 -> 1130, exact.
    # fix(#1847): the lock order, its gate and its 409 mapping. Cap 1134, exact.
    # fix(#1847): phase 3 takes the job row before the datasets row. Cap
    # 1134 -> 1141, exact.
    # fix(#1902): the atomic bump comment states its contract. Cap 1141 -> 1137.
    "backend/app/processing/ingest/tasks_postgis_refresh.py": 1137,
    # --- entered by the inclusion rule, feat(#765) -------------------------
    # First time this module crosses 1000. main sat at 994, six lines under the
    # gate, so it was going to fire on whoever added next; it fired here.
    # +38 — DerivedFromResponse. The provenance reference was typed
    # dict[str, Any], which OpenAPI renders as additionalProperties: true, and
    # both SDKs then generate an untyped map — the shape is exactly what a
    # durable reference exists to carry, so leaving it untyped defeated the
    # feature (#1045 review). The model's own docstring holds the part worth
    # keeping: `params` stays untyped deliberately, because it is the
    # operation's parameter dict AND it is redacted per requester, so a union
    # of per-operation models would describe a shape visible_derived_from is
    # free to punch holes in.
    # +95 — the four analysis operations. Each one adds a value to both
    # AnalysisOperation Literals, a params field with its bounds, and its row
    # in _ANALYSIS_PARAM_OWNERS, which is what makes a param submitted to the
    # wrong operation a 422 instead of a silently ignored key. 1032 -> 1127.
    # fix(#1097 review): +6 for the mask_dataset_id description, on both
    # request models. It said the field applied to clip and select_by_location
    # and was an alternative to `mask`, while the validator requires it for
    # every intersect and rejects a drawn mask there — so the generated SDK
    # docs led clients to requests that always 422.
    # fix(#1097 review): +5 for the match_count description, which said the
    # field is null for anything but spatial_join and select_by_location while
    # intersect returns it. This is the SOURCE the SDKs and the hand-typed
    # frontend mirror are generated from or checked against, so it had been
    # corrected in the mirror and left wrong here — backwards, and the reason
    # the wrong text shipped into both SDKs.
    # feat(#1070): +9 for DatasetResponse.metadata_warnings — the advisory
    # warnings a metadata PATCH can attach (inherited-keyword disclosure at a
    # visibility/status change). 1138 -> 1147.
    # fix(#1178 review): +9 for the same field on StatusUpdateResponse — the
    # publication status endpoints run the disclosure check too, so their
    # response carries it. 1147 -> 1156.
    # fix(#1183): +11 for the two record_status descriptions. Both said
    # "draft, ready, published" — three values, omitting `internal`, and
    # phrased as a closed set when `record_status` has no CHECK constraint
    # and its values come from the workflow extension's status_order(). The
    # wording now names the seam first and the community default second, so a
    # reader cannot mistake the list for the contract. This is the SOURCE the
    # SDKs and api.generated.ts are generated from, and #1184 already shipped
    # a `^(draft|ready|published)$` validator read straight off it. 1156 ->
    # 1167.
    # fix(#727): +38 for AnalysisPreviewRequest.bbox — the field, its
    # description, and the _validate_bbox field_validator (length, finiteness,
    # ordering) that gives 422s an actionable message instead of a generic
    # ST_MakeEnvelope failure. 1167 -> 1205.
    #
    # fix(#727 codex P2 round 1): +4 — source_feature_count's description now
    # names the live-bbox-scoped-count and could-not-be-computed cases, so a
    # reader of the schema (or the generated SDK docs) sees the same contract
    # _resolve_bbox_source_count's docstring states. 1205 -> 1209.
    #
    # fix(#727 codex round 2): +6 — match_count's description now covers
    # intersect's bbox-scoped total (it rides the same statement the
    # geometry preview runs, unlike select_by_location's separate uncapped
    # count query) now that the intersect branch actually receives bbox.
    # 1209 -> 1215.
    # feat(#1218): +56 — the eight read-only source-state fields on
    # DatasetResponse. Seven mirror the new columns; `origin` is computed at
    # the boundary rather than stored, so its description has to say so or a
    # reader will go looking for the column. source_health and
    # schema_drift_status carry the NULL -> "unknown" projection, which is
    # only discoverable from the description. Cap 1215 -> 1271, exact.
    # feat(#1224): +15 — the computed `source_freshness` field. The description
    # spends its lines on the three things a reader cannot see from the type:
    # that the value is derived from last_refreshed_at, update_frequency, and
    # origin rather than stored (so nobody goes looking for a column); that a
    # non-refreshable origin reads "unknown"; and that it is a different thing
    # from the quality score's own freshness, which the frontend already
    # computes under that word. Cap 1271 -> 1286, exact.
    # feat(#1222): +47 — SourceHealthResponse (the probe endpoint's reply) and
    # SOURCE_HEALTH_DETAIL_DESCRIPTION. Most of it is description text, and it
    # earns its place twice over: the three health words have to mean the same
    # thing here as on VrtSourceHealth or the UI cannot render one legend, and
    # the detail description has to say OUT LOUD that the field is an
    # enumerated GeoLens code rather than a message to show verbatim. It is
    # built from the probe's own DETAIL_CODES instead of retyping the list, so
    # the schema and the vocabulary cannot drift. Cap 1286 -> 1333, exact.
    # feat(#1219, #1223): +56 — DatasetRefreshRunResponse and its list
    # wrapper. Most of the growth is descriptions that state facts a reader
    # cannot get from the field name: started_at is DISPATCH time (so queue
    # wait is visible), ingest_job_id nulls out when the job is purged while
    # the run survives, and the response docstring enumerates the five fields
    # Decision 4e redacts for third-party readers. Cap 1333 -> 1389, exact.
    # feat(#1219 amendment): +7 — claimed_at, the third timestamp. started_at
    # is dispatch, claimed_at is when a worker picked the run up, finished_at
    # is the outcome; queue wait is only measurable because all three exist
    # separately, which the field's description has to say or a reader will
    # assume two of them are redundant. Cap 1389 -> 1396, exact.
    # feat(#1220): +39 — DatasetRefreshRequest and DatasetRefreshResponse.
    # The request model is one optional field and most of its lines are the
    # docstring stating what is NOT in it: no URL, no service type, no layer,
    # because reading those server-side is the entire feature and a reader
    # who assumes they were merely defaulted would add them back. The
    # response carries the run id alongside the job id, and says why — the
    # run is the durable history row that outlives the job the retention
    # purge removes. Cap 1396 -> 1435, exact.
    # feat(#1221): +5 — `stale` joins VrtSourceHealth.status, for a member
    # whose own raster was replaced after the parent VRT was last built. The
    # comment is the value: the member probes healthy and it is the PARENT
    # that needs regenerating, which is the opposite of where `inaccessible`
    # sends the reader. Cap 1435 -> 1440, exact.
    # feat(#1316): +14 — origin_uri/origin_ref descriptions now state the
    # owner-or-admin redaction inline (the same fact the field-level
    # description already carries for every other gated field in this
    # module), and DatasetVersionResponse gained a docstring for the same
    # reason on file_hash/uploaded_by. Cap 1440 -> 1454, exact.
    # fix(getgeolens.com#86 review): +4 — SourceHealthResponse's docstring
    # claimed it shared ALL of VrtSourceHealth.status's values, which stopped
    # being true when fix(#1221) added VrtSourceHealth's VRT-specific `stale`
    # value without updating this cross-reference. Cap 1454 -> 1458, exact.
    # fix(#1325): +7 — DatasetRefreshRunResponse.origin_kind's description now
    # states the door-vs-origin distinction inline (a raster-replace run's
    # door has no ORIGIN_KINDS counterpart), matching the CHECK constraint
    # comment in platform/refresh/models.py and the ORIGIN_KINDS docstring in
    # platform/dataset_origin.py. Cap 1458 -> 1465, exact.
    # fix(#1325 review): +1 — codex caught the description overclaiming
    # 'raster' as live behavior ("is the raster-replace door") when
    # refresh/models.py's own comment on the same constraint says reserved,
    # not live. Reworded to match: 'raster' is reserved for a future door
    # label, today's raster-replace runs are still recorded 'upload'. Cap
    # 1465 -> 1466, exact.
    # fix(#1325 review round 3): +2 — codex found a second, live divergence
    # the first reword still implied away: it said raster-replace 'upload'
    # runs "match the dataset's origin", true only when the dataset's origin
    # was already 'upload'. A STAC-imported raster's pending or failed
    # replace run is recorded 'upload' while the dataset's origin stays
    # 'stac' until the swap succeeds — reworded to drop the equality claim
    # entirely and name that case. Cap 1466 -> 1468, exact.
    # -16 — dead-code sweep: DatasetCreate deleted. The request schema had
    # zero references across backend/cli/mcp/sdks/frontend — creation uses
    # CreateEmptyDatasetRequest instead. Cap 1468 -> 1452, exact.
    # feat(#1472): +21 — `attribution` on DatasetResponse and DatasetMeta, plus
    # the NFC-normalization entry. The lines are mostly the note on the PATCH
    # field's max_length: 5000 rather than the 1000 its neighbours use, because
    # ManifestMetadata.attribution is NonEmptyString5000 and the ingest tail
    # writes it straight to the column, so a 1000 bound here would accept a
    # manifest value the dataset PATCH then refuses to round-trip.
    # Cap 1452 -> 1473, exact.
    # fix(#1472 review): +10 — the markup guard on `attribution`. It is the one
    # field in this schema that reaches an HTML render context (MapLibre's
    # attribution control assigns it to innerHTML, and MapLibre's own sanitizer
    # keeps img/iframe/style), so it is the one that must stay plain text. The
    # rule itself lives in core.text.reject_html_markup, shared with the
    # manifest schema; these lines are the field_validator and the note saying
    # why only this field carries it. Cap 1473 -> 1483, exact.
    # feat(#1746): +16. The re-upload commit and refresh request models gain
    # the `auth` object and the validator refusing a body that sets it and the
    # deprecated `token` at once. Both are imported from the sources schema
    # rather than restated here, so the four doors cannot describe the same
    # credential four ways. Cap 1483 -> 1499, exact.
    # feat(#1746 B2b): +17. `ReuploadServicePreviewRequest` is the fifth model
    # to carry the `auth` object, declared last like the other four. #1760 left
    # it out because no transport composed a header for the methods it adds;
    # with one in place, leaving it out would mean a basic-protected service
    # could be re-uploaded but not previewed first. Cap 1499 -> 1516, exact.
    # fix(#1746 B2b review r24): +8. `row_count_delta` is nullable (and still
    # required), with the reason recorded where the field is declared.
    # Cap 1516 -> 1524, exact.
    # fix(#1768): +12. `ReuploadCommitRequest.expected_origin_kind`, typed with
    # the shared `OriginKind` literal from platform/dataset_origin.py rather
    # than a second spelling of the vocabulary, plus the description telling a
    # client author what the field buys and that omitting it is supported.
    # Cap 1524 -> 1536, exact.
    # fix(#1847): +5. BulkDeleteResultItem gained an optional `code`, so a
    # per-item conflict is machine-readable with the same code the
    # single-delete 409 carries. Cap 1536 -> 1540, exact.
    "backend/app/modules/catalog/datasets/domain/schemas.py": 1540,
    # --- entered by the inclusion rule, feat(#953/#954/#955/#956) ----------
    # tasks.py crossed 1000 for the first time here because the four operations
    # are deliberately concentrated rather than spread: it grows by one branch
    # per operation so the CTAS shape is decided in one place, the same reason
    # every rendered statement lives in analysis_sql rather than in the preview
    # path and the worker separately. Splitting either one PER CALLER would
    # trade size for the drift both were built to prevent, so the growth is the
    # design working.
    #
    # refactor(#1089): analysis_sql left this dict. It crossed 1000 in the same
    # batch (662 -> 1173, later 1255) and carried the follow-up note this entry
    # used to hold; the split has now happened. It is a package split by
    # OPERATION FAMILY — overlay, measure, spatial_join, transform, over a
    # shared core holding the OFFSET 0 fence, the measured ceilings, the
    # antimeridian helper and the mask parser — and no file in it reaches the
    # inclusion threshold, so nothing needs a cap. What survived the move and
    # still binds: never split it by CALLER. Giving the preview path and the
    # materialize worker their own rendering modules recreates exactly the
    # drift the module exists to prevent, and the package docstring says to
    # reject that proposal on sight. The per-family reasoning the #1097 review
    # entries recorded here — NON_GROUPABLE_COLUMN_TYPES, INTERNAL_ALIAS_PREFIX
    # and MAX_IDENTIFIER_LENGTH each landing where more than one guard reads
    # them — now sits beside the constants themselves in analysis_sql/shared.py
    # and analysis_sql/spatial_join.py, which is where an edit to them starts.
    # tasks.py carries growth from BOTH sides of this rebase, so the number is
    # re-measured rather than taken from either. #1012 added the scoped
    # work_mem (the SET LOCAL, its budget arithmetic and the boot-time
    # validator); this branch added one CTAS branch per operation. Each cap was
    # correct for the tree that produced it and neither is correct for the
    # merge, which is the conflict doing its job.
    #
    # fix(#1097 review): +40 on top of that, for
    # _reject_ungroupable_overlay_columns — the worker half of the overlay type
    # guard. The router validates a catalog SNAPSHOT and a re-upload can
    # replace the overlay before the job runs, the same window
    # _reject_output_column_collision beside it exists for. Types rather than
    # names, because the live name list was already read there and would not
    # have caught it: the column that breaks the CTAS has an ordinary name.
    #
    # fix(#1097 review): +91 for the live-schema rechecks. Two more guards (the
    # reserved-alias prefix, and re-checking transferred join fields against the
    # join layer's live columns) plus _resolve_and_validate_columns, which the
    # set moved into rather than raising _materialize's C901 threshold: five
    # checks over two layers share a subject the surrounding job bookkeeping
    # does not.
    #
    # fix(#1097 review): +21 for re-applying the polygon requirement on the
    # mask layer at resolve time. The router refuses a non-polygonal mask at
    # enqueue and a re-upload can change that layer's geometry_type while the
    # job waits, and nothing downstream notices: the mask matches no rows and
    # the job dies on "produced no features", pointing the user at their data
    # instead of at the layer that changed.
    #
    # fix(#1097 review): +22 for the second geometry strength. The mask must
    # still be polygonal; the JOIN layer must only still be spatial, because a
    # join counts in any direction — but a re-upload from a non-spatial source
    # leaves no geom_4326 for render_spatial_join to reference.
    #
    # fix(#1097 review): +20 for _DRAWN_MASK_OPERATIONS and the note on why
    # mask_source belongs to every operation that can take a drawn mask. The
    # drawn geometry is deliberately excluded from provenance, so that
    # discriminator is the only trace a drawn selection leaves — the constant
    # is duplicated from schemas because PROCESS-02 forbids the import, and a
    # test pins the two copies together.
    #
    # fix(#1097 review): +3 for linearizing the three pass-through CTAS
    # geometry columns (measure, spatial_join, select_by_location) so a curved
    # source row is stored linear — a curved geometry written into the derived
    # table would fail that layer's tiles and feature reads later.
    # fix(#1104): -1 — those wraps are gone again; geom_4326 is linear at
    # ingest, so the pass-through columns read the bare column. Cap
    # 1450 -> 1449, exact.
    #
    # fix(#1097 review): +62 for the array-element half of the ungroupable
    # guards. information_schema stores an array column's data_type as
    # 'ARRAY', so json[]/xml[] passed the exact scalar comparison and failed
    # the CTAS with 42883 after the queue wait; _ungroupable_type_name reads
    # udt_name ('_json') as well, and the same check now also covers
    # dissolve's by_field, which had the identical blind spot plus no live
    # recheck at all.
    #
    # fix(#1099): -36 — _reject_ungroupable_overlay_columns is retired, along
    # with its call site in _resolve_and_validate_columns. The overlay's
    # attributes are joined back outside the aggregate now, so a re-upload that
    # introduces a json column has nothing left to break; leaving the recheck
    # would have refused, after the queue wait, exactly the layers that issue
    # set out to admit. _ungroupable_type_name and its ARRAY branch stay —
    # dissolve's by_field really does group by a user-chosen column. Cap
    # 1449 -> 1413, exact.
    # fix(#1452): +7 — managed=True on the output registration, with the note
    # that this table was CTAS'd here so delete may reclaim it. Without the
    # flag it is indistinguishable from an operator's registered table and
    # every analysis output would leak one on delete. Cap 1413 -> 1420, exact.
    # fix(#1778): +42. The generated output table name is persisted to
    # `user_metadata` in the transaction that creates the table, and the
    # probe-then-drop the two fence-miss handlers each carried inline is now one
    # `drop_unadopted_analysis_output` the stale-job sweeps call too. The
    # helper's docstring and its identifier re-validation are most of the net
    # growth; the two inlined copies came out. Cap 1420 -> 1462.
    # fix(#1778 codex r6): +33. `drop_unadopted_analysis_output` returns what
    # it established rather than the same None whether it dropped the table or
    # failed to. The sweep clears the recorded name on the strength of that
    # call, and the name is the table's last durable pointer, so a swallowed
    # failure read as success orphaned the table permanently. The five outcomes
    # and the note on why a raised probe is "failed" and not "adopted" are the
    # growth. Cap 1462 -> 1495.
    # fix(#1778 codex r7): +79. Output table names are scoped by the job that
    # creates them, so two jobs can never hold one physical name and the sweep
    # can verify ownership from the name alone, with no marker, registry or
    # lock. `analysis_output_table_name` and `analysis_output_table_belongs_to`
    # plus the ownership gate in the drop are the code; the docstring stating
    # the interleaving that made a shared name unsafe, and why the scope is by
    # job and not by attempt, is most of the growth. The gate is a REQUIRED
    # keyword with no default: the in-worker handlers pass their own id either
    # way, so an optional one would have bought nothing but a way to forget it.
    # Cap 1495 -> 1580, exact.
    # fix(#1778 codex r10): +122. The scope grows an attempt half — job scoping
    # alone left a retry able to derive the same name as its predecessor, since
    # `/jobs/{id}/retry` keeps `IngestJob.id` and only mints a new attempt
    # token. `analysis_output_table_name` takes both now, and the record
    # accumulates across attempts (`recorded_analysis_output_tables`,
    # `append_analysis_output_record`) rather than overwriting, the shape
    # `unpublished_storage_keys` took in r9 and for the same reason: overwriting
    # a retry's own field dropped the previous attempt's pointer. The other
    # half of the growth is `resolve_analysis_output_table`, which
    # collision-checks the SCOPED candidate against pg_class directly —
    # `generate_table_name`'s own `_N` walk only ever probed the unscoped base,
    # so it could hand back a name that scoped straight onto an orphan a
    # previous attempt of the same job left behind. Cap 1580 -> 1702, exact.
    # fix(#1778 audit r11): +23. `analysis_output_table_name` takes an
    # optional `collision_suffix` now instead of the caller pre-pending `_N`
    # to `base` and calling it again -- the second trim of an already-trimmed
    # string threw away the very characters that made one candidate differ
    # from the next, so a `base` at or past the reservation point made every
    # walked suffix identical and exhausted the whole `_N` walk instead of
    # self-healing. The tag is reserved for up front, in the same limit
    # computation as the scope, the idiom `generate_table_name`'s own
    # `_with_collision_suffix` already uses. Cap 1702 -> 1725, exact.
    "backend/app/processing/analysis/tasks.py": 1725,
    # Tenant-owned media now crosses the shared logical-to-physical storage
    # seam; explicit storage-failure responses keep the runtime/OpenAPI contract
    # aligned. Keep the ratchet exact after the import/decorator expansion.
    # fix(#1005): +32 — _record_image_capture, the shared write for both
    # image-upload endpoints. Its docstring carries the part that is easy to
    # get wrong: Map.updated_at has onupdate=func.now(), so dropping the
    # explicit assignment does not stop the bump. Ratchet stays exact.
    # fix(#941): +8 — the reworded add-layer history summary carries the reason
    # the immediate-POST and save-diff writers say different things, so a later
    # refactor does not collapse them. Ratchet stays exact.
    # fix(getgeolens.com#86 review): +35 — five read-gated GETs (list, single
    # map, access, thumbnail, og-image) gained per-route
    # `responses={403: FORBIDDEN_RESPONSE}` overrides; get_map_history_endpoint
    # keeps the router's write-flavored default since it genuinely requires
    # edit_metadata + ownership. Cap 1425 -> 1460, exact.
    # feat(#1691): +9 — the check_public_visibility_allowed gate on the map
    # update route (a non-admin may not move a map TO public when
    # restrict_public_visibility is on). Cap 1460 -> 1469, exact.
    # fix(#1778): +19 — the three call sites that discard a map's stored
    # thumbnail / OG-image objects, plus the comments recording why each key is
    # snapshotted before the write commits (after it, every attribute on
    # map_obj is expired and a lazy refresh would raise) and why the extension
    # flip strands a key at all. Cap 1469 -> 1488, exact.
    # fix(#1778 round 1): +9 — the import route answers 422 for the per-map
    # layer limit, above the generic ValueError arm it subclasses, with the
    # comment saying why that order is load-bearing. Cap 1488 -> 1497, exact.
    # fix(#1778 round 2): +12 — the three asset call sites take the row lock
    # that serializes a map's thumbnail and OG-image replacements, plus the
    # comments recording what the race produced (a committed URI pointing at an
    # object the other request had already deleted, both requests 204, the
    # endpoint 404 from then on) and why the lock is taken after payload
    # validation rather than at the top of each handler. The 404 for a
    # concurrently deleted map lives in the helper, not repeated three times.
    # This crosses the 1500 glob default the allowlist overrides, which is what
    # this entry is for. The seam if it grows again is the asset surface: the
    # thumbnail and OG-image routes move to router_assets.py, which already
    # exists and holds 142 lines. Cap 1497 -> 1509, exact.
    # fix(#1778 round 3): +1 — the two image keys come from new_map_asset_key,
    # which never returns a name twice. Cap 1509 -> 1510, exact.
    # fix(#1778 round 4): +16 — both upload handlers publish the object and the
    # row that names it inside one rollback scope, so a failure between the put
    # and the commit does not leave an undiscoverable object under maps/.
    # Cap 1510 -> 1526, exact.
    # fix(#1778 round 5): +8 — both handlers settle the publication on the
    # commit inside _record_image_capture, so a failure after it cannot roll
    # back an object the committed row names. Cap 1526 -> 1534, exact.
    # fix(#1778 round 6): +11 — the commit moved out of _record_image_capture so
    # each handler can mark its publication immediately before awaiting it, and
    # a commit that made the row durable but never acknowledged it deletes
    # nothing. Cap 1534 -> 1545, exact.
    # fix(#1778 round 7): +9 — the ledger entry moved above the write it covers,
    # with the comment saying why that is free: object storage can durably
    # accept a PUT and still fail the client, and the key is never reused, so a
    # rollback delete either cleans up or no-ops. Cap 1545 -> 1554, exact.
    # fix(#1778 round 9): +18 — lock_map_for_asset_write moved to after storage.put
    # in both image handlers, so a stalled write no longer holds the map row
    # locked; previous_key is now read under the lock, after the write, so two
    # concurrent uploads reap each other's key correctly instead of racing on
    # a stale read. Most of the growth is the docstring explaining why the
    # lock has to move rather than just gaining a shorter timeout of its own.
    # Cap 1554 -> 1572, exact.
    "backend/app/modules/catalog/maps/router.py": 1572,
    # fix(#474): thread negotiated languages through catalog search, cache keys,
    # and OGC record serialization; fix(#475) adds Records array-query handling,
    # including collection IDs, plus response-header and documented 400 parity.
    # fix(#892): +4 — the per-dataset OGC collection extent moved off a bare
    # to_shape().bounds read onto extent_to_bbox() so a seam-crossing extent
    # serves the RFC 7946 west > east bbox. Ratchet stays exact.
    # fix(#886): -5 — the aggregate collection extent moved off
    # ST_AsGeoJSON(ST_Envelope(ST_Collect(...))) plus its GeoJSON coordinate
    # fold onto rollup_bbox_columns()/rollup_bbox(), which also retires the
    # module's last json import. Cap lowered 1432 -> 1427, still exact.
    # fix(#1103): +13 — the OGC record's `lineage` property is access-checked
    # per requester now (the sentence names the titles of the datasets an
    # analysis output was derived from). The item endpoint keeps the roles
    # check_dataset_access_or_anonymous already resolved; the list endpoint
    # takes the batch form, one visibility query per page. Cap 1427 -> 1440,
    # still exact.
    # fix(#1290 review): +10 — the public-asset-key boundary. Rows are
    # filtered where they are FETCHED so an internal key never enters a
    # payload structure; `GET /datasets/{id}` had been building its assets
    # straight off the ORM rows and leaked the archived original's href and
    # filename to every viewer. Cap 1440 -> 1450, exact.
    # fix(#1372 codex r2): +5 — the collections-list raster tiles link carries
    # ?v=<tile_cache_version> like every rendered raster template.
    # fix(#1327): +13 — the OGC record item counts the VRT's live member links
    # instead of reading the in-flight generation's intended count, so this
    # surface reports the composition being SERVED like every other one. Most
    # of the lines are the comment explaining why the generation's own count is
    # a fact about the attempt, not about the dataset. Cap 1455 -> 1468, exact.
    # fix(#1671): the two pre-#1666 search compatibility shims are sunset --
    # `_legacy_keywords_body`, the `_LEGACY_FILTER_LANG_PARAM` fallback, and
    # the comments that only existed to explain them. Cap lowered
    # 1536 -> 1489, exact.
    # fix(#1778): +4 -- deterministic ORDER BY tiebreaker on the paginated
    # per-dataset OGC collections query. Cap 1489 -> 1493, exact.
    # fix(#1855): -1. The facets rate-limit note shrank when the endpoint
    # gained the SEC-S11 limiter. Cap 1493 -> 1492, exact.
    "backend/app/modules/catalog/search/router.py": 1492,
    # fix(#474): negotiate localized STAC record text; fix(#475) adds the
    # unassigned Collection and matching HTTP Link navigation. fix(#506): keep
    # validated STAC item responses wire-compatible with serializer output.
    # STAC hardening (roadmap trust batch): collection license aggregated from
    # member records, item-less collections hidden from the STAC surface
    # instead of advertising a fabricated global extent, and stac-api-validator
    # conformance (strict RFC 3339 datetime gate, bbox/intersects exclusivity,
    # south<=north bbox check, limit clamping). Ratchet stays exact.
    # fix(#886): -7 — both Collection extent queries drop their four repeated
    # ST_XMin/ST_YMin/ST_XMax/ST_YMax(ST_Extent(...)) columns for one
    # rollup_bbox_columns() splat, and _parse_extent_row folds the row through
    # rollup_bbox(). Cap lowered 1796 -> 1789, still exact.
    # feat(#765): +44 — _visible_derived_from_id resolves the rel="derived_from"
    # source against the same published+visible query the item endpoints serve
    # from, and user/user_roles are threaded to the four item builders that
    # feed it. Cap 1789 -> 1833, still exact.
    # fix(#1103): +10 — the STAC item's lineage property is gated the same way
    # as its derived_from link, on the user/user_roles already threaded here.
    # Cap 1833 -> 1843, still exact.
    # fix(#1108 review): +27 — the two item-page loops precompute lineage
    # visibility for the whole page (one query, mirroring PERF-5's
    # spatial_extent_geojson) instead of one round trip per item at limit=200.
    # Cap 1843 -> 1870, still exact.
    # fix(#1432): -15 — the two inline bbox parsers and
    # _require_finite_bbox collapse onto the shared parse_bbox, which now takes
    # the POST list as well as the GET string. Cap 1870 -> 1855, still exact.
    # refactor(stac): -1 — the raster-asset reads go through CatalogPort, so
    # the DatasetAsset select and the deferred raster-queries import give way
    # to port calls. Cap 1855 -> 1854, still exact.
    # fix(#1778): +15 -- deterministic ORDER BY tiebreakers on the two
    # paginated item queries, the open-ended interval-datetime fix, and
    # replacing the four nested async_session() pool checkouts in
    # get_collections with sequential reuse of the caller's own session.
    # Cap 1854 -> 1869, exact.
    "backend/app/standards/stac/router.py": 1869,
    # Central tenant-bound scope resolution replaced duplicated inline logic.
    # fix(#836): +1 — the RASTER_FAMILY_RECORD_TYPES import that replaces four
    # pasted family literals. Same +1 on the stac and search routers.
    # fix(#868): +3 lines for the cluster cache-key SQL-semantics version
    # ("v2") so deploys that change cluster tile geometry invalidate Valkey.
    # fix(#892): +2 — the raster tile-token bounds moved onto
    # extent_to_span_bbox() so a seam-crossing extent cannot feed a negative
    # span into the maxzoom derivation.
    # fix(#887): +17 — extent_to_span_bbox reports -180..180 for a two-ring seam
    # extent, which understates a Pacific raster's resolution by 36x and drops
    # its maxzoom by five levels, so the honest width now travels alongside the
    # bounds as an explicit `lon_span` keyword.
    # Merge of the carve-outs: 2043 base + 3 + 1 + 2 + 17. Ratchet stays exact.
    # fix(#929 review): -22 — _resolve_raster_access's inline RBAC mirror
    # replaced with delegation to the permission extension via the port.
    # fix(#939): +23 — the degrees-vs-metres decision in
    # _native_resolution_meters moved off `epsg == 4326` onto the stored WKT
    # (wkt_is_geographic + wkt_has_degree_unit), with the grads fall-through
    # documented at the site. Ratchet stays exact.
    # fix(#957): +12 — raster_auth_check dropped out of the OpenAPI schema, and
    # the note recording that the ROUTE is vestigial while the HANDLER is on the
    # live raster tile path sits at the decorator so nobody deletes the wrong
    # half. Ratchet stays exact.
    # fix(#688): +73 — the raster tile template is signed like its vector
    # sibling (mint in _build_tile_token_for_dataset, verify in
    # _resolve_raster_access via _has_tile_signature/_verify_raster_tile_signature).
    # Before this a client following the contract literally received an
    # unauthenticated template for a private raster. Ratchet stays exact.
    # fix(#1372): +6 — the signed raster template also carries
    # ?v=<tile_cache_version> (outside the signature, like the colormap
    # params) so nginx's $arg_v cache-key segment rolls on replace.
    # fix(#1372 codex r3): +19 — the auth check refuses to mark a response
    # cacheable when its `v` mismatches the dataset's current version, so a
    # predictable future key can never be pre-warmed with pre-replace bytes.
    # fix(#1372 codex r4): +12 — the check mirrors nginx's $arg_v semantics
    # (first occurrence, case-insensitive name), closing the duplicate-param
    # and name-case parser-disagreement variants of the same pre-warm attack.
    # fix(#1329): +64 — the raster meta cache key carries the request's `v`, so
    # the three in-place pointer swaps (reupload, VRT regeneration, STAC
    # moved-asset refresh) invalidate every api process's snapshot with the
    # version bump they already do, instead of each process serving the
    # pre-swap href for a TTL. Most of it is the note recording WHY it is the
    # request's `v` and not the row's: the row's version arrives through the
    # same cached snapshot, so it is exactly as stale as the href it would be
    # guarding.
    # fix(#1329 codex P1): +13 — the lookup key is the request's `v` but the
    # STORE key is the resolved row's, so no caller can name the entry it
    # writes and a predictable future `v` can no longer park a pre-swap
    # snapshot on the key the swap is about to make legitimate.
    # fix(#1778): +35 — `_resolve_raster_access` hands its API-pool connection
    # back before returning, so the caller's Titiler round trip (up to three
    # attempts at a 30s timeout plus backoff) no longer runs with the catalog
    # read's transaction open. Most of it is the note recording that the release
    # belongs in the resolver rather than at either call site, and the correction
    # to the #1329 cache-key note, which priced a cache-busting `v` as one extra
    # indexed read and left out the connection that read pinned. Four of the
    # lines say at the `cols=` call site that the dataset's column set now gates
    # the cache key, since the handler docstring above it is the published
    # operation description and saying it there churns every generated SDK.
    # fix(#1778 codex P1): +14 — that call site now hands `parse_cols_param` the
    # zoom, the allowlist and the route mode, because validating the names was
    # not enough: at z >= 10 the zoom default already projects every column, so
    # every valid subset of a wide table produced one set of bytes under its own
    # key. The key comes from the effective projection now, and each call site
    # says which of its inputs decide that.
    # fix(#1778 codex r2): +26 — pmin/pmax/sigma are now validated only when
    # the ACTIVE stretch mode reads them (percentile for pmin/pmax, stddev for
    # sigma), not whenever merely present. frontend/nginx.conf's raster
    # proxy_cache_key blanks an inactive value out of the cache key so a
    # random one cannot defeat the cache, and that is only safe if "inactive"
    # means the SAME thing, ignored, on both sides — otherwise a value nginx
    # blanks could still turn a cached 200 into what would have been a 422.
    # Most of the growth is the docstring and Query() description updates
    # recording that contract for both parameters and the endpoint.
    # fix(#1778 codex r8): +41 — eff_pmin/eff_pmax/eff_sigma used to be
    # resolved from "was the parameter merely present", independent of
    # stretch mode, so an INACTIVE parameter's raw (unvalidated) request
    # value still reached _fetch_band_statistics/_compute_stretch_rescale.
    # `?stretch=stddev&pmin=1e309` (inf) reached `int(pmin)` there and
    # raised an uncaught OverflowError, while nginx — which treats a value
    # it blanks as harmless — found `1e309` inside its canonical float
    # grammar and blanked it, sharing a cache key with a plain stddev
    # request: a cached 200 once warm, a 500 cold. eff_pmin/eff_pmax/
    # eff_sigma now gate on the SAME activity test the validation below
    # already used, so an inactive parameter's raw value is never read by
    # anything, and the validation itself now requires math.isfinite() on
    # the active path explicitly rather than relying on inf/nan's
    # comparison behavior to fail the existing bound check.
    # Ratchet stays exact.
    # fix(#1770 round 40 P2): +1. The raster tile proxy's two retry-path
    # `error=str(exc)` sites become `error=redact_exception_text(exc)`,
    # net +1 after the new import. Cap 2706 -> 2707, exact.
    # fix(#1770 round 47b P2 class): +14. `max_num_fields=MAX_QUERY_FIELDS`
    # on the `{fmt}` buried-query recovery parse, the one attacker-reachable
    # site in this round's sweep (unauthenticated, no source registration
    # needed), with a `try/except ValueError` degrading to "no buried
    # params recovered" rather than a raw 500. Cap 2707 -> 2721, exact.
    "backend/app/processing/tiles/router.py": 2721,
    # feat(#565): the SQL sandbox validator crossed 1000 lines across the codex
    # rounds on the query endpoint: the lexical CTE-scope fix (P1) and its
    # pg_catalog.pg_user rationale, the declaration-order refinement (P1 r2),
    # the transitive fan-out cost model (P1 r3) — _resolve_cte plus the
    # rows/work graph walk that catches a CTE chain multiplying one base table
    # to N^8 while every per-name count stays at 2 — and the per-row correlated
    # subquery term (P1 r4, _correlated_scopes/_work_fanout) that costs a
    # self-join hidden in a scalar/EXISTS/WHERE subquery. P1 r5 extended the
    # per-row term to JOIN ... ON predicates (a join's ON is not a source), and
    # P2 r5 taught _resolve_cte that a WITH can be owned by a set operation, not
    # only a SELECT; P1 r6 unwraps exp.Lateral so a repeated table hidden in a
    # LATERAL source is costed; P1 r7 adds a LATERAL's own internal per-row work
    # (its excess over its row count) so a correlated subquery inside a LATERAL
    # is bounded too; P1 r8 costs a parenthesized FROM join group's rows; and P1
    # r9 unifies group costing (_group_work/_add_source_excess/_outermost_scopes)
    # so a group's ON-predicate and internal LATERAL work is a first-class
    # candidate in the statement-wide max; P1 r10 propagates a CTE reference's
    # own internal work (an inlined / NOT MATERIALIZED CTE re-executes per outer
    # row) through _add_source_excess; P1 r11 rejects casts to OID-alias types
    # (regrole/regclass/…) that resolve catalog names with no table reference;
    # and P1 r12 matches those casts by normalized name (schema-qualified
    # pg_catalog.regrole is a DataType, not ObjectIdentifier), folds CTE
    # identifiers per PostgreSQL quoting so "PG_USER" cannot bind an unquoted
    # pg_user, and propagates ordinary derived-table excess; and P2 r13
    # combines sibling per-row subquery/source work by per-table MAX rather than
    # summing (_merge_max), so two scalar subqueries over one table no longer
    # false-reject; and P2 r14 splits per-row work into per-INPUT (WHERE/JOIN-ON/
    # sources) and per-OUTPUT (projection/HAVING/ORDER), collapsing the latter's
    # multiplier for an ungrouped aggregate (_is_ungrouped_aggregate) so a
    # projection subquery over an aggregate query is additive, not multiplied;
    # and P1 r15 keeps a subquery beneath an aggregate ARGUMENT per-input (it
    # runs per input row) so that reduction cannot hide it; P1 r16 costs
    # subqueries buried in a non-scope LATERAL (VALUES/function) and adds a
    # per-STATEMENT bucket (LIMIT/OFFSET, evaluated once, no row multiplier);
    # and P1 r17/r18 counts a VALUES relation as a fan-out source under ONE
    # shared key so distinct constant sources combine in the cross-product,
    # caps VALUES cardinality, threads an endpoint-only extra-blocked-function
    # set (output-amplifying format/replace/regexp_replace/concat + defensive
    # siblings), and P1 r19 blocks the `||` (exp.DPipe) concatenation operator
    # when concat is blocked (chained s||s doubling); P1 r20 adds the
    # cross-product degree (_XPROD_KEY / _join_is_constrained: distinct tables
    # cross-joined multiply even at per-table exponent 1) and an output-column
    # cap (repeated projections amplify response width). P1 r21 makes the join
    # constraint recursive (an equality inside `... OR TRUE` does not constrain)
    # and counts composite-constructor value slots / rejects `*` for the width
    # cap. r22 documents the runtime floor: the fan-out/width model is
    # best-effort pre-filtering, non-security, because every executed query is
    # runtime-bounded (advisory lock, semaphore, timeout, reader role, row+byte
    # caps) — the module docstring and a section anchor state it so cost-model
    # under-counts are documented, not chased. r23 folds unquoted table
    # identifiers (DATA.ROADS → data.roads) before the access check so a
    # PostgreSQL-valid reference is not false-404'd. Most of the added lines are
    # that rationale. Cap at the exact size.
    # fix(#1778): +63 — _BLOCKED_NILADIC_KEYWORDS and _check_niladic_keywords,
    # which reject PostgreSQL's parenless identity keywords. sqlglot gives only
    # some of them a Func subclass, so `user`, `current_role` and `system_user`
    # parsed as columns and slipped the allowlist walk entirely; the comments
    # record that parse-shape dependency so a sqlglot bump does not quietly
    # reopen it. The rest is the TokenError note at the parse site. Cap
    # 1871 -> 1934, exact.
    "backend/app/platform/sandbox/validator.py": 1934,
    # fix(#1778): crossed the 1000-line inclusion threshold, so it joins
    # the ratchet at its exact size. The growth is the token accounting on
    # the two map-generation failure exits (an exhausted or timed-out loop
    # is billed by the provider and used to record nothing), the fixed
    # error message replacing raw exception text in the SSE stream, and the
    # scrubbing of dataset content in the two catalog tool results.
    # fix(#1778 round 1): +3 - the SSE error branch passes only an explicitly
    # constructed UserFacingAIError through, so the five deliberate refusals
    # say so by type instead of every ValueError being trusted (
    # OpenAICredentialDestinationError is one, and its message IS the endpoint).
    # fix(#1778 round 2): +11 - every provider call site moved to the shared
    # usage_accounting context manager, including the two single-round repair
    # calls that had no failure accounting at all, and the map prompt gained
    # the tool-result protocol that says what the fence markers mean.
    "backend/app/processing/ai/service.py": 1019,
    # fix(#1463): crossed the inclusion threshold. The growth is the vector-tile
    # protocol constants and the stale-label repair in generate_distributions,
    # plus the comment recording why the repair has to exist at all: migration
    # 0048 is one-shot and the scripted upgrade runs it while the previous
    # release is still writing rows (#1467), so the template is not the only
    # place that has to know the old value.
    # fix(#1463 codex r4): +6 — the same comment recording what the repair does
    # NOT reach. Both refresh callers gate reconcile on a modality flip, so
    # naming it a closer for the deploy window was wrong; the correction is
    # worth more than the six lines. Cap at the exact size; the module is
    # otherwise a stable set of CRUD helpers over the record's related tables
    # and is not where new domains should land.
    # feat(#1681): +10 — the FlatGeobuf export format joined
    # `_DISTRIBUTION_TEMPLATES` (a download row, matching every other export
    # format already in that table) plus a docstring update to the row count
    # it now generates.
    # feat(export/pmtiles): +9 — PMTiles joined `_DISTRIBUTION_TEMPLATES` the
    # same way, plus the row-count docstring update.
    # fix(#1778): +3 -- RecordContact.id tiebreaker on the paginated contacts
    # list, sort_order being a non-unique server-default. Cap 1026 -> 1029,
    # exact.
    "backend/app/modules/catalog/records/service.py": 1029,
    # fix(#1528): crossed the inclusion threshold, and this is the file the
    # inclusion rule's own comment named as one of the two "routers-by-role the
    # glob's filename match cannot see ... watched by nothing until they cross
    # 1000". It just did.
    #
    # What the lines bought: HEAD and byte-range service on
    # /datasets/{id}/download/cog. A COG exists to be read by range — client
    # reads the header, fetches only the tiles it needs — and this endpoint
    # served neither, so GDAL /vsicurl/ could not open it at all (measured:
    # ERROR 4, not a slow download). The additions are the Range parser and its
    # RFC 9110 ignore/clamp/416 rules, a chunked range streamer that keeps a
    # multi-GB range off the heap, the 200/206/416 response shapes, and
    # _local_cog_response, which exists because folding three representations
    # into a handler that already branches over three storage backends put
    # download_cog past ruff's C901 ceiling.
    #
    # Roughly half the diff is comment: which starlette behaviour each explicit
    # header displaces, and why HEAD here carries a Content-Length where the
    # export route's deliberately omits one. Cap at the exact size. The DCAT
    # feed handlers above are the natural split if this grows again.
    #
    # +93 for the two fix(#1540) review findings. P1 pulled the object stat and
    # the HEAD response out of _local_cog_response into _cog_object_size /
    # _cog_headers / _cog_head_response so the `s3` branch can answer HEAD from
    # metadata instead of redirecting to a URL signed for GET — sharing them is
    # what makes HEAD provably identical on both backends, and it moved the long
    # explanatory comments from inline into three docstrings. P2 added
    # _range_int, which saturates every Range numeric field before int() so a
    # 4301-digit header cannot raise ValueError into a 500.
    #
    # +7, all prose. The double-stat review finding DELETED code — _cog_object_size
    # now calls size() once and maps its FileNotFoundError to 404 instead of asking
    # exists() first — and the lines are the paragraph saying why the second
    # head_object was worth removing: it doubled the round trips and the request
    # charges on every /vsicurl/ probe, against a design chosen for costing one,
    # and the gap between the two calls turned a deleted object into a 503.
    #
    # +90 for the range validator, which is what finishes the range feature rather
    # than extending it. _cog_etag publishes the COG's own sha256 as a strong ETag
    # on every stored-bytes response, and _range_bound_to_this_version evaluates
    # If-Range so a range resumed across a raster replacement returns the whole
    # current object instead of a 206 the client appends to a prefix of the COG it
    # is no longer reading. Ranges without a validator are how two COGs become one
    # corrupt file with no error anywhere, so the explanation is on the two helpers
    # and at the branch. If this file grows again, the DCAT feed handlers remain
    # the natural split.
    #
    # +111 for the two halves of that binding the first pass missed. _s3_cog_response
    # is an extraction, not new branching: the s3 block moved out of download_cog so
    # it could evaluate If-Range before redirecting, which it has to do because the
    # bucket does not (MEASURED: a presigned GET answers 206 for a non-matching
    # If-Range) and a 302 cannot strip the client's Range on the way past. The rest
    # is _if_none_match_matches and _cog_not_modified, so the ETag this route
    # publishes can end a revalidation with 304 instead of another multi-GB body.
    #
    # +7, all comment. The stale-resume fallback now streams from one get_object
    # rather than _iter_storage_range over the whole object, which issued a ranged
    # request per 1 MiB — 5,120 of them for a 5 GiB COG, selectable by any caller
    # willing to send a stale validator and counted by the rate limiter as one
    # request. The lines say which of the two streaming helpers belongs where.
    #
    # +4 net, and the code went DOWN: `_iter_storage_range` is deleted. Serving a
    # range by calling get_range per 1 MiB issued an object-store request per
    # chunk on the ORDINARY path this time, which on an S3 or Azure deployment is
    # every managed raster's range request. Only the provider can ask for a window
    # once and stream the answer, so `get_range_stream` is where the bound lives
    # now; what is left here is the note saying why a helper that turns one range
    # into N reads was removed rather than retuned.
    #
    # +53 for If-Match. A resuming client may spell "only if this is still my
    # representation" as If-Match rather than If-Range, and honouring one while
    # ignoring the other left the absent If-Range reading as permission — the
    # same splice through the other header. _if_match_passes is strong comparison
    # with * handling, _this_service_owns_the_bytes names the rule that already
    # governed the remote branch's blank validator row, and the 412 carries the
    # ETag that IS current so a refused client can restart in one round trip.
    #
    # +36 for the last two review findings. If-Match had to be reachable from a
    # browser (the CORS half is enforced by a test now, not a memory), and the
    # precondition block had to stat the object before answering: a row whose
    # bytes are gone answers 404 unconditionally, so a 304 there told a cache its
    # stale copy was current for a representation that no longer exists. That
    # stat is handed down through _cog_size_once so a conditional request that
    # goes on to transfer bytes still measures once, and _managed_key names the
    # tenant-key seam the block now crosses in a second place.
    #
    # fix(#1554): +30, and 3 of them are code. `If-None-Match: *` is evaluated
    # whatever the row's digest is, because RFC 9110 section 13.1.2 makes the
    # wildcard a question about whether a representation EXISTS rather than
    # about which one it is — so a row predating the sha256 column answered a
    # revalidation by transferring the whole COG. The rest is the reasoning
    # this route keeps needing on hand: why the wildcard is checked before the
    # digest and the specific tags after it, why a 304 with no ETag is the
    # right answer rather than a gap to fill, and why an unconditional 304 is
    # licensed here at all (this path serves GET and HEAD, and the section
    # gives `*` a different answer for anything that would create a
    # representation). Cap 1656 -> 1686, exact.
    # fix(#1532): -97, the first time this cap has come DOWN. The byte-range
    # parser moved to app/platform/http/ranges.py because the export download
    # needs the same one and lives under processing/, which may not import
    # modules/catalog/. Nothing about the parsing changed; it is the same file's
    # worth of reasoning, now in a place both callers can reach.
    # fix(#1532 review r1): -18 more. `_range_bound_to_this_version` followed the
    # parser into the shared module, because the export route has to evaluate the
    # same If-Range precondition and a second implementation of strong comparison
    # is how the two would drift.
    # fix(#1532 review r9): -81 more, same reason a third time. If-Match,
    # If-None-Match and the 304 builder went to app/platform/http/ranges.py so
    # the export download can evaluate the same preconditions against the same
    # kind of strong ETag. Everything seven review rounds settled travelled with
    # them; only the home changed. Cap 1686 -> 1490, exact.
    # fix(#1693): +48. _resolve_download_user's no-auth-signal
    # case now returns None instead of an unconditional 401 (mirroring
    # get_optional_user, what /export's dependency already does), so
    # download_cog's existing check_dataset_access_or_anonymous +
    # public-visibility gate — previously unreachable for a plain anonymous
    # GET — actually runs. download_cog's authenticated branch also now
    # routes its capability check through get_permission_extension() instead
    # of inlining the matrix lookup, matching export_dataset_endpoint. The
    # docstring (published OpenAPI description) is left untouched to avoid
    # openapi.json/SDK/CLI churn; the new None case is explained in a plain
    # comment instead, same as the file already does for the HEAD/GET
    # docstring split above it. fix(#1693 codex r1): +10 more —
    # `if qt:` -> `if qt is not None:` so a present-but-empty ?token= 401s
    # through the existing PyJWTError path instead of falling through to the
    # new anonymous return None as if no token were supplied. Cap
    # 1490 -> 1548, exact.
    # fix(#1778): +3 lines — download_cog documents the
    # 412 its If-Match branch raises, closing a gap the repaired
    # OpenAPI-contract gate surfaced. Cap 1548 -> 1551, exact.
    # fix(#1778): 1551 -> 1602 -> 1632. +81 for `_cog_presign_seconds` and the
    # note above it. The s3 branch signed the redirect for a flat 3600 seconds,
    # which exchanged the 120-second, dataset-scoped, revocable download token
    # SEC-04 mints for an hour-long bearer URL the bucket will honour after the
    # grant is revoked. The last 30 are the codex r8 round, which removed the
    # 60-second floor the first pass had put under the window: a token with one
    # second left still bought a minute of access to a private COG. Those lines
    # are the refusal that replaced it and the reason it has to be a refusal,
    # quoting `require_signable_job_lifetime`, which settled the same question
    # for the upload doors under #1235.
    "backend/app/modules/catalog/datasets/api/router_export.py": 1632,
    # fix(#1532 review r29): first entry — crossed _RATCHET_INCLUSION_LOC. The
    # export artifact cache: everything is in the key (stamp, size, digest,
    # nonce), freshness and reclamation read one publication bound that is a
    # pure function of the object and clamps both clocks by the edge's request
    # budget, publication hands a lost race its incumbent, and the sweep, the
    # budget and the contested rule all read the same listing. Most of the
    # length is the reasoning from twenty-nine review rounds, kept next to the
    # rules it justifies. Cap 1020, exact.
    # fix(#1532) follow-up (#1585): +70 — the selection key becomes URL
    # segment / version segment, so every version of one URL shares a prefix,
    # and `url_answered_other_bytes_recently` asks that prefix whether the URL
    # answered with different bytes inside the last TTL: for that TTL bare
    # ranges are whole, which is what lets a fresh build honour the leading
    # Range of a cold GDAL open without reopening the splice, on the hit path
    # too. Cap 1020 -> 1090, exact.
    "backend/app/processing/export/artifact_cache.py": 1090,
    # fix(#1548 review P2): crossed the inclusion threshold. The growth is
    # assert_domain_lock_is_enforceable — the write-side precondition that
    # refuses a domain lock this deployment could never enforce, because
    # PUBLIC_APP_URL ships defaulted to localhost in both compose files and the
    # #1531 read-side fix is inert for anyone who leaves it there. Most of the
    # lines are the docstring, and they are the point: it records why the
    # serving origin is never INFERRED (every unconfigured source is
    # caller-controlled, so an inferred self-origin would be satisfiable by
    # exactly the parties a domain lock excludes) and why the refusal condition
    # is the narrow one, naming the two weaker predicates that were tried and
    # what each gets wrong. Cap at the exact size. This module is the embed
    # token domain end to end — CRUD, the single policy reader both validators
    # share, and now this precondition — and is not where new domains belong.
    # fix(#1548 review r2): +16 — get_active_embed_token, so the PATCH handler
    # can settle whether the token exists BEFORE applying the precondition
    # above. Asked in the other order, a deployment-level refusal answered for
    # a stale or concurrently revoked token id and told its owner to go
    # reconfigure PUBLIC_APP_URL. The router and update_embed_token share the
    # one query rather than carrying a copy each. Cap 1013 -> 1029, exact.
    # fix(#1548 review r8): +9 — gate the self-origin candidates on
    # is_usable_public_origin before normalizing them. The comment is most of
    # it, and it records why the order matters: _normalize_origin PREPENDS
    # https:// to anything without an http(s) scheme, so an environment value of
    # ftp://maps.example.com arrived as the plausible non-loopback origin
    # https://ftp: and convinced the domain-lock gate the deployment was
    # configured. Cap 1029 -> 1038, exact.
    # fix(#1548 review r9): +4 — depend on get_configured_public_app_url and
    # bail when it is None. get_public_app_url is a RESOLVER: with PUBLIC_APP_URL
    # unset it derives an app URL from an /api-stripped PUBLIC_API_URL, and a
    # split app/API deployment then had the API host accepted as a self-origin,
    # so a lock was issued that every shell request missed. Cap 1038 -> 1042.
    # fix(#1555): +14, all comment except two lines. _is_localhost_origin now
    # asks is_loopback_host (app/core/public_urls.py) instead of an enumerated
    # set of three spellings, because 127.0.0.0/8 is loopback in its entirety
    # and http://127.0.0.2:8080 was read as a routable public origin — enough
    # for the gate to issue a domain lock every recipient resolves to their own
    # machine. The rest records why _LOOPBACK_CLIENT_IPS stays an exact set:
    # that one GATES the localhost bypass, so a miss there denies, while a miss
    # in the other ISSUES an unenforceable lock. Cap 1042 -> 1056.
    # fix(#1778): +44, almost all comment. Revocation now stamps a denial over
    # the validation-cache entry instead of deleting it, and the validator
    # publishes its positive entry with set_if_absent, so a request that raced
    # an uncommitted revoke cannot re-cache the token for the rest of the TTL.
    # The four eviction sites collapse into one _deny_revoked_embed_tokens
    # helper; the rest records the interleaving, why deleting the key cannot
    # close it from either side, and the fail-closed trade a rolled-back
    # revocation makes. Cap 1056 -> 1100.
    # fix(#1778 codex r1): +6, all comment. The denial write is
    # set_authoritative, not set: `set` routes to whichever store the circuit
    # breaker says is live, so a positive that landed in the in-memory fallback
    # during an outage survived a denial written after Redis recovered.
    # Cap 1100 -> 1106, exact.
    # fix(#1778 codex r3): +52. The fallback and the replay queue are
    # PROCESS-local and production runs several Uvicorn workers, so a revoke on
    # one worker during a Redis outage reached no other. Reads and writes of the
    # validation entry now pass security=True (never answer an authorization
    # positive from this worker's memory), every positive is stamped with the
    # cluster-global revocation generation and compared against it on each hit,
    # and the revoke paths advance that generation. Most of the lines are the
    # comment on EMBED_TOKEN_POSITIVE_TTL_SECONDS, which names the residual this
    # bounds rather than closes, plus the note on what an unstamped pre-upgrade
    # entry does. Cap 1106 -> 1164, exact.
    # fix(#1778 codex r4): +10 for the comment saying why the generation bump
    # shares the caller's transaction rather than running ahead of it, and why
    # a failing bump must not be swallowed. Cap 1164 -> 1174, exact.
    # fix(#1778 codex r5): +18. An unreadable counter yields a SENTINEL, not a
    # generation, and two entries stamped with it compared EQUAL. The validator
    # now refuses to trust or to write anything while the generation is
    # unusable, so a positive cached during that window cannot outlive a later
    # revocation. Cap 1174 -> 1192, exact.
    # fix(#1860): +59. The mint took its dataset snapshot straight off the map's
    # layers with no visibility filter and ignored who was asking, so a map
    # owner who lost access to a layer could still freeze it into a fresh
    # anonymous tile capability of up to 365 days. Adds
    # _assert_scope_visible_to_minter and its EmbedScopeNotVisibleError, and
    # moves the snapshot ahead of the revoke block. Most of the lines are the
    # two docstrings, which carry the parts a later reader would otherwise
    # simplify away: why the minter is resolved from user_id rather than passed
    # in (so the row's created_by and the checked identity cannot diverge), and
    # why the refusal has to precede the revoke (the cache denial it writes is
    # not rolled back with the transaction). Cap 1192 -> 1254, exact.
    # fix(#1860 audit P3): +1 for EmbedScopeNotVisibleError's docstring naming
    # the 403 it is answered with. The maps-router siblings it copies its shape
    # from answer 403, and the licensing refusal on the same handler answers
    # 400, so the status is what separates "your deployment cannot do that"
    # from "you cannot see that data". Cap 1254 -> 1255, exact.
    "backend/app/modules/embed_tokens/service.py": 1255,
    # fix(#1778): first entry for this module — it crossed the 1000-line
    # inclusion threshold on the property-filter typing. Property filters used
    # to bind the raw query-string value, so PostgreSQL had no
    # `bigint = character varying` operator and every non-text filter failed
    # with 42883, which the OGC items handler reported as a retryable 503.
    # The growth is the pg-type -> (parser, database type) table, the parsers
    # that reject a non-finite float / an out-of-int8-range integer / an
    # unparseable date, and the extracted `_property_filter_predicates`
    # (get_features was at ruff's C901 ceiling without it). Roughly half is the
    # comment recording WHY each numeric family keeps its own database type,
    # which is a correctness property a future reader would otherwise collapse
    # into one Float.
    #
    # The clean split when it next grows is the banner already in the file:
    # everything below "Write operations" moves to a sibling module behind a
    # re-export facade, because `standards/ogc/router.py` and
    # `standards/stac/router.py` may import `features.service` and nothing
    # else under features (_STANDARDS_MODULE_IMPORT_SURFACE), and several
    # tests reach private names through it.
    #
    # fix(#1778): +80 for the bounded filtered count. The cached-feature_count
    # fast path applied only to a COMPLETELY unfiltered request, so one bbox or
    # property filter put a full filtered COUNT(*) on EVERY page, including the
    # keyset pages whose whole point is constant-time access. The count now runs
    # inside a LIMIT and the planner answers past the cap. Most of the growth is
    # the comment on _FILTERED_COUNT_CAP recording what the cap buys and why the
    # estimate is never reported below the rows already counted (a `next` link
    # keyed on `offset + limit < total` would otherwise truncate pagination at
    # the cap), plus the docstring on _planner_row_estimate saying why it is
    # deliberately not wrapped in a try/except. Cap 1055 -> 1135, exact.
    #
    # fix(#1778): +52 for UnwritablePropertyError and is_writable_feature_column.
    # A key naming a real column that _COLUMN_NAME_RE rejects used to be
    # silently skipped by the write loop, so POST and PUT answered 201/200 with
    # the value never stored, and PUT did not even NULL the column it documents
    # as nulled. Most of the growth is the exception's docstring listing which
    # producer of column_info admits which names, because the fix is a
    # disagreement between two guards and a reader has to see both to keep them
    # in step. Cap 1135 -> 1187, exact.
    #
    # fix(#1778): +197 for the incremental metadata refresh.
    # `_refresh_count_and_extent` runs one unqualified COUNT(*) + ST_Extent over
    # the whole table on every single-feature write, plus a second scan over
    # ST_ShiftLongitude past 180 degrees of width and a third DISTINCT
    # GeometryType for created datasets; there is no bulk feature endpoint, so a
    # client digitizing 200 points paid it 200 times. The new pieces are
    # geojson_bounds / feature_bounds (where the write touched),
    # _stored_extent_box, _strictly_inside, _merged_created_geometry_type and
    # _apply_incremental_metadata. Most of the growth is the reasoning each of
    # them has to carry, because every one is a claim that a scan can be
    # skipped: why the containment test is STRICT (a row on the boundary may be
    # the row defining it), why a two-ring seam extent cannot be read as a box
    # at all, and why the type merge is insert-only (a delete can narrow the
    # derived type and no merge of the stored value can see that).
    # Cap 1187 -> 1384, exact.
    #
    # fix(#1778 review r1): +107 for two review findings. The page now
    # over-fetches one row and reports `has_more`, because a `next` link
    # decided by `offset + limit < total` disappears with a full page on screen
    # whenever the count is the planner's estimate; whether another row exists
    # is a fact about rows, so FeaturePage carries it and no router re-derives
    # one. And the envelope a write overwrites is captured BY the mutating
    # statement (DELETE ... RETURNING, and a locking CTE for UPDATE) instead of
    # by an unlocked SELECT before it, with the record row locked before either
    # metadata path reads the extent. The lines are the two NamedTuples, the
    # prior-bounds SQL helpers, and the comments recording which race each
    # closes. Cap 1384 -> 1491, exact.
    #
    # fix(#1778 review r2): +16 for the range checks. A caller value can be a
    # good Python number and still be wrong for the column, and how that failed
    # depended on which cast the compiler emitted: the property-filter path
    # answered 200 with zero features, the CQL2 path overflowed a real cast
    # with SQLSTATE 22003, and a pagination int outside int8 could not be
    # encoded at all. The lines are the two check calls, the int8 bound on
    # limit/offset/after_gid, and the comments recording which of those three
    # shapes each one closes; the tables and the messages live in
    # core/db/pg_ranges.py, which standards/ogc/filtering.py reads too.
    # Cap 1491 -> 1507, exact.
    #
    # fix(#1778 review r3): +34 for _floor_estimated_total. The r1 floor read
    # `offset + len(rows)` unconditionally, which invented matches out of the
    # offset: five features asked for at offset 100 answered an empty page and
    # reported numberMatched 100, and a keyset page borrowed an offset its own
    # query had ignored. Extracted rather than narrowed in place, because
    # get_features was back at ruff's C901 ceiling and because each of the
    # three conditions is a claim about what a page can PROVE -- an exact count
    # is never raised, an empty page proves nothing, and a keyset page can
    # prove only the rows in hand. That reasoning is most of the added lines.
    # Cap 1507 -> 1541, exact.
    # fix(#1847): the lock order, its gate and its 409 mapping. Cap 1560, exact.
    "backend/app/modules/catalog/features/service.py": 1560,
}


@pytest.mark.architecture
def test_module_loc_caps_have_no_headroom() -> None:
    """Every ratchet must equal its file's current LOC.

    A cap above the current size is permission to grow. The audit found 13, 3, and 29
    spare lines in the three largest routers — each one the seed of the next
    "cap raised to N, decomposition queued" comment.

    Shrinking a file fails this too. Lower the cap in the same commit.
    """
    drift: list[str] = []
    for rel, cap in sorted(_MODULE_LOC_CAPS.items()):
        actual = len(_repo_style_path(rel).read_text().splitlines())
        if actual != cap:
            verb = "shrank below" if actual < cap else "exceeds"
            drift.append(f"{rel}: {actual} lines {verb} its cap of {cap}")

    if drift:
        pytest.fail(
            "Module LOC ratchets are out of sync with the files they track. Set each "
            "cap to the file's current line count.\n" + "\n".join(drift)
        )


# fix(#958): the inclusion rule, so a module's ABSENCE from _MODULE_LOC_CAPS is
# a decision rather than an oversight.
#
#   Every module under backend/app/ at or above _RATCHET_INCLUSION_LOC lines
#   that no OTHER size gate watches belongs in _MODULE_LOC_CAPS, ratcheted at
#   its exact LOC.
#
# Why a rule and not another hand-picked entry. #836 added the four largest
# non-routers by hand, which left the dict's membership a judgement nobody
# wrote down: analysis_sql.py then grew 504 -> 651 through no gate at all, and
# adding just that one would have ratcheted the 24th-largest ungated module
# while five modules above 1000 lines stayed free to grow. A threshold is
# arguable; an unwritten rule is not enforceable.
#
# Why 1000. It is where the modules this project has actually had to decompose
# live (the Phase 226 / 238 / 252 splits all started past it), and the measured
# distribution has a natural break there: a cluster at 1017-1201, then a gap
# down to 990. A file below the line is not safe, just cheaper to fix later.
#
# Why "no OTHER gate" rather than unconditionally. A module a ceiling gate
# already watches is not silent — it hits a wall, and whoever hits it ratchets
# the file in, which is exactly how ingest/router.py got here. Ratcheting them
# anyway would put exact caps on four routers sitting under the 1500 glob
# ceiling and on maps/style_json.py, doubling the bookkeeping for files that
# already fail loudly. This rule is about the modules NOTHING watches.
#
# The residue, recorded rather than papered over: a router.py at 1400 still has
# 100 lines of silent runway under the glob default, and the two routers-by-role
# the glob's filename match cannot see (datasets/api/router_export.py at 928 and
# router_reupload.py at 922) are watched by nothing until they cross 1000. The
# threshold catches them then. #958 also notes that any inclusion rule phrased
# as "routers are covered by the glob" is inaccurate for exactly that reason,
# which is why this one is phrased by size.
_RATCHET_INCLUSION_LOC = 1000

# The globs of test_decomposed_service_modules_stay_within_size_budgets, as
# (directory, filename prefix) pairs. fix(#958 review): the prefix alone is not
# the gate. That test globs specific directories, so a `service_*.py` anywhere
# else is watched by nothing — and a filename-only exemption here would have let
# such a module past 1000 lines through both gates, defeating the rule this
# file exists to state. Mirror the directories, not just the names.
_DECOMPOSED_MODULE_SCOPES: tuple[tuple[str, str], ...] = (
    ("backend/app/modules/catalog/maps/", "service_"),
    ("backend/app/modules/catalog/search/", "service_"),
    ("backend/app/modules/catalog/datasets/domain/", "service_"),
    ("backend/app/processing/ai/", "chat_"),
    ("backend/app/platform/extensions/", "defaults_"),
)


def _is_watched_by_another_size_gate(rel: str, name: str) -> bool:
    """True when some gate other than _MODULE_LOC_CAPS already caps this file."""
    if name == "router.py":
        return True  # test_router_orchestrator_modules_stay_within_loc_cap
    for directory, prefix in _DECOMPOSED_MODULE_SCOPES:
        # Directory, not prefix path: those globs are non-recursive.
        if rel == f"{directory}{name}" and name.startswith(prefix):
            return True  # test_decomposed_service_modules_stay_within_size_budgets
    return rel in _OPEN_CORE_SIZE_CAPS


@pytest.mark.architecture
def test_module_loc_cap_inclusion_rule_is_complete() -> None:
    """Nothing large is ungated by accident.

    The counterpart to test_module_loc_caps_have_no_headroom: that one keeps
    the listed files honest, this one decides which files get listed.
    """
    missing: list[str] = []
    for path in sorted(_backend_path("app").rglob("*.py")):
        rel = _repo_style_rel(path)
        if rel in _MODULE_LOC_CAPS or _is_watched_by_another_size_gate(rel, path.name):
            continue
        actual = len(path.read_text(encoding="utf-8").splitlines())
        if actual >= _RATCHET_INCLUSION_LOC:
            missing.append(f"{rel}: {actual} lines")

    if missing:
        pytest.fail(
            f"These modules crossed {_RATCHET_INCLUSION_LOC} lines with no size gate "
            "watching them. Add each to _MODULE_LOC_CAPS at its exact current line "
            "count, with a comment saying what the growth bought — or decompose it "
            "and stay under the threshold:\n" + "\n".join(missing)
        )


@pytest.mark.architecture
def test_decomposition_prefix_exemption_matches_the_gate_that_backs_it() -> None:
    """The exemption is a directory scope, not a filename prefix.

    fix(#958 review): ``test_decomposed_service_modules_stay_within_size_budgets``
    globs specific directories, so a ``service_*.py`` outside them is watched by
    nothing. A filename-only exemption would have let such a module grow past
    the inclusion threshold through both gates — the exact hole this rule was
    written to close, wearing a different name.
    """
    for directory, prefix in _DECOMPOSED_MODULE_SCOPES:
        inside = f"{directory}{prefix}example.py"
        assert _is_watched_by_another_size_gate(inside, f"{prefix}example.py"), (
            f"{inside} is inside a globbed directory and should read as watched"
        )

    # Same filename, a directory the gate does not glob: NOT watched, so the
    # inclusion rule keeps it once it crosses the threshold.
    stray = "backend/app/platform/service_orphan.py"
    assert not _is_watched_by_another_size_gate(stray, "service_orphan.py")

    # The globs are non-recursive; a subdirectory of a globbed one is not in
    # scope either.
    nested = "backend/app/modules/catalog/maps/nested/service_deep.py"
    assert not _is_watched_by_another_size_gate(nested, "service_deep.py")


@pytest.mark.architecture
def test_open_core_decomposition_boundaries_stay_clean() -> None:
    """Lock the shared-query, sharing, and style decompositions in place."""
    app_root = _backend_path("app")
    private_import_offenders: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "app.modules.catalog._ilike" in source:
            private_import_offenders.append(
                f"{_repo_style_rel(path)} imports removed catalog._ilike"
            )

    for domain in ("admin", "audit", "embed_tokens"):
        root = app_root / "modules" / domain
        for path in sorted(root.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.ImportFrom) or not node.module:
                    continue
                if node.module == "app.modules.catalog.maps.models":
                    private_import_offenders.append(
                        f"{_repo_style_rel(path)} imports catalog map ORM internals"
                    )

    if private_import_offenders:
        pytest.fail(
            "Cross-domain code bypassed stable text/sharing APIs:\n"
            + "\n".join(private_import_offenders)
        )

    oversized = []
    for rel, cap in _OPEN_CORE_SIZE_CAPS.items():
        actual = len(_repo_style_path(rel).read_text(encoding="utf-8").splitlines())
        if actual > cap:
            oversized.append(f"{rel}: {actual} lines > cap {cap}")
    if oversized:
        pytest.fail(
            "Decomposed modules regrew past their reviewed caps:\n"
            + "\n".join(oversized)
        )


@pytest.mark.architecture
def test_router_orchestrator_modules_stay_within_loc_cap() -> None:
    """Phase 276 CODE-01: router and orchestrator modules stay <= 1500 LOC.

    Catches regrowth of large API-edge modules toward the size cliff that
    triggered the Phase 226 / Phase 238 / Phase 252 decompositions.
    Allowlisted modules are ratcheted at their current size (see _MODULE_LOC_CAPS).

    Scope: ``backend/app/**/router.py`` (all module + standards routers).
    Decomposed service modules (``service_*.py``) are covered separately by
    ``test_decomposed_service_modules_stay_within_size_budgets``; the largest
    non-``router.py`` modules are path-ratcheted in _MODULE_LOC_CAPS (#836).
    """
    DEFAULT_CAP = 1500
    allowlist = _MODULE_LOC_CAPS

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
      - ``backend/app/platform/extensions/defaults_extensions.py`` —
        ``DefaultAuditSink.emit()`` calls ``log_action()`` via deferred import
        (Phase 222 D-04 / option a from AUDIT-02; moved from defaults.py by the
        #836 facade split). The community-edition default sink is the SOLE
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
            "-P",
            r"\bawait log_action\(",
            "--",
            "backend/app/",
            ":!backend/app/modules/audit/service.py",
            ":!backend/app/platform/extensions/defaults_extensions.py",
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
            "backend/app/platform/extensions/defaults_extensions.py. All 65 historical "
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
            "-P",
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
            "-P",
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
    },
    "ingest/router.py": {
        "app.modules.catalog.authorization",
        "app.modules.catalog.datasets.domain.service",
    },
    "ingest/service.py": {
        "app.modules.catalog.authorization",
    },
    "ingest/tasks_vector.py": {
        "app.modules.catalog.sources.adapters.arcgis",
    },
    "tiles/router.py": {"app.modules.catalog.datasets.domain.models"},
}

# fix(#1438 codex review): built from `_backend_path()`/`BACKEND_ROOT`, not
# `REPO_ROOT / "backend" / ...`. `_discover_repo_roots()` returns `BACKEND_ROOT
# == REPO_ROOT / "backend"` only in the host layout; in the backend-container
# layout it also supports, `REPO_ROOT` is `/` and `BACKEND_ROOT` is `/app`, so
# the `REPO_ROOT`-relative spelling resolved to a nonexistent `/backend/app/
# processing` and every guard built on it scanned zero files and passed
# vacuously in-container. Proven both ways: constructing the analogous
# _STANDARDS_DIR the same (wrong) way and rglob-ing it found 0 files in a
# simulated container layout; constructing it via BACKEND_ROOT found the
# files. `_PLATFORM_DIR` below had the identical bug.
_PROCESSING_DIR = _backend_path("app/processing")


def _processing_import_edges() -> dict[str, set[str]]:
    """Every `app.modules.*` import under processing/, at ANY scope.

    fix(#1438 F17): broadened from `app.modules.catalog` so a bypass into ANY
    product domain (auth, audit, quota, embed_tokens, ...) is visible, not just
    catalog. `_catalog_import_edges()` and `_other_domains_import_edges()` below
    are the two ways this gets sliced — kept as separate burndowns rather than
    one merged list because they lead to different fixes (see
    `_other_domains_import_edges()`'s docstring).

    Handles two import-syntax gaps (fix #1438 codex review): a RELATIVE import
    (`from ...modules.auth import X`) is resolved to its absolute path via
    `_resolve_relative_import()` before the prefix check, rather than reading
    `node.module` as if it were always already-absolute. And `from app.modules
    import auth` resolves `node.module` to exactly `"app.modules"` — no
    trailing segment — which does not itself start with `"app.modules."`;
    falling back to each imported name as a possible extension catches the
    target this shape actually reaches (`"app.modules.auth"`) without also
    recording the bare, non-specific `"app.modules"` for the common shape
    where `node.module` already spells out the full target.
    """
    edges: dict[str, set[str]] = {}
    for path in sorted(_PROCESSING_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                resolved = _resolve_relative_import(path, node)
                if resolved is None:
                    continue
                if resolved.startswith("app.modules."):
                    modules = [resolved]
                else:
                    modules = [f"{resolved}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if module.startswith("app.modules."):
                    key = str(path.relative_to(_PROCESSING_DIR))
                    edges.setdefault(key, set()).add(module)
    return edges


def _catalog_import_edges() -> dict[str, set[str]]:
    """The `app.modules.catalog.*` subset of `_processing_import_edges()`."""
    edges: dict[str, set[str]] = {}
    for file, modules in _processing_import_edges().items():
        catalog_modules = {m for m in modules if m.startswith("app.modules.catalog")}
        if catalog_modules:
            edges[file] = catalog_modules
    return edges


def _other_domains_import_edges() -> dict[str, set[str]]:
    """The non-catalog subset of `_processing_import_edges()`.

    fix(#1438 F17): catalog edges are governed separately, above, by
    `test_no_processing_imports_catalog` — whose fix directs the reader at
    ProcessingPort (`app.core.processing_port`). That is correct for catalog:
    ProcessingPort's surface is dataset/record/map/grant methods. It has no
    auth, audit, quota, or embed-token surface, so an edge into one of those
    domains needs a different fix (a scoped port method, a dependency injected
    at the router layer, or a deferred import) — folding it into the catalog
    burndown would point the fixer at a port that cannot serve it. Kept as a
    parallel burndown instead, so each guard's failure message stays true for
    every edge it lists.
    """
    edges: dict[str, set[str]] = {}
    for file, modules in _processing_import_edges().items():
        other_modules = {m for m in modules if not m.startswith("app.modules.catalog")}
        if other_modules:
            edges[file] = other_modules
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


# fix(#1438 F17): burn-down list of `app.modules.*` imports inside
# `backend/app/processing/` that reach a product domain OTHER than catalog — the
# same PROCESS-02/04 bypass the catalog burndown above tracks, widened to every
# domain now that the guard sees all of `app.modules.` rather than just
# `app.modules.catalog`. See `_other_domains_import_edges()` for why this stays a
# separate dict instead of merging into `_PROCESSING_CATALOG_IMPORT_BURNDOWN`.
#
# The list may SHRINK, never grow.
_PROCESSING_OTHER_DOMAINS_IMPORT_BURNDOWN: dict[str, set[str]] = {
    "ai/query_router.py": {
        "app.modules.audit.service",
        "app.modules.auth.dependencies",
    },
    "ai/router.py": {
        "app.modules.auth.dependencies",
    },
    "export/router.py": {
        "app.modules.audit.service",
        "app.modules.auth.dependencies",
        "app.modules.auth.permissions",
    },
    "ingest/manifest_router.py": {
        "app.modules.auth.dependencies",
    },
    "ingest/manifest_service.py": {
        "app.modules.quota.service",
    },
    "ingest/presigned.py": {
        "app.modules.quota.service",
    },
    "ingest/router.py": {
        "app.modules.auth.dependencies",
        "app.modules.quota.service",
    },
    "ingest/tasks_common.py": {
        "app.modules.audit.service",
    },
    "ingest/tasks_raster.py": {
        "app.modules.quota.service",
    },
    "ingest/tasks_raster_common.py": {
        "app.modules.quota.service",
    },
    "ingest/tasks_raster_replace.py": {
        "app.modules.audit.service",
    },
    "ingest/tasks_raster_swap.py": {
        "app.modules.quota.service",
    },
    "ingest/tasks_vrt.py": {
        "app.modules.quota.service",
    },
    "tiles/router.py": {
        "app.modules.auth.dependencies",
        "app.modules.embed_tokens.service",
    },
}


@pytest.mark.architecture
def test_no_processing_imports_other_domains() -> None:
    """Phase 225 PROCESS-02/04, broadened past catalog: processing/ reaches every
    product domain through a port, never `app.modules.*` directly.

    fix(#1438 F17): `test_no_processing_imports_catalog` held processing/ to a
    catalog-only boundary, so an equally direct reach into auth, audit, quota, or
    embed_tokens passed silently. processing/ has exactly one blessed
    cross-domain seam (ProcessingPort, for catalog); every other `app.modules.*`
    reference is the same bypass in a different domain. Walks the same
    AST-at-any-scope collector as the catalog guard (`_processing_import_edges()`),
    so a function-local import cannot hide from either.
    """
    offenders: list[str] = []
    for file, modules in sorted(_other_domains_import_edges().items()):
        allowed = _PROCESSING_OTHER_DOMAINS_IMPORT_BURNDOWN.get(file, set())
        for module in sorted(modules - allowed):
            offenders.append(f"  backend/app/processing/{file}: {module}")

    if offenders:
        pytest.fail(
            "backend/app/processing/ imports app.modules.* outside the catalog "
            "domain and outside the burn-down allowlist. Route the behavior "
            "through a port — app.core.processing_port for catalog-shaped "
            "access, or a scoped port method / injected dependency for auth, "
            "audit, quota, or embed-token access — instead of adding an entry "
            "to _PROCESSING_OTHER_DOMAINS_IMPORT_BURNDOWN.\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_processing_other_domains_import_allowlist_is_current() -> None:
    """The cross-domain burn-down list must shrink as edges are migrated.

    Mirrors `test_processing_catalog_import_allowlist_is_current` for the
    non-catalog axis — a stale entry is a silent licence to reintroduce the
    bypass later.
    """
    edges = _other_domains_import_edges()
    stale: list[str] = []
    for file, modules in sorted(_PROCESSING_OTHER_DOMAINS_IMPORT_BURNDOWN.items()):
        for module in sorted(modules - edges.get(file, set())):
            stale.append(f"  {file}: {module}")

    if stale:
        pytest.fail(
            "_PROCESSING_OTHER_DOMAINS_IMPORT_BURNDOWN lists edges that no longer "
            "exist. Delete them — the list only shrinks.\n" + "\n".join(stale)
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
            "-P",
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
            "-P",
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


# fix(#909): env-sensitive helpers that test fixtures redirect by assigning to
# the module the fixture actually patches. A module-scope `from <module> import
# <name>` snapshots the object into the importing module's own namespace, so
# the fixture's patch never reaches it — and the test silently reads or WRITES
# the dev database while passing (the #898 export-ogr incident). Call sites
# must late-bind (`from <module> import <name>` inside the function) so the
# patched module's current attribute is resolved at call time.
#
# Maps patched module -> redirected symbol names. Extend this when a fixture
# starts redirecting another module-scope-importable helper.
_FIXTURE_REDIRECTED_SYMBOLS: dict[str, frozenset[str]] = {
    # fix(#909 codex review): engine included — the client fixture reassigns
    # db_module.engine to the test engine, so a module-scope engine binding
    # escapes the redirect exactly like async_session (the health-service
    # probe was the live instance).
    "app.core.db": frozenset({"async_session", "engine"}),
    "app.processing.ingest.ogr": frozenset({"build_pg_conn_str"}),
}

# fix(#909 codex review): the conftest fixture patches the FAÇADE attributes
# (`app.core.db.engine` / `.async_session`), never the origin module's, so
# importing these from `app.core.db.session` escapes the redirect at ANY
# scope — late-binding does not save it, because the attribute it late-binds
# against was never patched. `app/core/db/rls.py` used to do exactly that and
# would open a dev-database connection from inside a test. These imports are
# therefore banned outright and must go through the façade.
_UNPATCHED_ORIGIN_SYMBOLS: dict[str, frozenset[str]] = {
    "app.core.db.session": frozenset({"async_session", "engine"}),
}

# The one sanctioned binding: app/core/db/__init__.py re-exports from
# app.core.db.session, and that package attribute is exactly what the conftest
# fixture patches (`db_module.async_session = ...`), so the façade must keep
# its binding for the patch to have a target.
_FIXTURE_REDIRECT_ALLOWED_FILES = frozenset({"app/core/db/__init__.py"})


def _redirect_escaping_imports(tree: ast.AST) -> list[tuple[int, str, str, str]]:
    """Return (lineno, origin-module, symbol, reason) for offending imports.

    Two distinct failure modes:

    - ``module-scope``: the symbol IS patched on this module, but a
      module-scope ``from <origin> import <name>`` snapshots it at import
      time. Module scope means anywhere outside a function body — class
      bodies and conditional/try blocks at module level bind at import time
      and escape the patch the same way. Late-binding inside the function
      fixes these.
    - ``unpatched-origin``: the fixture never patches this module's
      attribute, so the import escapes at every scope. Only switching to the
      patched façade fixes these.
    """
    inside_functions: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if child is not node:
                    inside_functions.add(child)

    offenders: list[tuple[int, str, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        at_module_scope = node not in inside_functions
        for forbidden, reason in (
            (_UNPATCHED_ORIGIN_SYMBOLS.get(node.module), "unpatched-origin"),
            (
                _FIXTURE_REDIRECTED_SYMBOLS.get(node.module)
                if at_module_scope
                else None,
                "module-scope",
            ),
        ):
            if not forbidden:
                continue
            for alias in node.names:
                if alias.name in forbidden:
                    offenders.append((node.lineno, node.module, alias.name, reason))
    # ast.walk is breadth-first, so sort for a stable, source-ordered report.
    return sorted(offenders)


@pytest.mark.architecture
def test_no_imports_that_escape_the_fixture_db_redirect() -> None:
    """fix(#909): no import path may resolve the un-patched dev-database engine.

    AST-based rather than git grep so untracked files are covered and
    multi-name import lists (`from app.core.db import async_session,
    tenant_task`) cannot slip through.

    Negative-control: temporarily add `from app.core.db import async_session`
    at the top of any module under backend/app/, run this test, confirm it
    fails with the offending file:line surfaced. Revert. (Automated as
    test_fixture_redirect_guard_catches_seeded_violation below.)
    """
    app_root = _backend_path("app")
    failures: list[str] = []
    for path in sorted(app_root.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        if rel in _FIXTURE_REDIRECT_ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text(), filename=rel)
        for lineno, module, symbol, reason in _redirect_escaping_imports(tree):
            failures.append(
                f"{rel}:{lineno}: `from {module} import {symbol}` ({reason})"
            )

    assert not failures, (
        "Import(s) that escape the test fixture's database redirect, so the "
        "test silently reads or writes the DEV database while passing (see "
        "#909). `module-scope`: late-bind the import inside the function. "
        "`unpatched-origin`: import from the `app.core.db` façade, which is "
        "what the fixture patches:\n" + "\n".join(failures)
    )


def test_fixture_redirect_guard_catches_seeded_violation() -> None:
    """The guard must fail on a seeded module-scope offender (issue #909 §3)."""
    seeded = ast.parse(
        "import uuid\n"
        "from app.core.db import Base, async_session\n"
        "def ok():\n"
        "    from app.core.db import async_session\n"
    )
    assert _redirect_escaping_imports(seeded) == [
        (2, "app.core.db", "async_session", "module-scope")
    ]


def test_fixture_redirect_guard_catches_unpatched_origin_at_any_scope() -> None:
    """fix(#909 codex review): late-binding does NOT rescue an import from
    ``app.core.db.session``. conftest reassigns ``app.core.db.engine``, not
    ``app.core.db.session.engine``, so the deferred lookup still resolves the
    dev-database engine — the shape ``rls.apply_tenancy_rls_from_engine`` had.
    Both scopes must be reported, and the façade equivalent must not be."""
    seeded = ast.parse(
        "from app.core.db.session import engine\n"
        "def late():\n"
        "    from app.core.db.session import engine\n"
        "def facade():\n"
        "    from app.core.db import engine\n"
    )
    assert _redirect_escaping_imports(seeded) == [
        (1, "app.core.db.session", "engine", "unpatched-origin"),
        (3, "app.core.db.session", "engine", "unpatched-origin"),
    ]


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
    # fix(#1182): runs under `-P`, so `\w` in the optional `as` group is a real
    # word class. Under `-E` on macOS it matched nothing, so `except Exception
    # as foo:` lines were invisible locally while CI caught them.
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-P",
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


def test_every_parse_qsl_call_bounds_its_field_count() -> None:
    """fix(#1770 round 47 P1 class, `service_endpoints.py:bounded_parse_qsl`).

    `parse_qsl()`/`parse_qs()` have no field-count bound of their own: a
    service-advertised href can pack millions of short `key=value` pairs
    into a query string that stays comfortably under every byte/structural-
    token budget (the separators live inside one JSON string), and either
    function materialises every pair it finds before a caller's own
    comprehension or `urlencode()` copies the list again.
    `bounded_parse_qsl` in `service_endpoints.py` is the one call site every
    read of a service-advertised query string should share.

    fix(#1770 round 47b P2): round 47's own version of this test greped
    `parse_qsl\\(` only, missing `parse_qs\\(` -- same unbounded semantics,
    same `max_num_fields` fix, a different function name. Widened to
    `parse_qsl?\\(` (the trailing `l` optional), which matches both.

    Not every site gets the bound, and the exceptions are real:
    `url_redaction.py`'s two sites and `preview.py`'s one scrub or resolve
    the CALLER's own already-bounded input, and a redactor specifically must
    never itself raise (`max_num_fields` raises `ValueError` past the
    count, which would turn scrubbing an oversized credential out of an
    exception message into a crash INSIDE exception handling);
    `core/config.py`'s five sites all parse `DATABASE_URL_OVERRIDE`, an
    operator-supplied BOOT-TIME environment variable, never a runtime
    service-advertised value -- the operator already has arbitrary control
    over their own deployment, and a `ValueError` there surfaces as the
    existing boot-time config-validation failure, not a runtime refusal, so
    bounding it buys no security and a local literal would just duplicate
    `MAX_QUERY_FIELDS` across a layering boundary `config.py` cannot import
    across (it has no `app.*` imports at all, and importing `platform.
    service_endpoints` into it would very likely create an import cycle).

    fix(#1770 round 47c): `adapters/wfs.py::build_capabilities_url` and
    `service_endpoints.py::_capabilities_url` moved from the BOUND list to
    this exempted one. Round 47b bound them reasoning `_header_auth_probe`
    (`probe.py`) catches every `ValueError` from an adapter -- true for the
    `probe_wfs` caller, but not the only one: `origin_probe.py::service_
    probe_target` calls `build_capabilities_url` for the periodic health
    check (`GET /datasets/{id}/health`) with NO surrounding `except
    ValueError` at all, and `_capabilities_url` is reached from `preview.py`
    and the worker (`processing/ingest/ogr.py`) through `assert_endpoints_
    stay_on_origin`, both of which catch only `(CrossOriginEndpointError,
    EndpointCheckFailedError)`. A `ValueError` past the field count on
    either function reached three of five real callers as an uncaught
    exception -- a raw 500 on the health route, an unclassified failure on
    preview and the worker -- the exact class this whole test exists to
    close, reintroduced by "one caller checked, the rest assumed" reasoning.
    Both take the caller's own submitted service URL (`ProbeRequest`/
    `ServicePreviewRequest` cap it at 2048 chars, ~350 fields of `a=1&` at
    that length), never a value read out of a THIRD-PARTY response, so
    exempting them is the correct answer, not auditing five call sites for
    a bound that was never the fix.

    Every exempted site carries `# parse_qs: unbounded` on the same line,
    the same same-line-annotation discipline `test_no_unjustified_broad_
    except_sites` already uses for a broad `except`.

    Every OTHER site must carry `max_num_fields=` -- via `bounded_parse_qsl`
    itself, a call to it (`bounded_parse_qsl(` also matches the grep, since
    `bounded_parse_qsl(` contains the substring `parse_qsl(`), or an inline
    `max_num_fields=` on a native `parse_qs`/`parse_qsl` call where the
    caller needs that function's own return shape and EVERY real caller
    already degrades a `ValueError` past the count to a coded refusal
    (`processing/tiles/router.py`'s buried-query recovery is the one
    remaining example: attacker-reachable, unauthenticated, and its own
    `try/except ValueError` degrades to "no buried params recovered") --
    so a new second call site cannot silently reintroduce the unbounded
    class the finding named.

    Positive control: this repo has more than zero matching call sites
    today (asserted below), so an empty match list means the grep pattern
    itself broke, not that the class is closed.

    Negative-control: temporarily add a bare `parse_qsl(some_query)` call
    (or `parse_qs(...)`) with neither annotation to a sandbox file under
    `backend/app/`, run this test, confirm it fails naming the offending
    line. Revert.
    """
    result = subprocess.run(
        ["git", "grep", "-n", "-P", r"parse_qsl?\(", "--", "backend/app/"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode not in (0, 1):
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )

    lines = [line for line in result.stdout.splitlines() if line]
    assert lines, (
        "positive control failed: no `parse_qsl(`/`parse_qs(` call sites "
        "found at all -- the grep pattern is broken, not that the class is "
        "closed"
    )

    violations: list[str] = []
    for line in lines:
        if (
            "max_num_fields=" in line
            or "bounded_parse_qsl(" in line
            or "# parse_qs: unbounded" in line
        ):
            continue
        violations.append(line)

    if violations:
        pytest.fail(
            "fix(#1770 round 47 P1 class) invariant violated: a "
            "`parse_qsl(`/`parse_qs(` call site with no field-count bound "
            "and no unbounded justification. Route it through "
            "`bounded_parse_qsl` (`service_endpoints.py`), add "
            "`max_num_fields=` inline, OR mark it `# parse_qs: unbounded` "
            "on the SAME line with a comment above explaining why this "
            "specific site must never raise on field count.\n"
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

# fix(#1438 codex review): see the comment on `_PROCESSING_DIR` above — this
# constant had the identical `REPO_ROOT`-relative bug and is fixed the same
# way (vacuous-pass in the backend-container layout `_discover_repo_roots()`
# is meant to support).
_PLATFORM_DIR = _backend_path("app/platform")


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


# fix(#1438 F24): platform/ is not the only layer this rule protects — processing/
# and standards/ reach into app.modules.* too, and a leading underscore is exactly
# as fragile from either. `_STANDARDS_DIR` mirrors `_PLATFORM_DIR` / `_PROCESSING_DIR`
# above (also reused by `_standards_module_import_edges()` further down, for the
# F7 frozen-surface guard) — built via `_backend_path()`, not `REPO_ROOT`-relative,
# for the same backend-container-layout reason given on `_PROCESSING_DIR`.
_STANDARDS_DIR = _backend_path("app/standards")
_PRIVATE_MODULE_IMPORT_ROOTS: tuple[Path, ...] = (
    _PLATFORM_DIR,
    _PROCESSING_DIR,
    _STANDARDS_DIR,
)


def _private_module_import_edges() -> dict[str, set[str]]:
    """Every import reaching a `_`-prefixed segment under `app.modules.*`, at ANY
    scope, across platform/, processing/, and standards/.

    Two shapes count, because a leading underscore can sit on either side of the
    `from X import Y` boundary. `from app.modules.X import _name` marks the NAME
    private; `from app.modules.X._mod import name` (or `import
    app.modules.X._mod`) marks the MODULE private, and the imported name can look
    perfectly public while still being reached through a path that can move or
    vanish without notice. Resolving each import to its full dotted symbol path
    and checking every segment after `app.modules` catches both shapes with one
    rule, rather than two independent checks that could drift apart.

    A RELATIVE import is resolved to its absolute path first (fix #1438 codex
    review): `node.module` alone is only correct for a level-0 import, so
    `from ...modules.catalog._private import x` written deep in platform/ or
    processing/ would otherwise read as module `"modules.catalog._private"`
    — never reaching the `"app.modules"` prefix check at all.
    """
    offenders: dict[str, set[str]] = {}
    for root in _PRIVATE_MODULE_IMPORT_ROOTS:
        for path in sorted(root.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                targets: list[str] = []
                if isinstance(node, ast.ImportFrom):
                    resolved = _resolve_relative_import(path, node)
                    if resolved is None or not resolved.startswith("app.modules"):
                        continue
                    targets.extend(f"{resolved}.{alias.name}" for alias in node.names)
                elif isinstance(node, ast.Import):
                    targets.extend(
                        alias.name
                        for alias in node.names
                        if alias.name.startswith("app.modules")
                    )
                else:
                    continue
                for dotted in targets:
                    # Segments after `app`, `modules` are the product-domain path;
                    # any one of them starting with `_` is a private reach.
                    if any(part.startswith("_") for part in dotted.split(".")[2:]):
                        offenders.setdefault(_repo_style_rel(path), set()).add(dotted)
    return offenders


# fix(#1438 F24): kept separate from _PROCESSING_CATALOG_IMPORT_BURNDOWN even
# though it lists the same import line (ai/router.py:320) — that dict tracks the
# catalog-BOUNDARY crossing (fix: route through ProcessingPort); this one tracks
# the PRIVATE-SYMBOL reach the same import happens to also make (fix: promote the
# symbols to a public home). Two rules, one import, two reasons. When
# _PROCESSING_CATALOG_IMPORT_BURNDOWN's "ai/router.py":
# "app.modules.catalog.maps._router_helpers" entry is retired, this entry must be
# retired in the same commit — the underlying import is gone either way.
#
# The list may SHRINK, never grow.
_PRIVATE_MODULE_IMPORT_BURNDOWN: dict[str, set[str]] = {
    "backend/app/processing/ai/router.py": {
        "app.modules.catalog.maps._router_helpers._can_edit_map",
        "app.modules.catalog.maps._router_helpers._check_map_read_access",
    },
}


@pytest.mark.architecture
def test_no_private_module_imports_from_app_modules() -> None:
    """No `_`-prefixed name or module reached from app.modules.* outside its own
    domain, across platform/, processing/, and standards/, at any scope.

    fix(#1438 F24): broadens what was `test_platform_does_not_import_private_
    module_names` (platform/ only, name-shape only) on two axes. Directory:
    `platform/config_ops` importing the settings router's private
    `_ENTERPRISE_ONLY_TABS` was never a platform-only failure mode — the same
    fragility applies wherever backend/app/ reaches into a product module's
    internals. Shape: `processing/ai/router.py` imports two functions through
    `app.modules.catalog.maps._router_helpers` — a private MODULE — and a
    name-only check cannot see that the path itself, not just the names on it,
    is marked as liable to move or vanish without notice.
    """
    offenders: list[str] = []
    for file, symbols in sorted(_private_module_import_edges().items()):
        allowed = _PRIVATE_MODULE_IMPORT_BURNDOWN.get(file, set())
        for symbol in sorted(symbols - allowed):
            offenders.append(f"  {file}: {symbol}")

    if offenders:
        pytest.fail(
            "A private name or module is imported from app.modules.* outside its "
            "own domain. Promote it to a public home (core registry, port, or "
            "DTO) instead of adding an entry to _PRIVATE_MODULE_IMPORT_BURNDOWN.\n"
            + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_private_module_import_allowlist_is_current() -> None:
    """The burn-down list must shrink as edges are migrated — no stale entries.

    A stale entry is a silent licence to reintroduce the bypass later.
    """
    edges = _private_module_import_edges()
    stale: list[str] = []
    for file, symbols in sorted(_PRIVATE_MODULE_IMPORT_BURNDOWN.items()):
        for symbol in sorted(symbols - edges.get(file, set())):
            stale.append(f"  {file}: {symbol}")

    if stale:
        pytest.fail(
            "_PRIVATE_MODULE_IMPORT_BURNDOWN lists edges that no longer exist. "
            "Delete them — the list only shrinks.\n" + "\n".join(stale)
        )


# fix(#836): the platform->processing axis, mirroring _PLATFORM_MODULE_IMPORT_BURNDOWN
# above. `platform/extensions/defaults_*.py` delegates INTO app.processing by design
# (the CatalogPort/AI-provider defaults carried 63 such edges at audit time), but only
# through deferred function-local imports (D-17). The module-scope edges below are the
# reviewed exceptions. The list may SHRINK, never grow.
_PLATFORM_PROCESSING_IMPORT_BURNDOWN: dict[str, set[str]] = {
    # Upload/config API composition: these platform routers queue ingest work and
    # reuse the export Content-Disposition sanitizer. Resolvable by moving the
    # routers under processing/ or crossing via a core port.
    "config_ops/router.py": {"app.processing.export.service"},
    "jobs/router.py": {
        "app.processing.ingest.schemas",
        "app.processing.ingest.service",
    },
}


@pytest.mark.architecture
def test_platform_processing_imports_stay_deferred() -> None:
    """Module-scope platform->processing imports are enumerated, not tolerated.

    fix(#836): the layering guard scanned the platform->modules axis but not
    platform->processing, so the port defaults could accrete module-load-time
    processing dependencies unnoticed. Deferred (function-local) imports remain
    the sanctioned mechanism, exactly as on the modules axis.
    """
    import ast

    offenders: list[str] = []
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
            key = str(path.relative_to(_PLATFORM_DIR))
            allowed = _PLATFORM_PROCESSING_IMPORT_BURNDOWN.get(key, set())
            for module in modules:
                if module.startswith("app.processing") and module not in allowed:
                    offenders.append(f"  backend/app/platform/{key}: {module}")

    if offenders:
        pytest.fail(
            "platform/ imports app.processing.* at module scope. Defer the import "
            "into the function body (D-17) or cross via a core port, rather than "
            "adding an entry to _PLATFORM_PROCESSING_IMPORT_BURNDOWN.\n"
            + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_platform_never_imports_processing_routers() -> None:
    """No platform file imports a processing router module, at any scope.

    fix(#836): `DefaultCatalogPort.ingest_part_size` imported PART_SIZE from
    `app.processing.ingest.router` — importing an API-edge module executes route
    registration as a side effect and couples the platform seam to the router's
    import graph. Constants and helpers a port needs must live in a service or
    schema module; only api/main.py composes routers.
    """
    import ast

    offenders: list[str] = []
    for path in sorted(_PLATFORM_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if not module.startswith("app.processing"):
                    continue
                leaf = module.rsplit(".", 1)[-1]
                if leaf == "router" or leaf.endswith("_router"):
                    rel = path.relative_to(_PLATFORM_DIR)
                    offenders.append(f"  backend/app/platform/{rel}: {module}")

    if offenders:
        pytest.fail(
            "platform/ imports a processing router module. Move the needed name "
            "into a service/schema module and import that instead.\n"
            + "\n".join(offenders)
        )


# fix(#1438 F7): standards/ has two import-boundary guards, and this is the
# second. `backend/tests/test_standards_layering.py` (added by #1438) holds
# standards -> app.processing to a strict zero, mirroring the catalog rule
# (processing-owned ORM classes, queries, and helpers must be reached through
# CatalogPort). standards -> app.modules got no guard at all: the STAC and OGC
# routers construct queries directly against catalog ORM classes
# (datasets/collections/records/search), which is a live, reviewed design
# choice — those routers exist to expose the catalog through external
# standards, and a port indirection would not remove the coupling, only hide
# it. So this is NOT a burn-down toward zero the way the processing guards
# above are: it is a FROZEN surface. Today's edges are enumerated once so the
# surface cannot grow silently; shrinking (migrating an edge through
# CatalogPort) is welcome but not required.
_STANDARDS_MODULE_IMPORT_SURFACE: dict[str, set[str]] = {
    # fix(#1469): the shared "what may a feed publish" helper the three
    # DCAT-family serializers now share. Same catalog-ORM edge each of them
    # already carries, in one file instead of three, and TYPE_CHECKING-only —
    # it is duck-typed on the Dataset instance at runtime.
    "distributions.py": {
        "app.modules.catalog.datasets.domain.models",
    },
    "dcat/service.py": {
        "app.modules.catalog.datasets.domain.models",
        "app.modules.catalog.records.localization",
    },
    "dcat_us/service.py": {
        "app.modules.catalog.datasets.domain.models",
    },
    "geodcat_ap/service.py": {
        "app.modules.catalog.datasets.domain.models",
    },
    "ogc/filtering.py": {
        "app.modules.catalog.datasets.domain.models",
        "app.modules.catalog.search.schemas",
    },
    "ogc/router.py": {
        "app.modules.auth.dependencies",
        "app.modules.catalog.authorization",
        "app.modules.catalog.datasets.domain.models",
        "app.modules.catalog.features.schemas",
        "app.modules.catalog.features.service",
    },
    "ogc/schemas.py": {
        "app.modules.catalog.features.schemas",
    },
    "stac/router.py": {
        "app.modules.auth.dependencies",
        "app.modules.catalog.authorization",
        "app.modules.catalog.collections.models",
        "app.modules.catalog.datasets.domain.models",
        "app.modules.catalog.features.service",
        "app.modules.catalog.search.service",
    },
    "stac/schemas.py": {
        "app.modules.catalog.features.schemas",
    },
}


def _standards_module_import_edges() -> dict[str, set[str]]:
    """Every `app.modules.*` import under standards/, at ANY scope.

    Same two shapes handled as `_processing_import_edges()` above (fix #1438
    codex review): a relative import is resolved to its absolute path before
    the prefix check, and `from app.modules import X` falls back to each
    imported name as a possible extension of the bare, non-specific
    `"app.modules"` `node.module` resolves to.
    """
    edges: dict[str, set[str]] = {}
    for path in sorted(_STANDARDS_DIR.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                resolved = _resolve_relative_import(path, node)
                if resolved is None:
                    continue
                if resolved.startswith("app.modules."):
                    modules = [resolved]
                else:
                    modules = [f"{resolved}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                continue
            for module in modules:
                if module.startswith("app.modules."):
                    key = str(path.relative_to(_STANDARDS_DIR))
                    edges.setdefault(key, set()).add(module)
    return edges


@pytest.mark.architecture
def test_standards_module_import_surface_does_not_grow() -> None:
    """standards/ -> app.modules.* is frozen at today's edges, not banned.

    fix(#1438 F7): unlike the processing/platform burndowns elsewhere in this
    file, `_STANDARDS_MODULE_IMPORT_SURFACE` is not a to-do list — STAC/OGC/DCAT
    exist to expose the catalog to external standards, so direct ORM access is
    the design, not debt. What this guards against is the surface growing
    UNREVIEWED: a new file or a new edge here should be a deliberate addition to
    the allowlist, not a silent side effect of a router growing a new route.
    """
    offenders: list[str] = []
    for file, modules in sorted(_standards_module_import_edges().items()):
        allowed = _STANDARDS_MODULE_IMPORT_SURFACE.get(file, set())
        for module in sorted(modules - allowed):
            offenders.append(f"  backend/app/standards/{file}: {module}")

    if offenders:
        pytest.fail(
            "backend/app/standards/ imports app.modules.* outside its reviewed "
            "surface. If this is a deliberate, reviewed addition (mirroring the "
            "existing STAC/OGC/DCAT catalog-ORM access), add it to "
            "_STANDARDS_MODULE_IMPORT_SURFACE. If it is avoidable, prefer "
            "CatalogPort (app.core.catalog_port) instead.\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_standards_module_import_surface_is_current() -> None:
    """The frozen surface must shrink (or stay flat) as edges are migrated.

    A stale entry overstates today's coupling and is a silent licence to
    reintroduce a since-removed edge later without review.
    """
    edges = _standards_module_import_edges()
    stale: list[str] = []
    for file, modules in sorted(_STANDARDS_MODULE_IMPORT_SURFACE.items()):
        for module in sorted(modules - edges.get(file, set())):
            stale.append(f"  {file}: {module}")

    if stale:
        pytest.fail(
            "_STANDARDS_MODULE_IMPORT_SURFACE lists edges that no longer exist. "
            "Delete them — the surface only shrinks.\n" + "\n".join(stale)
        )


# fix(#1438 F6): widens test_platform_never_imports_processing_routers (fix #836)
# past its original platform-only, processing-only shape. That guard stays exactly
# as written below — it is STRICTER on its own axis (any scope, not just module
# scope) — this one adds the coverage it never had: every package, importing a
# router module belonging to any OTHER package.
def _dotted_package(path: Path) -> str:
    """The dotted `app.…` package a file lives in — its containing directory."""
    return ".".join(path.parent.relative_to(BACKEND_ROOT).parts)


def _module_package(dotted: str) -> str:
    """Everything before a dotted module path's last segment — its package."""
    return dotted.rsplit(".", 1)[0] if "." in dotted else dotted


def _is_router_module(module: str) -> bool:
    """True when a dotted module path's filename-equivalent leaf names a router.

    Mirrors how `test_platform_never_imports_processing_routers` identifies a
    router module (``leaf == "router"`` or ``leaf.endswith("_router")``), plus
    the ``router_*`` prefix convention used across catalog/maps, catalog/
    datasets/api, catalog/search, admin, and settings (router_assets.py,
    router_export.py, router_saved.py, router_operations.py, router_public.py,
    ...). Checked against every module in backend/app/ that actually
    instantiates ``APIRouter(``: the three shapes below match that set exactly
    — zero misses, zero false positives. (A private ``_router_helpers.py``
    starts with ``_``, not ``router``, so it does not match either shape.)
    """
    leaf = module.rsplit(".", 1)[-1]
    return leaf == "router" or leaf.startswith("router_") or leaf.endswith("_router")


def _resolves_to_real_module(dotted: str) -> bool:
    """True when a dotted `app.…` path names a real file or package under backend/.

    fix(#1438 F6 codex review): distinguishes `from app.platform.jobs import
    router` (imports the `router.py` SUBMODULE — `router` here names a real
    file) from `from app.core.schemas import router_id_param` (imports an
    ordinary NAME that happens to start with `router_` — no such file exists).
    Both are the same AST shape (`ImportFrom(module=X, names=[alias(name=Y)])`);
    only the filesystem tells them apart. Needed because `_is_router_module()`
    is a filename heuristic — applying it to every imported NAME without this
    check would flag the second case as a router import.
    """
    candidate = BACKEND_ROOT / Path(*dotted.split("."))
    return (
        candidate.with_suffix(".py").is_file() or (candidate / "__init__.py").is_file()
    )


# The aggregate composition root: app/api/router.py imports every domain's
# router to compose api_router, and app/api/main.py imports _titiler_client
# from app.processing.tiles.router at module scope. Both are the ONE place
# this fan-in is supposed to happen (every other guard in this file that
# mentions routers says the same thing: "only api/main.py composes routers").
_ROUTER_COMPOSITION_ROOT = frozenset(
    {"backend/app/api/router.py", "backend/app/api/main.py"}
)


def _cross_package_router_import_edges() -> dict[str, set[str]]:
    """Every MODULE-SCOPE import of a router module from outside its own
    package, across all of backend/app/.

    fix(#1438 F6): importing an API-edge module runs its route registration as
    a side effect and couples the importer to the router's whole transitive
    import graph, just to reach one constant or helper function — the exact
    shape fix(#836) diagnosed, but that guard could only see it for platform/
    importing app.processing.*. The failure mode is not domain-specific: any
    package reaching across a boundary for a name that belongs in a service or
    schema module has the same problem.

    Two import shapes reach a router submodule, and both are checked (fix
    #1438 F6 codex review): `from app.platform.jobs.router import name` names
    it as `node.module` directly; `from app.platform.jobs import router` names
    it as an imported NAME, resolved against the filesystem via
    `_resolves_to_real_module()` so an ordinary name that merely starts with
    `router_` is not mistaken for a submodule.

    Module scope only, determined by AST ancestry rather than `col_offset`
    (fix #1438 F6 codex review): `col_offset != 0` was the established idiom
    elsewhere in this file, but it also skips an import nested in a top-level
    `try`/`if` block — indented, so nonzero column, but still executed at
    module-import time. Walking function bodies to build an exclusion set
    (mirroring `_redirect_escaping_imports()` above) excludes only imports
    truly inside a function, which is where the D-17 deferred-import escape
    hatch used throughout this file actually defers to — it does not run the
    router's side effects at the importer's import time, so it does not
    reproduce the bug this guard exists to catch.

    Same-package nesting is not an edge: a domain's ``router.py`` composing
    its own ``router_*.py`` siblings (e.g. ``catalog/maps/router.py`` including
    ``catalog/maps/router_assets.py``) is the normal way a domain's API surface
    is assembled, and neither file is "outside its own package" from the
    other's perspective.

    A RELATIVE import is resolved to its absolute path first (fix #1438 codex
    review): `from ...platform.jobs.router import name`, written deep inside
    `app/modules/catalog/collections/`, stores `node.module ==
    "platform.jobs.router"` with `node.level == 3` — reading `node.module`
    directly gives a string that does not start with `"app."` and is silently
    skipped, the same equivalent-relative-syntax bypass `_resolve_relative_
    import()` closes for the other three collectors in this file.
    """
    offenders: dict[str, set[str]] = {}
    for path in sorted(_backend_path("app").rglob("*.py")):
        rel = _repo_style_rel(path)
        if rel in _ROUTER_COMPOSITION_ROOT:
            continue
        importer_package = _dotted_package(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))

        inside_functions: set[ast.AST] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    if child is not node:
                        inside_functions.add(child)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                resolved = _resolve_relative_import(path, node)
                if resolved is None:
                    continue
                candidates = [resolved]
                candidates.extend(
                    f"{resolved}.{alias.name}"
                    for alias in node.names
                    if _resolves_to_real_module(f"{resolved}.{alias.name}")
                )
            elif isinstance(node, ast.Import):
                candidates = [alias.name for alias in node.names]
            else:
                continue
            if node in inside_functions:
                continue
            for module in candidates:
                if not module.startswith("app.") or not _is_router_module(module):
                    continue
                if _module_package(module) == importer_package:
                    continue
                offenders.setdefault(rel, set()).add(module)
    return offenders


# fix(#1438 F6): the one edge the enumeration surfaced is flagged here rather
# than treated as routine reviewed debt. Every OTHER burndown in this file
# traces to a fix commit that named its tradeoff and accepted it; this edge
# predates any guard that could see it (source outside platform/, target
# outside app.processing/ — invisible to both axes fix(#836) checked) and was
# added in #476 ("harden lifecycle and tenant isolation"), a PR about tenant
# isolation with nothing suggesting this coupling was a deliberate choice.
# Seeded so the guard is actionable on today's tree rather than failing on
# pre-existing, unrelated code — worth a follow-up to move
# `get_retry_capability` into a plain service module, the way `sweep.py`
# already did for this same router's other non-route helpers (see
# app/platform/jobs/router.py's own module docstring).
#
# The list may SHRINK, never grow.
_CROSS_PACKAGE_ROUTER_IMPORT_BURNDOWN: dict[str, set[str]] = {
    "backend/app/modules/admin/router.py": {"app.platform.jobs.router"},
}


@pytest.mark.architecture
def test_no_cross_package_router_imports_at_module_scope() -> None:
    """No file outside its own package imports a router module at module
    scope, anywhere in backend/app/ — not just platform/ importing processing/.
    """
    offenders: list[str] = []
    for file, modules in sorted(_cross_package_router_import_edges().items()):
        allowed = _CROSS_PACKAGE_ROUTER_IMPORT_BURNDOWN.get(file, set())
        for module in sorted(modules - allowed):
            offenders.append(f"  {file}: {module}")

    if offenders:
        pytest.fail(
            "A module imports a router module from outside its own package at "
            "module scope. Importing an API-edge module runs its route "
            "registration as a side effect; move the needed name into a "
            "service or schema module instead of adding an entry to "
            "_CROSS_PACKAGE_ROUTER_IMPORT_BURNDOWN. If the name is only needed "
            "inside a function, deferring the import (D-17) avoids the side "
            "effect without needing an allowlist entry at all.\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_cross_package_router_import_allowlist_is_current() -> None:
    """The burn-down list must shrink as edges are migrated — no stale entries.

    A stale entry is a silent licence to reintroduce the bypass later.
    """
    edges = _cross_package_router_import_edges()
    stale: list[str] = []
    for file, modules in sorted(_CROSS_PACKAGE_ROUTER_IMPORT_BURNDOWN.items()):
        for module in sorted(modules - edges.get(file, set())):
            stale.append(f"  {file}: {module}")

    if stale:
        pytest.fail(
            "_CROSS_PACKAGE_ROUTER_IMPORT_BURNDOWN lists edges that no longer "
            "exist. Delete them — the list only shrinks.\n" + "\n".join(stale)
        )


# fix(#1778 codex r3): every cache read that DECIDES ACCESS must be marked
# security=True, so the layered provider refuses to answer it from this worker's
# process-local fallback. The provider cannot tell an authorization decision
# from a cached listing by looking at the value, so the marking is the contract
# and this test is what keeps the marking honest.
#
# Phrased as a per-module rule rather than a repo-wide one on purpose. Sweeping
# every `cache.get(` in backend/app/ and demanding the flag would be wrong: the
# catalog and collection listings, the search cache and persistent config are
# cached ANSWERS whose staleness is a correctness annoyance bounded by a TTL,
# not a capability someone still holds. Adding a module here is the deliberate
# act of saying "the values this module caches are decisions".
_AUTHORIZATION_CACHE_MODULES: tuple[str, ...] = (
    "backend/app/modules/embed_tokens/service.py",
)


@pytest.mark.architecture
def test_authorization_cache_reads_are_security_scoped() -> None:
    """Every cache get/set in an authorization module passes security=True.

    ``set_authoritative`` is exempt: it is security-shaped by construction (it
    writes a revocation into every store) and takes no flag.
    """
    import ast

    offenders: list[str] = []
    for rel in _AUTHORIZATION_CACHE_MODULES:
        path = _backend_path(rel.removeprefix("backend/"))
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in {"get", "set", "set_if_absent"}:
                continue
            # Only calls on something named `cache`, which is what get_cache()
            # is bound to everywhere in these modules.
            if not (isinstance(func.value, ast.Name) and func.value.id == "cache"):
                continue
            flagged = any(
                kw.arg == "security"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in node.keywords
            )
            if not flagged:
                offenders.append(f"  {rel}:{node.lineno} cache.{func.attr}(...)")

    if offenders:
        pytest.fail(
            "An authorization cache call is missing security=True, so a layered "
            "provider may answer it from this worker's in-memory fallback. That "
            "fallback cannot see a revoke another Uvicorn worker performed while "
            "Redis was down (fix(#1778 codex r3)). Offending calls:\n"
            + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_authorization_cache_guard_catches_a_seeded_violation() -> None:
    """The guard above fails on an unflagged call, so a green run means something."""
    import ast

    seeded = "cache.get(cache_key)\ncache.set(k, v, ttl=1, security=True)\n"
    found = []
    for node in ast.walk(ast.parse(seeded)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in {"get", "set"}:
            continue
        flagged = any(
            kw.arg == "security"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
            for kw in node.keywords
        )
        if not flagged:
            found.append(func.attr)
    assert found == ["get"], (
        "the seeded unflagged call was not detected, so the real guard is inert"
    )
