"""Online-safety guards for the tenant-boundary migration sequence."""

from pathlib import Path


VERSIONS = Path(__file__).parent.parent / "alembic" / "versions"


def _source(name: str) -> str:
    return (VERSIONS / name).read_text(encoding="utf-8")


def test_tenant_trigger_migration_bounds_strong_lock_acquisition() -> None:
    source = _source("0018_tenant_insert_stamping.py")

    assert "SET LOCAL lock_timeout = '5s'" in source
    assert "CREATE TRIGGER" in source


def test_dataset_uniqueness_indexes_are_online_and_resumable() -> None:
    source = _source("0020_tenant_dataset_table_names.py")

    assert "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS" in source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in source
    assert "indisvalid" in source and "indisready" in source
    assert "SET LOCAL lock_timeout = '5s'" in source
    assert "DROP CONSTRAINT IF EXISTS" in source
    assert "op.create_index" not in source


def test_control_plane_uniqueness_and_triggers_are_online_safe() -> None:
    source = _source("0021_tenant_control_plane_hardening.py")
    upgrade = source[source.index("def upgrade()") : source.index("def downgrade()")]

    assert "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS" in source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in source
    assert "ADD COLUMN IF NOT EXISTS tenant_id UUID" in source
    assert "DROP CONSTRAINT IF EXISTS" in source
    assert "SET LOCAL lock_timeout = '5s'" in source
    assert "op.create_index" not in source
    assert upgrade.index("_install_oauth_boundary()") < upgrade.index(
        "for definition in _PARTIAL_INDEXES[2:]"
    )


def test_audit_and_ingest_indexes_are_online_and_resumable() -> None:
    source = _source("0022_tenant_audit_job_isolation.py")
    upgrade = source[source.index("def upgrade()") : source.index("def downgrade()")]

    assert "CREATE INDEX CONCURRENTLY IF NOT EXISTS" in source
    assert "DROP INDEX CONCURRENTLY IF EXISTS" in source
    assert "indisvalid" in source and "indisready" in source
    assert source.count("ADD COLUMN IF NOT EXISTS tenant_id UUID") == 1
    assert "SET LOCAL lock_timeout = '5s'" in source
    assert "op.create_index" not in source
    assert upgrade.index("CREATE OR REPLACE FUNCTION") < upgrade.index(
        "for index_name, table in _TENANT_INDEXES"
    )
