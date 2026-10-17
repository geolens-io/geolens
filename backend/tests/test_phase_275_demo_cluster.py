"""README and cross-cutting correctness locks.

- No 'demo.geolens.io' references remain in active code or docs; the project
  owns getgeolens.com only.
- CLI flags in README.md keep their hyphens.

Pure static analysis: no docker daemon, database, or HTTP fixture needed.
"""

from __future__ import annotations

import subprocess

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_no_geolens_io_typos() -> None:
    """Project owns getgeolens.com only — no demo.geolens.io references.

    Active, public-tracked code + docs only. Excluded paths:
    - .planning/, docs-internal/  → both gitignored, historical context only
    - CHANGELOG.md                → preserves the historical fix record
    - this test file               → self-references in docstrings/strings
    """
    self_filename = "test_phase_275_demo_cluster.py"
    result = subprocess.run(
        [
            "grep",
            "-rn",
            "demo\\.geolens\\.io",
            ".",
            "--include=*.md",
            "--include=*.yml",
            "--include=*.py",
            "--include=*.ts",
            "--include=*.tsx",
            "--include=*.toml",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    hits = [
        line
        for line in result.stdout.splitlines()
        if "node_modules" not in line
        and "__pycache__" not in line
        and ".git/" not in line
        and ".planning/" not in line
        and "docs-internal/" not in line  # gitignored historical audits
        and "graphify-out/" not in line  # generated graphify knowledge-graph reports
        and "CHANGELOG.md" not in line  # historical fix record
        and not line.split(":", 1)[0].endswith(self_filename)
    ]
    assert not hits, (
        f"demo.geolens.io references in active code/docs: {hits}. "
        "Replace with demo.getgeolens.com per memory project_domain_ownership.md."
    )


def test_cli_flags_preserved_in_readme() -> None:
    """CLI flag instances like --username must NOT have been mutated."""
    body = _read("README.md")
    # Appears in the seed-showcase example; a real flag (em-dash sweep guard).
    assert "--username admin" in body or "--username/--password" in body, (
        "CLI flag --username is missing from README.md — "
        "em-dash sweep may have over-corrected"
    )
