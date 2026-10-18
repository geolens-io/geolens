"""publish.yml ships images only from a commit whose checks on main passed.

The gate step is run under bash against a stub ``gh`` that serves a fixed list
of workflow runs, so each case states what a real tag push would do.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from typing import Any

import pytest
import yaml

from tests.repo_paths import repo_root

PUBLISH = repo_root(__file__) / ".github" / "workflows" / "publish.yml"
GATE_JOB = "require-green-commit"
SHA = "a" * 40
CI = ".github/workflows/ci.yml"
CODEQL = ".github/workflows/codeql.yml"

# A silent skip would leave the gate untested while CI reports green.
if shutil.which("jq") is None and os.environ.get("CI"):
    raise RuntimeError("jq missing on a CI runner; the publish gate cannot be run.")


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(PUBLISH.read_text())["jobs"]


def _run(
    path: str,
    *,
    event: str = "push",
    branch: str = "main",
    status: str = "completed",
    conclusion: str | None = "success",
    created: str = "2026-10-18T12:00:00Z",
    attempt: int = 1,
) -> dict[str, Any]:
    return {
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "event": event,
        "head_branch": branch,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "created_at": created,
        "run_attempt": attempt,
        "html_url": f"https://github.com/example/repo/actions/runs/{path}/{event}",
    }


GREEN = [_run(CI), _run(CODEQL)]


def _gate(
    tmp_path, *polls: list[dict[str, Any]], gh_body: str | None = None, **env: str
):
    """Run the gate; the stub ``gh`` serves one poll per call, repeating the last."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for i, runs in enumerate(polls):
        (tmp_path / f"poll-{i}").write_text("".join(json.dumps(r) + "\n" for r in runs))
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{tmp_path}/gh-args"\n'
        f'n=$(cat "{tmp_path}/count" 2>/dev/null || echo 0)\n'
        f'echo $((n + 1)) > "{tmp_path}/count"\n'
        f"[ $n -lt {len(polls)} ] || n={len(polls) - 1}\n"
        f'cat "{tmp_path}/poll-$n"\n'
        if gh_body is None
        else f"#!/bin/sh\n{gh_body}\n"
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    step = _jobs()[GATE_JOB]["steps"][0]
    step_env = {k: str(v) for k, v in step["env"].items() if "${{" not in str(v)}
    proc = subprocess.run(
        # The flags GitHub's default bash shell runs a step with.
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
        env={
            **os.environ,
            **step_env,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITHUB_REPOSITORY": "example/repo",
            "GITHUB_SHA": SHA,
            "EVENT_NAME": "push",
            "PUSH_IMAGES": "",
            "WAIT_SECONDS": "2",
            "POLL_SECONDS": "0",
            **env,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    args_file = tmp_path / "gh-args"
    return proc, args_file.read_text() if args_file.exists() else ""


def test_every_publish_job_waits_for_the_gate():
    jobs = _jobs()
    gate = jobs[GATE_JOB]
    # A skipped gate would let the publish jobs run on a red commit only if
    # they opted in with a status function; keep both sides unconditional.
    assert "if" not in gate
    assert gate["permissions"] == {"actions": "read", "contents": "read"}
    for name, job in jobs.items():
        if name == GATE_JOB:
            continue
        needs = job.get("needs")
        needs = [needs] if isinstance(needs, str) else needs or []
        assert GATE_JOB in needs, f"{name} must need {GATE_JOB}"
        assert "if" not in job, f"{name} must not override the gate with an if:"


def test_green_commit_publishes(tmp_path):
    proc, args = _gate(tmp_path, GREEN)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"repos/example/repo/actions/runs?head_sha={SHA}" in args


def test_run_paths_with_a_ref_suffix_still_match(tmp_path):
    runs = [{**run, "path": f"{run['path']}@main"} for run in GREEN]
    proc, _ = _gate(tmp_path, runs)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_red_codeql_run_blocks_and_is_listed(tmp_path):
    runs = [_run(CI), _run(CODEQL, conclusion="failure")]
    proc, _ = _gate(tmp_path, runs)
    assert proc.returncode == 1
    assert "Refusing to publish" in proc.stdout
    assert "codeql.yml (push, attempt 1): failure" in proc.stdout


@pytest.mark.parametrize("conclusion", ["timed_out", "startup_failure"])
def test_other_red_conclusions_block(tmp_path, conclusion):
    proc, _ = _gate(
        tmp_path, [*GREEN, _run(CI, event="schedule", conclusion=conclusion)]
    )
    assert proc.returncode == 1


def test_run_rerun_to_green_counts(tmp_path):
    # The runs API reports the latest attempt's conclusion.
    proc, _ = _gate(tmp_path, [_run(CI), _run(CODEQL, attempt=2)])
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_newer_scheduled_success_supersedes_an_older_failure(tmp_path):
    runs = [
        *GREEN,
        _run(
            CI, event="schedule", conclusion="failure", created="2026-10-17T07:00:00Z"
        ),
        _run(CI, event="schedule", created="2026-10-18T07:00:00Z"),
    ]
    proc, _ = _gate(tmp_path, runs)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_runs_that_do_not_test_the_commit_are_ignored(tmp_path):
    red = {"conclusion": "failure"}
    runs = [
        *GREEN,
        _run(".github/workflows/publish.yml", branch="v1.2.3", **red),
        _run(".github/workflows/prod-smoke.yml", branch="v1.2.3", **red),
        _run(".github/workflows/verify-published.yml", event="workflow_run", **red),
        _run(".github/workflows/publish.yml", event="workflow_dispatch", **red),
        _run("dynamic/dependabot/dependabot-updates", event="dynamic", **red),
        _run(CODEQL, event="pull_request", branch="feature", **red),
    ]
    proc, _ = _gate(tmp_path, runs)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_running_scheduled_run_is_not_waited_for(tmp_path):
    proc, _ = _gate(
        tmp_path, [*GREEN, _run(CI, event="schedule", status="in_progress")]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (tmp_path / "count").read_text().strip() == "1"


def test_merge_queue_success_satisfies_ci_when_the_push_run_was_cancelled(tmp_path):
    runs = [
        _run(CI, conclusion="cancelled"),
        _run(CI, event="merge_group", branch="gh-readonly-queue/main/pr-1-abc"),
        _run(CODEQL),
    ]
    proc, _ = _gate(tmp_path, runs)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_in_progress_check_is_waited_for(tmp_path):
    running = [_run(CI), _run(CODEQL, status="in_progress")]
    proc, _ = _gate(tmp_path, running, GREEN)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Waiting for checks" in proc.stdout


def test_in_progress_check_that_then_fails_blocks(tmp_path):
    running = [_run(CI), _run(CODEQL, status="in_progress")]
    proc, _ = _gate(tmp_path, running, [_run(CI), _run(CODEQL, conclusion="failure")])
    assert proc.returncode == 1


def test_check_still_running_at_the_deadline_blocks(tmp_path):
    proc, _ = _gate(tmp_path, [_run(CI), _run(CODEQL, status="in_progress")])
    assert proc.returncode == 1
    assert "did not finish green" in proc.stdout
    assert "codeql.yml (push, attempt 1): in_progress" in proc.stdout


@pytest.mark.parametrize("required", [CI, CODEQL])
def test_missing_required_workflow_blocks(tmp_path, required):
    proc, _ = _gate(tmp_path, [r for r in GREEN if r["path"] != required])
    assert proc.returncode == 1
    assert required in proc.stdout


def test_manual_publish_is_gated(tmp_path):
    proc, _ = _gate(
        tmp_path,
        [_run(CI), _run(CODEQL, conclusion="failure")],
        EVENT_NAME="workflow_dispatch",
        PUSH_IMAGES="true",
    )
    assert proc.returncode == 1


def test_scan_only_dry_run_skips_the_check(tmp_path):
    proc, args = _gate(
        tmp_path,
        [_run(CODEQL, conclusion="failure")],
        EVENT_NAME="workflow_dispatch",
        PUSH_IMAGES="false",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert args == ""


def test_api_error_blocks(tmp_path):
    proc, _ = _gate(tmp_path, gh_body="echo 'HTTP 502' >&2; exit 1")
    assert proc.returncode != 0
