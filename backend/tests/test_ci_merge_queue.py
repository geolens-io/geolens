"""fix(#1000): a merge-queue run must actually run the gates it reports on.

`ci-ok` counts a SKIPPED dependency as a pass. That is right for a
path-filtered pull request and wrong in the merge queue, where a skip means
"never ran against this candidate merge". Twelve jobs were gated on
``needs.changes.outputs.X == 'true' || github.event_name == 'push'``, and a
``merge_group`` event matches neither ``push`` nor ``pull_request``, so
enabling the queue without touching those conditionals would have produced a
green `CI OK` on a run that tested nothing.

The fix is that every job feeding `ci-ok` runs on ``merge_group``. That is an
invariant about a YAML file, which nothing enforces, so it is asserted here:
add a job to the aggregator without a ``merge_group`` clause and this fails
instead of silently reopening the hole after the queue is switched on.

Deliberately NOT asserted: that the queue is enabled. That is a
repository-admin setting, not a file in this repo.
"""

import pathlib

import pytest
import yaml

CI = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict:
    return yaml.safe_load(CI.read_text())


def _triggers(wf: dict) -> dict:
    # PyYAML resolves a bare `on:` key to the boolean True (YAML 1.1), so read
    # both spellings rather than depending on which one this parser produced.
    return wf.get("on") or wf.get(True) or {}


def _runs_on_merge_group(job: dict) -> bool:
    condition = job.get("if")
    if condition is None:
        return True  # unconditional job
    return "merge_group" in str(condition)


def test_ci_reacts_to_merge_group():
    """Without this trigger, a queue run produces no checks and never merges."""
    assert "merge_group" in _triggers(_workflow()), (
        "ci.yml does not react to merge_group, but all three required contexts "
        "come from it — the queue would wait forever for checks that never start"
    )


def test_every_required_gate_runs_in_the_queue():
    """The one that matters: no dependency of ci-ok may skip on merge_group."""
    jobs = _workflow()["jobs"]
    skipping = [
        name for name in jobs["ci-ok"]["needs"] if not _runs_on_merge_group(jobs[name])
    ]
    assert not skipping, (
        "these ci-ok dependencies would SKIP on a merge_group run, and ci-ok "
        "counts a skip as a pass — the queue would merge them untested: "
        f"{sorted(skipping)}. Add `|| github.event_name == 'merge_group'` to "
        "each one's `if:`."
    )


@pytest.mark.parametrize(
    "job",
    ["backend-test", "frontend-test", "e2e-smoke"],
    ids=["backend", "frontend", "browser"],
)
def test_the_expensive_suites_are_among_them(job):
    """#1000's acceptance names these three specifically.

    A queue run whose Backend Tests and frontend suites skipped to a green
    `CI OK` is the exact failure the issue was filed about, so pin them by name
    rather than trusting the aggregator list to keep containing them.
    """
    jobs = _workflow()["jobs"]
    assert job in jobs["ci-ok"]["needs"], f"{job} no longer gates CI OK"
    assert _runs_on_merge_group(jobs[job]), f"{job} would skip on merge_group"


def test_changes_job_does_not_pretend_to_have_filtered_the_queue():
    """`dorny/paths-filter` has no base ref on merge_group.

    It is configured with ``token: ''`` (git-diff detection, the #546 fix for
    the API's transient 503s), and git-diff detection resolves its base from
    pull-request context or a push's before-SHA. A ``gh-readonly-queue/*``
    branch supplies neither. The step is skipped there so `Detect Changes` — a
    REQUIRED context — still succeeds, and the empty outputs it leaves behind
    are ignored because every consumer ORs in ``merge_group``.

    If someone re-enables the filter on merge_group, its outputs become
    load-bearing again and this assertion should be replaced by one that pins
    whatever base it was given, not deleted.
    """
    steps = _workflow()["jobs"]["changes"]["steps"]
    filter_steps = [s for s in steps if "paths-filter" in str(s.get("uses", ""))]
    assert len(filter_steps) == 1, "expected exactly one paths-filter step"
    assert "merge_group" in str(filter_steps[0].get("if", "")), (
        "the paths-filter step must be skipped on merge_group; with no base to "
        "diff against its outputs cannot be trusted, and a failure there fails "
        "a required check"
    )
