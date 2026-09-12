"""Enforce backend dependency boundaries and size ratchets.

Core does not depend on product modules. Processing reaches catalog through
``ProcessingPort``; catalog reaches processing through ``CatalogPort``.
Permission, workflow, and provider decisions use their extension seams.
Private module internals and route modules do not leak across packages.

Explicit allowlists describe existing debt and must shrink as edges disappear.
Line-count caps are exact where stated, so a module that shrinks must lower its
cap and a module that grows must split or document its current exception.

Tests marked ``architecture`` run by default and may be excluded locally with
``pytest -m 'not architecture'``. Failures name the offending paths or lines.
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
    # Source-tree fallback when neither host nor container layout is detected.
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
    rather than fail.
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


# Cache git capabilities for module-level skip decorators.
_GIT_METADATA_AVAILABLE: bool = _has_git_metadata()
_PATHSPEC_MAGIC_AVAILABLE: bool = _has_pathspec_magic()
_GIT_METADATA_REASON = "git metadata unavailable; arch test only runs on full clones"
_PATHSPEC_MAGIC_REASON_GENERIC = (
    "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce architecture "
    "invariant via grep-based guard"
)


def _git_grep(pattern: str, path: str) -> subprocess.CompletedProcess[str]:
    # PCRE is required because POSIX ERE does not define \s, \b, or \w.
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

    `node.module` is absolute only for a level-zero import. A relative import —
    ``from . import X``,
    ``from ..pkg.mod import X`` — stores the leading dots as `node.level` and
    `node.module` as whatever follows them (``None`` for a bare ``from .
    import``), so a guard that reads `node.module` directly sees
    ``"platform.jobs.router"`` (or nothing at all) for what is actually
    ``app.platform.jobs.router`` — invisible to any check anchored on the
    ``app.`` prefix. Climbing `node.level - 1` steps up from the FILE's own
    package and appending `node.module` reconstructs the real target.
    This local copy avoids coupling test modules through private helpers.
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
    """Core is the lowest layer and must not import product modules."""
    result = _git_grep(
        r"^\s*(from|import)\s+app\.modules\.",
        "backend/app/core/",
    )

    # git grep exit codes: 0 = matches found, 1 = no matches, >1 = error
    if result.returncode == 0:
        pytest.fail(
            "Layering violation: backend/app/core/ contains imports from "
            "app.modules.* (modules must depend on core, not the reverse). "
            "core/ is the lowest layer. Offending lines:\n" + result.stdout
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
def test_app_settings_imports_only_via_core_db_models() -> None:
    """The deleted settings-model path must not return anywhere in the backend."""
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
    """The deleted auth visibility module must not be imported."""
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
    """References to the deleted auth visibility path must not return.

    Import-shaped lines are checked so this guard does not match its own documentation."""
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
    """Known permission chokepoints delegate to PermissionExtension.

    The guard covers capability checks, visibility filtering, and dataset-detail access."""
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
            "require_permission() must "
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
            "apply_visibility_filter() "
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
            "dataset detail access must "
            "delegate access decisions to PermissionExtension. Expected "
            "get_permission_extension().can_access_dataset(...) in "
            f"{_repo_style_rel(catalog_path)}."
        )


@pytest.mark.architecture
def test_workflow_publication_chokepoints_use_extension() -> None:
    """Known dataset publication transitions delegate to WorkflowExtension."""
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
                "publication workflow invariant violated: "
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
            "metadata PATCH record_status "
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
    """Cross-domain code must not bind the concrete auth User ORM.

    Auth/admin code and named SQL query sites are explicit exceptions. Type-only annotations use UserIdentity; runtime relationship targets use strings."""
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
            "`User` ORM from `app.modules.auth.models`. "
            "Cross-domain code must type against "
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
    """Dataset callers use the public service facade, never split internals.

    The split modules may import each other; the facade re-exports their supported surface. Tests are excluded so they can exercise internals directly."""
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
            "external module "
            "imports from a catalog/datasets/domain/service_X sub-module "
            "directly. All consumers must go through the "
            "`app.modules.catalog.datasets.domain.service` façade. "
            "Cross-imports between the 5 sub-modules themselves are "
            "permitted (D-05) — only external bypasses are forbidden.\n"
            "Offending lines:\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_no_external_imports_of_maps_private_service_modules() -> None:
    """Map callers use the public service facade; split implementation modules remain private."""
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
            "production code imports "
            "maps private service modules directly. External callers must "
            "import from `app.modules.catalog.maps.service`; only the maps "
            "facade and maps service_*.py modules may import private service "
            "modules directly.\nOffending lines:\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_no_external_imports_of_search_private_service_modules() -> None:
    """Search callers use the public service facade; split implementation modules remain private."""
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
            "production code imports "
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
# Three covers the supported simple-assignment chains; the loop exits early.
_BINDING_REBIND_ROUNDS = 3

# Legitimate facade consumers. The positive-direction check keeps the guard
# from rejecting them. Buffer rendering and SQL generation share the distance
# ceiling, so both AI modules consume the facade.
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
    """Return expressions bound to the analysis_sql facade, including aliases.

    Bindings are collected file-wide and through simple assignment forms. This deliberately over-approximates across scopes so the architecture guard fails closed."""
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

    # Propagate simple, annotated, walrus, attribute, and sequence rebindings.
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
    """Return statically resolvable references to analysis_sql family modules.

    The scan covers direct and relative imports, names imported from the facade, aliases, and simple rebindings. Dynamic getattr/importlib and general data flow are outside static reach. Star imports are safe because the facade __all__ excludes family names."""
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
    """Analysis SQL consumers use one facade so preview and materialization share renderers.

    Family modules may import each other internally. External callers must use app.platform.analysis_sql; the AST scan includes untracked files."""
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
            "worker from drifting apart on what SQL they run.\n" + "\n".join(offenders)
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
    """The facade importable surface must equal __all__ plus named exemptions.

    Exact comparison prevents accidental public helpers. A companion guard forbids external access to unavoidable package-bound submodule attributes; both checks are required."""
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
        # Must-pass twins prove binding resolution rather than alias blacklisting.
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
        f"`from {_ANALYSIS_SQL_PACKAGE} import *` reaches a family: "
        f"{sorted(exported & _ANALYSIS_SQL_FAMILIES)}"
    )


@pytest.mark.architecture
def test_decomposed_service_modules_stay_within_size_budgets() -> None:
    """Keep split service modules and their stable facades bounded."""
    facade_line_budgets = {
        "backend/app/modules/catalog/maps/service.py": 100,
        "backend/app/modules/catalog/search/service.py": 80,
        "backend/app/modules/catalog/datasets/domain/service.py": 112,
        "backend/app/processing/ai/chat_service.py": 519,
        "backend/app/platform/extensions/defaults.py": 75,
    }
    private_service_default_line_budget = 350
    private_service_line_budget_allowlist = {
        # Domain splits retain operation orchestration that spans their narrower helpers.
        # Preview operations share one sandbox concurrency and serialization boundary.
        "backend/app/modules/catalog/datasets/domain/service_analysis.py": 612,
        # Database commits and object publication/rollback form one asset lifecycle.
        "backend/app/modules/catalog/maps/service_crud.py": 850,
        "backend/app/modules/catalog/search/service_datasets.py": 281,
        # Shared-map audience decisions stay behind the permission extension seam.
        "backend/app/modules/catalog/maps/service_public.py": 987,
        "backend/app/modules/catalog/search/service_records.py": 559,
        "backend/app/modules/catalog/search/service_semantic.py": 481,
        "backend/app/modules/catalog/maps/service_diff.py": 400,
        "backend/app/modules/catalog/maps/service_shared.py": 400,
        "backend/app/modules/catalog/datasets/domain/service_relationships.py": 657,
        "backend/app/modules/catalog/datasets/domain/service_metadata.py": 512,
        "backend/app/modules/catalog/datasets/domain/service_query.py": 439,
        "backend/app/modules/catalog/datasets/domain/service_lifecycle.py": 513,
        # Chat splits retain tool execution and result-serialization workflows.
        "backend/app/processing/ai/chat_actions.py": 587,
        "backend/app/processing/ai/chat_geojson.py": 440,
        # Default adapters expose explicit extension contracts rather than catch-all shims.
        "backend/app/platform/extensions/defaults_ai_openai.py": 520,
        "backend/app/platform/extensions/defaults_ai_anthropic.py": 372,
        "backend/app/platform/extensions/defaults_catalog_port.py": 569,
        # ProcessingPort signatures remain explicit across the catalog boundary.
        "backend/app/platform/extensions/defaults_processing_port.py": 568,
        "backend/app/platform/extensions/defaults_extensions.py": 433,
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
    # Discover chat implementation modules; the facade has its own budget.
    files_to_check.extend(
        _repo_style_rel(path)
        for path in sorted(_backend_path("app/processing/ai").glob("chat_*.py"))
        if path.name != "chat_service.py"
    )
    # Discover extension defaults implementations; the facade is listed above.
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
            "Decomposed service modules "
            "(maps / search / datasets-domain / processing/ai/chat_*) "
            "exceeded their line-count budgets. Split the module or add a "
            "reviewed explicit cap only when growth is intentional.\n"
            + "\n".join(violations)
        )


# These decomposition ceilings may shrink freely; the inclusion rule uses them
# to avoid tracking the same module in both cap tables.
_OPEN_CORE_SIZE_CAPS: dict[str, int] = {
    "backend/app/modules/catalog/maps/style_json.py": 1597,
    "backend/app/modules/catalog/maps/style_import.py": 605,
    "backend/app/modules/catalog/maps/style_sanitizers.py": 192,
    "backend/app/modules/catalog/maps/router_assets.py": 149,
    "backend/app/modules/catalog/maps/router_sharing.py": 430,
    "backend/app/modules/catalog/search/query_params.py": 205,
    "backend/app/modules/catalog/search/router_saved.py": 97,
    "backend/app/modules/admin/router_operations.py": 323,
    "backend/app/modules/settings/router_public.py": 175,
}


# Caps equal current LOC. Lower them when modules shrink; split or explain growth.
# Full paths cover oversized modules beyond the router glob.
_MODULE_LOC_CAPS: dict[str, int] = {
    # Manifest reservation, staging and fenced settlement share one apply workflow.
    "backend/app/processing/ingest/manifest_service.py": 1163,
    # Endpoint parsing, SSRF checks and credential forwarding share one security
    # boundary.
    "backend/app/platform/service_endpoints.py": 1360,
    # Pagination and materialization keep credentials and remote page traversal out of
    # GDAL.
    "backend/app/platform/service_items.py": 777,
    # ArcGIS sign-in shares destination checks, abuse budgets and deadlines across its
    # protocol.
    "backend/app/modules/catalog/sources/arcgis_signin.py": 1151,
    # ArcGIS probing and metadata adapter debt; split protocol helpers before raising.
    "backend/app/modules/catalog/sources/adapters/arcgis.py": 887,
    # Source API router debt; split discovery, preview and dispatch endpoints before
    # raising.
    "backend/app/modules/catalog/sources/router.py": 1736,
    # Adoption DDL mirrors the current schema without importing historical migrations.
    "backend/app/core/db/tenant_adoption_sql.py": 2093,
    # Adoption coordinates resumable tenant transactions with ownership and ACL repair.
    "backend/app/core/db/tenant_adoption.py": 1258,
    # Application composition debt; preserve lifespan and middleware ordering when
    # splitting.
    "backend/app/api/main.py": 1721,
    # Published map schema debt; separate validation helpers before raising.
    "backend/app/modules/catalog/maps/schemas.py": 1396,
    # Metadata facade preserves the import and patch surface used by extensions and
    # callers.
    "backend/app/processing/ingest/metadata.py": 153,
    # Ingest API router debt; split upload, import and registration endpoints before
    # raising.
    "backend/app/processing/ingest/router.py": 1830,
    # Shared task finalization keeps lifecycle and cleanup consistent across ingest
    # formats.
    "backend/app/processing/ingest/tasks_common.py": 1912,
    # Reupload coordinates staging, credentials and fenced settlement across
    # file/service paths.
    "backend/app/processing/ingest/tasks_reupload.py": 1295,
    # Refresh strategies share access, admission and dispatch rules at this API
    # boundary.
    "backend/app/modules/catalog/datasets/api/router_refresh.py": 1291,
    # Config planning, signed dry runs and application share one transaction workflow.
    "backend/app/platform/config_ops/service.py": 1161,
    # Reconciliation and reapers serve startup, workers and admin cleanup consistently.
    "backend/app/platform/jobs/sweep.py": 1537,
    # Refresh transitions serve request and worker paths without crossing domain
    # boundaries.
    "backend/app/platform/refresh/service.py": 929,
    # Central settings and boot-validation debt; split by configuration domain before
    # raising.
    "backend/app/core/config.py": 1496,
    # Config resolution coordinates validation, overrides, caching, audit and side
    # effects.
    "backend/app/core/persistent_config.py": 943,
    # Backfill batches share vector/model validation and progress/cancellation
    # semantics.
    "backend/app/processing/embeddings/backfill.py": 933,
    # Reupload preview, compatibility and staged commit share an endpoint lifecycle.
    "backend/app/modules/catalog/datasets/api/router_reupload.py": 1472,
    # VRT creation and regeneration share publication and superseded-object cleanup.
    "backend/app/processing/ingest/tasks_vrt.py": 1690,
    # Raster conversion, verification and fenced publication share one failure
    # lifecycle.
    "backend/app/processing/ingest/tasks_raster_replace.py": 996,
    # File/service tasks share publication fencing, heartbeat phases and failure
    # cleanup.
    "backend/app/processing/ingest/tasks_vector.py": 1179,
    # GDAL environments, timeouts, reaping and error sanitization share one process
    # boundary.
    "backend/app/processing/ingest/ogr.py": 1351,
    # Archive and GDAL content validation remain centralized at the upload security
    # boundary.
    "backend/app/processing/ingest/validation.py": 1104,
    # OAuth destination validation, account linking and role reconciliation share one
    # boundary.
    "backend/app/modules/auth/oauth/service.py": 1111,
    # Admin mutations share locking and audit outcomes.
    "backend/app/modules/admin/service.py": 1019,
    # Ingest admission, staging and job settlement share one orchestration boundary.
    "backend/app/processing/ingest/service.py": 1437,
    # PostGIS refresh coordinates geometry repair, measurement and fenced catalog
    # updates.
    "backend/app/processing/ingest/tasks_postgis_refresh.py": 979,
    # Dataset schema debt; split request/response families before raising.
    "backend/app/modules/catalog/datasets/domain/schemas.py": 1510,
    # Analysis validation, bounded execution and fenced registration share one task
    # lifecycle.
    "backend/app/processing/analysis/tasks.py": 1421,
    # Maps API router debt; split endpoint families before raising.
    "backend/app/modules/catalog/maps/router.py": 1507,
    # Native search and OGC Records share visibility, query parsing and pagination.
    "backend/app/modules/catalog/search/router.py": 1433,
    # STAC endpoints share visibility, extent, lineage and pagination conformance rules.
    "backend/app/standards/stac/router.py": 1828,
    # Authorization, acquisition order and cache rehydration share this route boundary;
    # the Enterprise overlay pins _check_cold_rehydrate here.
    "backend/app/processing/tiles/router.py": 2480,
    # SQL allowlisting and cost validation must share canonical AST resolution.
    "backend/app/platform/sandbox/validator.py": 1691,
    # AI orchestration coordinates tool execution, usage accounting and SSE failures.
    "backend/app/processing/ai/service.py": 994,
    # Record children share ownership, ordering and publication-version invariants.
    "backend/app/modules/catalog/records/service.py": 877,
    # Export formats share visibility, lineage and private-artifact authorization.
    "backend/app/modules/catalog/datasets/api/router_export.py": 1484,
    # Artifact selection, atomic publication, range reads and eviction share one cache
    # protocol.
    "backend/app/processing/export/artifact_cache.py": 559,
    # Embed tokens share origin/scope checks, revocation and cached-denial behavior.
    "backend/app/modules/embed_tokens/service.py": 1030,
    # Feature reads/writes share schema typing, safe SQL and geometry/metadata
    # invariants; temporal writes reuse the validated filter parsers.
    "backend/app/modules/catalog/features/service.py": 1400,
}


@pytest.mark.architecture
def test_module_loc_caps_have_no_headroom() -> None:
    """Every ratchet must equal its file's current LOC.

    Shrinking a file also fails; lower its cap in the same change.
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


