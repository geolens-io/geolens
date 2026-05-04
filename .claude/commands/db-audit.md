# /db-audit — PostgreSQL Configuration & Runtime Health Audit

Audit PostgreSQL configuration, runtime health, and operational readiness for GeoLens's triple-extension stack (PostGIS + pgvector + pg_trgm). This stack has unique tuning requirements: PostGIS spatial indexing competes with pgvector HNSW for work_mem, pg_trgm GIN indexes compete with both for maintenance_work_mem, and the target 2GB VPS means every MB of shared_buffers matters. Generic PostgreSQL tuning advice will over-allocate.

**Usage:** `/db-audit` (full audit) or `/db-audit <area>` where area is `config`, `bloat`, `extensions`, `queries`, `connections`, or `backup`

---

## INTAKE (Serial — do this first)

### Step 1: Check if the Docker stack is running

```bash
docker compose ps
```

If the `db` service is not running, fall back to static analysis of docker-compose.yml and code only. Note this limitation in the report.

### Step 2: Read Docker Compose PostgreSQL settings

```bash
# Docker Compose PG configuration (command flags, environment vars, volumes)
cat docker-compose.yml 2>/dev/null | grep -A 30 "^\s*db:"
```

### Step 3: Read backend connection configuration

```bash
# Connection settings, pool config, database URL construction
cat backend/app/core/config.py 2>/dev/null

# Database session/engine setup
find backend/app -name "database.py" -o -name "db.py" -o -name "session.py" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done
```

### Step 4: Get current PostgreSQL runtime settings (if DB is running)

```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "SHOW ALL;" 2>/dev/null | grep -E "shared_buffers|work_mem|effective_cache_size|maintenance_work_mem|max_connections|random_page_cost|jit|max_worker_processes|max_parallel_workers|checkpoint_completion_target|wal_buffers|min_wal_size|max_wal_size|autovacuum|log_min_duration"
```

### Step 5: Get extension versions

```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "SELECT extname, extversion FROM pg_extension ORDER BY extname;" 2>/dev/null || echo "NO_DB_CONNECTION"
```

### Step 6: Get table sizes and row counts

```bash
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
  SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid))
  FROM pg_stat_user_tables
  ORDER BY pg_total_relation_size(relid) DESC
  LIMIT 20;
" 2>/dev/null || echo "NO_DB_CONNECTION"
```

---

## 2GB VPS TUNING RULES (Embedded)

These are the target-appropriate settings for GeoLens on a 2GB RAM / 1 vCPU VPS (~$20/mo). Deviations from these values should be flagged with context about *why* the target value matters for this stack.

### Memory allocation budget (2GB total)

| Setting | Target | Rationale |
|---------|--------|-----------|
| `shared_buffers` | 512MB | 25% of RAM — standard PG guideline. Larger wastes memory on 2GB. |
| `effective_cache_size` | 1.5GB | 75% of RAM — tells planner how much OS cache to expect. |
| `work_mem` | 4-8MB | Careful: PostGIS complex queries * max_connections can exhaust RAM. 8MB * 30 connections = 240MB worst case. |
| `maintenance_work_mem` | 128MB | For VACUUM and index builds. PostGIS GiST, pgvector HNSW, and pg_trgm GIN all compete here. |
| `wal_buffers` | 16MB | Standard for any deployment with write activity. |

### Connection limits

| Setting | Target | Rationale |
|---------|--------|-----------|
| `max_connections` | 20-30 | asyncpg pool should be 5-10. Each connection consumes ~5-10MB. 100 connections = 500MB-1GB wasted. |
| `max_worker_processes` | 2 | 1 vCPU — don't over-subscribe. Each parallel worker is a full process. |
| `max_parallel_workers` | 2 | Match max_worker_processes. |
| `max_parallel_workers_per_gather` | 1 | Single vCPU — at most 1 parallel worker per query. |

### Disk and I/O

