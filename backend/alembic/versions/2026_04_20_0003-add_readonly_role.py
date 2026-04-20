"""Add geolens_readonly PostgreSQL role for AI sandbox queries.

Defense-in-depth: even if SET TRANSACTION READ ONLY is somehow skipped,
this role has no write grants on any schema.

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-04-20 14:30:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "r4s5t6u7v8w9"
down_revision = "q3r4s5t6u7v8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create readonly role if it doesn't already exist.
    # NOLOGIN: the role is used via SET ROLE, not direct connection.
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
    # Grant usage on the data schema and SELECT on all current + future tables
    op.execute("GRANT USAGE ON SCHEMA data TO geolens_readonly")
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_readonly")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA data GRANT SELECT ON TABLES TO geolens_readonly"
    )
    # The application DB user must be able to SET ROLE to geolens_readonly
    op.execute(
        """
        DO $$
        BEGIN
            EXECUTE format('GRANT geolens_readonly TO %I', current_user);
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA data REVOKE SELECT ON TABLES FROM geolens_readonly"
    )
    op.execute("REVOKE SELECT ON ALL TABLES IN SCHEMA data FROM geolens_readonly")
    op.execute("REVOKE USAGE ON SCHEMA data FROM geolens_readonly")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'geolens_readonly') THEN
                EXECUTE format('REVOKE geolens_readonly FROM %I', current_user);
                DROP ROLE geolens_readonly;
            END IF;
        END
        $$;
        """
    )
