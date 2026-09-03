"""fix(#1798 review round 11 audit, P1): RUNBOOK.md told operators to
`set -a; . ./.env; set +a` in three places (globals restore, runtime-role
verification, role rotation) — exactly the shell-sourcing restore.sh's own
header explains get_env_value exists to avoid: `.` executes the file, so an
operator-typed value containing a bare space becomes "set VAR=<first word>,
run <second word> as a command" (a 127 under `set -e`), and a value
containing backticks or $(...) is EXECUTED with the operator's privileges.
The runbook now reads each value through scripts/env-value.sh (a thin
wrapper around common.sh's get_env_value) instead.
"""

from __future__ import annotations

import re

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)

# Matches any shape of "source .env" / ". ./.env" / "set -a" env-file
# sourcing this repo's operator-facing scripts already treat as unsafe —
# see restore.sh's own header comment for the full reasoning. Deliberately
# broader than the exact `set -a; . ./.env; set +a` string the finding
# reported, so a reworded reintroduction of the same pattern still trips
# it: any `. ./.env`/`. .env`/`source .env`-shaped line, or a bare `set -a`
# immediately preceding one.
_SOURCING_PATTERN = re.compile(
    r"(^|\s)(\.|source)\s+\.{0,2}/?\.env\b|set\s+-a\s*;\s*\.\s"
)


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_runbook_does_not_shell_source_env() -> None:
    body = _read("RUNBOOK.md")
    match = _SOURCING_PATTERN.search(body)
    assert match is None, (
        "RUNBOOK.md shell-sources .env "
        f"({match.group(0)!r} at offset {match.start() if match else -1}) — "
        "an operator-typed value containing backticks or $(...) would "
        "execute with the operator's privileges; read it through "
        "scripts/env-value.sh (get_env_value) instead, matching "
        "restore.sh/check-env.sh/upgrade.sh."
    )


def test_runbook_uses_the_env_value_wrapper_for_postgres_settings() -> None:
    body = _read("RUNBOOK.md")
    assert "scripts/env-value.sh POSTGRES_USER" in body
    assert "scripts/env-value.sh POSTGRES_DB" in body
    assert "scripts/env-value.sh GEOLENS_RUNTIME_DB_ROLE" in body
    assert "scripts/env-value.sh GEOLENS_RUNTIME_DB_PASSWORD" in body


def test_env_value_wrapper_script_exists_and_is_executable() -> None:
    path = REPO_ROOT / "scripts" / "env-value.sh"
    assert path.is_file(), "scripts/env-value.sh (referenced by RUNBOOK.md) is missing"
    assert path.stat().st_mode & 0o111, "scripts/env-value.sh must be executable"
    body = path.read_text(encoding="utf-8")
    assert "get_env_value" in body
    assert (
        '. "$SCRIPT_DIR/lib/common.sh"' in body
        or '. "${SCRIPT_DIR}/lib/common.sh"' in body
    )
