"""Legacy finding-tag guard for AGENTS.md's Contracts and Comments policy.

Plain explanations need no anchor. Retained coded references must be scoped.
"""

from pathlib import Path

import pytest
import yaml

from tests import finding_markers as fm

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
DETECTOR_ENTRY = "backend/tests/finding_markers.py"
HOOK_ID = "no-unscoped-finding-markers"


def _local_hooks() -> list[dict]:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    return [
        hook
        for repo in config["repos"]
        if repo["repo"] == "local"
        for hook in repo["hooks"]
    ]


class TestTree:
    """The gate over the real backend/app tree."""

    def test_no_new_unscoped_finding_markers(self):
        problems = fm.check()
        assert not problems, "\n".join(problems)

    def test_scan_reaches_the_whole_tree(self):
        """The floors are real numbers, and the tree clears them."""
        _, modules, units = fm.scan_tree()
        assert fm.MIN_SCANNED_MODULES > 0 and fm.MIN_SCANNED_UNITS > 0
        assert modules >= fm.MIN_SCANNED_MODULES
        assert units >= fm.MIN_SCANNED_UNITS

    def test_collapsed_scan_fails_instead_of_passing_empty(self, tmp_path):
        problems = fm.check(tmp_path)
        assert problems, "an empty tree must fail the floors, not pass clean"

    def test_a_new_marker_fails_the_gate(self, monkeypatch, tmp_path):
        (tmp_path / "probe.py").write_text("# ZZTEST-01: no anchor here.\nX = 1\n")
        self._without_floors(monkeypatch)
        assert any("ZZTEST-01" in problem for problem in fm.check(tmp_path))

    @staticmethod
    def _without_floors(monkeypatch) -> None:
        monkeypatch.setattr(fm, "MIN_SCANNED_MODULES", 0)
        monkeypatch.setattr(fm, "MIN_SCANNED_UNITS", 0)


class TestDetector:
    """What the detector reads, and what it refuses to read."""

    @pytest.mark.parametrize(
        "source",
        [
            "# SEC-002: the token is never persisted.\nx = 1\n",
            'def f():\n    """Do a thing (PERF-005)."""\n',
            'X = 1\n"""Attribute doc for COLD-02."""\n',
            "# T-1214-17 / PERF-N5 / IA-P0-01 are all the same shape.\nx = 1\n",
            "# Resolution order (Phase 1184 seam).\nx = 1\n",
            "# Pitfall 11 again.\nx = 1\n",
            "# Lane B owns this module.\nx = 1\n",
            '"""Bypasses the cache (RESEARCH.md section 1)."""\n',
            "# Per 1140-01-PLAN.md, keep the lock.\nx = 1\n",
            "# Same shape as the SEC-FOLLOWUP note.\nx = 1\n",
            "# Tracked as quick-260417.\nx = 1\n",
        ],
    )
    def test_reports_a_bare_marker(self, source):
        assert fm.scan_module("m.py", source)

    @pytest.mark.parametrize(
        "source",
        [
            "# SEC-002 (#1234): the token is never persisted.\nx = 1\n",
            "# Scope the fetch, see #1234.\n# SEC-002 holds while internal.\nx = 1\n",
            "# SEC-002 holds while internal.\n# See #1234 for the constraint.\nx = 1\n",
            "# GH-1302 recorded the ordering, and MVT-04 is the same bug.\nx = 1\n",
        ],
    )
    def test_an_anchor_within_two_lines_scopes_the_marker(self, source):
        assert not fm.scan_module("m.py", source)

    def test_an_anchor_further_away_does_not_scope_it(self):
        source = '"""Title (REMED-04).\n\nl2\nl3\nl4\nSee #1927.\n"""\n'
        hits = fm.scan_module("m.py", source)
        assert [h.markers for h in hits] == [("REMED-04",)]

    @pytest.mark.parametrize(
        "source",
        [
            'x = "SEC-002 is data, not documentation"\n',
            "x = 1  # noqa: E501\n",
            "# codeql[py/sql-injection]\nx = 1\n",
            "# 55P03 is lock_not_available, and 40001 is a serialization failure.\n",
            "# GHSA-hrf5-v3cq-frx5 covers it; the header is X-Esri-Authorization.\n",
            "# Decode as UTF-8, hash with SHA-256, format dates as ISO-8601.\n",
            "# The link schema requires `method` to match ^[A-Z]+$.\nx = 1\n",
            "# NIST SP 800-53 AU-5 asks for an alert; AU-5(4) is waived.\nx = 1\n",
            "# Keys 0..N-1 were already persisted when key N failed.\nx = 1\n",
            "# Phase 1: validate the SQL. Phase 2 runs it.\nx = 1\n",
            "# See AGENTS.md and .github/ADR-002.md for the rules (#1218).\nx = 1\n",
        ],
    )
    def test_legitimate_text_does_not_trip(self, source):
        assert not fm.scan_module("m.py", source)

    def test_agent_tag_is_a_marker(self):
        tag = "pony" + "tail:"
        assert fm.scan_module("m.py", f"# {tag} skipped the retry loop\nx = 1\n")
        assert not fm.scan_module("m.py", f"# {tag} one retry is enough (#99)\n")

    @pytest.mark.parametrize(
        "source",
        [
            "# fix(#1234): scope the fetch.\nx = 1\n",
            "# Scoped (fix(#1234 review round 2)) by the caller.\nx = 1\n",
            'def f():\n    """feat(#88): a new door."""\n',
        ],
    )
    def test_a_provenance_prefix_fails_even_though_it_is_anchored(self, source):
        assert fm.scan_module("m.py", source)

    @pytest.mark.parametrize(
        "source",
        ["def (:\n", "x = = 1\n", 'f"{1}"\n'],
    )
    def test_unreadable_source_is_fatal_and_names_the_file(self, source):
        with pytest.raises(fm.MarkerScanError, match="wanted.py"):
            fm.scan_module("wanted.py", source)


class TestHookWiring:
    """The pre-commit hook and this gate check the same thing."""

    def test_hook_runs_the_detector(self):
        hooks = {hook["id"]: hook for hook in _local_hooks()}
        assert HOOK_ID in hooks, f"{HOOK_ID} is gone from {PRE_COMMIT_CONFIG.name}"
        hook = hooks[HOOK_ID]
        assert DETECTOR_ENTRY in hook["entry"], (
            f"{HOOK_ID} must run {DETECTOR_ENTRY}, so that what the hook "
            "checks is what its name claims."
        )
        assert hook.get("pass_filenames") is False