| Setting | Target | Rationale |
|---------|--------|-----------|
| `random_page_cost` | 1.1 | SSD (Docker volume on VPS SSD). Default 4.0 biases planner against index scans. |
| `checkpoint_completion_target` | 0.9 | Spread checkpoint writes to reduce I/O spikes. |
| `min_wal_size` | 100MB | Reasonable floor for write-moderate workload. |
| `max_wal_size` | 1GB | Cap WAL disk usage on small VPS. |

### Extension compatibility

| Setting | Target | Rationale |
|---------|--------|-----------|
| `jit` | off | **Required.** pgvector + JIT causes crashes and hangs. This is not a performance concern — it is a correctness requirement. |

---

## SUBAGENT DISPATCH (Parallel)

Run these 6 subagents in parallel.

### Subagent 1: Configuration Tuning

**Goal:** Compare actual PostgreSQL settings against the 2GB VPS targets above. Identify dangerous defaults and misconfigured values.

**Process:**

1. **Docker Compose command flags:**
   ```bash
   # Extract PostgreSQL command-line flags from docker-compose.yml
   grep -A 50 "^\s*db:" docker-compose.yml 2>/dev/null | grep -E "command:|^\s*-c\s|^\s*-\s.*="

   # Check for postgresql.conf mount
   grep -A 50 "^\s*db:" docker-compose.yml 2>/dev/null | grep -E "volumes:|postgresql.conf|pg_hba.conf"
   ```

2. **Compare runtime settings to targets:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT name, setting, unit, source, boot_val
     FROM pg_settings
     WHERE name IN (
       'shared_buffers', 'work_mem', 'effective_cache_size',
       'maintenance_work_mem', 'max_connections', 'random_page_cost',
       'jit', 'max_worker_processes', 'max_parallel_workers',
       'max_parallel_workers_per_gather', 'checkpoint_completion_target',
       'wal_buffers', 'min_wal_size', 'max_wal_size',
       'autovacuum', 'log_min_duration_statement'
     )
     ORDER BY name;
   " 2>/dev/null
   ```

   For each setting, classify:
   - **Dangerous default** — PostgreSQL default that will cause problems (e.g., `shared_buffers=128MB`, `max_connections=100`, `random_page_cost=4.0`)
   - **Over-allocated** — Value too high for 2GB VPS (e.g., `work_mem=64MB`, `max_worker_processes=8`)
   - **Under-allocated** — Value too low for the workload (e.g., `shared_buffers=32MB`)
   - **Correct** — Matches or is within acceptable range of target

3. **Memory budget check:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       current_setting('shared_buffers') AS shared_buffers,
       current_setting('work_mem') AS work_mem,
       current_setting('maintenance_work_mem') AS maintenance_work_mem,
       current_setting('max_connections') AS max_connections;
   " 2>/dev/null
   ```

   Calculate worst-case memory usage:
   - `shared_buffers` + (`work_mem` * `max_connections`) + `maintenance_work_mem` + OS overhead (~500MB)
   - If total > 2GB, flag as memory exhaustion risk

4. **Logging configuration:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT name, setting FROM pg_settings
     WHERE name LIKE 'log%' AND setting != 'off' AND setting != '-1'
     ORDER BY name;
   " 2>/dev/null
   ```

   Check for:
   - `log_min_duration_statement` — should be set (e.g., 1000ms) to catch slow queries
   - `log_checkpoints` — should be on for I/O monitoring
   - `log_connections` / `log_disconnections` — useful for connection leak detection

**Output:** Settings comparison table — Setting | Current | Target | Status (Correct/Over/Under/Dangerous) | Impact.

---

### Subagent 2: Extension Health

**Goal:** Verify extension version compatibility and configuration for the PostGIS 3.5 + pgvector + pg_trgm stack on PostgreSQL 17.

**Process:**

1. **Extension version matrix:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT extname, extversion, extrelocatable
     FROM pg_extension
     ORDER BY extname;
   " 2>/dev/null
   ```

   Verify compatibility:
   - PostGIS 3.5 on PG 17 — supported since PostGIS 3.5.0
   - pgvector on PG 17 — check version (0.5.0+ for HNSW, 0.7.0+ for halfvec)
   - pg_trgm on PG 17 — bundled contrib module, always compatible

