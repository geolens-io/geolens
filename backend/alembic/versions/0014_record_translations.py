"""Add normalized localized title/summary variants for catalog records.

Revision ID: 0014_record_translations
Revises: 0013_backfill_geoparquet_distributions
Create Date: 2026-07-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_record_translations"
down_revision: Union[str, None] = "0013_backfill_geoparquet_distributions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The DDL prefix commits independently so its brief ACCESS EXCLUSIVE lock is
    # released before the data repair scans records. The conditional constraint
    # add makes this prefix safe to retry if a later autocommit step is interrupted.
    # NOT VALID skips the locked table scan but still constrains every new write.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                """
                DO $$
                BEGIN
                  ALTER TABLE catalog.records
                    ALTER COLUMN language TYPE VARCHAR(35);

                  IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conrelid = 'catalog.records'::regclass
                      AND conname = 'chk_records_language_tag'
                  ) THEN
                    ALTER TABLE catalog.records
                      ADD CONSTRAINT chk_records_language_tag
                      CHECK (
                        language IS NULL
                        OR language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'
                      ) NOT VALID;
                  END IF;
                END $$;
                """
            )
        )

    # Canonicalize only rows whose value actually changes. The scan can run for
    # a large catalog, but it no longer rewrites every non-NULL row or runs while
    # the DDL lock above is held.
    op.execute(
        sa.text(
            """
            WITH normalized AS (
              SELECT id,
                     CASE
                       WHEN btrim(replace(language, '_', '-'))
                            ~* '^[a-z]{2,3}(-[a-z0-9]{2,8})*$'
                       THEN lower(
                              split_part(
                                btrim(replace(language, '_', '-')), '-', 1
                              )
                            )
                            || substring(
                              btrim(replace(language, '_', '-'))
                              FROM length(
                                split_part(
                                  btrim(replace(language, '_', '-')), '-', 1
                                )
                              ) + 1
                            )
                       ELSE 'en'
                     END AS normalized_language
              FROM catalog.records
              WHERE language IS NOT NULL
            )
            UPDATE catalog.records AS records
            SET language = normalized.normalized_language
            FROM normalized
            WHERE records.id = normalized.id
              AND records.language IS DISTINCT FROM normalized.normalized_language
            """
        )
    )

    # Entering this block commits the targeted repair. PostgreSQL validates the
    # already-enforced constraint under SHARE UPDATE EXCLUSIVE, which permits
    # ordinary reads and writes. VALIDATE is a no-op on crash/retry once valid.
    with op.get_context().autocommit_block():
        op.execute(
            sa.text(
                """
                ALTER TABLE catalog.records
                  VALIDATE CONSTRAINT chk_records_language_tag
                """
            )
        )
    op.create_table(
        "record_translations",
        sa.Column(
            "id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("record_id", sa.UUID(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "language ~ '^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$'",
            name="chk_record_translations_language_tag",
        ),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["catalog.records.id"],
            name="fk_record_translations_record_id_records",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_record_translations",
        ),
        schema="catalog",
    )
    op.create_index(
        "uq_record_translations_record_language_ci",
        "record_translations",
        ["record_id", sa.text("lower(language)")],
        unique=True,
        schema="catalog",
    )
    op.create_index(
        "ix_record_translations_simple_search_vector",
        "record_translations",
        [
            sa.text(
                "to_tsvector('simple'::regconfig, (COALESCE(title, ''::text) || ' '::text) || COALESCE(summary, ''::text))"
            )
        ],
        unique=False,
        schema="catalog",
        postgresql_using="gin",
    )
    op.create_index(
        "ix_record_translations_title_trgm",
        "record_translations",
        [sa.literal_column("lower(catalog.immutable_unaccent(title))")],
        unique=False,
        schema="catalog",
        postgresql_using="gin",
        postgresql_ops={"lower(catalog.immutable_unaccent(title))": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_record_translations_summary_trgm",
        "record_translations",
        [sa.literal_column("lower(catalog.immutable_unaccent(coalesce(summary, '')))")],
        unique=False,
        schema="catalog",
        postgresql_using="gin",
        postgresql_ops={
            "lower(catalog.immutable_unaccent(coalesce(summary, '')))": "gin_trgm_ops"
        },
    )


def downgrade() -> None:
    op.drop_index(
        "ix_record_translations_summary_trgm",
        table_name="record_translations",
        schema="catalog",
        postgresql_using="gin",
    )
    op.drop_index(
        "ix_record_translations_title_trgm",
        table_name="record_translations",
        schema="catalog",
        postgresql_using="gin",
    )
    op.drop_index(
        "ix_record_translations_simple_search_vector",
        table_name="record_translations",
        schema="catalog",
        postgresql_using="gin",
    )
    op.drop_index(
        "uq_record_translations_record_language_ci",
        table_name="record_translations",
        schema="catalog",
    )
    op.drop_table("record_translations", schema="catalog")
    op.drop_constraint(
        "chk_records_language_tag",
        "records",
        schema="catalog",
        type_="check",
    )
    op.execute(
        sa.text(
            """
            UPDATE catalog.records
            SET language = lower(split_part(language, '-', 1))
            WHERE length(language) > 10
            """
        )
    )
    op.alter_column(
        "records",
        "language",
        existing_type=sa.String(length=35),
        type_=sa.String(length=10),
        existing_nullable=True,
        schema="catalog",
    )
