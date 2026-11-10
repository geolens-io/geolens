"""Which ci.yml jobs run for a given event and diff.

The job conditions are evaluated here rather than pattern-matched, so each
case states the selection a real run would make. Jobs that run are assumed to
pass, and a job without a status function in its ``if:`` skips when any job it
needs did not succeed, as GitHub does.

The queue-lookup step from the ``changes`` job is also run under bash against a
stub ``gh``, because its output decides whether a push repeats the matrix.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from typing import Any

import pytest
import yaml

from tests.repo_paths import repo_root

CI = repo_root(__file__) / ".github" / "workflows" / "ci.yml"

_TOKEN = re.compile(
    r"\s*(?:(?P<str>'[^']*')|(?P<op>&&|\|\||==|!=|!|\(|\)|,)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_.*-]*))"
)
_STATUS_FUNCS = ("always()", "success()", "failure()", "cancelled()")


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(CI.read_text())


def _tokens(expr: str) -> list[tuple[str, str]]:
    out, pos, expr = [], 0, expr.strip()
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        assert m and m.end() > pos, f"cannot tokenize {expr[pos:]!r}"
        kind = m.lastgroup
        assert kind is not None
        out.append((kind, m.group(kind)))
        pos = m.end()
    return out


class _Expr:
    """Recursive-descent evaluator for the expression subset ci.yml uses."""

    def __init__(self, expr: str, ctx: dict[str, Any]):
        self.toks = _tokens(expr)
        self.i = 0
        self.ctx = ctx

    def _peek(self) -> str | None:
        return self.toks[self.i][1] if self.i < len(self.toks) else None

    def _take(self) -> tuple[str, str]:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def evaluate(self) -> Any:
        value = self._or()
        assert self.i == len(self.toks), f"trailing tokens {self.toks[self.i :]}"
        return value

    def _or(self) -> Any:
        value = self._and()
        while self._peek() == "||":
            self._take()
            rhs = self._and()
            value = value or rhs
        return value

    def _and(self) -> Any:
        value = self._unary()
        while self._peek() == "&&":
            self._take()
            rhs = self._unary()
            value = value and rhs
        return value

    def _unary(self) -> Any:
        if self._peek() == "!":
            self._take()
            return not self._unary()
        lhs = self._primary()
        if self._peek() in ("==", "!="):
            op = self._take()[1]
            rhs = self._primary()
            return (lhs == rhs) if op == "==" else (lhs != rhs)
        return lhs

    def _primary(self) -> Any:
        kind, text = self._take()
        if text == "(":
            value = self._or()
            assert self._take()[1] == ")"
            return value
        if kind == "str":
            return text[1:-1]
        assert kind == "name", f"unexpected token {text!r}"
        if self._peek() == "(":
            self._take()
            args = []
            while self._peek() != ")":
                args.append(self._or())
                if self._peek() == ",":
                    self._take()
            self._take()
            return self._call(text, args)
        return self._lookup(text)

    def _call(self, name: str, args: list[Any]) -> Any:
        if name == "always":
            return True
        if name == "contains":
            return args[1] in args[0]
        raise AssertionError(f"unsupported function {name}()")

    def _lookup(self, path: str) -> Any:
        if path == "github.event_name":
            return self.ctx["event"]
        if path == "needs.*.result":
            return list(self.ctx["needs"].values())
        m = re.fullmatch(r"needs\.changes\.outputs\.([a-z0-9_]+)", path)
        if m:
            return self.ctx["outputs"].get(m.group(1), "")
        m = re.fullmatch(r"needs\.([a-z0-9-]+)\.result", path)
        if m:
            return self.ctx["needs"][m.group(1)]
        raise AssertionError(f"unsupported context {path}")


def _glob_regex(pattern: str) -> re.Pattern[str]:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def _step_runs(step: dict[str, Any], event: str) -> bool:
    cond = str(step.get("if", "")).strip()
    return not cond or bool(_Expr(cond, {"event": event}).evaluate())


def _changes_outputs(
    wf: dict[str, Any], event: str, files: list[str], queue_verified: str
) -> dict[str, str]:
    """The ``changes`` job's outputs, from whichever of its steps would run."""
    steps = wf["jobs"]["changes"]["steps"]
    outputs: dict[str, str] = {}
    queue = next((s for s in steps if s.get("id") == "queue"), None)
    if queue is not None and _step_runs(queue, event):
        outputs["queue_verified"] = queue_verified
    step = next(s for s in steps if "paths-filter" in str(s.get("uses")))
    if _step_runs(step, event):
        filters = yaml.safe_load(step["with"]["filters"])
        for name, globs in filters.items():
            hit = any(_glob_regex(g).fullmatch(f) for g in globs for f in files)
            outputs[name] = "true" if hit else "false"
    return outputs


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _select(
    event: str, files: list[str] | None = None, queue_verified: str = ""
) -> set[str]:
    """Return the jobs that run for one event, diff and queue-lookup result."""
    wf = _workflow()
    jobs = wf["jobs"]
    outputs = _changes_outputs(wf, event, files or [], queue_verified)

    results: dict[str, str] = {}
    pending = list(jobs)
    while pending:
        for name in pending:
            needs = _needs(jobs[name])
            if all(n in results for n in needs):
                break
        else:
            raise AssertionError(f"dependency cycle among {pending}")
        pending.remove(name)
        cond = str(jobs[name].get("if", "")).strip()
        cond = cond.removeprefix("${{").removesuffix("}}").strip()
        need_results = {n: results[n] for n in needs}
        if not any(f in cond for f in _STATUS_FUNCS) and any(
            r != "success" for r in need_results.values()
        ):
            results[name] = "skipped"
            continue
        ctx = {"event": event, "outputs": outputs, "needs": need_results}
        runs = not cond or bool(_Expr(cond, ctx).evaluate())
        results[name] = "success" if runs else "skipped"
    return {name for name, result in results.items() if result == "success"}