# Every module at or above this threshold needs an exact cap unless another
# size gate already covers it. The threshold catches large nonstandard router
# names and other modules that filename-based gates miss, without duplicating
# caps for files already governed by a ceiling.
_RATCHET_INCLUSION_LOC = 1000

# Mirror the decomposed-module gate's non-recursive directory and prefix globs;
# a matching filename elsewhere is not covered.
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
    """Size-gate exemptions match both the directory and filename prefix used by the underlying non-recursive globs."""
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
    """Router and orchestrator modules stay within the shared ceiling.

    Specific decomposed modules use stricter caps elsewhere in this file."""
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
            "Router modules exceeded "
            "their LOC cap. Either decompose the module (preferred — split "
            "into a facade and cohesive submodules rather than raising "
            "patterns) or, if growth is intentional, raise the explicit "
            "allowlist entry with a current rationale.\n" + "\n".join(violations)
        )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
@pytest.mark.skipif(
    not _PATHSPEC_MAGIC_AVAILABLE,
    reason=(
        "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
        "the audit-call boundary via its grep-based guard"
    ),
)
def test_no_log_action_calls_outside_audit_service() -> None:
    """Only the default audit sink calls log_action directly.

    Production callers use audit_emit so deployments can replace the audit extension. The AST guard checks only call sites, not definitions or documentation."""
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
            "log_action() is called "
            "outside backend/app/modules/audit/service.py and "
            "backend/app/platform/extensions/defaults_extensions.py. All "
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
    """The removed app.core.marketplace module must not return."""
    import importlib

    # (a) Importing the module must fail
    try:
        importlib.import_module("app.core.marketplace")
        pytest.fail(
            "app.core.marketplace must not be importable. "
            "Marketplace billing belongs in the enterprise overlay."
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
            "the removed marketplace path via its grep-based guard"
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
            "backend/app/ still "
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
    """The billing dispatch loop passes the required literal timeout to every handler invocation."""
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-P",
            r"asyncio\.wait_for\(ext\.on_startup\(app\), timeout=10\.0\)",
            "--",
            # API lifespan and worker startup share this bootstrap dispatch loop.
            "backend/app/platform/extensions/bootstrap.py",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 1:
        pytest.fail(
            "Billing dispatch invariant violated: "
            "backend/app/platform/extensions/bootstrap.py does NOT contain the "
            "production BillingExtension dispatch loop with literal "
            "`asyncio.wait_for(ext.on_startup(app), timeout=10.0)`. The "
            "10-second timeout must remain fixed. Either the dispatch loop is missing or the "
            "literal timeout was changed."
        )
    if result.returncode not in (0,):
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )


