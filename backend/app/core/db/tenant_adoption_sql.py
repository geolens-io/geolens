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

Repair boundary
---------------
Adoption rewrites only grants it is itself the grantor of, plus ACLs on objects
it owns or can own for the duration.  A pre-existing anomaly — a membership
granted by a third party, a duplicate row hiding behind a canonical one, a
default-privilege entry belonging to a role this credential cannot assume — is
detected and refused with the exact statement to run and the role to run it as,
not repaired.  Removing somebody else's grant means naming its grantor and being
able to assume it, and PostgreSQL answers that differently for every combination
of server version, grantor and dependent grant; the operator has authority this
process does not, and a refusal that names the remedy costs one re-run.
- The reserved-role membership guard aggregates with ``bool_or`` instead of
  reading one row.  PostgreSQL keeps one membership row per grantor, so a member
  can hold two grants of the same role and 0019's scalar read picks one
  arbitrarily — a canonical row can hide an unsafe one.
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
#: The membership PostgreSQL 16+ hands a non-superuser role creator, and the
#: reason none of this file tries to revoke one: its grantor is the bootstrap
#: superuser, a member's plain ``REVOKE`` of it is a warning-level no-op, and
#: ``GRANTED BY`` that grantor is permission denied for every customer role on a
#: managed provider — measured, on 18.  It confers nothing on its own (ADMIN
#: without INHERIT or SET), so it is tolerated wherever it appears instead.
#:
#: Before 16 there is no automatic membership at all, so the pre-16 arm of the
#: jsonb read never matches and nothing is tolerated by accident.
_MEMBERSHIP_CREATOR_SHAPE = """(
              membership.admin_option
              AND jsonb_exists(to_jsonb(membership), 'set_option')
              AND NOT (to_jsonb(membership) ->> 'inherit_option')::boolean
              AND NOT (to_jsonb(membership) ->> 'set_option')::boolean
          )"""

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

