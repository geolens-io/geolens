"""#1609: a GA release must notify BOTH downstream repos, not just the site.

``.github/workflows/release.yml`` sends a ``geolens-release`` repository
dispatch so downstream repos can react to a release the moment it publishes.
``geolens-io/getgeolens.com`` has listened for it since getgeolens.com#108;
``geolens-io/geolens-examples`` pins every published client (``geolens``,
``@geolens/sdk``, ``geolens-mcp``, ``geolens-cli``) to one version across a
dozen files, and before #1609 learned about a release only from a weekly
``ci/check-pins.py`` log line that warns and passes.

Both dispatches live in ONE step, which is what makes this worth a test. The
failure mode is not "the examples dispatch was never written" — it is a later
edit quietly re-coupling the two targets, so a site outage takes the examples
notification down with it (or the reverse). Hence the assertions below cover
the shape as much as the endpoints: two independent token names with a
documented fallback, and the step still marked ``continue-on-error`` and
still gated to GA tags.

Reads the workflow off disk and parses it as YAML. No database, no network.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# fix(#1673): tracks the step name, which changed when the Buttondown
# newsletter joined the site and examples dispatches as a third target.
STEP_NAME_MARKER = "Notify downstream"

SITE_DISPATCH_API = "repos/geolens-io/getgeolens.com/dispatches"
EXAMPLES_DISPATCH_API = "repos/geolens-io/geolens-examples/dispatches"


def _dispatch_step() -> dict[str, Any]:
    """The single step in release.yml that sends the release dispatches.

    Matched on a prefix of its name rather than the whole string. That is not
    rename-proof — fix(#1673) renamed the step past the old ``"Notify the
    site"`` marker and this had to move with it — but the ``== 1`` assertion
    below is what makes that safe: a marker that no longer matches fails
    loudly here instead of letting every assertion in this file pass
    vacuously against a step it could not find. Renaming the step means
    updating this marker in the same commit.
    """
    workflow: dict[str, Any] = yaml.safe_load(RELEASE_YML.read_text(encoding="utf-8"))

    matches = [
        step
        for job in workflow.get("jobs", {}).values()
        for step in job.get("steps", [])
        if STEP_NAME_MARKER in str(step.get("name", ""))
    ]
    assert len(matches) == 1, (
        f"Expected exactly one step in {RELEASE_YML.name} whose name contains "
        f"{STEP_NAME_MARKER!r}; found {len(matches)}: "
        f"{[step.get('name') for step in matches]}"
    )
    return matches[0]


def _run_text() -> str:
    return str(_dispatch_step().get("run", ""))


class TestBothDispatchTargets:
    """Both downstream repos get the same event from the same step."""

    def test_site_is_dispatched(self):
        assert SITE_DISPATCH_API in _run_text(), (
            f"The release step no longer dispatches to {SITE_DISPATCH_API}. "
            "getgeolens.com's release-sync.yml (getgeolens.com#108) is driven "
            "by this call."
        )

    def test_examples_repo_is_dispatched(self):
        assert EXAMPLES_DISPATCH_API in _run_text(), (
            f"The release step does not dispatch to {EXAMPLES_DISPATCH_API}. "
            "#1609: geolens-examples pins every client to one version and has "
            "no other prompt to bump them."
        )

    def test_both_targets_get_the_geolens_release_event(self):
        """One ``event_type=geolens-release`` per target, not one shared call."""
        run = _run_text()
        events = re.findall(r"event_type=geolens-release", run)
        assert len(events) == 2, (
            "Expected exactly two `event_type=geolens-release` dispatches (the "
            f"site and the examples repo); found {len(events)}."
        )

    def test_both_targets_get_the_tag_as_the_payload_version(self):
        run = _run_text()
        payloads = re.findall(r"client_payload\[version\]=\$\{TAG\}", run)
        assert len(payloads) == 2, (
            "Both dispatches must carry the released tag as "
            "`client_payload[version]=${TAG}`; found "
            f"{len(payloads)} occurrence(s)."
        )


class TestDispatchTokens:
    """Two token names, with the examples target falling back to the site's."""

    def test_both_token_names_are_wired_into_the_step_env(self):
        env = _dispatch_step().get("env", {})
        for name in ("SITE_DISPATCH_TOKEN", "EXAMPLES_DISPATCH_TOKEN"):
            assert name in env, (
                f"{name} is not in the dispatch step's env, so the secret never "
                f"reaches the run script. env keys: {sorted(env)}"
            )
            assert f"secrets.{name}" in str(env[name]), (
                f"{name} must be read from `secrets.{name}`; got {env[name]!r}."
            )

    def test_examples_token_falls_back_to_the_site_token(self):
        """One PAT scoped to both repos must be enough to wire this up.

        Asserted as the fallback expression rather than as "the examples
        dispatch succeeds", because the alternative — requiring a second
        secret — is a silently skipped dispatch, not a red build.
        """
        assert "${EXAMPLES_DISPATCH_TOKEN:-$SITE_DISPATCH_TOKEN}" in _run_text(), (
            "The examples dispatch must fall back to SITE_DISPATCH_TOKEN when "
            "EXAMPLES_DISPATCH_TOKEN is unset, so a single PAT scoped to both "
            "target repos works without a second secret."
        )

    def test_each_target_reports_its_own_missing_token(self):
        """A missing secret is a visible ::notice::, per target, never a skip."""
        run = _run_text()
        notices = re.findall(r"::notice title=[^:]*not notified::", run)
        assert len(notices) == 2, (
            "Each target needs its own ::notice:: for the no-token case, so a "
            "PAT that is scoped to only one of them is legible in the run log; "
            f"found {len(notices)}."
        )


class TestFailureIsolation:
    """Neither target's result may mask the other's."""

    def test_the_step_never_fails_the_release(self):
        step = _dispatch_step()
        assert step.get("continue-on-error") is True, (
            "The dispatch step must stay `continue-on-error: true`. The release "
            "is already published by the time it runs; a downstream repo being "
            "unreachable must never turn a shipped release red."
        )

    def test_a_failure_flag_is_collected_rather_than_exited_on(self):
        """The site dispatch must not `exit 1` before the examples one runs.

        The whole point of #1609 is that the examples repo hears about every
        release. An early exit on the site's failure would make that
        conditional on the site being reachable.
        """
        run = _run_text()
        site_at = run.index(SITE_DISPATCH_API)
        examples_at = run.index(EXAMPLES_DISPATCH_API)
        assert site_at < examples_at, (
            "Expected the site dispatch before the examples dispatch in the run script."
        )
        between = run[site_at:examples_at]
        assert "exit 1" not in between, (
            "There is an `exit 1` between the two dispatches: a site failure "
            "would abort the step before the examples repo is notified. "
            "Collect a failure flag and exit non-zero after both have run."
        )
        assert re.search(r"^\s*exit \"?\$\{?failed\}?\"?\s*$", run, re.MULTILINE), (
            "The run script must end by exiting on the collected failure flag, "
            "so a failed dispatch is still reported (under continue-on-error) "
            "rather than swallowed."
        )

    def test_each_target_has_its_own_failure_warning(self):
        run = _run_text()
        warnings = re.findall(r"::warning title=[^:]*dispatch failed::", run)
        assert len(warnings) >= 2, (
            "Each target needs its own ::warning:: on failure, or one repo's "
            f"outage reads as the other's; found {len(warnings)}."
        )


class TestUnchangedGuards:
    """#1609 must not loosen what already gated this step."""

    def test_only_ga_tags_dispatch(self):
        condition = str(_dispatch_step().get("if", ""))
        assert "!contains(env.TAG, '-')" in condition, (
            "The GA-only guard is gone. A prerelease never becomes the `latest` "
            f"release downstream repos follow. Current if: {condition!r}"
        )

    def test_only_the_latest_release_dispatches(self):
        """The stale-tag guard: an older tag's smoke must not sync backwards."""
        run = _run_text()
        assert "releases/latest" in run and '"$LATEST" != "$TAG"' in run, (
            "The latest-release guard is gone. prod-smoke.yml runs tag smokes "
            "in parallel with no concurrency group, so an older tag can reach "
            "this step after a newer release published."
        )

    def test_the_step_caps_its_own_runtime(self):
        assert _dispatch_step().get("timeout-minutes") == 5, (
            "The dispatch step must keep its own timeout-minutes; two network "
            "calls to two repos are two chances to hang."
        )


class TestBackendFilterCoversThisWorkflow:
    """This file is only a gate on PRs that actually run the backend suite."""

    def test_release_yml_triggers_backend_tests(self):
        """A release.yml-only PR must run Backend Tests.

        Same class as fix(#561), fix(#1088) and fix(#1517) in ci.yml: a backend
        test that reads a file by literal path is dead weight unless changing
        that file turns the suite on.
        """
        ci: dict[str, Any] = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
        filter_step = next(
            step
            for step in ci["jobs"]["changes"]["steps"]
            if "dorny/paths-filter" in str(step.get("uses", ""))
        )
        filters: dict[str, list[str]] = yaml.safe_load(filter_step["with"]["filters"])
        backend_globs = filters.get("backend", [])
        assert ".github/workflows/release.yml" in backend_globs, (
            "'.github/workflows/release.yml' is not in ci.yml's backend "
            "paths-filter, so a PR editing only that workflow skips the suite "
            "holding this file's assertions. Backend globs: {}".format(backend_globs)
        )
