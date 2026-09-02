"""Structural contracts for the opt-in single-tenant PostgreSQL runtime role."""

from pathlib import Path
import json
import os
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import yaml

from tests.repo_paths import repo_root


ROOT = repo_root(__file__)
ROLE_SCRIPT = ROOT / "scripts" / "lib" / "configure-runtime-db-role.sh"
ROUNDTRIP_SCRIPT = ROOT / "scripts" / "tests" / "test-backup-restore-roundtrip.sh"

requires_docker_cli = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="docker CLI is not installed in this image (fix(#1745))",
)


def _compose(filename: str) -> dict:
    return yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))


def _render_compose(filename: str, overrides: dict[str, str]) -> dict:
    environment = os.environ.copy()
    for key in (
        "DATABASE_URL_OVERRIDE",
        "GEOLENS_MIGRATION_DB_ROLE",
        "GEOLENS_MIGRATION_DB_LOCAL",
        "GEOLENS_RUNTIME_DB_ROLE",
        "GEOLENS_RUNTIME_DB_PASSWORD",
        "MIGRATION_DATABASE_URL_OVERRIDE",
    ):
        environment.pop(key, None)
    environment.update(
        {
            "POSTGRES_DB": "local_geolens",
            "POSTGRES_USER": "local_bootstrap",
            "POSTGRES_PASSWORD": "local-bootstrap-password",
            **overrides,
        }
    )
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / ".env.example"),
            "-f",
            str(ROOT / filename),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout)


def test_bootstrap_restore_and_upgrade_share_one_role_reconciler() -> None:
    init_source = (ROOT / "scripts" / "init-db.sh").read_text(encoding="utf-8")
    restore_source = (ROOT / "scripts" / "restore.sh").read_text(encoding="utf-8")
    runbook = (ROOT / "RUNBOOK.md").read_text(encoding="utf-8")

    command = "/usr/local/bin/configure-runtime-db-role"
    assert command in init_source
    assert restore_source.index(command) > restore_source.index("pg_restore -U")
    assert "Adopt the single-tenant runtime role on an existing install" in runbook
    assert f"docker compose exec -T db {command}" in runbook
    assert "geolens-managed-runtime-role:v2:database=<current-database>" in runbook
    assert "A second live database" in runbook
    assert "cannot reuse that" in runbook


def test_clean_db_migration_smoke_mounts_role_reconciler_read_only() -> None:
    source = (ROOT / "backend/scripts/test_alembic_upgrade_clean_db.sh").read_text(
        encoding="utf-8"
    )

    assert (
        'ROLE_RECONCILER="${REPO_ROOT}/scripts/lib/configure-runtime-db-role.sh"'
        in source
    )
    assert '[ ! -f "${ROLE_RECONCILER}" ]' in source
    assert '[ ! -r "${ROLE_RECONCILER}" ]' in source
    assert (
        '-v "${ROLE_RECONCILER}:/usr/local/bin/configure-runtime-db-role:ro"' in source
    )


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
        assert db["environment"]["GEOLENS_MIGRATION_DB_ROLE"] == (
            "${GEOLENS_MIGRATION_DB_ROLE:-}"
        )
        assert db["environment"]["GEOLENS_MIGRATION_DB_URL_CONFIGURED"] == (
            "${MIGRATION_DATABASE_URL_OVERRIDE:+configured}"
            "${DATABASE_URL_OVERRIDE:+configured}"
        )
        assert db["environment"]["GEOLENS_MIGRATION_DB_LOCAL"] == (
            "${GEOLENS_MIGRATION_DB_LOCAL:-false}"
        )
        for service_name in ("api", "worker", "migrate"):
            assert (
                "GEOLENS_RUNTIME_DB_PASSWORD"
                not in services[service_name]["environment"]
            )


@requires_docker_cli
def test_compose_scopes_managed_migrator_role_away_from_local_db() -> None:
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        services = _render_compose(
            filename,
            {
                "DATABASE_URL_OVERRIDE": (
                    "postgresql://geolens_app:runtime-password@managed/geolens"
                ),
                "GEOLENS_MIGRATION_DB_ROLE": "external_migrator",
                "GEOLENS_RUNTIME_DB_ROLE": "geolens_app",
                "GEOLENS_RUNTIME_DB_PASSWORD": "runtime-password-at-least-32-characters",
                "MIGRATION_DATABASE_URL_OVERRIDE": (
                    "postgresql://external_migrator:migration-password@managed/geolens"
                ),
            },
        )["services"]

        assert (
            services["db"]["environment"]["GEOLENS_MIGRATION_DB_ROLE"]
            == "external_migrator"
        )
        assert services["db"]["environment"]["GEOLENS_MIGRATION_DB_URL_CONFIGURED"] == (
            "configuredconfigured"
        )
        assert services["db"]["environment"]["GEOLENS_MIGRATION_DB_LOCAL"] == ("false")
        assert services["db"]["environment"]["POSTGRES_USER"] == "local_bootstrap"
        assert (
            services["migrate"]["environment"]["GEOLENS_MIGRATION_DB_ROLE"]
            == "external_migrator"
        )


