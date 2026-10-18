"""Run the legacy agent-tag hook against its supported file types.

Execute the configured command so changes to its shell matching are tested.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
HOOK_ID = "no-agent-tag-markers"

# Built by concatenation, not written contiguously, so this source file does
# not itself become a bare-tag hit under the hook it is testing.
TAG = "pony" + "tail:"


def _hook() -> dict:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    for repo in config["repos"]:
        if repo["repo"] != "local":
            continue
        for hook in repo["hooks"]:
            if hook["id"] == HOOK_ID:
                return hook
    raise AssertionError(f"{HOOK_ID} is gone from {PRE_COMMIT_CONFIG.name}")


HOOK = _hook()
ARGV = shlex.split(HOOK["entry"])


def _run(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ARGV + [str(path)], capture_output=True, text=True, check=False
    )


class TestAgentTag:
    """Any agent tag fails wherever this hook runs, anchored or not."""

    def test_bare_tag_in_a_frontend_ts_file_fails(self, tmp_path):
        f = tmp_path / "a.ts"
        f.write_text(f"// {TAG} skip the retry loop\n")
        result = _run(f)
        assert result.returncode == 1
        assert "has an agent tag" in result.stdout

    def test_an_anchored_tag_fails_too(self, tmp_path):
        f = tmp_path / "a.ts"
        f.write_text(f"// fix(#1960) {TAG} skip the retry loop\n")
        result = _run(f)
        assert result.returncode == 1

    def test_bare_tag_in_a_markdown_file_fails(self, tmp_path):
        f = tmp_path / "notes.md"
        f.write_text(f"<!-- {TAG} skip the retry loop -->\n")
        result = _run(f)
        assert result.returncode == 1

    def test_a_file_without_a_tag_passes(self, tmp_path):
        f = tmp_path / "a.ts"
        f.write_text("// One retry is enough here.\n")
        result = _run(f)
        assert result.returncode == 0
        assert result.stdout == ""


class TestHookWiring:
    """The hook covers the file types AGENTS.md and gh#1960 name."""

    def test_widened_types_cover_markdown_sql_yaml_json(self):
        for file_type in ("markdown", "sql", "yaml", "json"):
            assert file_type in HOOK["types_or"], (
                f"{HOOK_ID} must cover {file_type!r} (gh#1960 coverage gap)"
            )

    def test_original_types_still_covered(self):
        for file_type in ("python", "ts", "tsx", "javascript", "shell"):
            assert file_type in HOOK["types_or"]
