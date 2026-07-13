"""Static and shell-level coverage for API migration bootstrap policy."""

from pathlib import Path
import subprocess

import yaml

from tests.repo_paths import repo_root


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = repo_root(__file__)
_ENTRYPOINT = _BACKEND_ROOT / "scripts" / "api-entrypoint.sh"
_SHELL_TEST = Path(__file__).with_suffix(".sh")
_COMPOSE_TOGGLE = "${GEOLENS_API_RUN_MIGRATIONS:-true}"


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


def test_official_compose_files_forward_api_migration_toggle() -> None:
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        compose = yaml.safe_load((_REPO_ROOT / filename).read_text(encoding="utf-8"))
        api_environment = compose["services"]["api"]["environment"]

        assert api_environment["GEOLENS_API_RUN_MIGRATIONS"] == _COMPOSE_TOGGLE


def test_env_example_documents_api_migration_toggle() -> None:
    env_example = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "# GEOLENS_API_RUN_MIGRATIONS=true" in env_example
    assert "least-privilege runtime login" in env_example
