"""`make env-test` carries the dev .env password to the value `make cli-test` uses."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.repo_paths import repo_root

_REPO_ROOT = repo_root(__file__)

# Runs cli-test's password lookup and compares, so no value reaches the output.
_CHECK_RULE = (
    "_check_test_db_password:\n"
    '\t@$(READ_TEST_DB_PASSWORD); [ "$$pg_pw" = "$$EXPECTED_TEST_DB_PASSWORD" ]\n'
)


@pytest.mark.skipif(shutil.which("make") is None, reason="needs make")
@pytest.mark.parametrize(
    ("env_line", "expected"),
    [
        ("POSTGRES_PASSWORD=it's-a-test\\", "it's-a-test\\"),
        ('POSTGRES_PASSWORD="dq $$ and \\" quote"', 'dq $ and " quote'),
        ("POSTGRES_PASSWORD=plain-test-value", "plain-test-value"),
    ],
)
def test_env_test_password_reaches_cli_test(tmp_path: Path, env_line, expected):
    """A password with an apostrophe, backslash or quotes survives the round trip."""
    (tmp_path / "scripts" / "lib").mkdir(parents=True)
    shutil.copy(
        _REPO_ROOT / "scripts" / "lib" / "common.sh",
        tmp_path / "scripts" / "lib" / "common.sh",
    )
    shutil.copy(_REPO_ROOT / ".env.test.example", tmp_path / ".env.test.example")
    (tmp_path / ".env").write_text(f"POSTGRES_USER=geolens\n{env_line}\n")
    (tmp_path / "check.mk").write_text(_CHECK_RULE)
    env = {k: v for k, v in os.environ.items() if not k.startswith("POSTGRES_")} | {
        "EXPECTED_TEST_DB_PASSWORD": expected
    }

    def make(*targets: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["make", "-s", "-C", str(tmp_path), "-f", str(_REPO_ROOT / "Makefile")]
            + ["-f", str(tmp_path / "check.mk"), *targets],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    created = make("env-test")
    assert created.returncode == 0, created.stderr
    assert oct((tmp_path / ".env.test").stat().st_mode & 0o777) == "0o600"

    checked = make("_check_test_db_password")
    assert checked.returncode == 0, "cli-test would read a different password"
