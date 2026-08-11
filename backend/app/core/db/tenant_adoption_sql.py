"""DDL ported from migration 0019, runnable at the current head schema.

Split out of :mod:`app.core.db.tenant_adoption` so the tool and the ported DDL
stay separately readable — these blocks are a faithful port of
``_create_and_validate_cluster_roles`` and
``_adopt_and_backfill_existing_tenants`` in
``backend/alembic/versions/0019_tenant_provisioning_boundary.py``, and they are
reviewed against that file rather than against the surrounding Python.

Historical migrations must stay self-contained, so this is a port, not an
import.  Two deliberate divergences from 0019, both because the head schema
moved (#998):

- 0019 parked every tenant relation on the provisioner so its provisioning
  function could rewrite their ACLs.  Migration 0024 removed that object-ACL
  pass, so relations move straight to the per-tenant writer and the reader's
  per-relation ``SELECT`` is granted by the writer, which is the contract
  ingest already follows.
- Every step is gated on the gap it closes, so an already-adopted tenant
  issues no DDL at all.  0019 ran once, inside a migration; this runs whenever
  an operator needs it.
"""

from __future__ import annotations

#: The fixed cluster role topology installed by 0019.  Cluster roles are not
#: carried by a database dump; on a fresh cluster they arrive from a globals
#: dump, or from :func:`app.core.db.tenant_adoption.ensure_cluster_roles`.
PROVISIONER = "geolens_tenant_provisioner"
CONTROL = "geolens_tenant_control"
WRITER = "geolens_tenant_writer"
SANDBOX = "geolens_tenant_sandbox"
TILE = "geolens_tile_gateway"

#: Transaction-local GUC carrying the tenant id into the adoption block, so no
#: identifier or value is ever interpolated into SQL.
TENANT_GUC = "geolens.adoption_tenant_id"

#: Relation kinds a tenant data schema can hold: tables, partitioned tables,
#: views, materialized views, foreign tables, sequences.
_RELATION_KINDS = "'r', 'p', 'v', 'm', 'f', 'S'"

#: The ADMIN-only membership shape the provisioning function demands: ``ADMIN``,
#: and on PostgreSQL 16+ neither ``INHERIT`` nor ``SET``.
#:
#: ``admin_option`` alone is not enough to test.  A globals dump written by
#: PostgreSQL 13-15 carries ``GRANT … WITH ADMIN OPTION``, and replaying that on
#: 16+ lands ``SET TRUE`` — measured, not assumed — which
#: ``provision_tenant_data_schema`` rejects as "not ADMIN-only".  Re-issuing the
#: explicit three-option grant rewrites it in place.
#:
#: The options are read out of the row as jsonb because those columns arrived in
#: 16 and GeoLens supports 13 and up (README); naming them directly would be a
#: parse error on an older server, where ``admin_option`` is the whole story.
_MEMBERSHIP_ADMIN_ONLY = """(
              membership.admin_option
              AND (
                  NOT jsonb_exists(to_jsonb(membership), 'set_option')
                  OR NOT (
                      (to_jsonb(membership) ->> 'inherit_option')::boolean
                      OR (to_jsonb(membership) ->> 'set_option')::boolean
                  )
              )
          )"""

#: True for a sequence a column owns — ``serial`` (dependency ``a``) or an
#: identity column (dependency ``i``).  PostgreSQL refuses ``ALTER SEQUENCE …
#: OWNER TO`` on those ("cannot change owner of sequence") and instead moves
#: them with their table, so the transfer must skip them and let the ``ALTER
#: TABLE`` carry them.  0019 did not exclude them, which is why the ordinary
#: ``ogr2ogr`` output of a vector ingest — every ``ogc_fid`` serial — would
#: have stopped its adoption loop dead.
_COLUMN_OWNED_SEQUENCE = """(
          relation.relkind = 'S'
          AND EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend AS dependency
              WHERE dependency.classid = 'pg_class'::regclass
                AND dependency.objid = relation.oid
                AND dependency.refclassid = 'pg_class'::regclass
                AND dependency.deptype IN ('a', 'i')
          )
      )"""


# ---------------------------------------------------------------------------
# Cluster role topology (port of 0019 ``_create_and_validate_cluster_roles``)
# ---------------------------------------------------------------------------

