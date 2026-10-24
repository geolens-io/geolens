"""Workflow supply-chain hardening: token scopes and pinned installs.

Top-level ``permissions:`` apply to every job that does not set its own, so
write scopes belong on the job that uses them.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import yaml

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# Existing top-level grants. Shrink this map; never add to it.
_TOP_LEVEL_WRITE_ALLOWED = {
    "publish-cli.yml": {"id-token"},
    "publish-mcp.yml": {"id-token"},
    "publish-sdks.yml": {"id-token"},
}


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def _write_scopes(permissions: Any) -> set[str]:
    if permissions == "write-all":
        return {"write-all"}
    if not isinstance(permissions, dict):
        return set()
    return {scope for scope, level in permissions.items() if level == "write"}


def test_top_level_permissions_grant_no_write_scope():
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert files
    for path in files:
        workflow = _load(path)
        assert "permissions" in workflow, f"{path.name} has no top-level permissions"
        writes = _write_scopes(workflow["permissions"])
        assert writes == _TOP_LEVEL_WRITE_ALLOWED.get(path.name, set()), (
            f"{path.name} grants {sorted(writes)} at the top level; "
            "grant write scopes on the jobs that need them"
        )


def test_publish_job_holds_the_image_push_and_attestation_scopes():
    publish = _load(WORKFLOWS / "publish.yml")["jobs"]["publish"]

    assert publish["permissions"] == {
        "contents": "read",
        "packages": "write",
        "id-token": "write",
        "attestations": "write",
    }


def test_release_job_runs_only_for_a_tag_push_smoke():
    release = _load(WORKFLOWS / "release.yml")["jobs"]["release"]

    assert release["permissions"] == {"contents": "write"}
    condition = " ".join(release["if"].split())
    assert "github.event.workflow_run.event == 'push'" in condition
    assert "github.event.workflow_run.conclusion == 'success'" in condition


def test_pre_commit_job_installs_the_locked_group():
    steps = _load(WORKFLOWS / "ci.yml")["jobs"]["pre-commit"]["steps"]
    runs = "\n".join(step.get("run", "") for step in steps)

    assert "pip install" not in runs
    assert "uv sync --project backend --locked --only-group pre-commit" in runs
    pyproject = tomllib.loads((REPO_ROOT / "backend" / "pyproject.toml").read_text())
    assert "pre-commit" in pyproject["dependency-groups"]
