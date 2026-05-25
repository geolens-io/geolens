"""Create geolens_readonly role for AI SQL sandbox defense-in-depth.

The role is set via ``SET LOCAL ROLE`` inside a SAVEPOINT at
``app/platform/sandbox/executor.py:58-67``. Before this migration ran the
role did not exist, so the SAVEPOINT silently rolled back to the
application user — the defense layer was effectively a no-op.

After this migration, AI-generated SQL executes as ``geolens_readonly``
with USAGE on the ``data`` schema and SELECT on existing + future tables.
INSERT/UPDATE/DELETE/TRUNCATE are not granted, so even a hypothetical
sandbox-validator escape (e.g., a future regression that lets an UPDATE
slip past sqlglot) still cannot mutate data.

Upgrade: create role if missing, grant minimum read privileges, grant
membership to the current (application) user so ``SET ROLE`` works.

Downgrade: revoke and drop the role. Safe to re-run.
"""

from typing import Union

from alembic import op

revision: str = "0023_geolens_readonly_role"
down_revision: Union[str, None] = "0022_ingest_jobs_progress_columns"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # Idempotent role creation — safe on re-run, and survives shared-cluster
    # scenarios where another database in the cluster already owns the role.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'geolens_readonly') THEN
                CREATE ROLE geolens_readonly NOLOGIN;
            END IF;
        END
        $$;
        """
    )

    # Schema access — required before any table SELECT works
    op.execute("GRANT USAGE ON SCHEMA data TO geolens_readonly;")

    # SELECT on existing tables in data schema (where user-uploaded datasets live)
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_readonly;")
    op.execute("GRANT SELECT ON ALL SEQUENCES IN SCHEMA data TO geolens_readonly;")

    # SELECT on future tables (newly ingested datasets create tables in data.*)
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA data
        GRANT SELECT ON TABLES TO geolens_readonly;
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA data
        GRANT SELECT ON SEQUENCES TO geolens_readonly;
        """
    )

    # Membership: application user must be able to SET ROLE TO geolens_readonly.
    # current_user at migration time is the POSTGRES_USER from the env.
    op.execute("GRANT geolens_readonly TO current_user;")


def downgrade() -> None:
    op.execute("REVOKE geolens_readonly FROM current_user;")
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA data
        REVOKE SELECT ON SEQUENCES FROM geolens_readonly;
        """
    )
    op.execute(
        """
        ALTER DEFAULT PRIVILEGES IN SCHEMA data
        REVOKE SELECT ON TABLES FROM geolens_readonly;
        """
    )
    op.execute("REVOKE SELECT ON ALL SEQUENCES IN SCHEMA data FROM geolens_readonly;")
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA data FROM geolens_readonly;")
    op.execute("REVOKE USAGE ON SCHEMA data FROM geolens_readonly;")
    op.execute("DROP ROLE IF EXISTS geolens_readonly;")