#: Creates whatever is absent and nothing else.  Split from the validation half
#: (below) so the dry run can answer "would ``--apply`` refuse this cluster?"
#: by running the identical guard, read-only, instead of a second copy of it.
CLUSTER_ROLE_CREATE_SQL = f"""
DO $$
DECLARE
    group_name text;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('geolens:tenant-role-bootstrap', 0)
    );

    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{PROVISIONER}'
    ) THEN
        CREATE ROLE {PROVISIONER}
            NOLOGIN NOSUPERUSER NOCREATEDB CREATEROLE NOINHERIT
            NOREPLICATION NOBYPASSRLS;
    END IF;

    FOREACH group_name IN ARRAY ARRAY[
        '{CONTROL}', '{WRITER}', '{SANDBOX}', '{TILE}'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = group_name
        ) THEN
            EXECUTE pg_catalog.format(
                'CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB '
                'NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
                group_name
            );
        END IF;
    END LOOP;
END
$$
"""

#: Pure validation: reads the catalogs and raises, issuing no DDL of any kind.
CLUSTER_ROLE_VALIDATE_SQL = f"""
DO $$
DECLARE
    role_row record;
    membership_row record;
    direct_membership_unsafe boolean;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('geolens:tenant-role-bootstrap', 0)
    );

    SELECT * INTO role_row
    FROM pg_catalog.pg_roles
    WHERE rolname = '{PROVISIONER}';

    IF NOT FOUND THEN
        RAISE EXCEPTION 'role {PROVISIONER} is missing';
    ELSIF role_row.rolcanlogin
       OR role_row.rolsuper
       OR role_row.rolcreatedb
       OR NOT role_row.rolcreaterole
       OR role_row.rolinherit
       OR role_row.rolreplication
       OR role_row.rolbypassrls THEN
        RAISE EXCEPTION 'existing role {PROVISIONER} has unsafe attributes';
    END IF;

    FOR role_row IN
        SELECT * FROM pg_catalog.pg_roles
        WHERE rolname IN ('{CONTROL}', '{WRITER}', '{SANDBOX}', '{TILE}')
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
        WHERE rolname IN ('{CONTROL}', '{WRITER}', '{SANDBOX}', '{TILE}')
    ) <> 4 THEN
        RAISE EXCEPTION 'tenant role topology is incomplete';
    END IF;

    -- Reserved role names must not arrive with hidden privilege paths.  The
    -- adopting role may hold the automatic ADMIN membership PostgreSQL grants
    -- to a role creator.  Safe LOGIN members of the fixed gateways are retained
    -- so a globals replay that restored operator-managed credentials is not
    -- undone here.
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
            '{PROVISIONER}', '{CONTROL}', '{WRITER}', '{SANDBOX}', '{TILE}'
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
                      '{CONTROL}';
        END IF;

        IF direct_membership_unsafe
           OR membership_row.granted_name = '{PROVISIONER}'
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
                     membership_row.member_name, powerful_role.oid, 'MEMBER'
                 )
           )
           OR (
               membership_row.granted_name = '{TILE}'
               AND EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_roles AS application_gateway
                   WHERE application_gateway.rolname IN (
                       '{CONTROL}', '{WRITER}', '{SANDBOX}'
                   )
                     AND pg_catalog.pg_has_role(
                         membership_row.member_name,
                         application_gateway.oid,
                         'MEMBER'
                     )
               )
           )
           OR (
               membership_row.granted_name IN ('{CONTROL}', '{WRITER}', '{SANDBOX}')
               AND EXISTS (
                   SELECT 1
                   FROM pg_catalog.pg_roles AS tile_gateway
                   WHERE tile_gateway.rolname = '{TILE}'
                     AND pg_catalog.pg_has_role(
                         membership_row.member_name, tile_gateway.oid, 'MEMBER'
                     )
               )
           ) THEN
            RAISE EXCEPTION
                'reserved role % has unsafe direct member %',
                membership_row.granted_name,
                membership_row.member_name;
        END IF;
    END LOOP;

    -- A reserved role being a member OF another role creates an escalation
    -- path.  Only the three SET-only/maintenance roles may be upstream members
    -- of strictly named per-tenant roles.
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
            '{PROVISIONER}', '{CONTROL}', '{WRITER}', '{SANDBOX}', '{TILE}'
        )
    LOOP
        IF membership_row.member_name IN ('{CONTROL}')
           OR (
               membership_row.member_name IN ('{SANDBOX}', '{TILE}')
               AND membership_row.upstream_name !~
                   '^geolens_reader_t_[0-9a-f]{{8}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{12}}$'
           )
           OR (
               membership_row.member_name = '{WRITER}'
               AND membership_row.upstream_name !~
                   '^geolens_writer_t_[0-9a-f]{{8}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{4}}_[0-9a-f]{{12}}$'
           )
           OR (
               membership_row.member_name = '{PROVISIONER}'
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

#: Re-own and re-restrict the two migration-owned SECURITY DEFINER functions
#: after a ``pg_restore --no-owner --no-acl``.  Bodies are never touched.
#:
#: ``ALTER FUNCTION … OWNER TO`` wants two things PostgreSQL does not spell out
#: in the error message: the incoming owner must hold ``CREATE`` on the
#: containing schema, and the caller must hold the *privileges* of that owner,
#: not merely ``ADMIN`` on it.  A superuser migrator has both implicitly.  The
#: migrator this module documents — ``CREATEROLE`` plus authority over the
#: restored objects, which is what a managed provider hands out — has neither by
#: default, and would otherwise stop here with the restored functions still
#: owned by the restore login and still executable by ``PUBLIC``.
#:
#: The schema privilege is borrowed for the repair and given back before commit,
#: the same shape the per-tenant writer edge uses below; a database already in
#: the right state borrows nothing.  The role edge is *not* borrowed: rewriting
#: the operator's own membership in the provisioner would mean guessing what to
#: restore it to, so a caller without those privileges gets the exact ``GRANT``
#: to run instead.

SECURE_BOUNDARY_FUNCTIONS_SQL = f"""
DO $$
DECLARE
    routine_name text;
    temporary_schema_create boolean := false;
    repair_pending boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'catalog'
          AND routine.proname IN (
              'provision_tenant_data_schema', 'deprovision_tenant_data_schema'
          )
          AND routine.pronargs = 1
          AND routine.proargtypes[0] = 'uuid'::regtype
          AND (
              pg_catalog.pg_get_userbyid(routine.proowner) <> '{PROVISIONER}'
              OR pg_catalog.has_function_privilege('public', routine.oid, 'EXECUTE')
              OR NOT pg_catalog.has_function_privilege(
                  '{CONTROL}', routine.oid, 'EXECUTE'
              )
          )
    ) INTO repair_pending;

    IF NOT repair_pending THEN
        RETURN;
    END IF;

    IF NOT pg_catalog.pg_has_role(CURRENT_USER, '{PROVISIONER}', 'USAGE') THEN
        RAISE EXCEPTION
            'current role % does not hold the privileges of {PROVISIONER}, '
            'which PostgreSQL requires to give it ownership of the tenant '
            'boundary functions', CURRENT_USER
            USING HINT =
                'run GRANT {PROVISIONER} TO "' || CURRENT_USER ||
                '" WITH INHERIT TRUE, or adopt with a superuser migrator';
    END IF;

    IF NOT pg_catalog.has_schema_privilege('{PROVISIONER}', 'catalog', 'CREATE') THEN
        temporary_schema_create := true;
        GRANT CREATE ON SCHEMA catalog TO {PROVISIONER};
    END IF;

    FOREACH routine_name IN ARRAY ARRAY[
        'provision_tenant_data_schema', 'deprovision_tenant_data_schema'
    ] LOOP
        EXECUTE pg_catalog.format(
            'ALTER FUNCTION catalog.%I(uuid) OWNER TO {PROVISIONER}', routine_name
        );
        EXECUTE pg_catalog.format(
            'REVOKE ALL ON FUNCTION catalog.%I(uuid) FROM PUBLIC', routine_name
        );
        EXECUTE pg_catalog.format(
            'GRANT EXECUTE ON FUNCTION catalog.%I(uuid) TO {CONTROL}', routine_name
        );
    END LOOP;

    IF temporary_schema_create THEN
        REVOKE CREATE ON SCHEMA catalog FROM {PROVISIONER};
    END IF;