#: The SET-only membership shape the fixed gateways must hold in a per-tenant
#: role: no ADMIN, no INHERIT, SET.  Same jsonb read and the same pre-16
#: degradation as :data:`_MEMBERSHIP_ADMIN_ONLY`, where ``NOINHERIT`` on the
#: gateway carries the guarantee instead.
_MEMBERSHIP_SET_ONLY = """(
              NOT membership.admin_option
              AND (
                  NOT jsonb_exists(to_jsonb(membership), 'set_option')
                  OR (
                      NOT (to_jsonb(membership) ->> 'inherit_option')::boolean
                      AND (to_jsonb(membership) ->> 'set_option')::boolean
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

    -- PostgreSQL 16+ makes a non-superuser creator an ADMIN member of the role
    -- it just created, but with INHERIT FALSE and SET FALSE — measured on 18 —
    -- so the creator does not hold the new role's privileges.  Everything after
    -- this point needs them: the boundary-function repair, and every tenant's
    -- ADMIN path to its own roles.
    --
    -- Taken on every apply run, not only the one that creates the role, because
    -- the run hands it back at the end.  A superuser already holds the
    -- privileges and does nothing here.  A caller with no ADMIN cannot grant
    -- itself anything either, so it falls through to the refusal in
    -- SECURE_BOUNDARY_FUNCTIONS_SQL, which prints the GRANT to run.
    --
    -- No ADMIN in the grant: PostgreSQL refuses "ADMIN option cannot be granted
    -- back to your own grantor", and the automatic membership already carries
    -- it.
    IF NOT pg_catalog.pg_has_role(CURRENT_USER, '{PROVISIONER}', 'USAGE') THEN
        IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
            -- 16+ requires an ADMIN edge to grant the role, and the creator
            -- automatically has one. Without it the caller cannot grant itself
            -- anything, so fall through to the refusal below.
            IF EXISTS (
                SELECT 1
                FROM pg_catalog.pg_auth_members AS membership
                JOIN pg_catalog.pg_roles AS granted_role
                  ON granted_role.oid = membership.roleid
                JOIN pg_catalog.pg_roles AS member_role
                  ON member_role.oid = membership.member
                WHERE granted_role.rolname = '{PROVISIONER}'
                  AND member_role.rolname = CURRENT_USER
                  AND membership.admin_option
            ) THEN
                EXECUTE pg_catalog.format(
                    'GRANT {PROVISIONER} TO %I WITH INHERIT TRUE, SET TRUE',
                    CURRENT_USER
                );
            END IF;
        ELSE
            -- Before 16 there is no creator membership to look for: CREATEROLE
            -- carries admin rights over every non-superuser role, so the grant
            -- is simply attempted. A caller without that authority is told what
            -- to run by SECURE_BOUNDARY_FUNCTIONS_SQL rather than by a raw
            -- permission error.
            BEGIN
                EXECUTE pg_catalog.format('GRANT {PROVISIONER} TO %I', CURRENT_USER);
            EXCEPTION
                WHEN insufficient_privilege THEN NULL;
            END;
        END IF;
    END IF;
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

        -- fix(#998 codex r44): the automatic creator membership was tolerated
        -- here for any login, but ADMIN alone lets its holder grant itself a
        -- usable edge — the bootstrap takes its own edge exactly that way — so
        -- on any login other than the one running adoption (exempted above) it
        -- is a live escalation path, not a harmless leftover.  Refuse it with
        -- the remedy that works on managed platforms, where the recorded
        -- grantor is the unassumable bootstrap superuser: drop the retired
        -- login.
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_auth_members AS membership
            WHERE membership.roleid = membership_row.granted_oid
              AND membership.member = membership_row.member_oid
        ) AND NOT EXISTS (
            SELECT 1
            FROM pg_catalog.pg_auth_members AS membership
            WHERE membership.roleid = membership_row.granted_oid
              AND membership.member = membership_row.member_oid
              AND NOT {_MEMBERSHIP_CREATOR_SHAPE}
        ) THEN
            RAISE EXCEPTION
                'reserved role % keeps the creator membership of %, which '
                'ADMIN alone can turn back into a usable edge',
                membership_row.granted_name, membership_row.member_name
                USING HINT =
                    'if that login is retired, run DROP ROLE ' ||
                    pg_catalog.quote_ident(membership_row.member_name) ||
                    ' (REASSIGN OWNED BY it first if PostgreSQL refuses); to '
                    'keep the login, revoke that membership as its recorded '
                    'grantor (REVOKE ... GRANTED BY, PostgreSQL 16+); then '
                    're-run adoption';
        END IF;

        direct_membership_unsafe := membership_row.membership_admin;
        IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
            -- bool_or, not a bare SELECT INTO: PostgreSQL keeps one row per
            -- grantor, so a member can hold two grants of the same reserved
            -- role and a scalar read would pick one arbitrarily — letting a
            -- canonical row mask an unsafe one. 0019 has the same shape; this
            -- is the one place the port is deliberately stricter than it.
            EXECUTE
                'SELECT pg_catalog.bool_or('
                'membership.admin_option OR CASE WHEN $3 = $4 '
                'THEN NOT membership.inherit_option OR membership.set_option '
                'ELSE membership.inherit_option OR NOT membership.set_option '
                'END) '
                'FROM pg_catalog.pg_auth_members AS membership '
                'WHERE membership.roleid = $1 AND membership.member = $2'
                INTO direct_membership_unsafe
                USING membership_row.granted_oid,
                      membership_row.member_oid,
                      membership_row.granted_name,
                      '{CONTROL}';
        END IF;

        -- fix(#1913): members are judged by oid, never by name; a role dropped
        -- since the scan is then no hazard instead of an undefined-object error.
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
                     membership_row.member_oid, powerful_role.oid, 'MEMBER'
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
                         membership_row.member_oid,
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
                         membership_row.member_oid, tile_gateway.oid, 'MEMBER'
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
    --
    -- The edge's *options* are deliberately not judged here, and neither is
    -- whether catalog.tenants still has the tenant. Roles are cluster objects
    -- and this table is not: in a cluster hosting more than one GeoLens
    -- database — which the downgrade note below assumes — every other
    -- database's live tenant roles look orphaned from here, and refusing them
    -- would make each database unadoptable from the others' existence. The
    -- per-tenant checks own that judgement for the tenants of this database.
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
    grantee_name text;
    foreign_acl_row RECORD;
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
              OR EXISTS (
                  SELECT 1
                  FROM LATERAL pg_catalog.aclexplode(routine.proacl) AS acl
                  JOIN pg_catalog.pg_roles AS grantee_role
                    ON grantee_role.oid = acl.grantee
                  WHERE grantee_role.rolname NOT IN ('{PROVISIONER}', '{CONTROL}')
                     OR (grantee_role.rolname = '{CONTROL}' AND acl.is_grantable)
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
                CASE
                    WHEN pg_catalog.current_setting('server_version_num')::integer
                         >= 160000
                    THEN 'run GRANT {PROVISIONER} TO ' ||
                         pg_catalog.quote_ident(CURRENT_USER) ||
                         ' WITH INHERIT TRUE'
                    ELSE 'run GRANT {PROVISIONER} TO ' ||
                         pg_catalog.quote_ident(CURRENT_USER) ||
                         ' (before PostgreSQL 16 there are no per-membership '
                         'options; if that role is NOINHERIT, ALTER ROLE ' ||
                         pg_catalog.quote_ident(CURRENT_USER) || ' INHERIT too)'
                END || ', or adopt with a superuser migrator';
    END IF;

    IF NOT pg_catalog.has_schema_privilege('{PROVISIONER}', 'catalog', 'CREATE') THEN
        temporary_schema_create := true;
        GRANT CREATE ON SCHEMA catalog TO {PROVISIONER};
    END IF;

    FOREACH routine_name IN ARRAY ARRAY[
        'provision_tenant_data_schema', 'deprovision_tenant_data_schema'
    ] LOOP
        -- fix(#998 codex r44): transferring the owner re-attributes only the
        -- owner's own ACL entries.  An entry some third role granted keeps its
        -- grantor, the plain REVOKEs below cannot remove it (a non-grantor's
        -- REVOKE is a warning-level no-op), so every --apply would repeat an
        -- ineffective repair while the grantee kept EXECUTE on provisioner-
        -- owned SECURITY DEFINER tenant management.  Refuse before touching
        -- the function.  Entries granted by the current owner re-attribute on
        -- transfer and the sweep below clears them; the provisioner's own
        -- entries are already inside the canonical authority.
        FOR foreign_acl_row IN
            SELECT grantor_role.rolname AS grantor_name,
                   grantee_role.rolname AS grantee_name
            FROM pg_catalog.pg_proc AS routine
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = routine.pronamespace
            JOIN LATERAL pg_catalog.aclexplode(routine.proacl) AS acl ON true
            JOIN pg_catalog.pg_roles AS grantor_role
              ON grantor_role.oid = acl.grantor
            LEFT JOIN pg_catalog.pg_roles AS grantee_role
              ON grantee_role.oid = acl.grantee
            WHERE namespace.nspname = 'catalog'
              AND routine.proname = routine_name
              AND routine.pronargs = 1
              AND routine.proargtypes[0] = 'uuid'::regtype
              AND grantor_role.oid <> routine.proowner
              AND grantor_role.rolname <> '{PROVISIONER}'
        LOOP
            RAISE EXCEPTION
                'boundary function catalog.%(uuid) carries an EXECUTE entry '
                'granted by %, which adoption cannot revoke',
                routine_name, foreign_acl_row.grantor_name
                USING HINT =
                    'as ' ||
                    pg_catalog.quote_ident(foreign_acl_row.grantor_name) ||
                    ' (or a role that can assume it) run: REVOKE ALL ON '
                    'FUNCTION catalog.' ||
                    pg_catalog.quote_ident(routine_name) || '(uuid) FROM ' ||
                    CASE
                        WHEN foreign_acl_row.grantee_name IS NULL THEN 'PUBLIC'
                        ELSE pg_catalog.quote_ident(
                            foreign_acl_row.grantee_name
                        )
                    END || '; then re-run adoption';
        END LOOP;

        EXECUTE pg_catalog.format(
            'ALTER FUNCTION catalog.%I(uuid) OWNER TO {PROVISIONER}', routine_name
        );
        EXECUTE pg_catalog.format(
            'REVOKE ALL ON FUNCTION catalog.%I(uuid) FROM PUBLIC', routine_name
        );
        -- Revoke before granting: a re-GRANT does not clear an existing GRANT
        -- OPTION, and a grantable EXECUTE lets a control-role member delegate
        -- provisioner-owned tenant management to anyone.
        EXECUTE pg_catalog.format(
            'REVOKE ALL ON FUNCTION catalog.%I(uuid) FROM {CONTROL}', routine_name
        );
        EXECUTE pg_catalog.format(
            'GRANT EXECUTE ON FUNCTION catalog.%I(uuid) TO {CONTROL}', routine_name
        );

        -- REVOKE … FROM PUBLIC does not touch a direct grant to a named role,
        -- and a restore or an old deployment can leave one. Anything outside
        -- the canonical pair can call provisioner-owned tenant management.
        FOR grantee_name IN
            SELECT DISTINCT grantee_role.rolname
            FROM pg_catalog.pg_proc AS routine
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = routine.pronamespace
            JOIN LATERAL pg_catalog.aclexplode(routine.proacl) AS acl ON true
            JOIN pg_catalog.pg_roles AS grantee_role
              ON grantee_role.oid = acl.grantee
            WHERE namespace.nspname = 'catalog'
              AND routine.proname = routine_name
              AND routine.pronargs = 1
              AND routine.proargtypes[0] = 'uuid'::regtype
              AND grantee_role.rolname NOT IN ('{PROVISIONER}', '{CONTROL}')
        LOOP
            EXECUTE pg_catalog.format(
                'REVOKE ALL ON FUNCTION catalog.%I(uuid) FROM %I',
                routine_name,
                grantee_name
            );
        END LOOP;
    END LOOP;

    IF temporary_schema_create THEN
        REVOKE CREATE ON SCHEMA catalog FROM {PROVISIONER};
    END IF;
END
$$
"""

#: Hand back the usable provisioner edge this run took, if it took one.
#:
#: Gated by the caller on whether the run actually acquired it: an operator on
#: PostgreSQL 13-15 may have granted the migrator this same shape by hand before
#: recovery, and revoking somebody else's grant is not this tool's business.
#:
#: ``CLUSTER_ROLE_VALIDATE_SQL`` rejects *any* direct member of these roles
#: except the role running it, so anything left here makes the next recovery
#: depend on reusing the same migrator credential.  Two sources: the usable
#: provisioner edge ``CLUSTER_ROLE_CREATE_SQL`` takes for the run, and the
#: automatic ADMIN membership PostgreSQL 16+ gives a non-superuser creator on
#: every role it creates.
#:
#: The provisioner's automatic ADMIN edge is deliberately kept.  It grants no
#: privileges by itself — measured — and it is what lets the same credential
#: re-take a usable edge on the next run; without it the operator would have to
#: re-grant by hand after every recovery.  What goes is the usable edge this run
#: granted (grantor ``CURRENT_USER``, no ``ADMIN``) and the gateway memberships,
#: which nothing in this tool ever reads.
RELEASE_PROVISIONER_EDGE_SQL = f"""
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        LEFT JOIN pg_catalog.pg_roles AS grantor_role
          ON grantor_role.oid = membership.grantor
        WHERE granted_role.rolname = '{PROVISIONER}'
          AND member_role.rolname = CURRENT_USER
          AND grantor_role.rolname = CURRENT_USER
          AND NOT membership.admin_option
    ) THEN
        IF pg_catalog.current_setting('server_version_num')::integer >= 160000 THEN
            EXECUTE pg_catalog.format(
                'REVOKE {PROVISIONER} FROM %I GRANTED BY %I',
                CURRENT_USER,
                CURRENT_USER
            );
        ELSE
            -- GRANTED BY on REVOKE ROLE arrived in 16. Before that a role can
            -- hold only one membership in another, and this branch runs only
            -- when the run granted it, so the plain form removes exactly it.
            EXECUTE pg_catalog.format(
                'REVOKE {PROVISIONER} FROM %I', CURRENT_USER
            );
        END IF;
    END IF;
END
$$
"""

