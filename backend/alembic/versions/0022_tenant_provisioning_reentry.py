"""Make tenant substrate provisioning safely repeatable after data creation.

Tenant data relations are owned by the per-tenant writer role.  The tenant
provisioner deliberately has ADMIN-only, non-SET membership in that role, so it
cannot and must not rewrite ACLs on writer-owned relations.  The original
provisioning function nevertheless attempted schema-wide table and sequence
grants on every call.  A legitimate retry therefore failed as soon as the
writer had created the first relation.

Provisioning now reconciles only the substrate it owns: the schema, tenant
roles, gateway memberships, and schema privileges.  Object creators and
restore paths remain responsible for explicit reader grants on each relation.
Downgrade reinstates the legacy object-ACL reconciliation exactly.

Revision ID: 0022_tenant_provisioning_reentry
Revises: 0021_tenant_slug_unique
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0022_tenant_provisioning_reentry"
down_revision: Union[str, None] = "0021_tenant_slug_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROVISIONER = "geolens_tenant_provisioner"
_CONTROL = "geolens_tenant_control"
_WRITER = "geolens_tenant_writer"
_SANDBOX = "geolens_tenant_sandbox"
_TILE = "geolens_tile_gateway"


def _install_provision_function(*, reconcile_existing_objects: bool) -> None:
    """Install the provisioner contract for upgrade or downgrade."""
    reader_object_acl_sql = ""
    writer_object_acl_sql = ""
    if reconcile_existing_objects:
        reader_object_acl_sql = """
            EXECUTE pg_catalog.format(
                'GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I',
                schema_name,
                reader_name
            );
            EXECUTE pg_catalog.format(
                'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I',
                schema_name,
                reader_name
            );
        """
        writer_object_acl_sql = """
            EXECUTE pg_catalog.format(
                'GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I TO %I',
                schema_name,
                writer_name
            );
            EXECUTE pg_catalog.format(
                'GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %I TO %I',
                schema_name,
                writer_name
            );
        """

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION catalog.provision_tenant_data_schema(p_tenant_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $$
        DECLARE
            schema_name text := 'data_t_' || pg_catalog.replace(p_tenant_id::text, '-', '_');
            reader_name text := 'geolens_reader_t_' || pg_catalog.replace(p_tenant_id::text, '-', '_');
            writer_name text := 'geolens_writer_t_' || pg_catalog.replace(p_tenant_id::text, '-', '_');
            reader_row record;
            reader_exists boolean;
            writer_row record;
            writer_exists boolean;
            schema_owner text;
            unexpected_member text;
            upstream_role text;
            owner_membership_unsafe boolean;
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'geolens:tenant-data-plane:' || p_tenant_id::text,
                    0
                )
            );

            PERFORM 1
            FROM catalog.tenants
            WHERE id = p_tenant_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'tenant % does not exist', p_tenant_id
                    USING ERRCODE = '23503';
            END IF;

            SELECT owner_role.rolname INTO schema_owner
            FROM pg_catalog.pg_namespace AS namespace
            JOIN pg_catalog.pg_roles AS owner_role
              ON owner_role.oid = namespace.nspowner
            WHERE namespace.nspname = schema_name;

            IF schema_owner IS NULL THEN
                EXECUTE pg_catalog.format(
                    'CREATE SCHEMA %I AUTHORIZATION {_PROVISIONER}',
                    schema_name
                );
            ELSIF schema_owner <> '{_PROVISIONER}' THEN
                RAISE EXCEPTION
                    'existing schema % has unsafe owner %; expected {_PROVISIONER}',
                    schema_name,
                    schema_owner;
            END IF;

            SELECT * INTO reader_row
            FROM pg_catalog.pg_roles
            WHERE rolname = reader_name;
            reader_exists := FOUND;

            IF NOT reader_exists THEN
                EXECUTE pg_catalog.format(
                    'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                    'NOINHERIT NOREPLICATION NOBYPASSRLS',
                    reader_name
                );
                SELECT * INTO reader_row
                FROM pg_catalog.pg_roles
                WHERE rolname = reader_name;
                reader_exists := true;
            END IF;

            IF reader_row.rolcanlogin
               OR reader_row.rolsuper
               OR reader_row.rolcreatedb
               OR reader_row.rolcreaterole
               OR reader_row.rolinherit
               OR reader_row.rolreplication
               OR reader_row.rolbypassrls THEN
                RAISE EXCEPTION
                    'existing tenant reader role % has unsafe attributes',
                    reader_name;
            END IF;

            SELECT granted_role.rolname INTO upstream_role
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted_role
              ON granted_role.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member_role
              ON member_role.oid = membership.member
            WHERE member_role.rolname = reader_name
            LIMIT 1;
            IF upstream_role IS NOT NULL THEN
                RAISE EXCEPTION
                    'tenant reader role % has unsafe upstream membership in %',
                    reader_name,
                    upstream_role;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted_role
                  ON granted_role.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role
                  ON member_role.oid = membership.member
                WHERE granted_role.rolname = reader_name
                  AND member_role.rolname = '{_PROVISIONER}'
                  AND membership.admin_option
            ) THEN
                RAISE EXCEPTION
                    'tenant provisioner lacks ADMIN on reader role %', reader_name;
            END IF;
            IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
                EXECUTE
                    'SELECT NOT membership.admin_option '
                    'OR membership.inherit_option OR membership.set_option '
                    'FROM pg_catalog.pg_auth_members AS membership '
                    'JOIN pg_catalog.pg_roles AS granted_role '
                    'ON granted_role.oid = membership.roleid '
                    'JOIN pg_catalog.pg_roles AS member_role '
                    'ON member_role.oid = membership.member '
                    'WHERE granted_role.rolname = $1 '
                    'AND member_role.rolname = $2'
                    INTO owner_membership_unsafe
                    USING reader_name, '{_PROVISIONER}';
                IF owner_membership_unsafe THEN
                    RAISE EXCEPTION
                        'tenant provisioner membership in % is not ADMIN-only',
                        reader_name;
                END IF;
            END IF;

            SELECT member_role.rolname INTO unexpected_member
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted_role
              ON granted_role.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member_role
              ON member_role.oid = membership.member
            WHERE granted_role.rolname = reader_name
              AND member_role.rolname NOT IN (
                  '{_PROVISIONER}', '{_SANDBOX}', '{_TILE}'
              )
            LIMIT 1;
            IF unexpected_member IS NOT NULL THEN
                RAISE EXCEPTION
                    'tenant reader role % has unexpected direct member %',
                    reader_name,
                    unexpected_member;
            END IF;

            IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
                EXECUTE pg_catalog.format(
                    'GRANT %I TO {_SANDBOX} '
                    'WITH INHERIT FALSE, SET TRUE',
                    reader_name
                );
                EXECUTE pg_catalog.format(
                    'GRANT %I TO {_TILE} '
                    'WITH INHERIT FALSE, SET TRUE',
                    reader_name
                );
            ELSE
                EXECUTE pg_catalog.format('GRANT %I TO {_SANDBOX}', reader_name);
                EXECUTE pg_catalog.format('GRANT %I TO {_TILE}', reader_name);
            END IF;

            SELECT * INTO writer_row
            FROM pg_catalog.pg_roles
            WHERE rolname = writer_name;
            writer_exists := FOUND;
            IF NOT writer_exists THEN
                EXECUTE pg_catalog.format(
                    'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                    'NOINHERIT NOREPLICATION NOBYPASSRLS',
                    writer_name
                );
                SELECT * INTO writer_row
                FROM pg_catalog.pg_roles
                WHERE rolname = writer_name;
                writer_exists := true;
            END IF;

            IF writer_row.rolcanlogin
               OR writer_row.rolsuper
               OR writer_row.rolcreatedb
               OR writer_row.rolcreaterole
               OR writer_row.rolinherit
               OR writer_row.rolreplication
               OR writer_row.rolbypassrls THEN
                RAISE EXCEPTION
                    'existing tenant writer role % has unsafe attributes',
                    writer_name;
            END IF;

            upstream_role := NULL;
            SELECT granted_role.rolname INTO upstream_role
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted_role
              ON granted_role.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member_role
              ON member_role.oid = membership.member
            WHERE member_role.rolname = writer_name
            LIMIT 1;
            IF upstream_role IS NOT NULL THEN
                RAISE EXCEPTION
                    'tenant writer role % has unsafe upstream membership in %',
                    writer_name,
                    upstream_role;
            END IF;

            IF NOT EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted_role
                  ON granted_role.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role
                  ON member_role.oid = membership.member
                WHERE granted_role.rolname = writer_name
                  AND member_role.rolname = '{_PROVISIONER}'
                  AND membership.admin_option
            ) THEN
                RAISE EXCEPTION
                    'tenant provisioner lacks ADMIN on writer role %', writer_name;
            END IF;
            IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
                EXECUTE
                    'SELECT NOT membership.admin_option '
                    'OR membership.inherit_option OR membership.set_option '
                    'FROM pg_catalog.pg_auth_members AS membership '
                    'JOIN pg_catalog.pg_roles AS granted_role '
                    'ON granted_role.oid = membership.roleid '
                    'JOIN pg_catalog.pg_roles AS member_role '
                    'ON member_role.oid = membership.member '
                    'WHERE granted_role.rolname = $1 '
                    'AND member_role.rolname = $2'
                    INTO owner_membership_unsafe
                    USING writer_name, '{_PROVISIONER}';
                IF owner_membership_unsafe THEN
                    RAISE EXCEPTION
                        'tenant provisioner membership in % is not ADMIN-only',
                        writer_name;
                END IF;
            END IF;

            unexpected_member := NULL;
            SELECT member_role.rolname INTO unexpected_member
            FROM pg_catalog.pg_auth_members AS membership
            JOIN pg_catalog.pg_roles AS granted_role
              ON granted_role.oid = membership.roleid
            JOIN pg_catalog.pg_roles AS member_role
              ON member_role.oid = membership.member
            WHERE granted_role.rolname = writer_name
              AND member_role.rolname NOT IN ('{_PROVISIONER}', '{_WRITER}')
            LIMIT 1;
            IF unexpected_member IS NOT NULL THEN
                RAISE EXCEPTION
                    'tenant writer role % has unexpected direct member %',
                    writer_name,
                    unexpected_member;
            END IF;

            IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
                EXECUTE pg_catalog.format(
                    'GRANT %I TO {_WRITER} WITH INHERIT FALSE, SET TRUE',
                    writer_name
                );
            ELSE
                EXECUTE pg_catalog.format('GRANT %I TO {_WRITER}', writer_name);
            END IF;

            EXECUTE pg_catalog.format(
                'REVOKE ALL ON SCHEMA %I FROM PUBLIC', schema_name
            );
            EXECUTE pg_catalog.format(
                'GRANT USAGE ON SCHEMA %I TO %I', schema_name, reader_name
            );
            {reader_object_acl_sql}
            EXECUTE pg_catalog.format(
                'GRANT USAGE, CREATE ON SCHEMA %I TO %I',
                schema_name,
                writer_name
            );
            {writer_object_acl_sql}
        END;
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION catalog.provision_tenant_data_schema(uuid) "
        f"OWNER TO {_PROVISIONER}"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION catalog.provision_tenant_data_schema(uuid) FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION catalog.provision_tenant_data_schema(uuid) "
        f"TO {_CONTROL}"
    )


def upgrade() -> None:
    _install_provision_function(reconcile_existing_objects=False)


def downgrade() -> None:
    _install_provision_function(reconcile_existing_objects=True)