END
$$
"""

PROVISIONER_DATABASE_GRANT_SQL = f"""
DO $$
BEGIN
    EXECUTE pg_catalog.format(
        'GRANT CREATE ON DATABASE %I TO {PROVISIONER}',
        pg_catalog.current_database()
    );
END
$$
"""


# ---------------------------------------------------------------------------
# Per-tenant adoption (port of 0019 ``_adopt_and_backfill_existing_tenants``)
# ---------------------------------------------------------------------------

ADOPT_TENANT_SQL = f"""
DO $$
DECLARE
    tenant_id uuid := pg_catalog.current_setting('{TENANT_GUC}')::uuid;
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
    schema_owner text;
    pending_owner_transfer bigint;
    reader_privilege_gap bigint;
    temporary_writer_membership boolean := false;
BEGIN
    schema_name := 'data_t_' || pg_catalog.replace(tenant_id::text, '-', '_');
    reader_name := 'geolens_reader_t_' || pg_catalog.replace(tenant_id::text, '-', '_');
    writer_name := 'geolens_writer_t_' || pg_catalog.replace(tenant_id::text, '-', '_');

    PERFORM 1 FROM catalog.tenants WHERE id = tenant_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'tenant % does not exist', tenant_id
            USING ERRCODE = '23503';
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
        OR reader_row.rolreplication
        OR reader_row.rolbypassrls
    ) THEN
        RAISE EXCEPTION
            'existing tenant reader role % has unsafe attributes', reader_name;
    END IF;
    IF reader_exists AND reader_row.rolinherit THEN
        EXECUTE pg_catalog.format('ALTER ROLE %I NOINHERIT', reader_name);
    END IF;

    -- The pre-0019 runtime helper created readers with the default INHERIT
    -- flag, an automatic creator membership, and an ALTER DEFAULT PRIVILEGES
    -- entry.  Normalize that known legacy shape before the strict provision
    -- function validates the role.
    FOR legacy_member_row IN
        SELECT member_role.rolname AS member_name
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        WHERE granted_role.rolname = reader_name
          AND member_role.rolname NOT IN ('{PROVISIONER}', '{SANDBOX}', '{TILE}')
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE %I FROM %I', reader_name, legacy_member_row.member_name
        );
    END LOOP;

    FOR default_acl_row IN
        SELECT DISTINCT owner_role.rolname AS owner_name
        FROM pg_catalog.pg_default_acl AS default_acl
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = default_acl.defaclrole
        JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) AS acl ON true
        JOIN pg_catalog.pg_roles AS grantee_role ON grantee_role.oid = acl.grantee
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = default_acl.defaclnamespace
        WHERE namespace.nspname = schema_name
          AND default_acl.defaclobjtype = 'r'
          AND grantee_role.rolname = reader_name
    LOOP
        EXECUTE pg_catalog.format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I '
            'REVOKE ALL ON TABLES FROM %I',
            default_acl_row.owner_name, schema_name, reader_name
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
            'existing tenant writer role % has unsafe attributes', writer_name;
    END IF;

    SELECT owner_role.rolname INTO schema_owner
    FROM pg_catalog.pg_namespace AS namespace
    JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = namespace.nspowner
    WHERE namespace.nspname = schema_name;
    IF schema_owner IS NOT NULL AND schema_owner <> '{PROVISIONER}' THEN
        EXECUTE pg_catalog.format(
            'ALTER SCHEMA %I OWNER TO {PROVISIONER}', schema_name
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
          AND member_role.rolname = '{PROVISIONER}'
          AND {_MEMBERSHIP_ADMIN_ONLY}
    ) THEN
        IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
            EXECUTE pg_catalog.format(
                'GRANT %I TO {PROVISIONER} '
                'WITH ADMIN TRUE, INHERIT FALSE, SET FALSE',
                reader_name
            );
        ELSE
            EXECUTE pg_catalog.format(
                'GRANT %I TO {PROVISIONER} WITH ADMIN OPTION', reader_name
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
          AND member_role.rolname = '{PROVISIONER}'
          AND {_MEMBERSHIP_ADMIN_ONLY}
    ) THEN
        IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
            EXECUTE pg_catalog.format(
                'GRANT %I TO {PROVISIONER} '
                'WITH ADMIN TRUE, INHERIT FALSE, SET FALSE',
                writer_name
            );
        ELSE
            EXECUTE pg_catalog.format(
                'GRANT %I TO {PROVISIONER} WITH ADMIN OPTION', writer_name
            );
        END IF;
    END IF;

    -- The writer's counterpart to the reader normalization above, and the same
    -- cause: PostgreSQL 16+ grants the creating role an automatic ADMIN
    -- membership, so a non-superuser CREATEROLE migrator that replayed the
    -- globals dump is a direct member of every restored writer, which the
    -- provisioning function refuses outright.
    --
    -- It sits *here*, after the provisioner's ADMIN grants rather than beside
    -- the reader's loop, because that creator membership can be the only ADMIN
    -- path this transaction has: revoking it any earlier would strand the grant
    -- above. Afterwards the caller reaches the writer through the provisioner,
    -- whose privileges it must hold to have got this far.
    FOR legacy_member_row IN
        SELECT member_role.rolname AS member_name
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        WHERE granted_role.rolname = writer_name
          AND member_role.rolname NOT IN ('{PROVISIONER}', '{WRITER}')
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE %I FROM %I', writer_name, legacy_member_row.member_name
        );
    END LOOP;

    -- The guarded boundary owns schema creation, role creation, gateway
    -- memberships, and schema-level privileges.  Since 0024 it deliberately
    -- does NOT touch per-relation ACLs, which is why the reader grants below
    -- are issued by the writer instead of by this function.
    PERFORM catalog.provision_tenant_data_schema(tenant_id);

    SELECT pg_catalog.count(*) INTO pending_owner_transfer
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
    WHERE namespace.nspname = schema_name
      AND relation.relkind IN ({_RELATION_KINDS})
      AND owner_role.rolname <> writer_name
      AND NOT {_COLUMN_OWNED_SEQUENCE};

    SELECT pg_catalog.count(*) INTO reader_privilege_gap
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = schema_name
      AND (
          (
              relation.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND NOT pg_catalog.has_table_privilege(
                  reader_name, relation.oid, 'SELECT'
              )
          )
          OR (
              relation.relkind = 'S'
              AND NOT pg_catalog.has_sequence_privilege(
                  reader_name, relation.oid, 'SELECT'
              )
          )
      );

    -- Nothing to move and nothing to grant: an already-adopted tenant issues
    -- zero DDL here, which is what makes a re-run a genuine no-op.
    IF pending_owner_transfer = 0 AND reader_privilege_gap = 0 THEN
        RETURN;
    END IF;

    -- Restored tenant relations are owned by whoever ran pg_restore.  A GRANT
    -- is not enough: owner-only ALTER/DROP has to follow the per-tenant writer,
    -- and the reader's SELECT has to be granted by that same owner.  The
    -- adopting login takes a transaction-scoped SET edge for exactly that, and
    -- gives it back before commit.
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
                writer_name, CURRENT_USER
            );
        ELSE
            EXECUTE pg_catalog.format('GRANT %I TO %I', writer_name, CURRENT_USER);
        END IF;
    END IF;

    FOR object_row IN
        SELECT relation.relname, relation.relkind
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
        WHERE namespace.nspname = schema_name
          AND relation.relkind IN ({_RELATION_KINDS})
          AND owner_role.rolname <> writer_name
          AND NOT {_COLUMN_OWNED_SEQUENCE}
        ORDER BY relation.relkind, relation.relname
    LOOP
        IF object_row.relkind = 'S' THEN
            EXECUTE pg_catalog.format(
                'ALTER SEQUENCE %I.%I OWNER TO %I',
                schema_name, object_row.relname, writer_name
            );
        ELSE
            EXECUTE pg_catalog.format(
                'ALTER TABLE %I.%I OWNER TO %I',
                schema_name, object_row.relname, writer_name
            );
        END IF;
    END LOOP;

    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
        WHERE namespace.nspname = schema_name
          AND relation.relkind IN ({_RELATION_KINDS})
          AND owner_role.rolname <> writer_name
    ) THEN
        RAISE EXCEPTION
            'tenant schema % contains relation not owned by %',
            schema_name, writer_name;
    END IF;

    EXECUTE pg_catalog.format('SET ROLE %I', writer_name);
    EXECUTE pg_catalog.format(
        'GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I', schema_name, reader_name
    );
    EXECUTE pg_catalog.format(
        'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I',
        schema_name, reader_name
    );
    RESET ROLE;

    IF temporary_writer_membership THEN
        EXECUTE pg_catalog.format('REVOKE %I FROM %I', writer_name, CURRENT_USER);
    END IF;
END
$$
"""
