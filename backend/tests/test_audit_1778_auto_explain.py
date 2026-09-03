"""fix(#1778): auto_explain.log_analyze/log_buffers instrument EVERY
statement the cluster executes, not just the ones slower than the
log_min_duration threshold — auto_explain has to install per-node
row-counting and timing at ExecutorStart, before a statement's duration is
known, so the threshold only gates the LOGGING. Shipped on by default at
100ms, that overhead landed on every query in both the dev and prod stacks
(db/postgresql.conf is bind-mounted into both docker-compose.yml and
docker-compose.prod.yml), worst on the vector-tile and search paths this
product is built on. `auto_explain.log_min_duration = -1` disables the
instrumentation entirely (not just the log line), so it is now a deliberate
per-incident opt-in via `ALTER SYSTEM`, documented inline.
"""

from __future__ import annotations

import re

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
POSTGRESQL_CONF = REPO_ROOT / "db" / "postgresql.conf"


def _read() -> str:
    return POSTGRESQL_CONF.read_text(encoding="utf-8")


def test_auto_explain_is_disabled_by_default() -> None:
    text = _read()
    assert re.search(
        r"^auto_explain\.log_min_duration\s*=\s*-1\b", text, re.MULTILINE
    ), (
        "auto_explain.log_min_duration must default to -1 (disabled) — "
        "instrumentation overhead must not be unconditional in production"
    )
    assert not re.search(
        r"^auto_explain\.log_min_duration\s*=\s*'100ms'", text, re.MULTILINE
    )


def test_auto_explain_documents_the_per_incident_alter_system_recipe() -> None:
    text = _read()
    assert "ALTER SYSTEM SET auto_explain.log_min_duration" in text
    assert "pg_reload_conf" in text