# Existing processing-to-catalog port bypasses. This list may shrink, never
# grow; new calls route through ProcessingPort so overlays can intercept them.
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

# Resolve from BACKEND_ROOT so host and backend-container layouts scan the same tree.
_PROCESSING_DIR = _backend_path("app/processing")


def _processing_import_edges() -> dict[str, set[str]]:
    """Collect every app.modules import under processing at any scope.

    Relative imports and from-app.modules-import-name forms are resolved to absolute targets before classification."""
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
    """Return processing imports into product domains other than catalog.

    Catalog has its own burn-down and ProcessingPort remedy. Other domains may require a scoped port, router injection, or deferred import, so their diagnostics remain separate."""
    edges: dict[str, set[str]] = {}
    for file, modules in _processing_import_edges().items():
        other_modules = {m for m in modules if not m.startswith("app.modules.catalog")}
        if other_modules:
            edges[file] = other_modules
    return edges


@pytest.mark.architecture
def test_no_processing_imports_catalog() -> None:
    """Processing reaches catalog through ProcessingPort.

    The AST scan covers imports at every scope; named existing edges form a shrink-only burn-down."""
    offenders: list[str] = []
    for file, modules in sorted(_catalog_import_edges().items()):
        allowed = _PROCESSING_CATALOG_IMPORT_BURNDOWN.get(file, set())
        for module in sorted(modules - allowed):
            offenders.append(f"  backend/app/processing/{file}: {module}")

    if offenders:
        pytest.fail(
            "backend/app/processing/ "
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


# Existing processing imports into non-catalog product domains. This stays
# separate because those edges need different ports or injection. Shrink only.
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
    # Staging reads current usage to bound its stream; the router checks upload admission.
    "ingest/url_import_staging.py": {
        "app.modules.quota.service",
    },
    "tiles/router.py": {
        "app.modules.auth.dependencies",
        "app.modules.embed_tokens.service",
    },
}


