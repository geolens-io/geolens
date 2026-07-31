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


def _top_level_or_split(cond: str) -> list[str]:
    """Split on ``||`` at paren depth zero. Nested groups stay intact."""
    parts, depth, buf, i = [], 0, [], 0
    while i < len(cond):
        c = cond[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and cond.startswith("||", i):
            parts.append("".join(buf))
            buf, i = [], i + 2
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return [pp.strip() for pp in parts if pp.strip()]


def _wraps_whole(part: str) -> bool:
    """True when the outer parens enclose the WHOLE expression.

    `(a || b)` does; `(a) && (b)` does not, and stripping its outer characters
    would produce `a) && (b`.
    """
    if not (part.startswith("(") and part.endswith(")")):
        return False
    depth = 0
    for i, c in enumerate(part):
        depth += (c == "(") - (c == ")")
        if depth == 0 and i < len(part) - 1:
            return False
    return depth == 0


def _satisfied_by_merge_group_alone(part: str) -> bool:
    """True when this branch is satisfied by ``merge_group`` and nothing else.

    fix(#1074 review), a second P1. Asking "does `merge_group` appear among the
    equality comparisons" accepted it wherever it sat, including inside a
    conjunction: ``github.event_name == 'merge_group' && needs.changes.outputs
    .backend == 'true'`` returned True, while the `changes` job leaves that
    output empty in the queue so the gate really skips. The equality appearing
    is not the equality deciding.

    So: unwrap enclosing parens, recurse through ``||``, and accept a leaf only
    when it is exactly the merge_group equality. Anything conjoined with it
    might be false and this cannot evaluate it.
    """
    part = part.strip()
    while _wraps_whole(part):
        part = part[1:-1].strip()
    branches = _top_level_or_split(part)
    if len(branches) > 1:
        return any(_satisfied_by_merge_group_alone(b) for b in branches)
    return bool(re.fullmatch(r"github\.event_name\s*==\s*['\"]merge_group['\"]", part))


def _runs_on_merge_group(job: dict) -> bool:
    """Whether ``job``'s ``if:`` lets it run on a ``merge_group`` event.

    ``always()`` is a STATUS-check function: it means "run even if the jobs I
    need failed or were cancelled". It says nothing about which event triggered
    the run, and ``always() && <clause>`` still evaluates ``<clause>``. So it is
    stripped before looking at event context — treating its presence as "runs
    everywhere" would report ``e2e-test`` and ``accessibility`` as running in
    the queue when their event allowlists provably exclude it.

    After stripping: nothing left means no gate at all, so the job runs.
    Otherwise the condition is split into top-level ``||`` disjuncts, and the
    job is reported as running only when **some disjunct is satisfied by
    merge_group alone** — the shape every gated job in ``ci.yml`` actually
    uses. A disjunct that conjoins the equality with anything else does not
    count, because the other conjunct may be false and this cannot evaluate it.

    **Everything else is reported as NOT running.** Two P1s came from the
    opposite default. A bare ``needs.changes.outputs.backend == 'true'`` has no
    event clause at all, but ``changes`` skips its paths-filter step in the
    queue so those outputs are empty and the job skips. And the equality
    appearing inside a conjunction is not the equality deciding. Both read as
    "runs" under a permissive rule, which is the green-CI-OK-over-skipped-gates
    failure this file exists to detect.

    The direction is deliberate: a false alarm costs someone ten minutes; a
    false all-clear costs an untested merge and nobody looks. If a legitimate
    new shape trips it, teach this function that shape or evaluate the
    expression — do not widen the fallback.
    """
    condition = job.get("if")
    if condition is None:
        return True  # no gate
    cond = " ".join(str(condition).split()).replace("always()", "").strip()
    while cond.startswith("&&"):
        cond = cond[2:].strip()
    if not cond:
        return True  # bare always()
    if "merge_group" in _EVENT_NE.findall(cond):
        return False  # explicitly excluded
    return any(_satisfied_by_merge_group_alone(p) for p in _top_level_or_split(cond))


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


def test_predicate_bare_output_condition_reports_as_skipping():
    """fix(#1074 review), P1. The shape that made "no event comparison means
    no event gate" wrong.

    `changes` skips its paths-filter step on merge_group — it has no base ref
    to diff — so `needs.changes.outputs.*` are EMPTY there and a job gated only
    on one of them really does skip. Reading it as running is the false
    all-clear this whole file exists to prevent, reproduced inside the guard.
    """
    condition = "needs.changes.outputs.backend == 'true'"
    assert _runs_on_merge_group({"if": condition}) is False


def test_predicate_unrecognised_condition_reports_as_skipping():
    """The general form of the same rule: what cannot be proven to run is
    reported. A false alarm costs ten minutes; a false all-clear costs an
    untested merge and nobody looks."""
    assert (
        _runs_on_merge_group({"if": "github.repository == 'geolens-io/geolens'"})
        is False
    )


def test_predicate_merge_group_inside_a_conjunction_reports_as_skipping():
    """fix(#1074 review), the second P1. The equality APPEARING is not the
    equality DECIDING. `changes` leaves its outputs empty in the queue, so this
    gate really skips — and a membership test called it running."""
    condition = (
        "github.event_name == 'merge_group' && needs.changes.outputs.backend == 'true'"
    )
    assert _runs_on_merge_group({"if": condition}) is False


def test_predicate_merge_group_in_a_parenthesised_disjunct_runs():
    """The control: a real disjunct satisfied by merge_group alone still runs,
    including when the whole allowlist is wrapped in parens."""
    condition = (
        "always() && (github.event_name == 'push' "
        "|| github.event_name == 'merge_group')"
    )
    assert _runs_on_merge_group({"if": condition}) is True


def test_predicate_nested_conjunction_beside_a_clean_disjunct_runs():
    """A conjunctive branch does not poison a sibling that stands alone —
    e2e-smoke is exactly this shape."""
    condition = (
        "(github.event_name == 'pull_request' && needs.changes.outputs.e2e == 'true') "
        "|| github.event_name == 'merge_group'"
    )
    assert _runs_on_merge_group({"if": condition}) is True