2. **Extension-specific settings verification:**
   ```bash
   # JIT must be off for pgvector
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "SHOW jit;" 2>/dev/null

   # PostGIS configuration
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "SELECT PostGIS_Full_Version();" 2>/dev/null

   # pgvector available index types
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT amname FROM pg_am WHERE amname IN ('ivfflat', 'hnsw');
   " 2>/dev/null
   ```

3. **Extension function usage vs version requirements:**
   ```bash
   # PostGIS functions used in application code
   grep -rn "ST_\|AddGeometryColumn\|UpdateGeometrySRID\|Populate_Geometry_Columns" backend/app/ --include="*.py" | grep -v __pycache__

   # pgvector operators used
   grep -rn "<->\|<#>\|<=>\|cosine_distance\|l2_distance\|inner_product" backend/app/ --include="*.py" | grep -v __pycache__

   # pg_trgm functions used
   grep -rn "similarity\|word_similarity\|strict_word_similarity\|show_trgm\|gin_trgm_ops\|gist_trgm_ops" backend/app/ --include="*.py" | grep -v __pycache__
   ```

   Cross-reference each function against the installed extension version to confirm availability.

4. **Extension upgrade path safety:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT * FROM pg_available_extension_versions
     WHERE name IN ('postgis', 'vector', 'pg_trgm')
     ORDER BY name, version;
   " 2>/dev/null
   ```

   Flag if current version is outdated and an upgrade is available in the image.

**Output:** Extension compatibility matrix — Extension | Installed version | Min required | Functions used | Compatible | Upgrade available.

---

### Subagent 3: Table & Index Bloat

**Goal:** Detect table and index bloat, autovacuum health, and toast table overhead — especially for large geometry, raster, and embedding columns.

**Process:**

1. **Dead tuple accumulation:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       relname,
       n_live_tup,
       n_dead_tup,
       CASE WHEN n_live_tup > 0
           THEN round(100.0 * n_dead_tup / n_live_tup, 1)
           ELSE 0
       END AS dead_pct,
       last_vacuum,
       last_autovacuum,
       last_analyze,
       last_autoanalyze
     FROM pg_stat_user_tables
     ORDER BY n_dead_tup DESC
     LIMIT 20;
   " 2>/dev/null
   ```

   Flag:
   - Tables with dead tuple percentage > 20% (autovacuum may be struggling)
   - Tables never vacuumed or analyzed
   - Tables with last vacuum > 24 hours ago and active writes

2. **Table bloat estimation:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       current_database(), schemaname, tablename,
       pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename)) AS total_size,
       pg_size_pretty(pg_relation_size(schemaname || '.' || tablename)) AS table_size,
       pg_size_pretty(pg_total_relation_size(schemaname || '.' || tablename) - pg_relation_size(schemaname || '.' || tablename)) AS index_toast_size
     FROM pg_tables
     WHERE schemaname = 'public'
     ORDER BY pg_total_relation_size(schemaname || '.' || tablename) DESC
     LIMIT 20;
   " 2>/dev/null
   ```

3. **Index bloat estimation:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       schemaname, relname, indexrelname,
       pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
       idx_scan,
       idx_tup_read,
       idx_tup_fetch
     FROM pg_stat_user_indexes
     ORDER BY pg_relation_size(indexrelid) DESC
     LIMIT 20;
   " 2>/dev/null
   ```

   Flag:
   - Indexes larger than the table they belong to (common with GiST/GIN on geometry/trgm)
   - Indexes with 0 scans (unused — wasting memory and slowing writes)
   - Duplicate indexes on the same columns

4. **Autovacuum settings:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT name, setting FROM pg_settings
     WHERE name LIKE 'autovacuum%'
     ORDER BY name;
   " 2>/dev/null
   ```

   Check:
   - `autovacuum_vacuum_scale_factor` — default 0.2 (20%). May need 0.05 for large tables.
   - `autovacuum_analyze_scale_factor` — default 0.1 (10%). Should be lower for large tables.
   - `autovacuum_vacuum_threshold` — default 50 rows. Fine for most tables.
   - `autovacuum_max_workers` — default 3. On 1 vCPU, 1-2 is more appropriate.

5. **Toast table overhead:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       c.relname AS table_name,
       t.relname AS toast_table,
       pg_size_pretty(pg_relation_size(t.oid)) AS toast_size
     FROM pg_class c
     JOIN pg_class t ON c.reltoastrelid = t.oid
     WHERE c.relkind = 'r' AND c.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
     ORDER BY pg_relation_size(t.oid) DESC
     LIMIT 10;
   " 2>/dev/null
   ```

   Large toast tables indicate oversized geometry, raster, or JSONB columns that may benefit from compression tuning.

