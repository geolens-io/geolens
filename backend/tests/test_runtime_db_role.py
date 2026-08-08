"""Structural contracts for the opt-in single-tenant PostgreSQL runtime role."""

from pathlib import Path
import os
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
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
    assert "SECURITY DEFINER" in source
    assert "SET search_path = pg_catalog" in source
    assert (
        "REVOKE ALL ON FUNCTION catalog.geolens_rebuild_embedding_column(integer)"
        in source
    )
    assert "OWNER TO" not in "\n".join(
        line for line in source.splitlines() if "catalog" in line.lower()
    )


def test_runtime_role_never_receives_tenant_control_function_execution() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    assert "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA catalog" not in source
    assert (
        "ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT EXECUTE ON FUNCTIONS"
        not in source
    )
    assert (
        "ALTER DEFAULT PRIVILEGES IN SCHEMA catalog REVOKE EXECUTE ON FUNCTIONS"
        in source
    )
    for signature in (
        "catalog.provision_tenant_data_schema(uuid)",
        "catalog.deprovision_tenant_data_schema(uuid)",
    ):
        assert f"REVOKE ALL ON FUNCTION {signature}" in source
        assert f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC" in source
        assert (
            f"GRANT EXECUTE ON FUNCTION {signature} TO geolens_tenant_control" in source
        )


@pytest.mark.anyio
async def test_runtime_embedding_resize_uses_narrow_definer_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runtime login must not receive broad catalog ownership for one DDL path."""
    from app.processing.embeddings import service

    current_result = Mock()
    current_result.scalar_one_or_none.return_value = 1536
    rebuild_result = Mock()
    rebuild_result.scalar_one.return_value = True
    db = AsyncMock()
    db.execute.side_effect = [current_result, rebuild_result]
    monkeypatch.setattr(
        service,
        "settings",
        SimpleNamespace(geolens_runtime_db_role="geolens_app"),
    )

    assert await service.rebuild_embedding_column(db, 768) is True

    statements = [str(call.args[0]) for call in db.execute.await_args_list]
    assert any("catalog.geolens_rebuild_embedding_column" in sql for sql in statements)
    assert not any("ALTER TABLE" in sql or "DROP INDEX" in sql for sql in statements)
    assert db.execute.await_args_list[-1].args[1] == {"new_dims": 768}
    db.commit.assert_awaited_once()


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


@pytest.mark.parametrize(
    ("postgres_user", "runtime_role"),
    [
        ("geolens_app", "geolens_app"),
        ("geolens", "geolens_reader"),
        ("geolens", "geolens_readonly"),
        ("geolens", "geolens_writer"),
        ("geolens", "geolens_tile"),
        ("geolens", "geolens_tenant_control"),
        ("geolens", "geolens_tenant_provisioner"),
        ("geolens", "geolens_tenant_sandbox"),
        ("geolens", "geolens_tenant_writer"),
        ("geolens", "geolens_tile_gateway"),
        ("geolens", "geolens_reader_t_deadbeef"),
        ("geolens", "geolens_writer_t_deadbeef"),
    ],
)
def test_role_script_rejects_bootstrap_and_reserved_roles_before_sql(
    tmp_path: Path,
    postgres_user: str,
    runtime_role: str,
) -> None:
    fake_psql = tmp_path / "psql"
    fake_psql.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    fake_psql.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(ROLE_SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "POSTGRES_USER": postgres_user,
            "POSTGRES_DB": "geolens",
            "GEOLENS_RUNTIME_DB_ROLE": runtime_role,
            "GEOLENS_RUNTIME_DB_PASSWORD": (
                "distinct-runtime-password-with-at-least-32-characters"
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 64, completed.stderr
    assert "reserved" in completed.stderr or "POSTGRES_USER" in completed.stderr
