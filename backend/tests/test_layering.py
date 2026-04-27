"""Layering rules: core/ must not depend on modules/settings/.

Enforces the open-core boundary closed by Phase 212. If this test fails, a
`from app.modules.settings.<...>` import (or `import app.modules.settings.<...>`)
was introduced under `backend/app/core/`, which violates the rule that modules
depend on core, not the reverse.

Scope (Phase 212): NARROW — only `from app.modules.settings`. Phases 213
(catalog-authz-relocate) and 214 (identity-protocol-extract) close additional
core->modules edges; Phase 218 will broaden this guard to `from app.modules.<*>`
once those phases land.

Markers:
- `@pytest.mark.architecture` — opt-out locally with `pytest -m 'not architecture'`
  (D-07). Runs by default in CI because `addopts` does not exclude it.
"""

from __future__ import annotations

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


def _git_grep(pattern: str, path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "grep", "-n", "-E", pattern, "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


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