**Output:** Bloat summary — Table | Live rows | Dead rows | Dead % | Last vacuum | Table size | Index size | Toast size | Action needed.

---

### Subagent 4: Query Performance

**Goal:** Identify hot queries, check for missing indexes, and evaluate spatial query performance.

**Process:**

1. **Identify hot queries from code:**
   ```bash
   # SQLAlchemy query patterns
   grep -rn "session.execute\|session.query\|select(\|text(" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Spatial query patterns (need GiST indexes)
   grep -rn "ST_Intersects\|ST_DWithin\|ST_Contains\|ST_Within\|ST_Distance\|ST_Covers\|ST_Touches\|func.ST_" backend/app/ --include="*.py" | grep -v __pycache__

   # Vector similarity queries (need HNSW/IVFFlat indexes)
   grep -rn "<->\|<#>\|<=>\|cosine_distance\|l2_distance\|nearest_neighbor\|similarity_search" backend/app/ --include="*.py" | grep -v __pycache__

   # Text search queries (need GIN/GiST trgm indexes)
   grep -rn "ILIKE\|LIKE\|similarity\|trgm\|to_tsvector\|@@\|plainto_tsquery" backend/app/ --include="*.py" | grep -v __pycache__
   ```

2. **Check for sequential scans on large tables:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       relname,
       seq_scan,
       seq_tup_read,
       idx_scan,
       CASE WHEN (seq_scan + idx_scan) > 0
           THEN round(100.0 * seq_scan / (seq_scan + idx_scan), 1)
           ELSE 0
       END AS seq_scan_pct,
       n_live_tup
     FROM pg_stat_user_tables
     WHERE n_live_tup > 1000
     ORDER BY seq_scan_pct DESC;
   " 2>/dev/null
   ```

   Flag tables with >50% sequential scans and >1000 rows — likely missing an index.

3. **Index usage stats:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       schemaname, relname, indexrelname,
       idx_scan, idx_tup_read, idx_tup_fetch,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size
     FROM pg_stat_user_indexes
     ORDER BY idx_scan DESC
     LIMIT 20;
   " 2>/dev/null
   ```

4. **Missing indexes on foreign keys:**
   ```bash
   # Foreign keys in models — check if indexed
   grep -rn "ForeignKey" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v alembic

   # Check live database for unindexed foreign keys
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       conrelid::regclass AS table_name,
       conname AS constraint_name,
       a.attname AS column_name
     FROM pg_constraint c
     JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
     WHERE c.contype = 'f'
     AND NOT EXISTS (
       SELECT 1 FROM pg_index i
       WHERE i.indrelid = c.conrelid
       AND a.attnum = ANY(i.indkey)
     );
   " 2>/dev/null
   ```

5. **EXPLAIN ANALYZE on representative spatial queries (if DB has data):**
   ```bash
   # Check if there is data to query
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT relname, n_live_tup
     FROM pg_stat_user_tables
     WHERE n_live_tup > 0
     ORDER BY n_live_tup DESC
     LIMIT 5;
   " 2>/dev/null
   ```

   If spatial tables have data, run EXPLAIN ANALYZE on representative queries from the codebase. Look for:
   - Seq Scan where Index Scan is expected
   - Nested Loop with high row estimates
   - Sort operations without index support

6. **Slow query detection:**
   ```bash
   # Check if pg_stat_statements is available
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';
   " 2>/dev/null

   # If available, get top slow queries
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       calls,
       round(mean_exec_time::numeric, 2) AS avg_ms,
       round(total_exec_time::numeric, 2) AS total_ms,
       rows,
       left(query, 100) AS query
     FROM pg_stat_statements
     ORDER BY mean_exec_time DESC
     LIMIT 10;
   " 2>/dev/null
   ```