@pytest.mark.architecture
def test_no_processing_imports_other_domains() -> None:
    """Processing does not import product domains directly.

    The same all-scope AST collector backs this shrink-only non-catalog burn-down."""
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
        "the catalog-to-processing boundary via its grep-based guard"
    ),
)
def test_no_catalog_imports_processing() -> None:
    """Catalog reaches processing only through CatalogPort.

    The scan covers module-level and deferred imports while ignoring comment-only references."""
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
                "catalog-to-processing boundary violated: "
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
        "the provider-dispatch boundary via its grep-based guard"
    ),
)
def test_no_hardcoded_ai_provider_branches() -> None:
    """AI provider dispatch goes through the provider extension rather than provider-name branches."""
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
            "Hardcoded AI provider "
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
    """Processing does not import provider SDKs at module scope.

    Provider defaults own SDK imports; processing depends on extension protocols and remains importable without optional SDKs."""
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


# Fixture-redirected helpers must be read from the patched module at call time;
# a module-scope direct import can retain a development-database object.
_FIXTURE_REDIRECTED_SYMBOLS: dict[str, frozenset[str]] = {
    # Both attributes are reassigned by the client fixture.
    "app.core.db": frozenset({"async_session", "engine"}),
    "app.processing.ingest.ogr": frozenset({"build_pg_conn_str"}),
}

