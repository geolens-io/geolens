"""Structural contracts for the opt-in single-tenant PostgreSQL runtime role."""

from pathlib import Path
import os
import subprocess

import yaml

from tests.repo_paths import repo_root


ROOT = repo_root(__file__)
ROLE_SCRIPT = ROOT / "scripts" / "lib" / "configure-runtime-db-role.sh"


def _compose(filename: str) -> dict:
    return yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))


def test_bootstrap_restore_and_upgrade_share_one_role_reconciler() -> None:
    init_source = (ROOT / "scripts" / "init-db.sh").read_text(encoding="utf-8")
    restore_source = (ROOT / "scripts" / "restore.sh").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")

    command = "/usr/local/bin/configure-runtime-db-role"
    assert command in init_source
    assert restore_source.index(command) > restore_source.index("pg_restore -U")
    assert "Adopt the single-tenant runtime role on an existing install" in runbook
    assert f"docker compose exec -T db {command}" in runbook


def test_compose_mounts_reconciler_read_only_and_scopes_the_password_to_db() -> None:
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        services = _compose(filename)["services"]
        db = services["db"]

        assert (
            "./scripts/lib/configure-runtime-db-role.sh:"
            "/usr/local/bin/configure-runtime-db-role:ro"
        ) in db["volumes"]
        assert db["environment"]["GEOLENS_RUNTIME_DB_PASSWORD"] == (
            "${GEOLENS_RUNTIME_DB_PASSWORD:-}"
        )
        for service_name in ("api", "worker", "migrate"):
            assert (
                "GEOLENS_RUNTIME_DB_PASSWORD"
                not in services[service_name]["environment"]
            )


def test_role_script_keeps_password_out_of_argv_and_catalog_ownership() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    assert "\\getenv runtime_password GEOLENS_RUNTIME_DB_PASSWORD" in source
    assert "--set=runtime_password" not in source
    assert "namespace.nspname = 'data'" in source
    assert "OWNER TO %I" in source
    assert "GRANT USAGE ON SCHEMA catalog" in source
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA data" in source
    assert "OWNER TO" not in "\n".join(
        line for line in source.splitlines() if "catalog" in line.lower()
    )


def test_env_example_documents_the_complete_opt_in_split() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    for variable in (
        "GEOLENS_RUNTIME_DB_ROLE",
        "GEOLENS_RUNTIME_DB_PASSWORD",
        "DATABASE_URL_OVERRIDE",
        "MIGRATION_DATABASE_URL_OVERRIDE",
        "GEOLENS_API_RUN_MIGRATIONS=false",
    ):
        assert variable in env_example

    assert (
        "Existing installs keep their current POSTGRES_USER connection" in env_example
    )


def test_role_script_is_executable() -> None:
    mode = Path(ROLE_SCRIPT).stat().st_mode
    assert mode & 0o111


def test_role_script_rejects_unsafe_input_before_connecting() -> None:
    base_env = {
        **os.environ,
        "POSTGRES_USER": "geolens",
        "POSTGRES_DB": "geolens",
        "GEOLENS_RUNTIME_DB_PASSWORD": "test-runtime-password-with-32-characters",
    }
    for role in ("bad-role", "Uppercase", "role;select_pg_sleep"):
        completed = subprocess.run(
            ["bash", str(ROLE_SCRIPT)],
            env={**base_env, "GEOLENS_RUNTIME_DB_ROLE": role},
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 64
        assert "lowercase PostgreSQL identifier" in completed.stderr


def test_role_script_rejects_reused_privileged_password_before_connecting() -> None:
    shared_password = "shared-password-that-is-at-least-32-characters"
    completed = subprocess.run(
        ["bash", str(ROLE_SCRIPT)],
        env={
            **os.environ,
            "POSTGRES_USER": "geolens",
            "POSTGRES_DB": "geolens",
            "POSTGRES_PASSWORD": shared_password,
            "GEOLENS_RUNTIME_DB_ROLE": "geolens_app",
            "GEOLENS_RUNTIME_DB_PASSWORD": shared_password,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 64
    assert "must differ from the privileged" in completed.stderr