**Output:** Query performance summary — Query pattern | Source file | Index available | Scan type | Estimated cost | Recommendation.

---

### Subagent 5: Connection Management

**Goal:** Verify asyncpg pool configuration against max_connections, detect connection leaks, and assess pool exhaustion risk under concurrent load.

**Process:**

1. **asyncpg pool settings in code:**
   ```bash
   # Engine/pool configuration
   grep -rn "create_async_engine\|pool_size\|max_overflow\|pool_timeout\|pool_recycle\|pool_pre_ping\|connect_args" backend/app/ --include="*.py" | grep -v __pycache__

   # Database URL construction
   grep -rn "DATABASE_URL\|SQLALCHEMY_DATABASE_URI\|postgresql+asyncpg\|postgresql+psycopg" backend/app/ --include="*.py" | grep -v __pycache__

   # Alembic connection (separate driver — psycopg, not asyncpg)
   grep -rn "sqlalchemy.url\|connection\|connectable" backend/alembic/ --include="*.py" --include="*.ini" 2>/dev/null
   ```

   Verify:
   - `pool_size` + `max_overflow` <= `max_connections` (with headroom for Alembic and admin)
   - `pool_pre_ping` is enabled (detects stale connections)
   - `pool_recycle` is set (prevents long-lived connections from going stale)

2. **Current connection state (if DB is running):**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       count(*) AS total,
       count(*) FILTER (WHERE state = 'active') AS active,
       count(*) FILTER (WHERE state = 'idle') AS idle,
       count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_tx,
       count(*) FILTER (WHERE wait_event_type IS NOT NULL) AS waiting
     FROM pg_stat_activity
     WHERE backend_type = 'client backend';
   " 2>/dev/null
   ```

   Flag:
   - `idle in transaction` connections — indicates uncommitted transactions (potential leak)
   - Connection count approaching `max_connections`
   - Connections open longer than expected (`pool_recycle` may not be set)

3. **Connection detail:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       pid, state, wait_event_type, wait_event,
       age(clock_timestamp(), backend_start) AS connection_age,
       age(clock_timestamp(), state_change) AS state_age,
       left(query, 80) AS current_query
     FROM pg_stat_activity
     WHERE backend_type = 'client backend'
     ORDER BY backend_start;
   " 2>/dev/null
   ```

4. **Connection leak detection patterns in code:**
   ```bash
   # Sessions not properly closed — missing async with, missing close()
   grep -rn "AsyncSession\|get_db\|get_session\|Depends.*Session" backend/app/ --include="*.py" | grep -v __pycache__

   # Background tasks that might hold connections
   grep -rn "BackgroundTask\|background_tasks\|create_task\|asyncio.create_task" backend/app/ --include="*.py" | grep -v __pycache__
   ```

   Common leak patterns:
   - Background tasks that receive a session but outlive the request
   - Exception paths that skip session cleanup
   - `session.begin()` without matching `commit()` or `rollback()` in error handlers

5. **Pool exhaustion risk calculation:**
   ```
   Available connections = max_connections - superuser_reserved_connections (default 3)
   App pool demand = pool_size + max_overflow
   Other consumers = Alembic (1) + admin psql (1-2)
   Headroom = Available - App pool demand - Other consumers
   ```

   If headroom < 3, flag as pool exhaustion risk.

**Output:** Connection management summary — Pool size | Max overflow | Max connections | Current active | Idle in transaction | Leak risk | Exhaustion headroom.

---

### Subagent 6: Backup & Recovery

**Goal:** Assess backup strategy, recovery feasibility, and WAL configuration for the target VPS deployment.

**Process:**