@requires_docker_cli
def test_compose_infers_bundled_migrator_role_only_for_migrate() -> None:
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        services = _render_compose(
            filename,
            {
                "GEOLENS_RUNTIME_DB_ROLE": "geolens_app",
                "GEOLENS_RUNTIME_DB_PASSWORD": "runtime-password-at-least-32-characters",
            },
        )["services"]

        assert services["db"]["environment"]["GEOLENS_MIGRATION_DB_ROLE"] == ""
        assert (
            services["db"]["environment"]["GEOLENS_MIGRATION_DB_URL_CONFIGURED"] == ""
        )
        assert (
            services["migrate"]["environment"]["GEOLENS_MIGRATION_DB_ROLE"]
            == "local_bootstrap"
        )


@requires_docker_cli
def test_compose_passes_explicit_bundled_migration_owner_to_local_db() -> None:
    for filename in ("docker-compose.yml", "docker-compose.prod.yml"):
        services = _render_compose(
            filename,
            {
                "DATABASE_URL_OVERRIDE": (
                    "postgresql://geolens_app:runtime-password@db/local_geolens"
                ),
                "GEOLENS_MIGRATION_DB_LOCAL": "true",
                "GEOLENS_MIGRATION_DB_ROLE": "local_migrator",
                "GEOLENS_RUNTIME_DB_ROLE": "geolens_app",
                "GEOLENS_RUNTIME_DB_PASSWORD": (
                    "runtime-password-at-least-32-characters"
                ),
                "MIGRATION_DATABASE_URL_OVERRIDE": (
                    "postgresql://local_migrator:migration-password@db/local_geolens"
                ),
            },
        )["services"]

        assert (
            services["db"]["environment"]["GEOLENS_MIGRATION_DB_ROLE"]
            == "local_migrator"
        )
        assert services["db"]["environment"]["GEOLENS_MIGRATION_DB_URL_CONFIGURED"] == (
            "configuredconfigured"
        )
        assert services["db"]["environment"]["GEOLENS_MIGRATION_DB_LOCAL"] == ("true")
        assert (
            services["migrate"]["environment"]["GEOLENS_MIGRATION_DB_ROLE"]
            == "local_migrator"
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
    legacy_start = source.index('if [ -z "$runtime_role" ]')
    legacy_exit = source.index("    exit 0", legacy_start)
    legacy_block = source[legacy_start:legacy_exit]
    assert (
        "SELECT 'REVOKE ALL ON FUNCTION "
        "catalog.geolens_rebuild_embedding_column(integer) FROM PUBLIC'" in legacy_block
    )
    assert "ALTER TABLE catalog.record_embeddings OWNER TO %I" in source
    assert "ALTER SCHEMA catalog" not in source


def test_role_script_requires_managed_marker_and_targets_migration_owner() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    assert 'migration_role="${GEOLENS_MIGRATION_DB_ROLE:-$db_user}"' in source
    assert "geolens-managed-runtime-role:v2:database=" in source
    assert "current_database()" in source
    assert "shobj_description" in source
    assert "GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING" in source
    assert "GEOLENS_MIGRATION_DB_ROLE" in source
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA catalog" in source
    assert "server_version_num" in source
    assert "pg_has_role(current_user" in source
    assert "'GRANT %I TO %I'" in source
    assert "'REVOKE %I FROM %I GRANTED BY %I'" in source
    assert "'REVOKE %I FROM %I'" in source
    assert "BEGIN;" in source
    assert "COMMIT;" in source
    # PostgreSQL 18's psql ignores arguments to \quit, so `\quit 1` reports
    # success and would turn a fail-closed branch into a silent pass.
    assert "\\quit 1" not in source


def test_role_script_rechecks_database_and_schema_ownership_before_mutation() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    ownership_preflight = "runtime_role_ownership_safe"
    first_reader_mutation = "COMMENT ON ROLE geolens_reader IS"
    final_gate = ") AS runtime_role_safe"
    assert ownership_preflight in source
    assert "FROM pg_database AS owned_database" in source
    assert "FROM pg_namespace AS owned_schema" in source
    assert "pg_has_role(runtime.oid, owned_database.datdba, 'MEMBER')" in source
    assert "pg_has_role(runtime.oid, owned_schema.nspowner, 'MEMBER')" in source
    assert source.index(ownership_preflight) < source.index(first_reader_mutation)
    assert source.rindex("FROM pg_database AS owned_database") < source.index(
        final_gate
    )
    assert source.rindex("FROM pg_namespace AS owned_schema") < source.index(final_gate)


def test_role_script_selects_local_migration_owner_without_external_role_leak() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    assert (
        'migration_url_configured="${GEOLENS_MIGRATION_DB_URL_CONFIGURED:-}"' in source
    )
    assert 'migration_db_local="${GEOLENS_MIGRATION_DB_LOCAL:-false}"' in source
    assert 'migration_role="$db_user"' in source
    assert (
        '[ -z "$migration_url_configured" ] || [ "$migration_db_local" = true ]'
        in source
    )
    assert 'migration_role="${GEOLENS_MIGRATION_DB_ROLE:-$db_user}"' in source


def test_role_script_scopes_shared_reader_to_the_current_database() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    revoke_public = "'REVOKE CONNECT ON DATABASE %I FROM PUBLIC'"
    grant_runtime = (
        "'GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'runtime_role'"
    )
    grant_reader = "'GRANT geolens_reader TO %I'"
    legacy_start = source.index('if [ -z "$runtime_role" ]')
    legacy_exit = source.index("    exit 0", legacy_start)
    assert revoke_public in source[legacy_start:legacy_exit]
    assert source.count(revoke_public) == 2
    assert (
        "'GRANT CONNECT ON DATABASE %I TO %I', current_database(), current_user"
        in source
    )
    assert (
        "'GRANT CONNECT ON DATABASE %I TO %I', current_database(), "
        ":'migration_role'" in source
    )
    assert grant_runtime in source
    assert source.index(revoke_public) < source.index(grant_reader)
    assert "database_acl.grantee = 0" in source
    assert "database_acl.privilege_type = 'CONNECT'" in source


def test_reader_role_requires_durable_marker_or_safe_legacy_shape() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    marker = "geolens-managed-reader-role:v1"
    create_reader = "CREATE ROLE geolens_reader"
    alter_reader = "ALTER ROLE geolens_reader"
    assert marker in source
    assert "reader_role_managed" in source
    assert "reader_role_legacy_safe" in source
    assert "existing geolens_reader role is not safe to adopt" in source
    assert source.index(marker) < source.index(alter_reader)
    assert source.index(create_reader) < source.index(alter_reader)


def test_runtime_can_only_read_alembic_version_table() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    create_version = "CREATE TABLE IF NOT EXISTS catalog.alembic_version"
    revoke_dml = (
        "REVOKE INSERT, UPDATE, DELETE ON TABLE catalog.alembic_version FROM %I"
    )
    default_dml = (
        "ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA catalog GRANT SELECT, "
        "INSERT, UPDATE, DELETE ON TABLES TO %I"
    )
    assert create_version in source
    assert revoke_dml in source
    assert source.index(create_version) < source.index(default_dml)
    assert source.index(default_dml) < source.rindex(revoke_dml)


def test_data_routines_are_runtime_owned_before_execute_grants() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    transfer_owner = "'ALTER %s %I.%I(%s) OWNER TO %I'"
    ownership_gate = "data_routine_owners_supported"
    revoke_public = "FROM PUBLIC"
    grant_runtime = "'GRANT EXECUTE ON %s %I.%I(%s) TO %I'"
    assert transfer_owner in source
    assert ownership_gate in source
    assert "function.prokind IN ('f', 'p', 'w')" in source
    assert grant_runtime in source
    transfer_index = source.index(transfer_owner)
    gate_index = source.index(ownership_gate, transfer_index)
    grant_index = source.index(grant_runtime, gate_index)
    assert transfer_index < gate_index < grant_index
    assert revoke_public in source[gate_index:grant_index]


def test_embedding_definer_is_created_as_the_validated_migration_owner() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    adopt_owner = (
        "'ALTER FUNCTION catalog.geolens_rebuild_embedding_column(integer) OWNER TO %I'"
    )
    set_migration = "SELECT format('SET LOCAL ROLE %I', :'migration_role')"
    create_function = (
        "CREATE OR REPLACE FUNCTION "
        "catalog.geolens_rebuild_embedding_column(new_dims integer)"
    )
    assert adopt_owner in source
    assert set_migration in source
    assert source.index(adopt_owner) < source.index(set_migration)
    assert source.index(set_migration) < source.index(create_function)
    assert source.index(create_function) < source.index("RESET ROLE;")


def test_roundtrip_gates_only_vector_specific_proof_on_extension_availability() -> None:
    source = ROUNDTRIP_SCRIPT.read_text(encoding="utf-8")

    vector_guard = 'if [ "$PGVECTOR_AVAILABLE" = "t" ]; then'
    create_vector = "CREATE EXTENSION IF NOT EXISTS vector;"
    assert "pg_available_extensions WHERE name = 'vector'" in source
    assert "SKIP [pgvector]: extension unavailable" in source
    assert source.count(vector_guard) >= 4
    assert source.index(vector_guard) < source.index(create_vector)
    assert "function ownership and ACL checks still run" in source


def test_role_script_atomically_retires_superseded_database_roles() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    collect_roles = "CREATE TEMP TABLE pg_temp.geolens_superseded_runtime_roles"
    reassign = "'REASSIGN OWNED BY %I TO %I'"
    drop_owned = "'DROP OWNED BY %I'"
    revoke_migrator_acl = "'REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM %I'"
    revoke_connect = "'REVOKE CONNECT ON DATABASE %I FROM %I'"
    disable_login = "'ALTER ROLE %I NOLOGIN NOINHERIT'"
    retired_marker = "geolens-retired-runtime-role:v1:database="
    assert collect_roles in source
    assert "= :'expected_runtime_marker'" in source
    assert "runtime.rolname <> :'runtime_role'" in source
    assert reassign in source
    assert drop_owned in source
    assert revoke_migrator_acl in source
    assert "aclexplode(relation.relacl)" in source
    assert revoke_connect in source
    assert disable_login in source
    assert retired_marker in source
    assert "superseded_roles_retired" in source
    assert "pg_default_acl" in source
    assert source.index(collect_roles) < source.index(reassign)
    assert source.index(collect_roles) < source.index(revoke_migrator_acl)
    assert source.index(revoke_migrator_acl) < source.index(drop_owned)
    assert source.index(reassign) < source.index(drop_owned)
    assert source.index(drop_owned) < source.index(disable_login)
    assert source.index(disable_login) < source.index(
        "COMMIT;", source.index(collect_roles)
    )
    # Managed-provider compatibility must not require pg_signal_backend.
    assert "pg_terminate_backend" not in source


def test_runtime_role_never_receives_tenant_control_function_execution() -> None:
    source = ROLE_SCRIPT.read_text(encoding="utf-8")

    assert "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA catalog" not in source
    assert (
        "ALTER DEFAULT PRIVILEGES IN SCHEMA catalog GRANT EXECUTE ON FUNCTIONS"
        not in source
    )
    assert "IN SCHEMA catalog REVOKE EXECUTE ON FUNCTIONS" in source
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
        "GEOLENS_MIGRATION_DB_ROLE",
        "GEOLENS_RUNTIME_DB_ROLE_ADOPT_EXISTING=false",
        "DATABASE_URL_OVERRIDE",
        "MIGRATION_DATABASE_URL_OVERRIDE",
        "GEOLENS_API_RUN_MIGRATIONS=false",
    ):
        assert variable in env_example

    assert (
        "Existing installs keep their current POSTGRES_USER connection" in env_example
    )