PROVISIONER_DATABASE_REVOKE_OPTION_SQL = f"""
DO $$
BEGIN
    EXECUTE pg_catalog.format(
        'REVOKE GRANT OPTION FOR CREATE ON DATABASE %I FROM {PROVISIONER}',
        pg_catalog.current_database()
    );
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

#: fix(#998 codex r45): the plain ``REVOKE GRANT OPTION`` statements in
#: ``ensure_cluster_roles`` reach only entries attributable to the executing
#: role (or the object owner, for a superuser).  A grantable privilege some
#: third role handed the provisioner survives them, and the final
#: ``missing_provisioner_grants`` read then reports it as grantable after
#: every ``--apply`` with nothing naming the grantor.  Refuse it up front,
#: on the same terms as every other foreign grant: the role that can revoke
#: it is named in the remedy.
PROVISIONER_GRANT_OPTION_GUARD_SQL = f"""
DO $$
DECLARE
    foreign_option_row RECORD;
BEGIN
    FOR foreign_option_row IN
        SELECT 'SCHEMA catalog' AS target,
               acl.privilege_type AS privilege,
               grantor_role.rolname AS grantor_name
        FROM pg_catalog.pg_namespace AS namespace
        JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl ON true
        JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = acl.grantee
        JOIN pg_catalog.pg_roles AS grantor_role
          ON grantor_role.oid = acl.grantor
        WHERE namespace.nspname = 'catalog'
          AND grantee_role.rolname = '{PROVISIONER}'
          AND acl.is_grantable
          AND grantor_role.oid <> namespace.nspowner
          AND grantor_role.rolname <> CURRENT_USER
        UNION ALL
        SELECT 'TABLE catalog.tenants',
               acl.privilege_type,
               grantor_role.rolname
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl ON true
        JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = acl.grantee
        JOIN pg_catalog.pg_roles AS grantor_role
          ON grantor_role.oid = acl.grantor
        WHERE namespace.nspname = 'catalog'
          AND relation.relname = 'tenants'
          AND grantee_role.rolname = '{PROVISIONER}'
          AND acl.is_grantable
          AND grantor_role.oid <> relation.relowner
          AND grantor_role.rolname <> CURRENT_USER
        UNION ALL
        SELECT 'DATABASE ' || pg_catalog.quote_ident(db.datname),
               acl.privilege_type,
               grantor_role.rolname
        FROM pg_catalog.pg_database AS db
        JOIN LATERAL pg_catalog.aclexplode(db.datacl) AS acl ON true
        JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = acl.grantee
        JOIN pg_catalog.pg_roles AS grantor_role
          ON grantor_role.oid = acl.grantor
        WHERE db.datname = pg_catalog.current_database()
          AND grantee_role.rolname = '{PROVISIONER}'
          AND acl.is_grantable
          AND grantor_role.oid <> db.datdba
          AND grantor_role.rolname <> CURRENT_USER
    LOOP
        RAISE EXCEPTION
            '{PROVISIONER} holds a grantable % on %, granted by %, which '
            'this run cannot revoke',
            foreign_option_row.privilege,
            foreign_option_row.target,
            foreign_option_row.grantor_name
            USING HINT =
                'as ' ||
                pg_catalog.quote_ident(foreign_option_row.grantor_name) ||
                ' (or a role that can assume it) run: REVOKE GRANT OPTION '
                'FOR ' || foreign_option_row.privilege || ' ON ' ||
                foreign_option_row.target ||
                ' FROM {PROVISIONER}; then re-run adoption';
    END LOOP;

    -- fix(#998 codex r47): a schema-less default privilege owned by the
    -- provisioner lands on every future data_t_* schema the provisioning
    -- function creates.  The per-tenant pass also refuses it, but with zero
    -- tenants that pass never runs — this is the one place that executes on
    -- every run regardless.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_default_acl AS default_acl
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = default_acl.defaclrole
        WHERE default_acl.defaclnamespace = 0
          AND owner_role.rolname = '{PROVISIONER}'
    ) THEN
        RAISE EXCEPTION
            '{PROVISIONER} carries schema-less default privileges, which '
            'apply to every tenant schema it creates'
            USING HINT =
                'as {PROVISIONER} run: ALTER DEFAULT PRIVILEGES REVOKE ALL '
                'ON TABLES FROM PUBLIC (and the same for the other object '
                'kinds and grantees shown by \\ddp); then re-run adoption';
    END IF;
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
    default_acl_gap bigint;
    routine_gap bigint;
    type_gap bigint;
    statistics_gap bigint;
    collation_gap bigint;
    other_object_gap bigint;
    foreign_grantor_gap bigint;
    global_default_acl_gap bigint;
    reader_oid oid;
    writer_oid oid;
    grantee_name text;
    temporary_writer_membership boolean := false;
