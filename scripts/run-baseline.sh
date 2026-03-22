#!/usr/bin/env bash
set -euo pipefail

# Baseline measurement orchestration script.
# Resets pg_stat_statements, runs warm-up + measured Locust load test,
# queries top-10 slowest queries, detects sequential scans, and captures
# auto_explain logs.
#
# Usage:
#   GEOLENS_API_KEY=<key> ./scripts/run-baseline.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$PROJECT_ROOT/tests/load/results"
LOAD_DIR="$PROJECT_ROOT/tests/load"

# Helper: run psql in the db container
db_psql() {
  docker compose -f "$PROJECT_ROOT/docker-compose.yml" exec -T db \
    psql -U geolens -d geolens "$@"
}

echo "========================================"
echo "  GeoLens Baseline Measurement"
echo "========================================"
echo ""

# ---------------------------------------------------------------
# 1. Preflight checks
# ---------------------------------------------------------------
echo "[1/9] Preflight checks..."

if [[ -z "${GEOLENS_API_KEY:-}" ]]; then
  echo "ERROR: GEOLENS_API_KEY is not set."
  echo "Usage: GEOLENS_API_KEY=<key> $0"
  exit 1
fi

# Check db container is running
if ! docker compose -f "$PROJECT_ROOT/docker-compose.yml" ps db --format json 2>/dev/null | grep -q '"running"'; then
  echo "ERROR: Database container is not running."
  echo "Start it with: docker compose up -d db"
  exit 1
fi

# Verify pg_stat_statements is accessible
if ! db_psql -c "SELECT count(*) FROM pg_stat_statements" > /dev/null 2>&1; then
  echo "ERROR: pg_stat_statements extension is not available."
  echo "Fix: docker compose exec db psql -U geolens -d geolens -c 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements'"
  exit 1
fi

# Verify datasets exist
DATASET_COUNT=$(db_psql -tAc "SELECT count(*) FROM catalog.datasets" 2>/dev/null || echo "0")
DATASET_COUNT=$(echo "$DATASET_COUNT" | tr -d '[:space:]')
if [[ "$DATASET_COUNT" -lt 100 ]]; then
  echo "WARNING: Only $DATASET_COUNT datasets found (expected 100+)."
  echo "Consider running: python scripts/seed-perf-data.py"
fi

echo "  API key: set"
echo "  Database: running"
echo "  pg_stat_statements: accessible"
echo "  Datasets: $DATASET_COUNT"
echo ""

# ---------------------------------------------------------------
# 2. Reset counters
# ---------------------------------------------------------------
echo "[2/9] Resetting pg_stat_statements counters..."
db_psql -c "SELECT pg_stat_statements_reset()" > /dev/null
echo "  Note: pg_stat_user_tables scan counters are cumulative and cannot be reset."
echo ""

# ---------------------------------------------------------------
# 3. Warm-up run (10s, 2 users)
# ---------------------------------------------------------------
echo "[3/9] Warm-up run (10s, 2 users)..."
(cd "$LOAD_DIR" && GEOLENS_API_KEY="$GEOLENS_API_KEY" \
  locust --headless -u 2 -r 2 --run-time 10s -f locustfile.py 2>&1 | tail -5)

echo "  Warm-up complete, resetting pg_stat_statements..."
db_psql -c "SELECT pg_stat_statements_reset()" > /dev/null
echo ""

# ---------------------------------------------------------------
# 4. Measured run (60s, 10 users)
# ---------------------------------------------------------------
echo "[4/9] Measured run (60s, 10 users)..."
(cd "$LOAD_DIR" && GEOLENS_API_KEY="$GEOLENS_API_KEY" \
  locust --headless -u 10 -r 2 --run-time 60s \
  --csv "$RESULTS_DIR/baseline" -f locustfile.py)
echo ""

# ---------------------------------------------------------------
# 5. Query pg_stat_statements top-10
# ---------------------------------------------------------------
echo "[5/9] Top-10 slowest queries by total execution time..."

TOP10_SQL="SELECT queryid,
       LEFT(query, 200) AS query_preview,
       calls,
       round(total_exec_time::numeric, 2) AS total_ms,
       round(mean_exec_time::numeric, 2) AS mean_ms,
       round(max_exec_time::numeric, 2) AS max_ms,
       rows
FROM pg_stat_statements
WHERE query NOT LIKE '%pg_stat_statements%'
  AND query NOT LIKE 'EXPLAIN%'
ORDER BY total_exec_time DESC
LIMIT 10;"

db_psql -c "$TOP10_SQL" | tee "$RESULTS_DIR/top10_queries.txt"
echo ""

# ---------------------------------------------------------------
# 6. Sequential scan detection
# ---------------------------------------------------------------
echo "[6/9] Sequential scan detection..."

SEQ_SCAN_SQL="SELECT schemaname,
       relname AS table_name,
       seq_scan,
       seq_tup_read,
       idx_scan,
       n_live_tup AS row_count
FROM pg_stat_user_tables
WHERE n_live_tup > 1000
  AND seq_scan > 0
  AND (idx_scan IS NULL OR idx_scan = 0 OR seq_scan > idx_scan * 2)
ORDER BY seq_tup_read DESC
LIMIT 20;"

db_psql -c "$SEQ_SCAN_SQL" | tee "$RESULTS_DIR/seq_scans.txt"
echo ""

# ---------------------------------------------------------------
# 7. Capture auto_explain logs
# ---------------------------------------------------------------
echo "[7/9] Capturing auto_explain logs from database..."
docker compose -f "$PROJECT_ROOT/docker-compose.yml" logs db --since=2m \
  > "$RESULTS_DIR/db_logs.txt" 2>&1

EXPLAIN_COUNT=$(grep -c "Query Text\|query plan" "$RESULTS_DIR/db_logs.txt" 2>/dev/null || echo "0")
echo "  Found $EXPLAIN_COUNT auto_explain entries."
echo ""

# ---------------------------------------------------------------
# 8. Prometheus metrics snapshot (pool + tile cache)
# ---------------------------------------------------------------
echo "[8/9] Scraping Prometheus metrics..."

METRICS_URL="${GEOLENS_BASE_URL:-http://localhost:8080}/api/metrics"
if curl -sf "$METRICS_URL" > /dev/null 2>&1; then
  curl -s "$METRICS_URL" | grep -E "^geolens_(db_pool|tile_cache)" \
    > "$RESULTS_DIR/prometheus_metrics.txt" 2>/dev/null
  echo "  Pool metrics:"
  grep "db_pool" "$RESULTS_DIR/prometheus_metrics.txt" 2>/dev/null | head -8
  echo "  Tile cache metrics:"
  grep "tile_cache" "$RESULTS_DIR/prometheus_metrics.txt" 2>/dev/null | head -4
else
  echo "  Prometheus /metrics endpoint not available (skipping)."
fi
echo ""

# ---------------------------------------------------------------
# 9. Summary
# ---------------------------------------------------------------
echo "[9/9] Summary"
echo "========================================"
echo "  Output files:"
echo "    $RESULTS_DIR/baseline_stats.csv"
echo "    $RESULTS_DIR/baseline_stats_history.csv"
echo "    $RESULTS_DIR/baseline_failures.csv"
echo "    $RESULTS_DIR/baseline_exceptions.csv"
echo "    $RESULTS_DIR/top10_queries.txt"
echo "    $RESULTS_DIR/seq_scans.txt"
echo "    $RESULTS_DIR/db_logs.txt"
echo "    $RESULTS_DIR/prometheus_metrics.txt"
echo "========================================"
echo ""
echo "Baseline measurement complete. Results in tests/load/results/"
