"""Create catalog schema, custom functions, and trigger functions.

These must exist before ORM tables because the records.search_vector
computed column references catalog.immutable_array_camel_to_spaced().

Revision ID: 0001_fdn
Revises:
Create Date: 2026-03-28
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0001_fdn"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Schema created by env.py (required before Alembic version table)

    # Verify required extensions exist (created by init-db.sh / conftest.py)
    for ext in ("postgis", "pg_trgm", "vector", "unaccent"):
        op.execute(
            f"DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = '{ext}') THEN "
            f'RAISE EXCEPTION \'Required extension "{ext}" is not installed. '
            f"Run scripts/init-db.sh or CREATE EXTENSION {ext} first.'; "
            f"END IF; END $$"
        )

    # --- Immutable text-processing functions (used in search_vector) ---

    op.execute("""
    CREATE FUNCTION catalog.immutable_camel_to_spaced(input text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        AS $$
            SELECT regexp_replace(input, '([a-z])([A-Z])', '\\1 \\2', 'g');
        $$
    """)

    op.execute("""
    CREATE FUNCTION catalog.immutable_array_camel_to_spaced(arr text[], sep text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        AS $$
            SELECT array_to_string(
                ARRAY(SELECT catalog.immutable_camel_to_spaced(unnest) FROM unnest(arr)),
                sep
            );
        $$
    """)

    op.execute("""
    CREATE FUNCTION catalog.immutable_array_to_string(arr text[], sep text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        AS $$ SELECT array_to_string(arr, sep); $$
    """)

    op.execute("""
    CREATE FUNCTION catalog.immutable_jsonb_column_names(info jsonb) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        AS $$
            SELECT CASE WHEN jsonb_typeof(info) = 'array'
                THEN (SELECT string_agg(elem->>'name', ' ')
                      FROM jsonb_array_elements(info) AS elem)
                ELSE NULL
            END;
        $$
    """)

    op.execute("""
    CREATE FUNCTION catalog.immutable_jsonb_sample_values(samples jsonb) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
        AS $$
            SELECT CASE WHEN jsonb_typeof(samples) = 'object'
                THEN (SELECT string_agg(val, ' ')
                      FROM (
                          SELECT jsonb_array_elements_text(value) AS val
                          FROM jsonb_each(samples)
                      ) sub)
                ELSE NULL
            END;
        $$
    """)

    # --- Trigger function for auto-updating updated_at columns ---

    op.execute("""
    CREATE FUNCTION catalog.set_updated_at() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS catalog.set_updated_at() CASCADE")
    op.execute(
        "DROP FUNCTION IF EXISTS catalog.immutable_jsonb_sample_values(jsonb) CASCADE"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS catalog.immutable_jsonb_column_names(jsonb) CASCADE"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS catalog.immutable_array_to_string(text[], text) CASCADE"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS catalog.immutable_array_camel_to_spaced(text[], text) CASCADE"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS catalog.immutable_camel_to_spaced(text) CASCADE"
    )
    op.execute("DROP SCHEMA IF EXISTS catalog CASCADE")