# The fixture patches facade attributes, so imports from their origin module
# escape the redirect even when late-bound. Always use app.core.db.
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
    """No backend import may retain an unpatched development-database object.

    The fixture redirects named facade attributes; direct imports of their
    definitions escape that redirect.
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
        "test silently reads or writes the DEV database while passing. "
        "`module-scope`: late-bind the import inside the function. "
        "`unpatched-origin`: import from the `app.core.db` façade, which is "
        "what the fixture patches:\n" + "\n".join(failures)
    )


def test_fixture_redirect_guard_catches_seeded_violation() -> None:
    """The guard must fail on a seeded module-scope offender."""
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
    """The fixture redirect guard detects direct imports and aliases at every scope."""
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
    """Backend manifest apply remains independent of CLI, generated SDK, and Enterprise packages."""

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
            "Backend manifest apply "
            "imports CLI, generated SDK, or Enterprise-only modules directly. "
            "Keep manifest apply backend-local and use existing community "
            "extension ports. Offending lines:\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_manifest_apply_router_uses_upload_permission() -> None:
    """Manifest apply uses the existing upload permission."""

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
    """Thumbnail upload uses a JSON request model rather than an ambiguous string body.

    The guard checks both positional and keyword-only defaults because FastAPI stores Body metadata there."""
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
            "Thumbnail route function "
            "'upload_thumbnail' not found in "
            "backend/app/modules/catalog/maps/router.py. The route was "
            "renamed or removed; update this guard or restore the route."
        )

    # Inspect the parameter list. The route must NOT have any parameter
    # whose default is a Body(...) call with a `media_type` keyword arg
    # set to a non-JSON content type (typically "text/plain").
    #
    # FastAPI Body metadata may live in positional or keyword-only defaults.
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
                    "Thumbnail route parameter "
                    f"'{arg.arg}' on upload_thumbnail uses "
                    f"Body(..., media_type='{kw.value.value}'). "
                    "openapi-python-client cannot parse non-JSON request "
                    "bodies and will silently drop the endpoint from the "
                    "Python SDK. Switch to a Pydantic JSON body model "
                    "such as ThumbnailUploadRequest."
                )


@pytest.mark.architecture
@pytest.mark.skipif(not _GIT_METADATA_AVAILABLE, reason=_GIT_METADATA_REASON)
@pytest.mark.skipif(
    not _PATHSPEC_MAGIC_AVAILABLE,
    reason=(
        "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
        "the broad-exception annotation rule via its grep-based guard"
    ),
)
def test_no_unjustified_broad_except_sites() -> None:
    """Every broad exception handler in backend/app carries a same-line reason.

    Use # broad: for intentional safety boundaries or # noqa: BLE001 where Ruff also needs suppression. Tests are outside this production guard."""
    # Match `except Exception:` and `except Exception as foo:` lines
    # under backend/app/ only (tests/ is out of scope).
    # PCRE is required for the optional `as name` word class on every host.
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
            "Unjustified broad-except "
            "sites found. Add `# broad: <reason>` (or `# noqa: BLE001 "
            "<reason>`) on the SAME line as the `except`, OR tighten the "
            "catch to a specific exception class.\n"
            "Offending lines:\n" + "\n".join(violations)
        )