def test_multi_tenant_recipe_admits_both_runtime_logins_to_database() -> None:
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    recipe_start = env_example.index("# PostgreSQL 16+ membership example")
    recipe_end = env_example.index("# Runtime application connection", recipe_start)
    recipe = env_example[recipe_start:recipe_end]

    assert "GRANT CONNECT ON DATABASE geolens TO geolens_app;" in recipe
    assert "GRANT CONNECT ON DATABASE geolens TO geolens_tile;" in recipe


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
        ("geolens", "postgres"),
        ("geolens", "pg_monitor"),
        ("geolens", "pg_read_all_data"),
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


def test_role_script_rejects_migration_owner_as_runtime_before_sql(
    tmp_path: Path,
) -> None:
    fake_psql = tmp_path / "psql"
    fake_psql.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    fake_psql.chmod(0o755)

    completed = subprocess.run(
        ["bash", str(ROLE_SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "POSTGRES_USER": "provider_admin",
            "POSTGRES_DB": "geolens",
            "GEOLENS_MIGRATION_DB_ROLE": "geolens_migrator",
            "GEOLENS_RUNTIME_DB_ROLE": "geolens_migrator",
            "GEOLENS_RUNTIME_DB_PASSWORD": (
                "distinct-runtime-password-with-at-least-32-characters"
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 64, completed.stderr
    assert "must differ" in completed.stderr
