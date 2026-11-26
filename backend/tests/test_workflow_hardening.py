"""Workflow supply-chain hardening: token scopes and pinned installs.

Top-level ``permissions:`` apply to every job that does not set its own, so
write scopes belong on the job that uses them.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
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

    assert release["permissions"] == {"contents": "write", "attestations": "read"}
    condition = " ".join(release["if"].split())
    assert "github.event.workflow_run.event == 'push'" in condition
    assert "github.event.workflow_run.conclusion == 'success'" in condition


def _step(steps: list[dict[str, Any]], name: str) -> int:
    return next(i for i, step in enumerate(steps) if step.get("name") == name)


def test_release_checks_out_the_tag_and_requires_the_smoked_commit():
    steps = _load(WORKFLOWS / "release.yml")["jobs"]["release"]["steps"]
    checkouts = [
        i
        for i, s in enumerate(steps)
        if s.get("uses", "").startswith("actions/checkout@")
    ]

    assert len(checkouts) == 1
    checkout = steps[checkouts[0]]
    assert checkout["with"]["ref"] == "refs/tags/${{ env.TAG }}"
    assert "workflow_run" not in str(checkout["with"])
    guard = _step(steps, "Require the tag to point at the smoked commit")
    assert checkouts[0] < guard < _step(steps, "Create release")
    assert steps[guard]["env"] == {
        "SMOKED_SHA": "${{ github.event.workflow_run.head_sha }}"
    }
    assert '"${HEAD_SHA}" != "${SMOKED_SHA}"' in steps[guard]["run"]


def test_release_image_builds_read_no_actions_cache():
    steps = _load(WORKFLOWS / "publish.yml")["jobs"]["publish"]["steps"]
    builds = [
        s
        for s in steps
        if str(s.get("uses", "")).startswith("docker/build-push-action")
    ]
    assert builds
    for step in builds:
        assert not {"cache-from", "cache-to"} & set(step["with"]), step["name"]


def test_installer_attestation_is_a_pinned_tag_push_job_that_cannot_fail_publish():
    job = _load(WORKFLOWS / "publish.yml")["jobs"]["attest-installer"]

    assert job["permissions"] == {
        "contents": "read",
        "id-token": "write",
        "attestations": "write",
    }
    assert job["continue-on-error"] is True
    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref
    attest = next(
        s for s in job["steps"] if s.get("uses", "").startswith("actions/attest@")
    )
    # The tagged checkout's script, never a downloaded release asset.
    assert attest["with"] == {"subject-path": "scripts/install.sh"}
    assert "github.ref_type == 'tag'" in attest["if"]


def test_install_script_provenance_cannot_stop_a_release():
    jobs = _load(WORKFLOWS / "release.yml")["jobs"]
    release = jobs["release"]
    steps = release["steps"]

    # A runner fetches every action a job uses before its first step, so an
    # attest action here could stop the release before it was created.
    assert list(jobs) == ["release"]
    assert not [s["uses"] for s in steps if "attest" in s.get("uses", "")]
    attach = _step(steps, "Attach the install script's provenance")
    assert _step(steps, "Upload install script") < attach
    assert _step(steps, "Generate + upload SHA256SUMS") < attach
    step = steps[attach]
    assert step["continue-on-error"] is True
    wait = int(step["env"]["WAIT_SECONDS"]) + int(step["env"]["POLL_SECONDS"]) + 60
    assert wait < step["timeout-minutes"] * 60 < release["timeout-minutes"] * 60
    assert '--source-ref "refs/tags/${TAG}"' in step["run"]
    assert '.github/workflows/publish.yml"' in step["run"]


SHA = "a" * 40
REPO = "example/repo"
SIGNER = f"{REPO}/.github/workflows/publish.yml"


def _run_step(
    step: dict[str, Any], tmp_path: Path, stubs: dict[str, str], **env: str
) -> subprocess.CompletedProcess[str]:
    """Run a step's script under GitHub's default bash flags with stub commands."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    step_env = {
        k: str(v) for k, v in step.get("env", {}).items() if "${{" not in str(v)
    }
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            **step_env,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
            **env,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )


def _named_step(workflow: str, job: str, name: str) -> dict[str, Any]:
    steps = _load(WORKFLOWS / workflow)["jobs"][job]["steps"]
    return steps[_step(steps, name)]


@pytest.mark.parametrize(("smoked", "released"), [(SHA, True), ("b" * 40, False)])
def test_release_refuses_a_tag_that_moved_after_its_smoke(tmp_path, smoked, released):
    step = _named_step(
        "release.yml", "release", "Require the tag to point at the smoked commit"
    )
    proc = _run_step(
        step, tmp_path, {"git": f"echo {SHA}"}, TAG="v1.2.3", SMOKED_SHA=smoked
    )

    assert (proc.returncode == 0) is released, proc.stdout + proc.stderr
    if not released:
        assert "refusing to release" in proc.stdout


