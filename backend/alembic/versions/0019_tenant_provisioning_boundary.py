"""Install the least-privilege tenant data-plane provisioning boundary.

Tenant schemas and per-tenant reader roles are dynamic, but the authority to
create and remove them must not live on an API or worker login.  This migration
creates a dedicated NOLOGIN/CREATEROLE owner and two SECURITY DEFINER
functions.  Runtime callers receive EXECUTE through a separate control group;
writers receive only data-schema privileges; sandbox and tile consumers receive
SET-only membership paths to each tenant reader role.

Revision ID: 0019_tenant_provisioning_boundary
Revises: 0018_tenant_insert_stamping
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0019_tenant_provisioning_boundary"
down_revision: Union[str, None] = "0018_tenant_insert_stamping"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROVISIONER = "geolens_tenant_provisioner"
_CONTROL = "geolens_tenant_control"
_WRITER = "geolens_tenant_writer"
_SANDBOX = "geolens_tenant_sandbox"
_TILE = "geolens_tile_gateway"


def _create_and_validate_cluster_roles() -> None:
    """Create the fixed role topology and reject unsafe name collisions."""
    op.execute(
        """
        SELECT pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended('geolens:tenant-role-bootstrap', 0)
        )
        """
    )
    op.execute(
        f"""
        DO $$
        DECLARE
            role_row record;
            group_name text;
            membership_row record;
            direct_membership_unsafe boolean;
        BEGIN
            SELECT * INTO role_row
            FROM pg_catalog.pg_roles
            WHERE rolname = '{_PROVISIONER}';

            IF NOT FOUND THEN
                CREATE ROLE {_PROVISIONER}
                    NOLOGIN NOSUPERUSER NOCREATEDB CREATEROLE NOINHERIT
                    NOREPLICATION NOBYPASSRLS;
            ELSIF role_row.rolcanlogin
               OR role_row.rolsuper
               OR role_row.rolcreatedb
               OR NOT role_row.rolcreaterole
               OR role_row.rolinherit
               OR role_row.rolreplication
               OR role_row.rolbypassrls THEN
                RAISE EXCEPTION
                    'existing role {_PROVISIONER} has unsafe attributes';
            END IF;

            FOREACH group_name IN ARRAY ARRAY[
                '{_CONTROL}', '{_WRITER}', '{_SANDBOX}', '{_TILE}'
            ] LOOP
                IF NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_roles
                    WHERE rolname = group_name
                ) THEN
                    EXECUTE pg_catalog.format(
                        'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB '
                        'NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
                        group_name
                    );
                END IF;
            END LOOP;

            FOR role_row IN
                SELECT * FROM pg_catalog.pg_roles
                WHERE rolname IN ('{_CONTROL}', '{_WRITER}', '{_SANDBOX}', '{_TILE}')
            LOOP
                IF role_row.rolcanlogin
                   OR role_row.rolsuper
                   OR role_row.rolcreatedb
                   OR role_row.rolcreaterole
                   OR role_row.rolinherit
                   OR role_row.rolreplication
                   OR role_row.rolbypassrls THEN
                    RAISE EXCEPTION
                        'existing role % has unsafe attributes', role_row.rolname;
                END IF;
            END LOOP;

            IF (
                SELECT pg_catalog.count(*)
                FROM pg_catalog.pg_roles
                WHERE rolname IN ('{_CONTROL}', '{_WRITER}', '{_SANDBOX}', '{_TILE}')
            ) <> 4 THEN
                RAISE EXCEPTION 'tenant role topology is incomplete';
            END IF;

            -- Reserved role names must not arrive with hidden privilege paths.
            -- The migration role may hold the automatic ADMIN membership that
            -- PostgreSQL grants to a role creator. Safe LOGIN members of the
            -- fixed gateways are retained so downgrade -> re-upgrade works on a
            -- deployed cluster without deleting operator-managed credentials.
            FOR membership_row IN
                SELECT granted_role.rolname AS granted_name,
                       member_role.rolname AS member_name,
                       membership.roleid AS granted_oid,
                       membership.member AS member_oid,
                       membership.admin_option AS membership_admin,
                       member_role.*
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted_role
                  ON granted_role.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role
                  ON member_role.oid = membership.member
                WHERE granted_role.rolname IN (
                    '{_PROVISIONER}', '{_CONTROL}', '{_WRITER}',
                    '{_SANDBOX}', '{_TILE}'
                )
            LOOP
                IF membership_row.member_name = CURRENT_USER THEN
                    CONTINUE;
                END IF;

                direct_membership_unsafe := membership_row.membership_admin;
                IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
                    EXECUTE
                        'SELECT membership.admin_option OR CASE WHEN $3 = $4 '
                        'THEN NOT membership.inherit_option OR membership.set_option '
                        'ELSE membership.inherit_option OR NOT membership.set_option '
                        'END '
                        'FROM pg_catalog.pg_auth_members AS membership '
                        'WHERE membership.roleid = $1 AND membership.member = $2'
                        INTO direct_membership_unsafe
                        USING membership_row.granted_oid,
                              membership_row.member_oid,
                              membership_row.granted_name,
                              '{_CONTROL}';
                END IF;

                IF direct_membership_unsafe
                   OR membership_row.granted_name = '{_PROVISIONER}'
                   OR NOT membership_row.rolcanlogin
                   OR membership_row.rolsuper
                   OR membership_row.rolcreatedb
                   OR membership_row.rolcreaterole
                   OR membership_row.rolreplication
                   OR membership_row.rolbypassrls
                   OR EXISTS (
                       SELECT 1
                       FROM pg_catalog.pg_roles AS powerful_role
                       WHERE (
                           powerful_role.rolsuper
                           OR powerful_role.rolcreatedb
                           OR powerful_role.rolcreaterole
                           OR powerful_role.rolreplication
                           OR powerful_role.rolbypassrls
                       )
                         AND pg_catalog.pg_has_role(
                             membership_row.member_name,
                             powerful_role.oid,
                             'MEMBER'
                         )
                   )
                   OR (
                       membership_row.granted_name = '{_TILE}'
                       AND EXISTS (
                           SELECT 1
                           FROM pg_catalog.pg_roles AS application_gateway
                           WHERE application_gateway.rolname IN (
                               '{_CONTROL}', '{_WRITER}', '{_SANDBOX}'
                           )
                             AND pg_catalog.pg_has_role(
                                 membership_row.member_name,
                                 application_gateway.oid,
                                 'MEMBER'
                             )
                       )
                   )
                   OR (
                       membership_row.granted_name IN (
                           '{_CONTROL}', '{_WRITER}', '{_SANDBOX}'
                       )
                       AND EXISTS (
                           SELECT 1
                           FROM pg_catalog.pg_roles AS tile_gateway
                           WHERE tile_gateway.rolname = '{_TILE}'
                             AND pg_catalog.pg_has_role(
                                 membership_row.member_name,
                                 tile_gateway.oid,
                                 'MEMBER'
                             )
                       )
                   ) THEN
                    RAISE EXCEPTION
                        'reserved role % has unsafe direct member %',
                        membership_row.granted_name,
                        membership_row.member_name;
                END IF;
            END LOOP;

            -- A reserved role being a member OF another role creates an
            -- escalation path. Only the three SET-only/maintenance roles may
            -- be upstream members of strictly named tenant readers left by an
            -- interrupted/backfill migration.
            FOR membership_row IN
                SELECT member_role.rolname AS member_name,
                       upstream_role.rolname AS upstream_name,
                       upstream_role.*
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS member_role
                  ON member_role.oid = membership.member
                JOIN pg_catalog.pg_roles AS upstream_role
                  ON upstream_role.oid = membership.roleid
                WHERE member_role.rolname IN (
                    '{_PROVISIONER}', '{_CONTROL}', '{_WRITER}',
                    '{_SANDBOX}', '{_TILE}'
                )
            LOOP
                IF membership_row.member_name IN ('{_CONTROL}')
                   OR (
                       membership_row.member_name IN ('{_SANDBOX}', '{_TILE}')
                       AND membership_row.upstream_name !~
                           '^geolens_reader_t_[0-9a-f]{{8}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{12}}$'
                   )
                   OR (
                       membership_row.member_name = '{_WRITER}'
                       AND membership_row.upstream_name !~
                           '^geolens_writer_t_[0-9a-f]{{8}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{12}}$'
                   )
                   OR (
                       membership_row.member_name = '{_PROVISIONER}'
                       AND membership_row.upstream_name !~
                           '^geolens_(reader|writer)_t_[0-9a-f]{{8}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{12}}$'
                   )
                   OR membership_row.rolcanlogin
                   OR membership_row.rolsuper
                   OR membership_row.rolcreatedb
                   OR membership_row.rolcreaterole
                   OR membership_row.rolinherit
                   OR membership_row.rolreplication
                   OR membership_row.rolbypassrls
                   OR EXISTS (
                       SELECT 1
                       FROM pg_catalog.pg_auth_members AS chained
                       WHERE chained.member = membership_row.oid
                   ) THEN
                    RAISE EXCEPTION
                        'reserved role % has unsafe upstream membership in %',
                        membership_row.member_name,
                        membership_row.upstream_name;
                END IF;
            END LOOP;
        END
        $$
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            EXECUTE pg_catalog.format(
                'GRANT CREATE ON DATABASE %I TO {_PROVISIONER}',
                pg_catalog.current_database()
            );
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA catalog TO {_PROVISIONER}")
    op.execute(f"GRANT SELECT ON TABLE catalog.tenants TO {_PROVISIONER}")