# Jobs with no path filter or event gate. They take a minute or less each and
# run on every event.
_ALWAYS = {
    "changes",
    "pre-commit",
    "version-coherence",
    "docs-contract",
    "readme-assets",
    "license-check",
    "ci-ok",
}
_BACKEND = {
    "backend-lint",
    "backend-test",
    "backend-coverage",
    "openapi-snapshot",
    "sdks-check",
    "cli-test",
    "security-scan",
}
_PROBE = {"runtime-extension-image-probe"}
_COMPAT = {"previous-release-compat"}


def test_frontend_only_pr_skips_the_backend_jobs():
    """A dependency bump in frontend/package.json touches no backend test input."""
    selected = _select(
        "pull_request", ["frontend/package.json", "frontend/package-lock.json"]
    )
    assert selected == _ALWAYS | {"frontend-lint", "frontend-test", "e2e-smoke"}


def test_backend_only_pr_skips_the_frontend_jobs():
    selected = _select("pull_request", ["backend/app/api/main.py"])
    assert selected == _ALWAYS | _BACKEND | {"mcp-test", "e2e-smoke"}


def test_merge_group_runs_every_gate():
    wf = _workflow()
    selected = _select("merge_group")
    assert set(wf["jobs"]["ci-ok"]["needs"]) <= selected
    assert not selected & (_PROBE | _COMPAT)


@pytest.mark.parametrize(
    "files",
    [[], ["backend/app/api/main.py", "frontend/src/main.tsx"]],
    ids=["any-diff", "backend-and-frontend-diff"],
)
def test_push_after_a_passing_queue_run_skips_the_matrix(files):
    """The queue already ran the matrix on this SHA; only push-only work runs,
    whatever the pushed diff touched."""
    assert _select("push", files, queue_verified="true") == _ALWAYS | _PROBE | _COMPAT


@pytest.mark.parametrize("lookup", ["", "false"])
def test_push_without_a_passing_queue_run_runs_the_full_matrix(lookup):
    wf = _workflow()
    selected = _select("push", queue_verified=lookup)
    expected = set(wf["jobs"]["ci-ok"]["needs"]) - {"e2e-smoke"}
    assert expected | _PROBE | _COMPAT <= selected


@pytest.mark.parametrize(
    "path",
    [
        "backend/alembic/versions/0088_dataset_kept_versions.py",
        "backend/app/modules/catalog/datasets/domain/models.py",
        "scripts/previous-release-compat.sh",
    ],
)
def test_schema_pr_runs_the_previous_release_check(path):
    """A migration or model change must run the previous release against it."""
    assert _COMPAT <= _select("pull_request", [path])


def test_previous_release_check_skips_unrelated_prs():
    assert not _select("pull_request", ["backend/app/api/main.py"]) & _COMPAT


def _queue_step() -> dict[str, Any]:
    steps = _workflow()["jobs"]["changes"]["steps"]
    return next(s for s in steps if s.get("id") == "queue")


def test_queue_lookup_failure_cannot_fail_detect_changes():
    step = _queue_step()
    assert step.get("continue-on-error") is True
    assert step.get("timeout-minutes")
    assert step.get("if") == "github.event_name == 'push'"
    perms = _workflow()["jobs"]["changes"]["permissions"]
    assert perms.get("actions") == "read"


def _run_lookup(tmp_path, gh_body: str) -> tuple[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\necho "$@" > "{tmp_path}/gh-args"\n{gh_body}\n')
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    output = tmp_path / "github-output"
    output.write_text("")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        "GITHUB_REPOSITORY": "example/repo",
        "GITHUB_SHA": "a" * 40,
    }
    subprocess.run(
        # The flags GitHub's default bash shell runs a step with.
        [
            "bash",
            "--noprofile",
            "--norc",
            "-eo",
            "pipefail",
            "-c",
            _queue_step()["run"],
        ],
        env=env,
        check=True,
        capture_output=True,
    )
    args_file = tmp_path / "gh-args"
    return output.read_text(), args_file.read_text() if args_file.exists() else ""


def test_queue_lookup_asks_for_a_successful_merge_group_run_of_this_sha(tmp_path):
    output, args = _run_lookup(tmp_path, "echo 1")
    assert output.strip() == "verified=true"
    assert "actions/workflows/ci.yml/runs" in args
    for param in ("event=merge_group", "status=success", f"head_sha={'a' * 40}"):
        assert param in args


@pytest.mark.parametrize(
    "gh_body",
    ["echo 0", "exit 1", "echo 'HTTP 502'; exit 1", "echo null", "echo"],
    ids=["no-run", "api-error", "api-error-with-output", "null", "empty"],
)
def test_queue_lookup_leaves_the_full_matrix_on_when_it_finds_nothing(
    tmp_path, gh_body
):
    output, _ = _run_lookup(tmp_path, gh_body)
    assert output == ""
