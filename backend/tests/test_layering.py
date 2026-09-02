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
        "backend/app/modules/catalog/search/service_semantic.py": 482,
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
        "backend/app/modules/catalog/datasets/domain/service_metadata.py": 479,
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
        "backend/app/modules/catalog/datasets/domain/service_lifecycle.py": 483,
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
        "backend/app/processing/ai/chat_geojson.py": 437,
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
    "backend/app/modules/catalog/sources/arcgis_signin.py": 1301,
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
    "backend/app/modules/catalog/sources/router.py": 1561,