1. **Existing backup strategy:**
   ```bash
   # Check for backup scripts, cron jobs, or documentation
   find . -name "*backup*" -o -name "*dump*" -o -name "*restore*" 2>/dev/null | grep -v node_modules | grep -v __pycache__ | grep -v .git

   # Docker volume configuration (where data lives)
   grep -A 10 "volumes:" docker-compose.yml 2>/dev/null

   # Check for backup-related environment variables
   grep -rn "BACKUP\|DUMP\|RESTORE\|S3.*BUCKET\|AWS.*BACKUP" docker-compose.yml .env .env.example backend/app/core/config.py 2>/dev/null
   ```

2. **Current database size (for dump time estimation):**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       pg_size_pretty(pg_database_size(current_database())) AS db_size;
   " 2>/dev/null
   ```

   Estimate pg_dump time: ~1 minute per GB on VPS SSD. Add 50% for PostGIS geometry serialization.

3. **WAL configuration for PITR:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT name, setting FROM pg_settings
     WHERE name IN (
       'wal_level', 'archive_mode', 'archive_command',
       'max_wal_senders', 'wal_keep_size',
       'min_wal_size', 'max_wal_size',
       'checkpoint_completion_target'
     )
     ORDER BY name;
   " 2>/dev/null
   ```

   For PITR capability:
   - `wal_level` must be `replica` or `logical` (default `replica` since PG 10)
   - `archive_mode` must be `on` with a valid `archive_command`
   - If not configured, PITR is not available — flag as informational, not critical

4. **Large object and BLOB handling:**
   ```bash
   # Check for large objects that pg_dump might miss with --no-blobs
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT count(*) AS large_object_count FROM pg_largeobject_metadata;
   " 2>/dev/null

   # Raster data storage (large binary in toast tables)
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT
       c.relname,
       pg_size_pretty(pg_relation_size(t.oid)) AS toast_size
     FROM pg_class c
     JOIN pg_class t ON c.reltoastrelid = t.oid
     WHERE pg_relation_size(t.oid) > 10485760
     ORDER BY pg_relation_size(t.oid) DESC;
   " 2>/dev/null
   ```

5. **Recovery time objective estimate:**
   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh -c "
     SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size;
   " 2>/dev/null
   ```

   Calculate RTO:
   - pg_restore from dump: ~2 minutes per GB on VPS
   - Index rebuild (spatial + vector): add 50-100% to base restore time
   - PostGIS GiST indexes are slow to rebuild on large geometry datasets
   - pgvector HNSW indexes are very slow to rebuild (O(n log n))

6. **Docker volume durability:**
   ```bash
   # Is the PG data directory on a named volume or bind mount?
   grep -A 20 "^\s*db:" docker-compose.yml 2>/dev/null | grep -E "volumes:|/var/lib/postgresql"

   # Is the volume backed by persistent storage?
   docker volume ls 2>/dev/null | grep -i geo
   ```

   Flag:
   - Anonymous volumes (data lost on `docker compose down -v`)
   - No named volume or bind mount for `/var/lib/postgresql/data`
   - Missing documentation on volume backup procedures

**Output:** Backup & recovery summary — Backup strategy | DB size | Estimated dump time | RTO estimate | WAL/PITR status | Volume durability | Recommendations.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

| Dimension | What it measures |
|-----------|-----------------|
| **Configuration Tuning** | Settings match 2GB VPS target, no dangerous defaults |
| **Extension Health** | Version compatibility, jit=off verified, function availability |
| **Table & Index Bloat** | Autovacuum health, dead tuples, index overhead |
| **Query Performance** | Index coverage, no full scans on large tables, spatial query efficiency |
| **Connection Management** | Pool sized correctly, no leaks, exhaustion headroom |
| **Backup & Recovery** | Backup strategy exists, RTO is acceptable, volume is durable |

Grade each A-F using:
- **A** — No issues. Production-ready configuration.
- **B** — Minor issues. Suboptimal settings, cosmetic. No data risk.
- **C** — Significant issues. Dangerous defaults, missing indexes. Deployable but underperforming.
- **D** — Dangerous issues. Memory exhaustion risk, connection leaks, no backups.
- **F** — Broken. Database won't start, extensions incompatible, data at risk.

**Overall DB health** = minimum grade (the weakest dimension determines production readiness).

### Action Items

| Field | Description |
|-------|-------------|
| Priority | P0 (database will crash/corrupt), P1 (performance degradation or data loss risk), P2 (suboptimal but functional) |
| Action | Specific fix — include file, setting name, current and target values |
| Dimension | Which audit dimension |
| Effort | Hours estimate |
| Risk if unfixed | What breaks |

Sort by priority, then effort.

### DB Health Summary

Summarize total database debt:
- Number of settings at dangerous defaults
- Memory budget utilization (current vs 2GB target)
- Number of tables with excessive bloat (>20% dead tuples)
- Number of unindexed spatial/vector queries
- Connection headroom (remaining connections available)
- Backup gap (none / dump-only / PITR-ready)
- Total estimated hours to resolve all P0 + P1 items

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/db-audit-{YYYYMMDD}.md`

