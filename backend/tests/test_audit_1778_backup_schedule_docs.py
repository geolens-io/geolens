"""fix(#1778): RUNBOOK.md and .env.example told operators to set
BACKUP_SCHEDULE to a sub-daily cron expression (a step/range form like
`0 */12 * * *`), but scripts/backup-entrypoint.sh's validate_cron_expr()
(pinned by tests/test_1184_backup_schedule_validation.py) rejects anything
but a literal "M H * * *" — a single fixed time once a day — and exits 1 at
container startup. Following the worked example silently disabled backups.
"""

from __future__ import annotations

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_runbook_does_not_suggest_shortening_rpo_via_backup_schedule() -> None:
    body = _read("RUNBOOK.md")
    assert "every 12 h" not in body
    assert "Shorten the exposure with a more frequent" not in body
    assert "`BACKUP_SCHEDULE` only accepts a single fixed daily time" in body


def test_runbook_non_daily_schedule_callout_does_not_imply_it_is_possible() -> None:
    body = _read("RUNBOOK.md")
    assert "Non-daily schedule?" not in body


def test_env_example_backup_schedule_states_accepted_form() -> None:
    body = _read(".env.example")
    assert "every 12 h" not in body
    assert '"M H * * *"' in body


def test_env_example_backup_max_age_does_not_scale_to_a_faster_interval() -> None:
    body = _read(".env.example")
    assert "~1.5x the interval" not in body