def test_every_parse_qsl_call_bounds_its_field_count() -> None:
    """Runtime query-string parsing must bound field count.

    Service-advertised URLs use bounded_parse_qsl or max_num_fields. Explicit # parse_qs: unbounded sites are limited to redaction of already-bounded input and operator-supplied boot configuration, where raising during cleanup or startup is the wrong contract. Both parse_qs and parse_qsl are scanned."""
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
            "Unbounded query parsing found: a "
            "`parse_qsl(`/`parse_qs(` call site with no field-count bound "
            "and no unbounded justification. Route it through "
            "`bounded_parse_qsl` (`service_endpoints.py`), add "
            "`max_num_fields=` inline, OR mark it `# parse_qs: unbounded` "
            "on the SAME line with a comment above explaining why this "
            "specific site must never raise on field count.\n"
            "Offending lines:\n" + "\n".join(violations)
        )


# Existing module-scope imports from platform into product modules. Shrink only.
# Deferred imports remain the supported cycle-breaking seam for default adapters.
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

# Resolve from BACKEND_ROOT for both host and backend-container layouts.
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
    """Platform does not add product-module imports beyond the shrink-only burn-down."""
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


# Private product-module imports are forbidden from every shared layer.
_STANDARDS_DIR = _backend_path("app/standards")
_PRIVATE_MODULE_IMPORT_ROOTS: tuple[Path, ...] = (
    _PLATFORM_DIR,
    _PROCESSING_DIR,
    _STANDARDS_DIR,
)


