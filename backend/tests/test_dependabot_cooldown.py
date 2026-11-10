"""Every Dependabot entry waits a week before proposing a newly published version.

Cooldown applies to version updates only, so security updates still open at once.
"""

from __future__ import annotations

import yaml

from tests.repo_paths import repo_root

DEPENDABOT = repo_root(__file__) / ".github" / "dependabot.yml"


def test_every_update_entry_has_a_seven_day_cooldown() -> None:
    updates = yaml.safe_load(DEPENDABOT.read_text())["updates"]
    missing = [
        f"{u['package-ecosystem']} {u['directory']}"
        for u in updates
        if (u.get("cooldown") or {}).get("default-days", 0) < 7
    ]
    assert not missing, f"Dependabot entries without a 7-day cooldown: {missing}"
