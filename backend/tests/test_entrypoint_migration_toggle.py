"""Static and shell-level coverage for API migration bootstrap policy."""

from pathlib import Path
import subprocess


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ENTRYPOINT = _BACKEND_ROOT / "scripts" / "api-entrypoint.sh"
_SHELL_TEST = Path(__file__).with_suffix(".sh")


def test_api_entrypoint_migration_toggle_is_default_on_and_fail_closed() -> None:
    source = _ENTRYPOINT.read_text(encoding="utf-8")

    assert "${GEOLENS_API_RUN_MIGRATIONS:-true}" in source
    assert "GEOLENS_API_RUN_MIGRATIONS must be exactly 'true' or 'false'" in source
    assert "alembic upgrade heads" in source


def test_api_entrypoint_migration_toggle_shell_contract() -> None:
    completed = subprocess.run(
        ["bash", str(_SHELL_TEST)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
