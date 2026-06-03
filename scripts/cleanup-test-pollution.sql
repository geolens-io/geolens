-- cleanup-test-pollution.sql
-- Removes test-created records from the dev database, leaving only the admin
-- user and the 4 seed datasets. Run once after enabling test isolation (15-01).
--
-- Usage:
--   docker compose exec -T db psql -U geolens -d geolens < scripts/cleanup-test-pollution.sql

BEGIN;

-- ============================================================
-- 1. Identify seed dataset table names for later use
-- ============================================================
-- Seed datasets: 'World Countries (110m)', 'World Populated Places',
--                'Major Rivers and Lakes', 'US State Capitals'

-- ============================================================
-- 2. Delete test data from catalog tables (FK-safe order)
-- ============================================================

-- Saved searches from non-admin users
DELETE FROM catalog.saved_searches
WHERE user_id NOT IN (SELECT id FROM catalog.users WHERE username = 'admin');

-- API keys from non-admin users
DELETE FROM catalog.api_keys
WHERE user_id NOT IN (SELECT id FROM catalog.users WHERE username = 'admin');

-- Audit logs from non-admin users
DELETE FROM catalog.audit_logs
WHERE user_id NOT IN (SELECT id FROM catalog.users WHERE username = 'admin');

-- Dataset grants for non-seed datasets
DELETE FROM catalog.dataset_grants
WHERE dataset_id IN (
    SELECT id FROM catalog.datasets
    WHERE name NOT IN (
        'World Countries (110m)',
        'World Populated Places',
        'Major Rivers and Lakes',
        'US State Capitals'
    )
);

-- Ingest jobs for non-seed datasets
DELETE FROM catalog.ingest_jobs
WHERE dataset_id IN (
    SELECT id FROM catalog.datasets
    WHERE name NOT IN (
        'World Countries (110m)',
        'World Populated Places',
        'Major Rivers and Lakes',
        'US State Capitals'
    )
);

-- Ingest jobs created by non-admin users (catch any with NULL dataset_id)
DELETE FROM catalog.ingest_jobs
WHERE created_by NOT IN (SELECT id FROM catalog.users WHERE username = 'admin');

-- Non-seed datasets
DELETE FROM catalog.datasets
WHERE name NOT IN (
    'World Countries (110m)',
    'World Populated Places',
    'Major Rivers and Lakes',
    'US State Capitals'
);

-- User-role mappings for non-admin users
DELETE FROM catalog.user_roles
WHERE user_id NOT IN (SELECT id FROM catalog.users WHERE username = 'admin');

-- Non-admin users
DELETE FROM catalog.users
WHERE username != 'admin';

-- ============================================================
-- 3. Drop test data tables from the 'data' schema
-- ============================================================
DO $$
DECLARE
    seed_tables text[];
    tbl text;
    dropped int := 0;
BEGIN
    -- Collect table names belonging to seed datasets
    SELECT array_agg(table_name) INTO seed_tables
    FROM catalog.datasets
    WHERE name IN (
        'World Countries (110m)',
        'World Populated Places',
        'Major Rivers and Lakes',
        'US State Capitals'
    );

    -- Drop every data-schema table that is NOT a seed table
    FOR tbl IN
        SELECT tablename FROM pg_tables WHERE schemaname = 'data'
    LOOP
        IF tbl != ALL(COALESCE(seed_tables, ARRAY[]::text[])) THEN
            EXECUTE format('DROP TABLE IF EXISTS data.%I CASCADE', tbl);
            dropped := dropped + 1;
            RAISE NOTICE 'Dropped test table: data.%', tbl;
        END IF;
    END LOOP;

    RAISE NOTICE 'Dropped % test table(s) from data schema', dropped;
END $$;

-- ============================================================
-- 4. Re-grant reader access on remaining data tables
-- ============================================================
GRANT USAGE ON SCHEMA data TO geolens_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA data TO geolens_reader;

COMMIT;

-- ============================================================
-- 5. Summary counts (outside transaction for visibility)
-- ============================================================
\echo '--- Cleanup complete. Verification counts: ---'
SELECT 'users' AS table_name, count(*) AS row_count FROM catalog.users
UNION ALL
SELECT 'datasets', count(*) FROM catalog.datasets
UNION ALL
SELECT 'saved_searches', count(*) FROM catalog.saved_searches
UNION ALL
SELECT 'audit_logs', count(*) FROM catalog.audit_logs
UNION ALL
SELECT 'ingest_jobs', count(*) FROM catalog.ingest_jobs
UNION ALL
SELECT 'api_keys', count(*) FROM catalog.api_keys
UNION ALL
SELECT 'data_tables', count(*) FROM pg_tables WHERE schemaname = 'data'
ORDER BY table_name;