def _create_functions() -> None:
    op.execute(
        f"""
        CREATE FUNCTION catalog.provision_tenant_data_schema(p_tenant_id uuid)
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

            -- PostgreSQL automatically grants the creating role ADMIN with
            -- non-inherited/non-SET membership. Existing roles are adopted by
            -- the migration before this function is called. Re-GRANTing ADMIN
            -- to the grantor is rejected by PostgreSQL, so validate instead.
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
                -- Before PostgreSQL 16, NOINHERIT on the fixed gateway roles
                -- supplies the same SET-only behavior.
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
            EXECUTE pg_catalog.format(
                'GRANT USAGE, CREATE ON SCHEMA %I TO %I',
                schema_name,
                writer_name
            );
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

    op.execute(
        f"""
        CREATE FUNCTION catalog.deprovision_tenant_data_schema(p_tenant_id uuid)
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
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'geolens:tenant-data-plane:' || p_tenant_id::text,
                    0
                )
            );

            IF EXISTS (
                SELECT 1 FROM catalog.tenants WHERE id = p_tenant_id
            ) THEN
                RAISE EXCEPTION
                    'refusing to deprovision active tenant %', p_tenant_id
                    USING ERRCODE = '55000';
            END IF;

            SELECT owner_role.rolname INTO schema_owner
            FROM pg_catalog.pg_namespace AS namespace
            JOIN pg_catalog.pg_roles AS owner_role
              ON owner_role.oid = namespace.nspowner
            WHERE namespace.nspname = schema_name;

            IF schema_owner IS NOT NULL AND schema_owner <> '{_PROVISIONER}' THEN
                RAISE EXCEPTION
                    'refusing to drop schema % owned by %; expected {_PROVISIONER}',
                    schema_name,
                    schema_owner;
            END IF;

            SELECT * INTO reader_row
            FROM pg_catalog.pg_roles
            WHERE rolname = reader_name;
            reader_exists := FOUND;
            IF reader_exists AND (
                reader_row.rolcanlogin
                OR reader_row.rolsuper
                OR reader_row.rolcreatedb
                OR reader_row.rolcreaterole
                OR reader_row.rolinherit
                OR reader_row.rolreplication
                OR reader_row.rolbypassrls
            ) THEN
                RAISE EXCEPTION
                    'refusing to drop unsafe tenant reader role %', reader_name;
            END IF;

            SELECT * INTO writer_row
            FROM pg_catalog.pg_roles
            WHERE rolname = writer_name;
            writer_exists := FOUND;
            IF writer_exists AND (
                writer_row.rolcanlogin
                OR writer_row.rolsuper
                OR writer_row.rolcreatedb
                OR writer_row.rolcreaterole
                OR writer_row.rolinherit
                OR writer_row.rolreplication
                OR writer_row.rolbypassrls
            ) THEN
                RAISE EXCEPTION
                    'refusing to drop unsafe tenant writer role %', writer_name;
            END IF;

            EXECUTE pg_catalog.format('DROP SCHEMA IF EXISTS %I CASCADE', schema_name);
            IF reader_exists THEN
                EXECUTE pg_catalog.format('DROP ROLE %I', reader_name);
            END IF;
            IF writer_exists THEN
                EXECUTE pg_catalog.format('DROP ROLE %I', writer_name);
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "ALTER FUNCTION catalog.deprovision_tenant_data_schema(uuid) "
        f"OWNER TO {_PROVISIONER}"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION catalog.deprovision_tenant_data_schema(uuid) "
        "FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION catalog.deprovision_tenant_data_schema(uuid) "
        f"TO {_CONTROL}"
    )