def _private_module_import_edges() -> dict[str, set[str]]:
    """Collect imports of private app.modules names from protected shared layers.

    Relative imports and imported submodule names are resolved before checking underscore-prefixed path segments."""
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


# This separately tracks private-symbol use; the same edge may also violate the
# catalog boundary. Retire both entries together when the import disappears.
_PRIVATE_MODULE_IMPORT_BURNDOWN: dict[str, set[str]] = {
    "backend/app/processing/ai/router.py": {
        "app.modules.catalog.maps._router_helpers._can_edit_map",
        "app.modules.catalog.maps._router_helpers._check_map_read_access",
    },
}


@pytest.mark.architecture
def test_no_private_module_imports_from_app_modules() -> None:
    """Platform, processing, and standards do not import product-domain private modules outside the shrink-only burn-down."""
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


# Platform defaults may delegate into processing through deferred imports.
# These existing module-scope exceptions are shrink only.
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
    """Platform may reach processing only through the named deferred-import burn-down."""
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
    """Platform never imports processing router modules at any scope."""
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


# Standards expose catalog models directly, so this is a frozen surface rather
# than a zero-edge rule. New imports are forbidden; migration through CatalogPort
# may shrink the set. Standards-to-processing remains zero tolerance elsewhere.
_STANDARDS_MODULE_IMPORT_SURFACE: dict[str, set[str]] = {
    # Shared feed-publication policy; the model import is type-checking only.
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
    """Collect standards imports into app.modules at any scope, resolving relative and imported-submodule forms."""
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
    """Standards-to-product imports may not grow beyond the frozen shrink-only surface."""
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
    """The standards import surface contains no stale entries."""
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


# Detect cross-package router imports across all backend packages.
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
    """Return whether a dotted app path names a real module or package.

    This distinguishes imported router submodules from ordinary imported names that happen to start with router_."""
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
    """Collect module-scope imports of router modules across package boundaries.

    Both direct-module and imported-submodule forms are resolved, including relative imports. Function-local imports are deferred and excluded. Same-package router composition and the API composition root are allowed."""
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


# Existing admin-to-jobs-router edge. Move get_retry_capability to a service
# module, then remove this shrink-only exception.
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


# Authorization cache reads use security=True so a process-local fallback
# cannot serve a stale capability after revocation.
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
            "Redis was down. Offending calls:\n" + "\n".join(offenders)
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
