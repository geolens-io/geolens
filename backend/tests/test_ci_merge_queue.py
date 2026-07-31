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
import re

import pytest
import yaml

CI = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _workflow() -> dict:
    return yaml.safe_load(CI.read_text())


def _triggers(wf: dict) -> dict:
    # PyYAML resolves a bare `on:` key to the boolean True (YAML 1.1), so read
    # both spellings rather than depending on which one this parser produced.
    return wf.get("on") or wf.get(True) or {}


# fix(#1051 follow-up): PARSE, DON'T SCAN. The first version of this predicate
# asked `"merge_group" in condition`, which is a substring match on an
# expression language and gets two shapes wrong in opposite directions.
_EVENT_EQ = re.compile(r"github\.event_name\s*==\s*['\"]([^'\"]+)['\"]")
_EVENT_NE = re.compile(r"github\.event_name\s*!=\s*['\"]([^'\"]+)['\"]")


def _runs_on_merge_group(job: dict) -> bool:
    """Whether ``job``'s ``if:`` lets it run on a ``merge_group`` event.

    ``always()`` is a STATUS-check function: it means "run even if the jobs I
    need failed or were cancelled". It says nothing about which event triggered
    the run, and ``always() && <clause>`` still evaluates ``<clause>``. So it is
    stripped before looking at event context — treating its presence as "runs
    everywhere" would report ``e2e-test`` and ``accessibility`` as running in
    the queue when their event allowlists provably exclude it, and a guard that
    is wrong toward "all clear" is worse than no guard because you stop looking.

    After that: no ``github.event_name`` comparison at all means no event gate,
    so the job runs. Comparisons present mean the job runs only if
    ``merge_group`` is among the permitted ones.

    Known limit, stated rather than papered over: this reads the SET of event
    comparisons, not the boolean structure around them. A condition that
    permits `merge_group` inside one branch of an `||` while a sibling `&&`
    excludes it would be read as running. No such condition exists in
    ``ci.yml``, and the honest fix if one appears is to evaluate the
    expression, not to add another special case here.
    """
    condition = job.get("if")
    if condition is None:
        return True  # unconditional job
    cond = " ".join(str(condition).split()).replace("always()", "")
    if "merge_group" in _EVENT_NE.findall(cond):
        return False  # explicitly excluded
    permitted = _EVENT_EQ.findall(cond)
    if not permitted:
        return True  # no event gate
    return "merge_group" in permitted


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
    condition = " ".join(str(filter_steps[0].get("if", "")).split())
    # fix(#1000 review): the NEGATIVE form specifically. A substring test for
    # "merge_group" would keep passing if the condition were inverted to
    # `== 'merge_group'`, i.e. if the step ran on exactly the event this test
    # exists to exclude.
    assert condition == "github.event_name != 'merge_group'", (
        "the paths-filter step must be skipped on merge_group; with no base to "
        f"diff against its outputs cannot be trusted. Found: {condition!r}"
    )


# ---------------------------------------------------------------------------
# The predicate itself. fix(#1051 follow-up): the first version substring-matched
# "merge_group" in the condition, which cried wolf on `always()` — reporting a
# job as skipping when it always runs. The obvious repair, also matching
# "always()", would have been worse: it reports `always() && (event_name ==
# 'push' || ...)` as running when that provably skips in the queue, turning a
# false alarm into a false all-clear in the one tool meant to answer step 1 of a
# queue incident. Neither is fixable by adding literals to a string match, which
# is the actual lesson. These four cases exist to stop the next person trying.
# ---------------------------------------------------------------------------


def test_predicate_bare_always_runs():
    """`always()` is a status check, not an event gate. `ci-ok` is this shape."""
    assert _runs_on_merge_group({"if": "always()"}) is True


def test_predicate_always_with_allowlist_excluding_merge_group_skips():
    """The shape the naive `always()` repair got backwards. `e2e-test` and
    `accessibility` are both written this way and both skip in the queue."""
    condition = (
        "always() && (github.event_name == 'push' "
        "|| github.event_name == 'schedule' "
        "|| github.event_name == 'workflow_dispatch') "
        "&& !contains(needs.*.result, 'failure')"
    )
    assert _runs_on_merge_group({"if": condition}) is False


def test_predicate_always_with_allowlist_including_merge_group_runs():
    condition = (
        "always() && (github.event_name == 'push' "
        "|| github.event_name == 'merge_group')"
    )
    assert _runs_on_merge_group({"if": condition}) is True


def test_predicate_no_condition_runs():
    """`changes`, `pre-commit`, `version-coherence` and `docs-contract`."""
    assert _runs_on_merge_group({}) is True


def test_predicate_path_filtered_shape_runs():
    """The twelve gated jobs #1051 fixed, in their actual written form."""
    condition = (
        "needs.changes.outputs.backend == 'true' "
        "|| github.event_name == 'push' "
        "|| github.event_name == 'merge_group'"
    )
    assert _runs_on_merge_group({"if": condition}) is True


def test_predicate_explicit_exclusion_skips():
    """`!=` is an exclusion, and a substring match reads it as permission —
    the same class of error as the `always()` one. The `paths-filter` STEP is
    written this way; no job is today, and the predicate should not care."""
    assert _runs_on_merge_group({"if": "github.event_name != 'merge_group'"}) is False


def test_predicate_agrees_with_the_real_workflow():
    """Cross-check against ci.yml rather than only synthetic conditions: every
    job whose condition names merge_group must read as running, and the
    push/schedule-only jobs must read as skipping."""
    jobs = _workflow()["jobs"]
    for name in jobs["ci-ok"]["needs"]:
        assert _runs_on_merge_group(jobs[name]), f"{name} must run in the queue"
    for name in ("e2e-test", "accessibility", "stac-validate"):
        assert not _runs_on_merge_group(jobs[name]), (
            f"{name} is deliberately off merge_group; if that changed, the "
            "non-gating-jobs decision in #1000 needs revisiting"
        )