def _adopt_and_backfill_existing_tenants() -> None:
    """Move old runtime-owned schemas/roles under the migration boundary."""
    op.execute(
        f"""
        DO $$
        DECLARE
            tenant_row record;
            object_row record;
            legacy_member_row record;
            default_acl_row record;
            schema_name text;
            reader_name text;
            writer_name text;
            reader_row record;
            reader_exists boolean;
            writer_row record;
            writer_exists boolean;
            temporary_writer_membership boolean;
        BEGIN
            FOR tenant_row IN
                SELECT id FROM catalog.tenants ORDER BY id
            LOOP
                schema_name := 'data_t_' ||
                    pg_catalog.replace(tenant_row.id::text, '-', '_');
                reader_name := 'geolens_reader_t_' ||
                    pg_catalog.replace(tenant_row.id::text, '-', '_');
                writer_name := 'geolens_writer_t_' ||
                    pg_catalog.replace(tenant_row.id::text, '-', '_');

                SELECT * INTO reader_row
                FROM pg_catalog.pg_roles
                WHERE rolname = reader_name;
                reader_exists := FOUND;
                IF reader_exists AND (
                    reader_row.rolcanlogin
                    OR reader_row.rolsuper
                    OR reader_row.rolcreatedb
                    OR reader_row.rolcreaterole
                    OR reader_row.rolreplication
                    OR reader_row.rolbypassrls
                ) THEN
                    RAISE EXCEPTION
                        'existing tenant reader role % has unsafe attributes',
                        reader_name;
                END IF;
                IF reader_exists AND reader_row.rolinherit THEN
                    EXECUTE pg_catalog.format(
                        'ALTER ROLE %I NOINHERIT', reader_name
                    );
                END IF;

                -- The pre-0019 runtime helper created readers with the default
                -- INHERIT flag, an automatic creator membership, and an ALTER
                -- DEFAULT PRIVILEGES entry. Normalize that known legacy shape
                -- before the strict provision function validates the role.
                FOR legacy_member_row IN
                    SELECT member_role.rolname AS member_name
                    FROM pg_catalog.pg_auth_members AS membership
                    JOIN pg_catalog.pg_roles AS granted_role
                      ON granted_role.oid = membership.roleid
                    JOIN pg_catalog.pg_roles AS member_role
                      ON member_role.oid = membership.member
                    WHERE granted_role.rolname = reader_name
                      AND member_role.rolname NOT IN (
                          '{_PROVISIONER}', '{_SANDBOX}', '{_TILE}'
                      )
                LOOP
                    EXECUTE pg_catalog.format(
                        'REVOKE %I FROM %I',
                        reader_name,
                        legacy_member_row.member_name
                    );
                END LOOP;

                FOR default_acl_row IN
                    SELECT DISTINCT owner_role.rolname AS owner_name
                    FROM pg_catalog.pg_default_acl AS default_acl
                    JOIN pg_catalog.pg_roles AS owner_role
                      ON owner_role.oid = default_acl.defaclrole
                    JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) AS acl
                      ON true
                    JOIN pg_catalog.pg_roles AS grantee_role
                      ON grantee_role.oid = acl.grantee
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = default_acl.defaclnamespace
                    WHERE namespace.nspname = schema_name
                      AND default_acl.defaclobjtype = 'r'
                      AND grantee_role.rolname = reader_name
                LOOP
                    EXECUTE pg_catalog.format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I '
                        'REVOKE ALL ON TABLES FROM %I',
                        default_acl_row.owner_name,
                        schema_name,
                        reader_name
                    );
                END LOOP;

                SELECT * INTO writer_row
                FROM pg_catalog.pg_roles
                WHERE rolname = writer_name;
                writer_exists := FOUND;
                IF writer_exists AND (
                    writer_row.rolcanlogin
                    OR writer_row.rolsuper
                    OR writer_row.rolcreatedb
                    OR writer_row.rolcreaterole
                    OR writer_row.rolinherit
                    OR writer_row.rolreplication
                    OR writer_row.rolbypassrls
                ) THEN
                    RAISE EXCEPTION
                        'existing tenant writer role % has unsafe attributes',
                        writer_name;
                END IF;

                IF EXISTS (
                    SELECT 1 FROM pg_catalog.pg_namespace
                    WHERE nspname = schema_name
                ) THEN
                    EXECUTE pg_catalog.format(
                        'ALTER SCHEMA %I OWNER TO {_PROVISIONER}', schema_name
                    );
                END IF;

                IF reader_exists AND NOT EXISTS (
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
                    IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
                        EXECUTE pg_catalog.format(
                            'GRANT %I TO {_PROVISIONER} '
                            'WITH ADMIN TRUE, INHERIT FALSE, SET FALSE',
                            reader_name
                        );
                    ELSE
                        EXECUTE pg_catalog.format(
                            'GRANT %I TO {_PROVISIONER} WITH ADMIN OPTION',
                            reader_name
                        );
                    END IF;
                END IF;

                IF writer_exists AND NOT EXISTS (
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
                    IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
                        EXECUTE pg_catalog.format(
                            'GRANT %I TO {_PROVISIONER} '
                            'WITH ADMIN TRUE, INHERIT FALSE, SET FALSE',
                            writer_name
                        );
                    ELSE
                        EXECUTE pg_catalog.format(
                            'GRANT %I TO {_PROVISIONER} WITH ADMIN OPTION',
                            writer_name
                        );
                    END IF;
                END IF;

                -- The provisioning function runs as the provisioner. Adopt
                -- legacy relations temporarily so it can revoke/re-grant their
                -- ACLs without relying on privileges of the old shared owner.
                FOR object_row IN
                    SELECT relation.relname, relation.relkind
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = schema_name
                      AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
                    ORDER BY relation.relkind, relation.relname
                LOOP
                    IF object_row.relkind = 'S' THEN
                        EXECUTE pg_catalog.format(
                            'ALTER SEQUENCE %I.%I OWNER TO {_PROVISIONER}',
                            schema_name,
                            object_row.relname
                        );
                    ELSE
                        EXECUTE pg_catalog.format(
                            'ALTER TABLE %I.%I OWNER TO {_PROVISIONER}',
                            schema_name,
                            object_row.relname
                        );
                    END IF;
                END LOOP;

                PERFORM catalog.provision_tenant_data_schema(tenant_row.id);

                -- Legacy data objects were commonly owned by the old shared
                -- runtime login. Mere GRANT ALL is insufficient for owner-only
                -- ALTER/DROP operations, so adopt every tenant relation into
                -- the per-tenant writer role. The migration login receives a
                -- transaction-scoped direct SET edge only while performing the
                -- ownership transfer; that edge is removed before commit.
                temporary_writer_membership := NOT EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_auth_members AS membership
                    JOIN pg_catalog.pg_roles AS granted_role
                      ON granted_role.oid = membership.roleid
                    JOIN pg_catalog.pg_roles AS member_role
                      ON member_role.oid = membership.member
                    WHERE granted_role.rolname = writer_name
                      AND member_role.rolname = CURRENT_USER
                );
                IF temporary_writer_membership THEN
                    IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
                        EXECUTE pg_catalog.format(
                            'GRANT %I TO %I WITH INHERIT FALSE, SET TRUE',
                            writer_name,
                            CURRENT_USER
                        );
                    ELSE
                        EXECUTE pg_catalog.format(
                            'GRANT %I TO %I', writer_name, CURRENT_USER
                        );
                    END IF;
                END IF;

                FOR object_row IN
                    SELECT relation.relname, relation.relkind
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = schema_name
                      AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
                    ORDER BY relation.relkind, relation.relname
                LOOP
                    IF object_row.relkind = 'S' THEN
                        EXECUTE pg_catalog.format(
                            'ALTER SEQUENCE %I.%I OWNER TO %I',
                            schema_name,
                            object_row.relname,
                            writer_name
                        );
                    ELSE
                        EXECUTE pg_catalog.format(
                            'ALTER TABLE %I.%I OWNER TO %I',
                            schema_name,
                            object_row.relname,
                            writer_name
                        );
                    END IF;
                END LOOP;

                IF EXISTS (
                    SELECT 1
                    FROM pg_catalog.pg_class AS relation
                    JOIN pg_catalog.pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    JOIN pg_catalog.pg_roles AS owner_role
                      ON owner_role.oid = relation.relowner
                    WHERE namespace.nspname = schema_name
                      AND relation.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
                      AND owner_role.rolname <> writer_name
                ) THEN
                    RAISE EXCEPTION
                        'tenant schema % contains relation not owned by %',
                        schema_name,
                        writer_name;
                END IF;

                IF temporary_writer_membership THEN
                    EXECUTE pg_catalog.format(
                        'REVOKE %I FROM %I', writer_name, CURRENT_USER
                    );
                END IF;
            END LOOP;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_and_validate_cluster_roles()
    _create_functions()
    _adopt_and_backfill_existing_tenants()


def downgrade() -> None:
    """Remove the callable boundary but retain shared cluster roles/data."""
    op.execute("DROP FUNCTION IF EXISTS catalog.deprovision_tenant_data_schema(uuid)")
    op.execute("DROP FUNCTION IF EXISTS catalog.provision_tenant_data_schema(uuid)")
    op.execute(
        f"""
        DO $$
        BEGIN
            -- A dump restored into a fresh cluster contains database objects,
            -- but not cluster roles. Keep downgrade usable there so operators
            -- can run 0018 -> 0019 to reconstruct the guarded role topology.
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles
                WHERE rolname = '{_PROVISIONER}'
            ) THEN
                REVOKE SELECT ON TABLE catalog.tenants FROM {_PROVISIONER};
                REVOKE USAGE ON SCHEMA catalog FROM {_PROVISIONER};
                EXECUTE pg_catalog.format(
                    'REVOKE CREATE ON DATABASE %I FROM {_PROVISIONER}',
                    pg_catalog.current_database()
                );
            END IF;
        END
        $$
        """
    )
    # Cluster roles and tenant reader memberships are intentionally retained.
    # Other databases in the same cluster may still depend on them, and the
    # downgrade must never remove tenant data or silently widen access.
