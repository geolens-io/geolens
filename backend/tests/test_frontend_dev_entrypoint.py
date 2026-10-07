"""Behavior of the dev frontend entrypoint's lockfile sync."""

import os
import stat
import subprocess

from tests.repo_paths import repo_root

SCRIPT = repo_root(__file__) / "frontend" / "docker-dev-entrypoint.sh"
STAMP = "node_modules/.package-lock.sha256"


def _run(app, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    npm = bin_dir / "npm"
    npm.write_text('#!/bin/sh\necho "$@" >> npm-calls\nmkdir -p node_modules\n')
    npm.chmod(npm.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    return subprocess.run(
        ["sh", str(SCRIPT), "true"], cwd=app, env=env, check=True, capture_output=True
    )


def _calls(app):
    f = app / "npm-calls"
    return f.read_text().splitlines() if f.exists() else []


def test_reinstalls_when_lockfile_differs_then_stays_quiet(tmp_path):
    app = tmp_path / "app"
    (app / "node_modules" / "stale-pkg").mkdir(parents=True)
    (app / "package-lock.json").write_text('{"v": 2}')
    (app / STAMP).write_text("old-hash\n")

    _run(app, tmp_path)
    assert len(_calls(app)) == 1
    assert not (app / "node_modules" / "stale-pkg").exists()

    _run(app, tmp_path)
    assert len(_calls(app)) == 1


def test_reinstalls_when_stamp_missing(tmp_path):
    app = tmp_path / "app"
    (app / "node_modules").mkdir(parents=True)
    (app / "package-lock.json").write_text("{}")

    _run(app, tmp_path)
    assert len(_calls(app)) == 1