BEGIN
    schema_name := 'data_t_' || pg_catalog.replace(tenant_id::text, '-', '_');
    reader_name := 'geolens_reader_t_' || pg_catalog.replace(tenant_id::text, '-', '_');
    writer_name := 'geolens_writer_t_' || pg_catalog.replace(tenant_id::text, '-', '_');

    -- Every ownership transfer below takes ACCESS EXCLUSIVE, and one
    -- forgotten session — a tile login, a stray psql, provider maintenance —
    -- would otherwise queue this transaction and everything behind it for as
    -- long as it holds on. Failing fast makes it one retryable tenant instead.
    SET LOCAL lock_timeout = '15s';
    SET LOCAL statement_timeout = '30min';

    -- The same lock 0019's provisioning and deprovisioning functions take as
    -- their first act. Taken here too, because everything this block decides is
    -- read before that function is called, and an unlocked read can race a live
    -- provisioning of the same tenant.
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            'geolens:tenant-data-plane:' || tenant_id::text, 0
        )
    );

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
    -- flag.  That one is normalized; the other two shapes it left — an
    -- automatic creator membership and an ALTER DEFAULT PRIVILEGES entry — are
    -- somebody else's grants, so they are refused further down instead.
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

    -- Both tenant roles' member lists. Unlike the five fixed roles, the
    -- creator shape is NOT tolerated here: catalog.provision_tenant_data_schema
    -- is migration-owned, unchanged, and refuses any reader member outside
    -- provisioner/sandbox/tile — so tolerating one only moves the failure to a
    -- hintless refusal a few lines down. The remedy is in the message, and for
    -- a creator edge it is the DROP ROLE branch: its grantor is the bootstrap
    -- superuser, so nobody else can revoke it, while the tenant role owns
    -- nothing at this point and provisioning recreates it.
    --
    -- Here rather than earlier: PostgreSQL 16+ grants the creating role an automatic ADMIN
    -- membership, so a non-superuser migrator that replayed the globals dump is
    -- a direct member of every restored reader and writer, which the
    -- provisioning function refuses outright.
    --
    -- That creator membership can also be the only ADMIN path this transaction
    -- has, which is why the revokes wait until after the provisioner has its own
    -- ADMIN above. Afterwards the caller reaches both roles through the
    -- provisioner, whose privileges it must hold to have got this far.
    -- Detect, do not rewrite.  Every row here predates this run: a restore, a
    -- globals replay, or an operator granted it, which makes some other role
    -- its grantor.  Removing it means naming that grantor and being able to
    -- assume it, and PostgreSQL has a different answer for every combination of
    -- server version, grantor and dependent grant.  Adoption repairs only the
    -- grants it made itself; anything else is one exact statement for the
    -- operator and a re-run.
    FOR legacy_member_row IN
        SELECT member_role.rolname AS member_name,
               COALESCE(grantor_role.rolname, 'a dropped role') AS grantor_name
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        LEFT JOIN pg_catalog.pg_roles AS grantor_role
          ON grantor_role.oid = membership.grantor
        WHERE granted_role.rolname = reader_name
          AND (
              member_role.rolname NOT IN ('{PROVISIONER}', '{SANDBOX}', '{TILE}')
              OR (
                  member_role.rolname IN ('{SANDBOX}', '{TILE}')
                  AND NOT {_MEMBERSHIP_SET_ONLY}
              )
          )
    LOOP
        RAISE EXCEPTION
            'tenant role % carries a membership adoption will not rewrite: '
            'member %, granted by %',
            reader_name,
            legacy_member_row.member_name,
            legacy_member_row.grantor_name
            USING HINT =
                'as ' || pg_catalog.quote_ident(legacy_member_row.grantor_name) ||
                ' run: REVOKE ' || pg_catalog.quote_ident(reader_name) ||
                ' FROM ' || pg_catalog.quote_ident(legacy_member_row.member_name) ||
                ' CASCADE. If that role is gone or cannot be assumed — a '
                'retired managed credential, say — DROP ROLE ' ||
                pg_catalog.quote_ident(reader_name) ||
                ' instead — first REASSIGN OWNED BY it TO CURRENT_USER and '
                'DROP OWNED BY it (an adopted tenant''s roles hold objects '
                'and privileges that block a bare DROP ROLE; adoption takes '
                'them back), then DROP ROLE: provisioning recreates it. Then '
                're-run adoption';
    END LOOP;

    -- Detect, do not rewrite.  Every row here predates this run: a restore, a
    -- globals replay, or an operator granted it, which makes some other role
    -- its grantor.  Removing it means naming that grantor and being able to
    -- assume it, and PostgreSQL has a different answer for every combination of
    -- server version, grantor and dependent grant.  Adoption repairs only the
    -- grants it made itself; anything else is one exact statement for the
    -- operator and a re-run.
    FOR legacy_member_row IN
        SELECT member_role.rolname AS member_name,
               COALESCE(grantor_role.rolname, 'a dropped role') AS grantor_name
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        LEFT JOIN pg_catalog.pg_roles AS grantor_role
          ON grantor_role.oid = membership.grantor
        WHERE granted_role.rolname = writer_name
          AND (
              member_role.rolname NOT IN ('{PROVISIONER}', '{WRITER}')
              OR (
                  member_role.rolname IN ('{WRITER}')
                  AND NOT {_MEMBERSHIP_SET_ONLY}
              )
          )
    LOOP
        RAISE EXCEPTION
            'tenant role % carries a membership adoption will not rewrite: '
            'member %, granted by %',
            writer_name,
            legacy_member_row.member_name,
            legacy_member_row.grantor_name
            USING HINT =
                'as ' || pg_catalog.quote_ident(legacy_member_row.grantor_name) ||
                ' run: REVOKE ' || pg_catalog.quote_ident(writer_name) ||
                ' FROM ' || pg_catalog.quote_ident(legacy_member_row.member_name) ||
                ' CASCADE. If that role is gone or cannot be assumed — a '
                'retired managed credential, say — DROP ROLE ' ||
                pg_catalog.quote_ident(writer_name) ||
                ' instead — first REASSIGN OWNED BY it TO CURRENT_USER and '
                'DROP OWNED BY it (an adopted tenant''s roles hold objects '
                'and privileges that block a bare DROP ROLE; adoption takes '
                'them back), then DROP ROLE: provisioning recreates it. Then '
                're-run adoption';
    END LOOP;

    -- The provisioner's own duplicates, detected for the same reason and on
    -- the same terms: the canonical row hides them, and only the grantor can
    -- take one away.
    FOR legacy_member_row IN
        SELECT granted_role.rolname AS granted_name,
               COALESCE(grantor_role.rolname, 'a dropped role') AS grantor_name
        FROM pg_catalog.pg_auth_members AS membership
        JOIN pg_catalog.pg_roles AS granted_role
          ON granted_role.oid = membership.roleid
        JOIN pg_catalog.pg_roles AS member_role
          ON member_role.oid = membership.member
        LEFT JOIN pg_catalog.pg_roles AS grantor_role
          ON grantor_role.oid = membership.grantor
        WHERE granted_role.rolname IN (reader_name, writer_name)
          AND member_role.rolname = '{PROVISIONER}'
          AND NOT {_MEMBERSHIP_ADMIN_ONLY}
    LOOP
        RAISE EXCEPTION
            'tenant role % carries a {PROVISIONER} membership that is not '
            'ADMIN-only, granted by %',
            legacy_member_row.granted_name,
            legacy_member_row.grantor_name
            USING HINT =
                'as ' || pg_catalog.quote_ident(legacy_member_row.grantor_name) ||
                ' run: REVOKE ' ||
                pg_catalog.quote_ident(legacy_member_row.granted_name) ||
                ' FROM {PROVISIONER} CASCADE. If that role is gone or cannot be '
                'assumed, DROP ROLE ' ||
                pg_catalog.quote_ident(legacy_member_row.granted_name) ||
                ' instead and let provisioning recreate it. Then re-run adoption';
    END LOOP;

    -- The guarded boundary owns schema creation, role creation, gateway
    -- memberships, and schema-level privileges.  Since 0024 it deliberately
    -- does NOT touch per-relation ACLs, which is why the reader grants below
    -- are issued by the writer instead of by this function.
    PERFORM catalog.provision_tenant_data_schema(tenant_id);

    SELECT oid INTO reader_oid FROM pg_catalog.pg_roles WHERE rolname = reader_name;
    SELECT oid INTO writer_oid FROM pg_catalog.pg_roles WHERE rolname = writer_name;

    -- The provisioning function grants the reader USAGE; it never takes CREATE
    -- away, and a restored schema can arrive carrying it.  The sandbox and tile
    -- gateways SET ROLE to this reader, so CREATE there is a write path into a
    -- schema that is supposed to be read-only.
    IF pg_catalog.has_schema_privilege(reader_name, schema_name, 'CREATE') THEN
        EXECUTE pg_catalog.format(
            'REVOKE CREATE ON SCHEMA %I FROM %I', schema_name, reader_name
        );
    END IF;

    -- A grantable schema privilege survives the provisioning function's GRANT,
    -- which adds privileges rather than replacing them. REVOKE GRANT OPTION FOR
    -- takes the delegation away and leaves the privilege.
    FOREACH grantee_name IN ARRAY ARRAY[reader_name, writer_name] LOOP
        IF EXISTS (
            SELECT 1
            FROM pg_catalog.pg_namespace AS namespace
            JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl ON true
            JOIN pg_catalog.pg_roles AS grantee_role ON grantee_role.oid = acl.grantee
            WHERE namespace.nspname = schema_name
              AND grantee_role.rolname = grantee_name
              AND acl.is_grantable
        ) THEN
            EXECUTE pg_catalog.format(
                'REVOKE GRANT OPTION FOR ALL ON SCHEMA %I FROM %I',
                schema_name,
                grantee_name
            );
        END IF;
    END LOOP;

    -- And anyone else the restore left on the schema. The provisioning function
    -- revokes PUBLIC and grants the two tenant roles; a named grantee with
    -- USAGE, or worse CREATE, is a path around the writer boundary that nothing
    -- else here would take away.
    FOR grantee_name IN
        SELECT DISTINCT
            CASE
                WHEN acl.grantee = 0 THEN 'PUBLIC'
                ELSE pg_catalog.quote_ident(grantee_role.rolname)
            END
        FROM pg_catalog.pg_namespace AS namespace
        JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl ON true
        LEFT JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = acl.grantee
        WHERE namespace.nspname = schema_name
          AND COALESCE(grantee_role.rolname, '') NOT IN (
              '{PROVISIONER}', reader_name, writer_name
          )
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL ON SCHEMA %I FROM %s', schema_name, grantee_name
        );
    END LOOP;

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
          -- Missing SELECT is only half of it: the reader is the SET target of
          -- the sandbox and tile gateways, so any privilege beyond reading is a
          -- write path into tenant data. Read out of the ACL rather than named
          -- one by one, because the set of privilege types grows by release.
          -- Grantee 0 is PUBLIC, which the reader holds too — along with every
          -- other role that can reach the schema. And a named role with its own
          -- grant plus USAGE on the schema reads or writes tenant data without
          -- going near either tenant role.
          -- Column grants live in pg_attribute, not pg_class, and a table-level
          -- REVOKE ALL does not clear them. UPDATE(col) on the reader is a
          -- write path through the gateways that SET ROLE to it.
          OR EXISTS (
              SELECT 1
              FROM pg_catalog.pg_attribute AS column_row
              JOIN LATERAL pg_catalog.aclexplode(column_row.attacl) AS acl ON true
              WHERE column_row.attrelid = relation.oid
                AND NOT column_row.attisdropped
                AND acl.grantee <> writer_oid
          )
          OR EXISTS (
              SELECT 1
              FROM LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
              WHERE acl.grantee NOT IN (writer_oid, reader_oid)
                 OR (acl.grantee = reader_oid AND acl.is_grantable)
                 OR (
                     acl.grantee = reader_oid
                     AND acl.privilege_type <> 'SELECT'
                     AND NOT (
                         relation.relkind = 'S' AND acl.privilege_type = 'USAGE'
                     )
                 )
          )
      );

    SELECT pg_catalog.count(*) INTO default_acl_gap
    FROM pg_catalog.pg_default_acl AS default_acl
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = default_acl.defaclnamespace
    WHERE namespace.nspname = schema_name;

    -- Nothing to move and nothing to grant: an already-adopted tenant issues
    -- zero DDL here, which is what makes a re-run a genuine no-op.
    SELECT pg_catalog.count(*) INTO routine_gap
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = routine.pronamespace
    JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = routine.proowner
    WHERE namespace.nspname = schema_name
      AND (
          owner_role.rolname <> writer_name
          OR routine.prosecdef
          OR NOT EXISTS (
              -- prokind 'a' names the `internal` pseudo-language and says
              -- nothing about the functions that run; same exemption as the
              -- refusal above, or every aggregate keeps this gap open forever.
              SELECT 1 FROM pg_catalog.pg_language AS language
              WHERE language.oid = routine.prolang
                AND (language.lanpltrusted OR routine.prokind = 'a')
          )
          OR pg_catalog.has_function_privilege('public', routine.oid, 'EXECUTE')
          OR NOT pg_catalog.has_function_privilege(
              reader_name, routine.oid, 'EXECUTE'
          )
          -- The ACL itself, not just the two effective checks above: a named
          -- grantee or a grantable reader entry is invisible to both.
          OR EXISTS (
              SELECT 1
              FROM LATERAL pg_catalog.aclexplode(routine.proacl) AS acl
              WHERE acl.grantee NOT IN (writer_oid, reader_oid)
                 OR (acl.grantee = reader_oid AND acl.is_grantable)
          )
      );

    -- fix(#998 codex r48): extended statistics are schema objects with an
    -- owner of their own; a restore leaves them under the restore login and
    -- the writer can neither ALTER nor DROP them.
    SELECT pg_catalog.count(*) INTO statistics_gap
    FROM pg_catalog.pg_statistic_ext AS statistics_row
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = statistics_row.stxnamespace
    JOIN pg_catalog.pg_roles AS owner_role
      ON owner_role.oid = statistics_row.stxowner
    WHERE namespace.nspname = schema_name
      AND owner_role.rolname <> writer_name
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_depend AS dependency
          WHERE dependency.classid = 'pg_statistic_ext'::regclass
            AND dependency.objid = statistics_row.oid
            AND dependency.deptype = 'e'
      );

    -- fix(#998 codex r49): collations are the last owned object kind adoption
    -- transfers; everything rarer is refused below, so no owned object kind in
    -- a tenant schema is unhandled.
    SELECT pg_catalog.count(*) INTO collation_gap
    FROM pg_catalog.pg_collation AS collation_row
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = collation_row.collnamespace
    JOIN pg_catalog.pg_roles AS owner_role
      ON owner_role.oid = collation_row.collowner
    WHERE namespace.nspname = schema_name
      AND owner_role.rolname <> writer_name
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_depend AS dependency
          WHERE dependency.classid = 'pg_collation'::regclass
            AND dependency.objid = collation_row.oid
            AND dependency.deptype = 'e'
      );

    -- Owned object kinds a tenant schema has no business containing but a
    -- hand-crafted restore can: conversions, operators, operator classes and
    -- families, text search dictionaries and configurations.  Detected and
    -- refused rather than transferred — each has its own ALTER quirks, and an
    -- operator who created one can move it.
    SELECT pg_catalog.count(*) INTO other_object_gap
    FROM (
        SELECT conversion.oid, 'pg_conversion'::regclass AS classid
        FROM pg_catalog.pg_conversion AS conversion
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = conversion.connamespace
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = conversion.conowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
        UNION ALL
        SELECT operator.oid, 'pg_operator'::regclass
        FROM pg_catalog.pg_operator AS operator
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = operator.oprnamespace
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = operator.oprowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
        UNION ALL
        SELECT opclass.oid, 'pg_opclass'::regclass
        FROM pg_catalog.pg_opclass AS opclass
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = opclass.opcnamespace
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = opclass.opcowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
        UNION ALL
        SELECT opfamily.oid, 'pg_opfamily'::regclass
        FROM pg_catalog.pg_opfamily AS opfamily
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = opfamily.opfnamespace
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = opfamily.opfowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
        UNION ALL
        SELECT dictionary.oid, 'pg_ts_dict'::regclass
        FROM pg_catalog.pg_ts_dict AS dictionary
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = dictionary.dictnamespace
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = dictionary.dictowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
        UNION ALL
        SELECT config.oid, 'pg_ts_config'::regclass
        FROM pg_catalog.pg_ts_config AS config
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = config.cfgnamespace
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = config.cfgowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
    ) AS owned_object
    WHERE NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_depend AS dependency
        WHERE dependency.classid = owned_object.classid
          AND dependency.objid = owned_object.oid
          AND dependency.deptype = 'e'
    );

    SELECT pg_catalog.count(*) INTO type_gap
    FROM pg_catalog.pg_type AS type_row
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = type_row.typnamespace
    JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = type_row.typowner
    WHERE namespace.nspname = schema_name
      AND owner_role.rolname <> writer_name
      -- Array types follow their element type, a table's row type follows the
      -- table, and a range's generated multirange follows the range (14+):
      -- all move on their own, and ALTER TYPE on the multirange directly is
      -- refused (fix(#998 codex r46)). An extension's types belong to the
      -- extension.
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_type AS element
          WHERE element.typarray = type_row.oid
      )
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_range AS range_type
          WHERE range_type.rngmultitypid = type_row.oid
      )
      AND (
          type_row.typrelid = 0
          OR EXISTS (
              SELECT 1 FROM pg_catalog.pg_class AS relation
              WHERE relation.oid = type_row.typrelid AND relation.relkind = 'c'
          )
      )
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_depend AS dependency
          WHERE dependency.classid = 'pg_type'::regclass
            AND dependency.objid = type_row.oid
            AND dependency.deptype = 'e'
      );

    -- fix(#998 codex r45): an otherwise-canonical tenant can still carry an
    -- allowed privilege issued by a third-party grantor.  The five counters
    -- above are all zero then, and returning here would skip the refusal
    -- sweep at the end — leaving --apply to exit incomplete forever without
    -- ever naming the grantor.  Count them with the sweep's own shape; when
    -- the other counters are zero every owner already matches, so the shapes
    -- agree exactly.
    SELECT pg_catalog.count(*) INTO foreign_grantor_gap
    FROM (
        SELECT acl.grantor AS grantor_oid
        FROM pg_catalog.pg_namespace AS namespace
        JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl ON true
        WHERE namespace.nspname = schema_name
          AND acl.grantor <> (
              SELECT oid FROM pg_catalog.pg_roles
              WHERE rolname = '{PROVISIONER}'
          )
        UNION ALL
        SELECT acl.grantor
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl ON true
        WHERE namespace.nspname = schema_name
          AND acl.grantor <> writer_oid
        UNION ALL
        SELECT acl.grantor
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS column_row
          ON column_row.attrelid = relation.oid
        JOIN LATERAL pg_catalog.aclexplode(column_row.attacl) AS acl ON true
        WHERE namespace.nspname = schema_name
          AND NOT column_row.attisdropped
          AND acl.grantor <> writer_oid
        UNION ALL
        SELECT acl.grantor
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        JOIN LATERAL pg_catalog.aclexplode(routine.proacl) AS acl ON true
        WHERE namespace.nspname = schema_name
          AND acl.grantor <> writer_oid
    ) AS foreign_grant;

    -- fix(#998 codex r47): schema-less default privileges are not in
    -- default_acl_gap (it joins on the tenant schema), so without this an
    -- otherwise-canonical tenant returned here and the schema-less refusal
    -- later in the block was unreachable.
    SELECT pg_catalog.count(*) INTO global_default_acl_gap
    FROM pg_catalog.pg_default_acl AS default_acl
    JOIN pg_catalog.pg_roles AS owner_role
      ON owner_role.oid = default_acl.defaclrole
    WHERE default_acl.defaclnamespace = 0
      AND owner_role.rolname IN (reader_name, writer_name, '{PROVISIONER}');

    IF pending_owner_transfer = 0
       AND reader_privilege_gap = 0
       AND default_acl_gap = 0
       AND routine_gap = 0
       AND type_gap = 0
       AND statistics_gap = 0
       AND collation_gap = 0
       AND other_object_gap = 0
       AND foreign_grantor_gap = 0
       AND global_default_acl_gap = 0 THEN
        RETURN;
    END IF;

    -- The refusal for the exotic kinds counted above, before any DDL: the
    -- operator who created one can move it; this run does not guess at
    -- per-kind ALTER syntax.
    IF other_object_gap > 0 THEN
        RAISE EXCEPTION
            'tenant schema % contains % owned object(s) of a kind adoption '
            'does not transfer (conversion, operator, operator class or '
            'family, text search dictionary or configuration) not owned by %',
            schema_name, other_object_gap, writer_name
            USING HINT =
                'as their owner run the matching ALTER ... OWNER TO ' ||
                pg_catalog.quote_ident(writer_name) ||
                ' (\\dc, \\do, \\dAc, \\dAf, \\dFd and \\dF list them); then '
                're-run adoption';
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
            -- ALTER TABLE ... OWNER TO is the right statement for every other
            -- kind here, views and materialized views included: PostgreSQL
            -- accepts it for relkind v/m/f as well as r/p (measured on 18).
            EXECUTE pg_catalog.format(
                'ALTER TABLE %I.%I OWNER TO %I',
                schema_name, object_row.relname, writer_name
            );
        END IF;
    END LOOP;

    FOR object_row IN
        SELECT relation.relname AS relname,
               owner_role.rolname AS grantee_name
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = relation.relowner
        WHERE namespace.nspname = schema_name
          AND relation.relkind IN ({_RELATION_KINDS})
          AND owner_role.rolname <> writer_name
          -- Same exclusion as the transfer: a column-owned sequence follows its
          -- table, and one owned by a column in another schema is not something
          -- this loop can move.
          AND NOT {_COLUMN_OWNED_SEQUENCE}
    LOOP
        RAISE EXCEPTION
            'tenant schema % still contains %, owned by % rather than %',
            schema_name,
            object_row.relname,
            object_row.grantee_name,
            writer_name
            USING HINT =
                'as ' || pg_catalog.quote_ident(object_row.grantee_name) ||
                ' run: ALTER TABLE ' || pg_catalog.quote_ident(schema_name) ||
                '.' || pg_catalog.quote_ident(object_row.relname) ||
                ' OWNER TO ' || pg_catalog.quote_ident(writer_name) ||
                '; then re-run adoption';
    END LOOP;

    -- Default-privilege entries: cleared when this run can act as the role
    -- that owns them — itself, or the tenant writer whose SET edge it holds
    -- inside this window — and refused otherwise, on the same terms as the
    -- memberships above. Every object kind and every grantee: the contract in a
    -- tenant schema is that the writer grants the reader explicitly on each
    -- relation, so an entry here hands out privileges on relations that do not
    -- exist yet.
    -- fix(#998 codex r45): one statement per object kind — PostgreSQL accepts
    -- a single kind per ALTER DEFAULT PRIVILEGES, so aggregating kinds (or
    -- crossing grantees between kinds) rendered a remedy that fails to parse.
    FOR default_acl_row IN
        SELECT per_kind.owner_name,
               pg_catalog.string_agg(
                   'ALTER DEFAULT PRIVILEGES FOR ROLE ' ||
                   pg_catalog.quote_ident(per_kind.owner_name) ||
                   ' IN SCHEMA ' || pg_catalog.quote_ident(schema_name) ||
                   ' REVOKE ALL ON ' || per_kind.object_kind || ' FROM ' ||
                   per_kind.grantees,
                   '; '
               ) AS statements
        FROM (
            SELECT owner_role.rolname AS owner_name,
                   CASE default_acl.defaclobjtype
                       WHEN 'r' THEN 'TABLES'
                       WHEN 'S' THEN 'SEQUENCES'
                       WHEN 'f' THEN 'FUNCTIONS'
                       WHEN 'T' THEN 'TYPES'
                       ELSE 'SCHEMAS'
                   END AS object_kind,
                   pg_catalog.string_agg(
                       DISTINCT CASE
                           WHEN acl.grantee = 0 THEN 'PUBLIC'
                           ELSE pg_catalog.quote_ident(grantee_role.rolname)
                       END, ', '
                   ) AS grantees
            FROM pg_catalog.pg_default_acl AS default_acl
            JOIN pg_catalog.pg_roles AS owner_role
              ON owner_role.oid = default_acl.defaclrole
            JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) AS acl
              ON true
            LEFT JOIN pg_catalog.pg_roles AS grantee_role
              ON grantee_role.oid = acl.grantee
            JOIN pg_catalog.pg_namespace AS namespace
              ON namespace.oid = default_acl.defaclnamespace
            WHERE namespace.nspname = schema_name
              AND owner_role.rolname NOT IN (CURRENT_USER, writer_name)
              AND acl.grantee IS DISTINCT FROM default_acl.defaclrole
              AND NOT (
                  acl.grantee = 0 AND default_acl.defaclobjtype IN ('f', 'T')
              )
            GROUP BY owner_role.rolname, default_acl.defaclobjtype
        ) AS per_kind
        GROUP BY per_kind.owner_name
    LOOP
        RAISE EXCEPTION
            'schema % carries default privileges owned by %, which this role '
            'cannot act as',
            schema_name,
            default_acl_row.owner_name
            USING HINT =
                'as ' || pg_catalog.quote_ident(default_acl_row.owner_name) ||
                ' run: ' || default_acl_row.statements ||
                '; then re-run adoption';
    END LOOP;

    FOR default_acl_row IN
        SELECT owner_role.rolname AS owner_name,
               default_acl.defaclobjtype AS object_type,
               CASE
                   WHEN acl.grantee = 0 THEN 'PUBLIC'
                   ELSE pg_catalog.quote_ident(grantee_role.rolname)
               END AS grantee_name
        FROM pg_catalog.pg_default_acl AS default_acl
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = default_acl.defaclrole
        JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) AS acl ON true
        LEFT JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = acl.grantee
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = default_acl.defaclnamespace
        WHERE namespace.nspname = schema_name
          -- aclexplode also returns the entries PostgreSQL puts there itself:
          -- the owner's own privileges on every object kind, and PUBLIC's
          -- EXECUTE on functions and USAGE on types. Revoking one of those
          -- turns an ordinary additive default into a subtractive one, which is
          -- a worse state than the one being cleared and which only the owner
          -- could then reset. Functions and types have no other privilege to
          -- carry, so skipping PUBLIC entirely for them is exact.
          AND acl.grantee IS DISTINCT FROM default_acl.defaclrole
          AND NOT (
              acl.grantee = 0 AND default_acl.defaclobjtype IN ('f', 'T')
          )
    LOOP
        IF default_acl_row.owner_name <> CURRENT_USER THEN
            EXECUTE pg_catalog.format('SET ROLE %I', default_acl_row.owner_name);
        END IF;
        EXECUTE pg_catalog.format(
            'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON %s FROM %s',
            default_acl_row.owner_name,
            schema_name,
            CASE default_acl_row.object_type
                WHEN 'r' THEN 'TABLES'
                WHEN 'S' THEN 'SEQUENCES'
                WHEN 'f' THEN 'FUNCTIONS'
                WHEN 'T' THEN 'TYPES'
                ELSE 'SCHEMAS'
            END,
            default_acl_row.grantee_name
        );
        RESET ROLE;
    END LOOP;

    -- Default privileges with no schema at all apply to every schema the owner
    -- creates in, so a tenant role carrying one seeds a stray grant on the next
    -- table the writer makes. They belong to whoever set them.
    FOR default_acl_row IN
        SELECT owner_role.rolname AS owner_name
        FROM pg_catalog.pg_default_acl AS default_acl
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = default_acl.defaclrole
        WHERE default_acl.defaclnamespace = 0
          -- The provisioner as well as the tenant pair: the provisioning
          -- function runs as it and creates every future data_t_* schema, so a
          -- default of its own lands on tenants that do not exist yet.
          AND owner_role.rolname IN (reader_name, writer_name, '{PROVISIONER}')
    LOOP
        RAISE EXCEPTION
            'role % carries schema-less default privileges, which apply to '
            'every schema it creates in',
            default_acl_row.owner_name
            USING HINT =
                'as ' || pg_catalog.quote_ident(default_acl_row.owner_name) ||
                ' run: ALTER DEFAULT PRIVILEGES REVOKE ALL ON TABLES FROM PUBLIC '
                '(and the same for the other object kinds and grantees shown by '
                '\\ddp); then re-run adoption';
    END LOOP;

    -- A subtractive entry — ALTER DEFAULT PRIVILEGES ... REVOKE ... FROM PUBLIC
    -- — leaves a pg_default_acl row that aclexplode has nothing to show for, so
    -- the loop above cannot reach it. Restoring the built-in default means
    -- re-granting what was taken, which only the owner can decide.
    IF EXISTS (
        SELECT 1
        FROM pg_catalog.pg_default_acl AS default_acl
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = default_acl.defaclnamespace
        WHERE namespace.nspname = schema_name
    ) THEN
        RAISE EXCEPTION
            'schema % still carries a default-privilege entry after clearing '
            'every grant in it — a subtractive entry, which only its owner can '
            'reset',
            schema_name
            USING HINT =
                'inspect pg_default_acl for this schema and, as the defaclrole, '
                'ALTER DEFAULT PRIVILEGES ... GRANT the privilege back to '
                'restore the built-in default; then re-run adoption';
    END IF;

    -- Routines in a tenant schema. They live in pg_proc, so none of the
    -- relation sweeps above sees them, and a restore brings one back owned by
    -- the restore login — normally the superuser — with the default PUBLIC
    -- EXECUTE. The shared `data` schema has the same rule and the same reason
    -- (see scripts/lib/configure-runtime-db-role.sh): the runtime owns what it
    -- can create, and PUBLIC never executes it.
    --
    -- SECURITY DEFINER is the exception, and a refusal. Re-owning one is
    -- blessing a body adoption cannot vouch for — there is no migration behind
    -- it, unlike the two boundary functions — and leaving it is worse.
    FOR object_row IN
        SELECT routine.proname AS relname,
               pg_catalog.pg_get_function_identity_arguments(routine.oid) AS relkind
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        JOIN pg_catalog.pg_language AS language ON language.oid = routine.prolang
        WHERE namespace.nspname = schema_name
          -- SECURITY DEFINER is one way to run as somebody else; an untrusted
          -- language is the other, and it needs no privilege escalation to do
          -- native work inside the server. Neither is re-owned.
          --
          -- prokind 'a' is an aggregate: its pg_proc row names the `internal`
          -- pseudo-language, which is untrusted by definition and says nothing
          -- about the transition and final functions that actually run.
          AND (
              routine.prosecdef
              OR (NOT language.lanpltrusted AND routine.prokind <> 'a')
          )
    LOOP
        RAISE EXCEPTION
            'tenant schema % contains a SECURITY DEFINER or untrusted-language '
            'routine adoption will not re-own: %(%)',
            schema_name,
            object_row.relname,
            object_row.relkind
            USING HINT =
                'inspect it, then either ALTER ROUTINE ' || schema_name || '.' ||
                pg_catalog.quote_ident(object_row.relname) || '(' ||
                object_row.relkind || ') SECURITY INVOKER (if that is all that '
                'is wrong) or DROP it; then re-run adoption. ALTER ROUTINE '
                'covers functions and procedures alike';
    END LOOP;

    FOR object_row IN
        SELECT routine.proname AS relname,
               pg_catalog.pg_get_function_identity_arguments(routine.oid) AS relkind
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = routine.proowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
    LOOP
        EXECUTE pg_catalog.format(
            'ALTER ROUTINE %I.%I(%s) OWNER TO %I',
            schema_name,
            object_row.relname,
            object_row.relkind,
            writer_name
        );
    END LOOP;

    -- Types a tenant defined: enums, domains, ranges, standalone composites.
    -- They are in pg_type, so the relation pass never saw them, and a writer
    -- that cannot alter or drop one cannot replace the dataset that uses it.
    FOR object_row IN
        SELECT type_row.typname AS relname
        FROM pg_catalog.pg_type AS type_row
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = type_row.typnamespace
        JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = type_row.typowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
      -- Array types follow their element type, a table's row type follows the
      -- table, and a range's generated multirange follows the range (14+):
      -- all move on their own, and ALTER TYPE on the multirange directly is
      -- refused (fix(#998 codex r46)). An extension's types belong to the
      -- extension.
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_type AS element
          WHERE element.typarray = type_row.oid
      )
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_range AS range_type
          WHERE range_type.rngmultitypid = type_row.oid
      )
      AND (
          type_row.typrelid = 0
          OR EXISTS (
              SELECT 1 FROM pg_catalog.pg_class AS relation
              WHERE relation.oid = type_row.typrelid AND relation.relkind = 'c'
          )
      )
      AND NOT EXISTS (
          SELECT 1 FROM pg_catalog.pg_depend AS dependency
          WHERE dependency.classid = 'pg_type'::regclass
            AND dependency.objid = type_row.oid
            AND dependency.deptype = 'e'
      )
    LOOP
        EXECUTE pg_catalog.format(
            'ALTER TYPE %I.%I OWNER TO %I',
            schema_name,
            object_row.relname,
            writer_name
        );
    END LOOP;

    -- fix(#998 codex r48): extended statistics, same terms as the types
    -- above — restore-owned, and the writer cannot ALTER or DROP them.
    FOR object_row IN
        SELECT statistics_row.stxname AS relname
        FROM pg_catalog.pg_statistic_ext AS statistics_row
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = statistics_row.stxnamespace
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = statistics_row.stxowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend AS dependency
              WHERE dependency.classid = 'pg_statistic_ext'::regclass
                AND dependency.objid = statistics_row.oid
                AND dependency.deptype = 'e'
          )
    LOOP
        EXECUTE pg_catalog.format(
            'ALTER STATISTICS %I.%I OWNER TO %I',
            schema_name,
            object_row.relname,
            writer_name
        );
    END LOOP;

    -- fix(#998 codex r49): collations, same terms again.
    FOR object_row IN
        SELECT collation_row.collname AS relname
        FROM pg_catalog.pg_collation AS collation_row
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = collation_row.collnamespace
        JOIN pg_catalog.pg_roles AS owner_role
          ON owner_role.oid = collation_row.collowner
        WHERE namespace.nspname = schema_name
          AND owner_role.rolname <> writer_name
          AND NOT EXISTS (
              SELECT 1 FROM pg_catalog.pg_depend AS dependency
              WHERE dependency.classid = 'pg_collation'::regclass
                AND dependency.objid = collation_row.oid
                AND dependency.deptype = 'e'
          )
    LOOP
        EXECUTE pg_catalog.format(
            'ALTER COLLATION %I.%I OWNER TO %I',
            schema_name,
            object_row.relname,
            writer_name
        );
    END LOOP;

    EXECUTE pg_catalog.format('SET ROLE %I', writer_name);
    -- Revoke first, then grant back exactly the read privileges: ALTER TABLE …
    -- OWNER TO re-attributes the restored grants to the writer, so the writer
    -- can take away an INSERT or DELETE the old owner had handed the reader.
    EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I', schema_name, reader_name
    );
    EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %I', schema_name, reader_name
    );
    -- Tenant data is never PUBLIC, in either direction: a PUBLIC SELECT is a
    -- cross-tenant read and a PUBLIC INSERT is a cross-tenant write.
    EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM PUBLIC', schema_name
    );
    EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM PUBLIC', schema_name
    );
    -- Ownership only re-attributes the old owner's own grants, so a grant made
    -- by anyone else survives it — and the writer's REVOKE below reaches only
    -- what the writer granted. One sweep for all four surfaces a tenant schema
    -- exposes, because the answer is the same on each: this run cannot remove
    -- it, and the role that can is named in the remedy.
    FOR object_row IN
        SELECT foreign_grant.object_name AS relname,
               COALESCE(grantor_role.rolname, 'a dropped role') AS grantee_name
        FROM (
        SELECT 'schema ' || namespace.nspname AS object_name,
               acl.grantor AS grantor_oid
        FROM pg_catalog.pg_namespace AS namespace
        JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl ON true
        WHERE namespace.nspname = schema_name
          AND acl.grantor <> (SELECT oid FROM pg_catalog.pg_roles WHERE rolname = '{PROVISIONER}')
        UNION ALL
        SELECT 'relation ' || relation.relname, acl.grantor
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl ON true
        WHERE namespace.nspname = schema_name
          AND acl.grantor <> writer_oid
        UNION ALL
        SELECT 'column ' || relation.relname || '.' || column_row.attname,
               acl.grantor
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS column_row
          ON column_row.attrelid = relation.oid
        JOIN LATERAL pg_catalog.aclexplode(column_row.attacl) AS acl ON true
        WHERE namespace.nspname = schema_name
          AND NOT column_row.attisdropped
          AND acl.grantor <> writer_oid
        UNION ALL
        SELECT 'routine ' || routine.proname, acl.grantor
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        JOIN LATERAL pg_catalog.aclexplode(routine.proacl) AS acl ON true
        WHERE namespace.nspname = schema_name
          AND acl.grantor <> writer_oid
        ) AS foreign_grant
        LEFT JOIN pg_catalog.pg_roles AS grantor_role
          ON grantor_role.oid = foreign_grant.grantor_oid
    LOOP
        RAISE EXCEPTION
            'tenant schema % carries a privilege on % granted by %, which this '
            'run cannot revoke',
            schema_name,
            object_row.relname,
            object_row.grantee_name
            USING HINT =
                'as ' || pg_catalog.quote_ident(object_row.grantee_name) ||
                ' revoke it (\\dp and \\ddp in schema ' ||
                pg_catalog.quote_ident(schema_name) || ' show which), or drop '
                'that role; then re-run adoption';
    END LOOP;

    -- Column-level grants, which the table-level REVOKE ALL above leaves in
    -- place. Emitted per column and grantee because PostgreSQL has no
    -- schema-wide form for them.
    FOR object_row IN
        SELECT relation.relname AS relname,
               column_row.attname AS attname,
               CASE
                   WHEN acl.grantee = 0 THEN 'PUBLIC'
                   ELSE pg_catalog.quote_ident(grantee_role.rolname)
               END AS grantee_name
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN pg_catalog.pg_attribute AS column_row
          ON column_row.attrelid = relation.oid
        JOIN LATERAL pg_catalog.aclexplode(column_row.attacl) AS acl ON true
        LEFT JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = acl.grantee
        WHERE namespace.nspname = schema_name
          AND NOT column_row.attisdropped
          AND COALESCE(grantee_role.rolname, '') <> writer_name
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL (%I) ON %I.%I FROM %s',
            object_row.attname,
            schema_name,
            object_row.relname,
            object_row.grantee_name
        );
    END LOOP;

    -- And every other grantee the restore carried in. Only the writer (as
    -- owner) and the reader belong on a tenant relation.
    FOR grantee_name IN
        SELECT DISTINCT grantee_role.rolname
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl ON true
        JOIN pg_catalog.pg_roles AS grantee_role ON grantee_role.oid = acl.grantee
        WHERE namespace.nspname = schema_name
          AND relation.relkind IN ({_RELATION_KINDS})
          AND grantee_role.rolname NOT IN (writer_name, reader_name)
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM %I', schema_name, grantee_name
        );
        EXECUTE pg_catalog.format(
            'REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM %I',
            schema_name,
            grantee_name
        );
    END LOOP;
    EXECUTE pg_catalog.format(
        'GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I', schema_name, reader_name
    );
    EXECUTE pg_catalog.format(
        'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I',
        schema_name, reader_name
    );
    EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL ROUTINES IN SCHEMA %I FROM PUBLIC', schema_name
    );
    EXECUTE pg_catalog.format(
        'REVOKE ALL ON ALL ROUTINES IN SCHEMA %I FROM %I', schema_name, reader_name
    );
    -- Symmetric with the relation sweep: only the writer, as owner, and the
    -- reader belong on a tenant routine.
    FOR grantee_name IN
        SELECT DISTINCT
            CASE
                WHEN acl.grantee = 0 THEN 'PUBLIC'
                ELSE pg_catalog.quote_ident(grantee_role.rolname)
            END
        FROM pg_catalog.pg_proc AS routine
        JOIN pg_catalog.pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        JOIN LATERAL pg_catalog.aclexplode(routine.proacl) AS acl ON true
        LEFT JOIN pg_catalog.pg_roles AS grantee_role
          ON grantee_role.oid = acl.grantee
        WHERE namespace.nspname = schema_name
          AND COALESCE(grantee_role.rolname, '') NOT IN (writer_name, reader_name)
    LOOP
        EXECUTE pg_catalog.format(
            'REVOKE ALL ON ALL ROUTINES IN SCHEMA %I FROM %s',
            schema_name,
            grantee_name
        );
    END LOOP;
    EXECUTE pg_catalog.format(
        'GRANT EXECUTE ON ALL ROUTINES IN SCHEMA %I TO %I', schema_name, reader_name
    );
    RESET ROLE;

    IF temporary_writer_membership THEN
        EXECUTE pg_catalog.format('REVOKE %I FROM %I', writer_name, CURRENT_USER);
    END IF;
END
$$
"""
