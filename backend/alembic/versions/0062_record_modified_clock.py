"""Keep record modification times monotonic across concurrent transactions."""

from alembic import op

revision = "0062_record_modified_clock"
down_revision = "0061_refresh_token_families"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION catalog.set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = GREATEST(OLD.updated_at, clock_timestamp());
            RETURN NEW;
        END;
        $$
    """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION catalog.set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$
    """)