### Report structure

```markdown
# DB Audit — {YYYY-MM-DD}

## Scorecard
<!-- Letter grades + overall health -->

## Executive Summary
<!-- 3-5 sentences: DB configuration state, biggest risks, top fix -->

## 1. Configuration Tuning
<!-- Subagent 1 findings — settings comparison table -->

## 2. Extension Health
### 2a. PostGIS
### 2b. pgvector
### 2c. pg_trgm
<!-- Subagent 2 findings -->

## 3. Table & Index Bloat
### 3a. Dead Tuples & Autovacuum
### 3b. Table Sizes
### 3c. Index Bloat
### 3d. Toast Overhead
<!-- Subagent 3 findings -->

## 4. Query Performance
### 4a. Sequential Scan Detection
### 4b. Missing Indexes
### 4c. Spatial Query Plans
### 4d. Slow Query Log
<!-- Subagent 4 findings -->

## 5. Connection Management
### 5a. Pool Configuration
### 5b. Active Connections
### 5c. Leak Detection
### 5d. Exhaustion Risk
<!-- Subagent 5 findings -->

## 6. Backup & Recovery
### 6a. Current Strategy
### 6b. Recovery Time Estimate
### 6c. WAL / PITR Status
### 6d. Volume Durability
<!-- Subagent 6 findings -->

## 7. DB Health Summary
<!-- Aggregate metrics -->

## 8. Prioritized Action Items
<!-- Action items table -->

## 9. Comparison to Prior Audit
<!-- If a previous db-audit exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append reusable insights about PostgreSQL tuning for PostGIS + pgvector + pg_trgm stacks.
2. Print one-line summary: overall grade + P0 count + total DB debt hours.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/migration-audit` — covers Alembic migration chain health. This command covers the running database.
- `/perf-profile` — covers application-level performance. This command covers database-level configuration and health.
- `/env-audit` — covers environment variable configuration. This command covers whether DATABASE_URL and PG settings are correct.

---

## WHAT NOT TO FLAG

Avoid false positives on these:

- **Default PostgreSQL settings in a development Docker Compose** — development != production. Flag as informational, not as errors. The audit targets production readiness, but dev environments should not receive alarming grades.
- **Missing connection pooler (PgBouncer)** — asyncpg has built-in pooling. PgBouncer is only needed at scale beyond what a single FastAPI process handles. Do not recommend PgBouncer unless max_connections is genuinely exhausted.
- **Autovacuum running on small tables (<1000 rows)** — this is normal PostgreSQL behavior. Autovacuum on small tables has negligible cost.
- **Extension versions that are the latest available in the Docker image** — can't upgrade without changing the base image. Flag only if the installed version is missing functions the app actually uses.
- **Missing replication setup** — single-node is appropriate for the target $20/mo VPS deployment. Replication adds complexity without proportional benefit at this scale.
- **`jit=off`** — this is intentional and required for pgvector compatibility. Do not flag as a performance concern or suggest enabling it.
- **Low `max_connections` when using connection pooling** — the pool handles this. A `max_connections` of 20-30 with a properly sized asyncpg pool is correct, not a limitation.
- **Missing `pg_stat_statements` extension** — useful but not critical. Recommend as enhancement, not requirement.
- **No PITR / WAL archiving** — for a $20/mo VPS, pg_dump backups may be sufficient. Flag as enhancement if data volume warrants PITR.
