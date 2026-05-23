"""Phase 275 / API-14 regression: README + cross-cutting correctness locks.

Static regression locks in:
- No 'demo.geolens.io' references remain in active code/docs (M-75 — the
  project owns getgeolens.com only per memory project_domain_ownership.md).
- README.md §'See It in Action' has the JWT-mint one-liner so a first-time
  reader can actually execute the curl examples (M-76).
- README.md em-dash conversion landed on the six body-prose lines flagged
  by L-16 (line 90 + the five Why GeoLens bullets at 94-98).

Pure static analysis — no docker daemon, database, or HTTP fixture needed.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_no_geolens_io_typos() -> None:
    """API-14 / M-75: project owns getgeolens.com only — no demo.geolens.io references.

    Active, public-tracked code + docs only. Excluded paths:
    - .planning/, docs-internal/  → both gitignored, historical context only
    - CHANGELOG.md                → preserves the Phase 269 fix record
    - this test file               → self-references in docstrings/strings
    """
    self_path = "backend/tests/test_phase_275_demo_cluster.py"
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
        and "CHANGELOG.md" not in line  # historical fix record from Phase 269
        and self_path not in line  # this test's own self-references
    ]
    assert not hits, (
        f"demo.geolens.io references in active code/docs: {hits}. "
        "Replace with demo.getgeolens.com per memory project_domain_ownership.md."
    )


def test_readme_has_jwt_mint_oneliner() -> None:
    """API-14 / M-76: README §See It in Action must give readers an actionable token flow."""
    body = _read("README.md")
    assert re.search(r"TOKEN=\$\(curl[^)]*auth/login", body, re.DOTALL), (
        "README.md missing the JWT mint one-liner before §'See It in Action' curl examples"
    )
    assert "Authorization: Bearer $TOKEN" in body, (
        "README.md curl examples should reference $TOKEN, not literal <token>"
    )


def test_readme_em_dash_consistency_in_six_known_lines() -> None:
    """API-14 / L-16: the six known '--' separator lines now use '—'.

    This test does NOT enforce em-dash everywhere — only the six lines flagged
    in the plan are checked. CLI flags (--username, --api-key) remain hyphens.
    """
    body = _read("README.md")
    expected_em_dash_signals = [
        "Spatial data ends up scattered — ",
        "One catalog** — ",
        "Works with your tools** — ",
        "Semantic + spatial search** — ",
        "Built-in map builder** — ",
        "AI-assisted (optional)** — ",
    ]
    for signal in expected_em_dash_signals:
        assert signal in body, f"README.md missing em-dash conversion for: {signal}"


def test_cli_flags_preserved_in_readme() -> None:
    """API-14: CLI flag instances like --username, --api-key must NOT have been mutated."""
    body = _read("README.md")
    # These appear in the seed-natural-earth example; they're real flags
    assert "--username admin" in body or "--username/--password" in body, (
        "CLI flag --username is missing from README.md — "
        "em-dash sweep may have over-corrected"
    )
    assert "--api-key" in body, (
        "CLI flag --api-key is missing from README.md — em-dash sweep may have over-corrected"
    )