def _attach(tmp_path: Path, verify_body: str, **env: str):
    if shutil.which("jq") is None:
        if os.environ.get("CI"):
            raise RuntimeError("jq missing on a CI runner")
        pytest.skip("jq is not installed")
    step = _named_step(
        "release.yml", "release", "Attach the install script's provenance"
    )
    stubs = {
        # GNU timeout(1) isn't on every developer machine; the bound isn't under test.
        "timeout": 'shift; exec "$@"',
        "gh": f"""case "$1 $2" in
  "attestation verify") echo "$@" >> "{tmp_path}/verify-args"; {verify_body} ;;
  "release upload") cp "$4" "{tmp_path}/uploaded" ;;
esac""",
    }
    env = {"TAG": "v1.2.3", "SMOKED_SHA": SHA, "POLL_SECONDS": "0", **env}
    return _run_step(step, tmp_path, stubs, **env)


def test_release_attaches_the_attestation_for_this_tag_and_commit(tmp_path):
    proc = _attach(tmp_path, """printf '{\n "mediaType": "m"\n}\n'""")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (tmp_path / "uploaded").read_text() == '{"mediaType":"m"}\n'
    args = (tmp_path / "verify-args").read_text().split()
    pairs = {args[i]: args[i + 1] for i in range(len(args) - 1)}
    assert pairs["--source-ref"] == "refs/tags/v1.2.3"
    assert pairs["--source-digest"] == SHA
    assert pairs["--signer-workflow"] == SIGNER
    assert pairs["--repo"] == REPO
    # gh filters by ref after fetching, and one install.sh digest collects an
    # attestation per release, so the lookup asks for the most gh allows.
    assert pairs["--limit"] == "1000"


def test_release_reports_a_missing_attestation_without_uploading(tmp_path):
    proc = _attach(tmp_path, "exit 1", WAIT_SECONDS="0")

    assert proc.returncode == 1
    assert "::warning title=Install script provenance missing::" in proc.stdout
    assert "MISSING for v1.2.3" in (tmp_path / "summary").read_text()
    assert not (tmp_path / "uploaded").exists()


def _verify(tmp_path: Path, assets: str, verify_body: str = "exit 0"):
    step = _named_step(
        "verify-published.yml",
        "verify-github-release",
        "Verify the install script's provenance",
    )
    assert step["if"] == "${{ steps.release_guard.outputs.hollow != 'true' }}"
    stubs = {
        "gh": f"""case "$1 $2" in
  "release view") printf '%s\n' {assets} ;;
  "release download") echo "$@" >> "{tmp_path}/download-args" ;;
  "attestation verify")
    echo "$@" >> "{tmp_path}/verify-args"
    n=$(cat "{tmp_path}/count" 2>/dev/null || echo 0)
    echo $((n + 1)) > "{tmp_path}/count"
    {verify_body} ;;
esac""",
    }
    env = {"VERSION": "v1.2.3", "REPOSITORY": REPO, "VERIFY_DELAY": "0"}
    return _run_step(step, tmp_path, stubs, **env)


def test_verify_published_checks_the_attached_bundle_for_the_tag(tmp_path):
    proc = _verify(tmp_path, "install.sh SHA256SUMS install.sh.intoto.jsonl")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    download = (tmp_path / "download-args").read_text().split()
    assert "install.sh" in download and "install.sh.intoto.jsonl" in download
    args = (tmp_path / "verify-args").read_text().split()
    pairs = {args[i]: args[i + 1] for i in range(len(args) - 1)}
    assert args[2] == "provenance/install.sh"
    assert pairs["--bundle"] == "provenance/install.sh.intoto.jsonl"
    assert pairs["--source-ref"] == "refs/tags/v1.2.3"
    assert pairs["--signer-workflow"] == SIGNER
    assert pairs["--repo"] == REPO


def test_verify_published_warns_when_a_release_has_no_bundle(tmp_path):
    proc = _verify(tmp_path, "install.sh SHA256SUMS")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "::warning::v1.2.3 has no install.sh.intoto.jsonl" in proc.stdout
    assert not (tmp_path / "verify-args").exists()


def test_verify_published_retries_then_fails_a_bundle_that_does_not_verify(tmp_path):
    (tmp_path / "flaky").mkdir()
    flaky = _verify(
        tmp_path / "flaky", "install.sh.intoto.jsonl", '[ "$n" -ge 1 ] || exit 1'
    )
    assert flaky.returncode == 0, flaky.stdout + flaky.stderr
    assert (tmp_path / "flaky" / "count").read_text().strip() == "2"

    (tmp_path / "bad").mkdir()
    bad = _verify(tmp_path / "bad", "install.sh.intoto.jsonl", "exit 1")
    assert bad.returncode != 0
    assert (tmp_path / "bad" / "count").read_text().strip() == "3"
    assert "did not verify after 3 attempts" in bad.stdout


def test_pre_commit_job_installs_the_locked_group():
    steps = _load(WORKFLOWS / "ci.yml")["jobs"]["pre-commit"]["steps"]
    runs = "\n".join(step.get("run", "") for step in steps)

    assert "pip install" not in runs
    assert "uv sync --project backend --locked --only-group pre-commit" in runs
    pyproject = tomllib.loads((REPO_ROOT / "backend" / "pyproject.toml").read_text())
    assert "pre-commit" in pyproject["dependency-groups"]
