"""Make tenant host slugs a globally unique routing key.

Every hosted request resolves ``{slug}.TENANT_BASE_DOMAIN`` through
``catalog.tenants`` before setting the RLS tenant GUC.  Duplicate slugs would
make that security boundary nondeterministic, so the invariant belongs beside
the Core host resolver rather than only in a Cloud service check.

The diagnostic runs before replacing the original non-unique index and names
the duplicate values that an operator must repair.  ``IF NOT EXISTS`` adopts
the same index created by older Cloud c002 deployments during a rolling
cross-repository upgrade.

Revision ID: 0023_tenant_slug_unique
Revises: 0022_tenant_audit_job_isolation
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0023_tenant_slug_unique"
down_revision: Union[str, None] = "0022_tenant_audit_job_isolation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            duplicate_slugs text;
        BEGIN
            SELECT string_agg(format('%L (%s rows)', slug, row_count), ', ')
            INTO duplicate_slugs
            FROM (
                SELECT slug, count(*) AS row_count
                FROM catalog.tenants
                GROUP BY slug
                HAVING count(*) > 1
                ORDER BY slug
                LIMIT 20
            ) AS duplicates;

            IF duplicate_slugs IS NOT NULL THEN
                RAISE EXCEPTION
                    'cannot make tenant routing slugs unique; duplicates: %',
                    duplicate_slugs
                    USING ERRCODE = '23505',
                          HINT = 'Rename or merge duplicate catalog.tenants rows before retrying the migration.';
            END IF;
        END;
        $$
        """
    )
    op.execute("DROP INDEX IF EXISTS catalog.ix_tenants_slug")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenants_slug ON catalog.tenants (slug)"
    )
    # IF NOT EXISTS may encounter an incorrectly shaped pre-existing index.
    # Verify the actual catalog invariant instead of trusting its name.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_class AS index_relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = index_relation.relnamespace
                JOIN pg_catalog.pg_index AS index_info
                  ON index_info.indexrelid = index_relation.oid
                JOIN pg_catalog.pg_class AS table_relation
                  ON table_relation.oid = index_info.indrelid
                JOIN pg_catalog.pg_namespace AS table_namespace
                  ON table_namespace.oid = table_relation.relnamespace
                WHERE namespace.nspname = 'catalog'
                  AND index_relation.relname = 'uq_tenants_slug'
                  AND table_namespace.nspname = 'catalog'
                  AND table_relation.relname = 'tenants'
                  AND index_info.indisunique
                  AND index_info.indnkeyatts = 1
                  AND pg_catalog.pg_get_indexdef(index_relation.oid)
                      LIKE '%(slug)%'
            ) THEN
                RAISE EXCEPTION
                    'catalog.uq_tenants_slug exists but is not the required unique tenants(slug) index'
                    USING ERRCODE = '55000';
            END IF;
        END;
        $$
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS catalog.uq_tenants_slug")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tenants_slug ON catalog.tenants (slug)")
