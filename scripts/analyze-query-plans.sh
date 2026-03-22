#!/usr/bin/env bash
# =============================================================================
# scripts/analyze-query-plans.sh
# Reusable query plan analysis diagnostic for GeoLens PostgreSQL.
#
# Flags sequential scans, stale statistics, missing gid indexes, and
# top queries by execution time. Run from the project root.
#
# Phase 180 OPT-05: permanent project fixture.
# =============================================================================

set -euo pipefail

db_psql() {
  docker compose exec -T db psql -U geolens -d geolens "$@"
}

echo "=============================================="
echo " GeoLens Query Plan Analysis"
echo " $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
echo "=============================================="
echo

# ---------------------------------------------------------------------------
# Section 1: Sequential Scan Detection
# ---------------------------------------------------------------------------
echo "=== Section 1: Sequential Scan Detection ==="
echo "Tables with >1000 live tuples where seq_scan dominates idx_scan:"
echo
db_psql -c "
SELECT schemaname, relname,
       seq_scan, seq_tup_read,
       idx_scan, n_live_tup
FROM pg_stat_user_tables
WHERE n_live_tup > 1000
  AND seq_scan > 0
  AND (idx_scan IS NULL OR idx_scan = 0 OR seq_scan > idx_scan * 2)
ORDER BY seq_tup_read DESC
LIMIT 20;
"
echo

# ---------------------------------------------------------------------------
# Section 2: Stale Table Statistics
# ---------------------------------------------------------------------------
echo "=== Section 2: Stale Table Statistics ==="
echo "Tables with >100 live tuples where ANALYZE has not run recently:"
echo
db_psql -c "
SELECT schemaname, relname, n_live_tup,
       last_autoanalyze, last_analyze,
       CASE
         WHEN last_analyze IS NULL AND last_autoanalyze IS NULL
           THEN 'NEVER ANALYZED'
         WHEN GREATEST(
                COALESCE(last_analyze, '1970-01-01'::timestamptz),
                COALESCE(last_autoanalyze, '1970-01-01'::timestamptz)
              ) < now() - interval '1 day'
           THEN 'STALE'
         ELSE 'OK'
       END AS status
FROM pg_stat_user_tables
WHERE n_live_tup > 100
ORDER BY status DESC, n_live_tup DESC;
"
echo

# ---------------------------------------------------------------------------
# Section 3: Missing GID Indexes
# ---------------------------------------------------------------------------
echo "=== Section 3: Missing GID Indexes ==="
echo "Data-schema tables with >1000 rows that lack a gid index:"
echo
db_psql -c "
SELECT t.relname AS table_name, t.n_live_tup
FROM pg_stat_user_tables t
WHERE t.schemaname = 'data'
  AND t.n_live_tup > 1000
  AND NOT EXISTS (
    SELECT 1 FROM pg_indexes i
    WHERE i.schemaname = 'data'
      AND i.tablename = t.relname
      AND i.indexdef LIKE '%gid%'
  )
ORDER BY t.n_live_tup DESC;
"
echo

# ---------------------------------------------------------------------------
# Section 4: Top Queries by Time
# ---------------------------------------------------------------------------
echo "=== Section 4: Top Queries by Execution Time ==="
echo "Top 10 queries from pg_stat_statements:"
echo
db_psql -c "
SELECT LEFT(query, 80) AS query_preview,
       calls,
       ROUND(total_exec_time::numeric, 1) AS total_ms,
       ROUND(mean_exec_time::numeric, 1) AS mean_ms,
       rows
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'geolens')
ORDER BY total_exec_time DESC
LIMIT 10;
"

echo
echo "=== Analysis Complete ==="
