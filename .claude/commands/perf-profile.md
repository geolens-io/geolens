# /perf-profile — Performance Profiling & Bottleneck Audit

Profile the critical performance hot paths in GeoLens: tile generation, search, ingestion, map rendering, AI latency, and database query plans. Special focus on behavior under resource constraints matching the target demo environment (2GB RAM, 1 vCPU, $20/mo VPS). Every finding includes the specific bottleneck, measured impact, and a concrete fix.

**Usage:** `/perf-profile` (full profile) or `/perf-profile <subsystem>` where subsystem is `tiles`, `search`, `ingest`, `queries`, `ai`, or `memory`

**Prerequisite:** A running GeoLens instance with at least one dataset loaded. If no instance is detected, the command falls back to static analysis of query patterns, index coverage, and algorithmic complexity.

---

## PHASE 0: DISCOVERY (Serial — do this first)

### Step 1: Detect running instance and baseline resources

```bash
# Is the stack running?
docker compose ps 2>/dev/null || docker-compose ps 2>/dev/null

# Resource allocation
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}" 2>/dev/null

# Host resources
free -h 2>/dev/null
nproc 2>/dev/null
df -h / 2>/dev/null

# PostgreSQL config
docker compose exec -T db psql -U postgres -c "SHOW shared_buffers;" 2>/dev/null
docker compose exec -T db psql -U postgres -c "SHOW work_mem;" 2>/dev/null
docker compose exec -T db psql -U postgres -c "SHOW effective_cache_size;" 2>/dev/null
docker compose exec -T db psql -U postgres -c "SHOW maintenance_work_mem;" 2>/dev/null
docker compose exec -T db psql -U postgres -c "SHOW max_connections;" 2>/dev/null
docker compose exec -T db psql -U postgres -c "SHOW random_page_cost;" 2>/dev/null

# PostgreSQL version and extensions
docker compose exec -T db psql -U postgres -c "SELECT version();" 2>/dev/null
docker compose exec -T db psql -U postgres -c "SELECT extname, extversion FROM pg_extension ORDER BY extname;" 2>/dev/null

# Dataset inventory (what data exists for testing)
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid))
  FROM pg_stat_user_tables
  ORDER BY n_live_tup DESC
  LIMIT 20;
" 2>/dev/null
```

### Step 2: Map the API surface for profiling

```bash
# All API endpoints (FastAPI routers)
grep -rn "@router\.\(get\|post\|put\|patch\|delete\)" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__

# Tile endpoints specifically
grep -rn "tile\|mvt\|pbf\|vector.*tile\|raster.*tile" backend/app/processing/tiles/ backend/app/processing/raster/ --include="*.py" 2>/dev/null | grep -v __pycache__

# Search endpoints
grep -rn "@router" backend/app/modules/catalog/search/ --include="*.py" 2>/dev/null | grep -v __pycache__

# Ingest endpoints
grep -rn "@router" backend/app/processing/ingest/ --include="*.py" 2>/dev/null | grep -v __pycache__

# AI endpoints
grep -rn "@router" backend/app/processing/ai/ --include="*.py" 2>/dev/null | grep -v __pycache__

# OGC/STAC endpoints
grep -rn "@router" backend/app/standards/ogc/ backend/app/standards/stac/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

### Step 3: Read database query patterns

```bash
# All raw SQL and ORM queries in the codebase
grep -rn "select\|SELECT\|execute\|text(\|session\.\(exec\|query\|execute\)" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -v alembic | head -60

# PostGIS function usage
grep -rn "ST_\|st_" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -v alembic

# pgvector queries
grep -rn "<->\|<=>\|<#>\|similarity_search\|cosine\|l2_distance\|embedding" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -v alembic

# pg_trgm queries
grep -rn "trgm\|similarity\|ILIKE\|%%\|word_similarity\|to_tsvector\|to_tsquery\|plainto_tsquery\|@@" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__ | grep -v alembic

# Connection pooling
grep -rn "pool\|Pool\|create_engine\|sessionmaker\|pool_size\|max_overflow\|pool_timeout\|pool_recycle" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

### Step 4: Read tile generation and caching

```bash
# Full tile pipeline code
find backend/app/processing/tiles backend/app/processing/raster -name "*.py" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done

# Caching layer
find backend/app/cache -name "*.py" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done

# Titiler / raster integration
grep -rn "titiler\|cogeo\|COG\|rio\|rasterio\|TileMatrixSet" backend/app/ --include="*.py" 2>/dev/null | grep -v __pycache__
```

---

## SUBAGENT DISPATCH (Parallel)

Run these 7 subagents in parallel. Subagents that perform live profiling require a running instance — if unavailable, they fall back to static analysis with estimated impact.

### Subagent 1: Vector Tile Generation

**Goal:** Profile MVT (Mapbox Vector Tile) generation across zoom levels and dataset sizes. This is the single most latency-sensitive path — every pan/zoom on the map triggers tile requests.

**Process:**

#### 1a. Tile generation pipeline analysis

Read the full tile generation code path:
1. How is the tile request routed? (z/x/y parameters)
2. What SQL is generated? (`ST_AsMVT`, `ST_AsMVTGeom`, custom?)
3. Is geometry simplified per zoom level? (`ST_Simplify`, `ST_SnapToGrid`, `ST_SimplifyPreserveTopology`)
4. Is there a row limit per tile?
5. Are tiles cached? Where? (Redis, filesystem, in-memory, CDN headers?)
6. Are empty tiles short-circuited? (bbox check before full query)

```bash
# Read tile service/generation code
find backend/app/processing/tiles -name "*.py" -exec cat {} \;

# ST_AsMVT and related functions
grep -rn "ST_AsMVT\|ST_AsMVTGeom\|ST_Simplify\|ST_SnapToGrid\|ST_TileEnvelope\|ST_Transform\|ST_Intersects.*bbox\|ST_MakeEnvelope" backend/app/ --include="*.py" | grep -v __pycache__

# Tile caching
grep -rn "cache\|Cache\|redis\|etag\|ETag\|cache.control\|Cache-Control\|304\|not.modified\|max.age" backend/app/processing/tiles/ --include="*.py" | grep -v __pycache__
```

#### 1b. Live tile profiling (if instance available)

Discover available datasets and their tile endpoints, then profile across zoom levels:

```bash
# Find a dataset to test with
DATASET_ID=$(curl -s http://localhost:8000/api/datasets/?limit=1 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['items'][0]['id'] if d.get('items') else '')" 2>/dev/null)

# If we found a dataset, profile tile generation at multiple zoom levels
if [ -n "$DATASET_ID" ]; then
  echo "Profiling tiles for dataset: $DATASET_ID"

  for ZOOM in 0 2 5 8 10 12 14; do
    # Calculate a tile coordinate at this zoom (center of data extent)
    # Use x=0,y=0 as baseline — adjust if data is in a specific region
    X=$((1 << (ZOOM / 2)))
    Y=$((1 << (ZOOM / 2)))

    START=$(date +%s%N)
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}:%{time_total}" "http://localhost:8000/api/tiles/${DATASET_ID}/${ZOOM}/${X}/${Y}.pbf" 2>/dev/null)
    echo "z=${ZOOM} x=${X} y=${Y}: ${HTTP_CODE}"
  done
fi
```

Also profile with timing headers:
```bash
# Server-Timing header check
curl -s -D - "http://localhost:8000/api/tiles/${DATASET_ID}/8/128/128.pbf" 2>/dev/null | grep -i "server-timing\|x-response-time\|x-process-time"
```

#### 1c. Tile SQL EXPLAIN analysis

If database access is available:
```bash
# Get the actual tile SQL and EXPLAIN ANALYZE it
# This requires knowing the exact query — reconstruct from the tile service code

docker compose exec -T db psql -U postgres -d geolens -c "
  EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
  SELECT ST_AsMVT(tile, 'default')
  FROM (
    SELECT
      ST_AsMVTGeom(geom, ST_TileEnvelope(8, 128, 128), 4096, 256, true) AS geom,
      id
    FROM features
    WHERE geom && ST_TileEnvelope(8, 128, 128)
    LIMIT 10000
  ) AS tile;
" 2>/dev/null
```

Adapt the actual SQL from the discovered tile service code.

#### 1d. Tile performance assessment

**Latency targets:**
- z0–z4 (world/continent): < 200ms (few features, heavy simplification)
- z5–z8 (region/state): < 500ms (moderate features)
- z9–z12 (city/neighborhood): < 300ms (more features but smaller bbox)
- z13+ (block/parcel): < 200ms (small bbox, minimal features)

**Common bottlenecks:**
- No `ST_Simplify` per zoom → sending full-resolution geometry at low zooms (huge tiles)
- No spatial index (`USING GIST`) on geometry column → sequential scan
- No row limit per tile → z0 tile tries to serialize entire dataset
- No empty tile short-circuit → full query for tiles outside data extent
- No tile caching → regenerating identical tiles per request
- `ST_Transform` inside the tile query → CRS conversion per row per request
- `ST_MakeValid` inside the tile query → expensive validation per row

**Output:** Tile latency profile per zoom level, SQL EXPLAIN analysis, bottleneck identification, specific optimization recommendations (with SQL examples).

---

### Subagent 2: Search Performance

**Goal:** Profile full-text search, semantic (pgvector) search, and faceted filtering response times.

**Process:**

#### 2a. Search pipeline analysis

```bash
# Read the full search service
find backend/app/modules/catalog/search -name "*.py" -exec cat {} \;

# Embedding generation for semantic search
find backend/app/processing/embeddings -name "*.py" -exec cat {} \;
```

Map the search pipeline:
1. How is the search query parsed? (single query string → multiple search strategies?)
2. Full-text path: `to_tsvector` / `to_tsquery` / `plainto_tsquery` / `websearch_to_tsquery`?
3. Trigram path: `ILIKE`, `%` similarity operator, `word_similarity()`?
4. Semantic path: Embedding generation → pgvector similarity search?
5. Faceted filtering: How are facets computed? Per-request COUNT queries?
6. Are search results ranked? How? (ts_rank, similarity score, vector distance, hybrid?)
7. Is there a search cache?

#### 2b. Index coverage for search

```bash
# Full-text search indexes
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT indexname, indexdef
  FROM pg_indexes
  WHERE indexdef LIKE '%gin%' OR indexdef LIKE '%gist%' OR indexdef LIKE '%tsvector%' OR indexdef LIKE '%trgm%'
  ORDER BY indexname;
" 2>/dev/null

# Vector indexes
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT indexname, indexdef
  FROM pg_indexes
  WHERE indexdef LIKE '%ivfflat%' OR indexdef LIKE '%hnsw%'
  ORDER BY indexname;
" 2>/dev/null

# Index sizes
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT
    indexrelname,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
    idx_scan,
    idx_tup_read
  FROM pg_stat_user_indexes
  ORDER BY pg_relation_size(indexrelid) DESC
  LIMIT 20;
" 2>/dev/null
```

#### 2c. Live search profiling (if instance available)

```bash
# Full-text search with varying query lengths
for QUERY in "water" "elevation model" "land use classification 2024" "a"; do
  START=$(date +%s%N)
  RESULT=$(curl -s -w "\n%{http_code}:%{time_total}" "http://localhost:8000/api/search/?q=$(echo $QUERY | sed 's/ /+/g')&limit=20" 2>/dev/null)
  echo "Query: '$QUERY' → $(echo "$RESULT" | tail -1)"
done

# Semantic search if available
curl -s -w "\n%{time_total}s" "http://localhost:8000/api/search/?q=find+datasets+about+flooding&semantic=true" 2>/dev/null

# Faceted filtering
curl -s -w "\n%{time_total}s" "http://localhost:8000/api/search/?format=GeoJSON&geometry_type=Polygon" 2>/dev/null
```

#### 2d. Search query EXPLAIN analysis

```bash
# Full-text search query plan
docker compose exec -T db psql -U postgres -d geolens -c "
  EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
  SELECT * FROM datasets
  WHERE search_vector @@ plainto_tsquery('english', 'water elevation')
  ORDER BY ts_rank(search_vector, plainto_tsquery('english', 'water elevation')) DESC
  LIMIT 20;
" 2>/dev/null

# Trigram search query plan
docker compose exec -T db psql -U postgres -d geolens -c "
  EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
  SELECT *, similarity(name, 'wter elevaton') AS sim
  FROM datasets
  WHERE name % 'wter elevaton'
  ORDER BY sim DESC
  LIMIT 20;
" 2>/dev/null

# Vector similarity search query plan
docker compose exec -T db psql -U postgres -d geolens -c "
  EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
  SELECT id, embedding <=> '[0.1, 0.2, ...]'::vector AS distance
  FROM dataset_embeddings
  ORDER BY distance
  LIMIT 20;
" 2>/dev/null
```

Adapt queries from the discovered search code.

#### 2e. Search performance assessment

**Latency targets:**
- Full-text search: < 100ms for up to 10K datasets
- Trigram fuzzy search: < 200ms (more expensive than full-text)
- Semantic search: < 500ms (includes embedding generation if not cached)
- Faceted counts: < 100ms per facet dimension
- Combined/hybrid search: < 500ms total

**Common bottlenecks:**
- No GIN index on tsvector column → sequential scan
- No GIN index with `gin_trgm_ops` → sequential scan on ILIKE/similarity
- No pgvector index → exact nearest neighbor (O(n)) instead of approximate
- Embedding generated per search request instead of pre-computed
- Facet counts using separate COUNT queries instead of a single GROUP BY
- `ts_rank` computed for all rows before LIMIT (should filter first, then rank)
- Short search terms (1-2 chars) defeating trigram indexes (trigrams need ≥3 chars)
- Missing `LIMIT` on search results before ranking

**Output:** Search latency by strategy, index utilization, query plan analysis, specific optimizations.

---

### Subagent 3: Data Ingestion Throughput

**Goal:** Profile the file upload → processing → database insertion pipeline for various file sizes and formats.

**Process:**

#### 3a. Ingestion pipeline analysis

```bash
# Read the full ingestion pipeline
find backend/app/processing/ingest -name "*.py" -exec cat {} \;

# ogr2ogr usage
grep -rn "ogr2ogr\|ogrinfo\|gdal\|GDAL\|subprocess" backend/app/processing/ingest/ --include="*.py" | grep -v __pycache__

# COG conversion
find backend/app/processing/raster -name "*.py" -exec cat {} \;

# Background task / queue processing
grep -rn "BackgroundTask\|celery\|rq\|dramatiq\|asyncio\|Thread\|Process\|concurrent" backend/app/processing/ingest/ backend/app/ --include="*.py" | grep -v __pycache__ | head -20

# Schema validation and metadata extraction
grep -rn "schema\|metadata\|validate\|extract\|inspect" backend/app/processing/ingest/ --include="*.py" | grep -v __pycache__
```

Map the pipeline:
1. File upload → where is it stored temporarily?
2. Format detection and validation
3. ogr2ogr conversion → PostGIS insertion (or direct insertion?)
4. Schema extraction and diff
5. Metadata generation (AI or rule-based?)
6. Embedding generation for semantic search
7. Spatial index creation / refresh
8. Tile cache invalidation
9. Is ingestion synchronous (blocking) or background (async)?

#### 3b. Ingestion bottleneck analysis

```bash
# Does ogr2ogr use COPY for batch insert?
grep -rn "COPY\|PG:.*COPY\|BATCH\|batch\|chunk\|bulk_insert" backend/app/processing/ingest/ --include="*.py" | grep -v __pycache__

# Transaction handling during ingestion
grep -rn "transaction\|commit\|rollback\|BEGIN\|COMMIT" backend/app/processing/ingest/ --include="*.py" | grep -v __pycache__

# File size limits
grep -rn "max.*size\|file.*limit\|upload.*limit\|MAX_CONTENT\|MAX_FILE" backend/app/ --include="*.py" | grep -v __pycache__

# Temporary file handling
grep -rn "tempfile\|tmp\|NamedTemporary\|SpooledTemporary\|/tmp" backend/app/processing/ingest/ --include="*.py" | grep -v __pycache__

# Memory-mapped or streaming processing
grep -rn "mmap\|stream\|chunk\|read.*bytes\|iter.*content\|aiofiles" backend/app/processing/ingest/ --include="*.py" | grep -v __pycache__
```

#### 3c. Ingestion performance estimation

Even without live testing, estimate throughput from the pipeline analysis:

| Factor | Impact |
|--------|--------|
| ogr2ogr with PG COPY | ~50K–100K features/min (good) |
| ogr2ogr with INSERT | ~5K–10K features/min (bad) |
| Synchronous processing | Blocks request for entire ingestion time |
| Background processing | Returns 202 immediately, processes async |
| No transaction batching | Each INSERT is a separate transaction (very slow) |
| In-memory file buffering | OOM risk on 2GB VPS with large files |
| Spatial index creation after bulk load | Correct (create index after data load, not during) |
| Spatial index creation during load | Very slow (index maintained per INSERT) |

#### 3d. Ingestion assessment

**Throughput targets (on 2GB RAM / 1 vCPU):**
- Shapefile 10K features: < 30 seconds
- Shapefile 100K features: < 3 minutes
- Shapefile 500K features: < 10 minutes
- GeoJSON 50MB: < 5 minutes
- CSV with coordinates, 100K rows: < 2 minutes
- Raster → COG conversion, 500MB GeoTIFF: < 10 minutes

**Common bottlenecks:**
- Synchronous ingestion blocking the API server during large uploads
- ogr2ogr using single-row INSERT instead of COPY
- Entire file loaded into memory before processing (OOM on large files)
- Spatial index rebuilt during import instead of after
- Embedding generation for every row during import (should be batched/deferred)
- No progress reporting for long-running imports
- Temporary files not cleaned up after failed imports (disk exhaustion)

**Output:** Pipeline diagram, estimated throughput by format/size, bottleneck identification, specific optimizations.

---

### Subagent 4: Database Query Plans & Configuration

**Goal:** Audit PostgreSQL configuration and the most expensive query patterns for the GeoLens workload. This is the foundation — bad PG config degrades everything.

**Process:**

#### 4a. PostgreSQL configuration audit

```bash
# Read the postgres config that Docker applies
docker compose exec -T db psql -U postgres -c "
  SELECT name, setting, unit, source
  FROM pg_settings
  WHERE source != 'default'
  ORDER BY source, name;
" 2>/dev/null

# Key settings for the GeoLens workload
docker compose exec -T db psql -U postgres -c "
  SELECT name, setting, unit
  FROM pg_settings
  WHERE name IN (
    'shared_buffers', 'work_mem', 'effective_cache_size',
    'maintenance_work_mem', 'random_page_cost',
    'max_connections', 'max_parallel_workers_per_gather',
    'max_parallel_workers', 'max_worker_processes',
    'jit', 'default_statistics_target',
    'checkpoint_completion_target', 'wal_buffers',
    'max_wal_size', 'min_wal_size'
  )
  ORDER BY name;
" 2>/dev/null
```

**Configuration recommendations by deployment size:**

For 2GB RAM demo VPS:
```
shared_buffers = 512MB         # 25% of RAM
work_mem = 16MB                # Per-sort operation (careful — multiplied by connections × sorts)
effective_cache_size = 1.5GB   # 75% of RAM — tells planner OS cache exists
maintenance_work_mem = 128MB   # For VACUUM, CREATE INDEX, ALTER TABLE
random_page_cost = 1.1         # SSD assumed (default 4.0 is for spinning disk)
max_connections = 20           # Low — solo dev demo, not production
jit = off                      # JIT compilation overhead not worth it at this scale
default_statistics_target = 100 # Default is fine
```

For 8GB RAM production:
```
shared_buffers = 2GB
work_mem = 64MB
effective_cache_size = 6GB
maintenance_work_mem = 512MB
random_page_cost = 1.1
max_connections = 50
```

#### 4b. Slow query identification

```bash
# Enable pg_stat_statements if available
docker compose exec -T db psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;" 2>/dev/null

# Top queries by total time
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT
    calls,
    round(total_exec_time::numeric, 2) AS total_ms,
    round(mean_exec_time::numeric, 2) AS mean_ms,
    round(max_exec_time::numeric, 2) AS max_ms,
    rows,
    left(query, 150) AS query
  FROM pg_stat_statements
  ORDER BY total_exec_time DESC
  LIMIT 20;
" 2>/dev/null

# Top queries by mean time (single-call expensive)
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT
    calls,
    round(mean_exec_time::numeric, 2) AS mean_ms,
    round(max_exec_time::numeric, 2) AS max_ms,
    rows,
    left(query, 150) AS query
  FROM pg_stat_statements
  WHERE calls > 1
  ORDER BY mean_exec_time DESC
  LIMIT 20;
" 2>/dev/null
```

#### 4c. Table and index statistics

```bash
# Table sizes and row counts
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT
    relname AS table_name,
    n_live_tup AS row_count,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    pg_size_pretty(pg_relation_size(relid)) AS table_size,
    pg_size_pretty(pg_indexes_size(relid)) AS index_size,
    n_dead_tup AS dead_rows,
    last_vacuum,
    last_autovacuum
  FROM pg_stat_user_tables
  ORDER BY pg_total_relation_size(relid) DESC
  LIMIT 20;
" 2>/dev/null

# Unused indexes (wasting space and slowing writes)
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT
    schemaname, relname, indexrelname,
    pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
    idx_scan
  FROM pg_stat_user_indexes
  WHERE idx_scan = 0
    AND indexrelname NOT LIKE '%_pkey'
  ORDER BY pg_relation_size(indexrelid) DESC;
" 2>/dev/null

# Missing indexes — sequential scans on large tables
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT
    relname, seq_scan, seq_tup_read,
    idx_scan, idx_tup_fetch,
    n_live_tup,
    round(seq_tup_read::numeric / greatest(seq_scan, 1), 0) AS avg_rows_per_seq_scan
  FROM pg_stat_user_tables
  WHERE seq_scan > 0
    AND n_live_tup > 1000
  ORDER BY seq_tup_read DESC
  LIMIT 20;
" 2>/dev/null
```

#### 4d. Spatial-specific query analysis

```bash
# EXPLAIN ANALYZE the most common spatial patterns found in the codebase
# Adapt these to actual queries discovered in Phase 0

# Bbox intersection (used in tiles, OGC Features, map viewer)
docker compose exec -T db psql -U postgres -d geolens -c "
  EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
  SELECT id, ST_AsGeoJSON(geom)
  FROM features
  WHERE geom && ST_MakeEnvelope(-74, 40, -73, 41, 4326)
  LIMIT 100;
" 2>/dev/null

# Distance query
docker compose exec -T db psql -U postgres -d geolens -c "
  EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
  SELECT id, ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(-73.9857, 40.7484), 4326)::geography) AS dist_m
  FROM features
  WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(-73.9857, 40.7484), 4326)::geography, 1000)
  ORDER BY dist_m
  LIMIT 20;
" 2>/dev/null
```

#### 4e. Connection pool analysis

```bash
# Active connections
docker compose exec -T db psql -U postgres -c "
  SELECT count(*), state, wait_event_type
  FROM pg_stat_activity
  WHERE datname = 'geolens'
  GROUP BY state, wait_event_type
  ORDER BY count DESC;
" 2>/dev/null

# Connection pool config in application code
grep -rn "pool_size\|max_overflow\|pool_timeout\|pool_recycle\|pool_pre_ping\|create_engine" backend/app/ --include="*.py" | grep -v __pycache__
```

**Pool recommendations for 2GB VPS:**
- `pool_size=5` (matches low max_connections)
- `max_overflow=5` (burst to 10 max)
- `pool_pre_ping=True` (avoid stale connections)
- `pool_recycle=3600` (recycle connections hourly)

**Output:** PG configuration audit with recommended values, top slow queries, table/index health, spatial query plan analysis.

---

### Subagent 5: AI Latency & Cost

**Goal:** Profile AI response times and token usage across metadata generation, map chat, and style generation.

**Process:**

#### 5a. AI response time analysis

```bash
# Read AI service code to understand the request flow
find backend/app/processing/ai -name "*.py" -exec cat {} \;

# What models are configured?
grep -rn "model\|gpt\|claude\|sonnet\|haiku\|temperature\|max_tokens" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Streaming vs non-streaming
grep -rn "stream\|SSE\|yield\|async.*for" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Timeout configuration
grep -rn "timeout\|TIMEOUT" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
```

#### 5b. Token budget estimation

For each AI subsystem, estimate per-request token usage from the prompt analysis:

```bash
# Measure system prompt sizes (character count ≈ tokens/4)
find backend/app/processing/ai -name "*.py" -exec python3 -c "
import ast, sys
with open(sys.argv[1]) as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 200:
        print(f'{sys.argv[1]}:{node.lineno} — {len(node.value)} chars (~{len(node.value)//4} tokens)')
" {} \; 2>/dev/null
```

Estimate for each subsystem:

| Subsystem | System prompt | Context (schema/style) | Few-shot | User msg | Output | Total est. |
|-----------|---------------|----------------------|----------|----------|--------|-----------|
| Metadata | ? | ? | ? | ? | ? | ? |
| SQL gen | ? | ? | ? | ? | ? | ? |
| Style gen | ? | ? | ? | ? | ? | ? |

#### 5c. AI caching and deduplication

```bash
# Is there any AI response caching?
grep -rn "cache\|memo\|lru\|redis\|ttl" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Is embedding generation cached?
grep -rn "cache\|memo\|store" backend/app/processing/embeddings/ --include="*.py" | grep -v __pycache__
```

#### 5d. Live AI profiling (if instance available and API keys configured)

```bash
# Test metadata generation latency
START=$(date +%s%N)
curl -s -w "\n%{time_total}s" -X POST "http://localhost:8000/api/ai/metadata/generate" \
  -H "Content-Type: application/json" \
  -d '{"dataset_id": "'$DATASET_ID'"}' 2>/dev/null

# Test chat/SQL generation latency
curl -s -w "\n%{time_total}s" -X POST "http://localhost:8000/api/ai/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "Show me all features within 1km of the center"}' 2>/dev/null
```

#### 5e. AI performance assessment

**Latency targets:**
- Metadata generation: < 5s (background, not blocking UI)
- SQL generation (first token): < 2s (streaming, user perceives responsiveness)
- SQL generation (complete): < 8s
- Style adjustment: < 3s
- Embedding generation: < 1s per text (should be batched for bulk)

**Common bottlenecks:**
- Using a large model (Opus, GPT-4) for simple tasks (metadata, style tweaks) → use Haiku/GPT-4o-mini
- Schema context rebuilding on every request → cache per dataset, invalidate on schema change
- System prompt too large (>2K tokens) → compress, use structured format
- Embedding generated per search query instead of using pre-computed lookup
- No streaming for chat → user waits for full response before seeing anything
- No timeout → API hangs if LLM provider is slow/down
- Synchronous embedding generation during ingestion → blocks upload response

**Output:** AI latency profile, token budget analysis, model sizing recommendations, caching opportunities.

---

### Subagent 6: Memory & Resource Profiling

**Goal:** Assess whether GeoLens can run reliably on a 2GB RAM / 1 vCPU VPS — the target demo deployment.

**Process:**

#### 6a. Service memory footprint

```bash
# Per-service memory usage
docker stats --no-stream --format "{{.Name}}: {{.MemUsage}} ({{.MemPerc}})" 2>/dev/null

# Process-level within the backend container
docker compose exec -T backend ps aux --sort=-rss 2>/dev/null | head -10

# Python memory profiling (if tracemalloc available)
docker compose exec -T backend python3 -c "
import tracemalloc
tracemalloc.start()
# Import the app to measure baseline memory
from app.main import app
snapshot = tracemalloc.take_snapshot()
top = snapshot.statistics('lineno')
for stat in top[:20]:
    print(stat)
" 2>/dev/null
```

#### 6b. Memory pressure scenarios

Estimate memory usage under load:

| Component | Baseline | Per-request | Peak scenario |
|-----------|----------|-------------|---------------|
| PostgreSQL | ~200MB (shared_buffers) | +work_mem per sort | Large EXPLAIN + multiple connections |
| Backend (FastAPI/Uvicorn) | ~100–200MB | +file buffer per upload | Large file ingestion |
| Frontend build (if dev mode) | ~300MB | N/A | Dev only |
| Redis (if used) | ~50MB | +tile cache | Depends on cache size |
| Titiler (if separate) | ~200MB | +raster buffer | Large COG rendering |

```bash
# Total service count and estimated floor
docker compose config --services 2>/dev/null | wc -l

# Are there resource limits set?
grep -n "mem_limit\|memory\|memswap\|cpus\|cpu_shares\|shm_size\|deploy.*resources" docker-compose.yml 2>/dev/null
```

#### 6c. OOM risk assessment

```bash
# Kernel OOM events
dmesg 2>/dev/null | grep -i "oom\|out of memory\|killed process" | tail -10

# Docker container restarts (sign of OOM kills)
docker compose ps 2>/dev/null | grep -i "restart\|exited"

# Swap usage
free -h 2>/dev/null
swapon --show 2>/dev/null
```

**2GB VPS memory budget:**
```
Total:                          2048MB
OS + Docker overhead:           ~300MB
PostgreSQL (shared_buffers):    ~512MB (recommended)
Backend (FastAPI + workers):    ~300MB
Redis/cache (if used):          ~100MB
Remaining headroom:             ~836MB

⚠️ This leaves NO room for:
- Large file uploads buffered in memory
- Multiple concurrent tile generations
- Raster processing (COG conversion)
- Frontend dev server (if running)
```

#### 6d. CPU profiling

```bash
# CPU-intensive operations in the codebase
grep -rn "ogr2ogr\|gdal_translate\|gdalwarp\|subprocess\|Popen\|ProcessPoolExecutor\|multiprocessing" backend/app/ --include="*.py" | grep -v __pycache__

# Uvicorn worker count
grep -rn "workers\|uvicorn\|gunicorn" docker-compose.yml Dockerfile* backend/Dockerfile* 2>/dev/null

# Is the backend single-worker?
docker compose exec -T backend ps aux 2>/dev/null | grep -c "uvicorn\|gunicorn" 2>/dev/null
```

On a 1 vCPU VPS, single-worker Uvicorn is correct. Multiple workers would fight for CPU and increase memory.

#### 6e. Disk I/O assessment

```bash
# Temporary file usage during ingestion
grep -rn "tempfile\|tmp\|/tmp\|NamedTemporary\|SpooledTemporary" backend/app/ --include="*.py" | grep -v __pycache__

# Disk usage by Docker volumes
docker system df -v 2>/dev/null | head -30

# Database size
docker compose exec -T db psql -U postgres -d geolens -c "
  SELECT pg_size_pretty(pg_database_size('geolens'));
" 2>/dev/null
```

**Output:** Memory budget breakdown, OOM risk assessment, CPU bottleneck analysis, resource limit recommendations for demo and production.

---

### Subagent 7: Frontend Rendering Performance

**Goal:** Profile map builder and data table rendering under realistic data loads.

**Process:**

#### 7a. Map rendering analysis

```bash
# MapLibre GL configuration
grep -rn "maxzoom\|minzoom\|maxTileCacheSize\|maxParallelImageRequests\|fadeDuration\|maxCanvasSize\|antialiasing\|pixelRatio" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules

# Number of layers in a typical map
grep -rn "addLayer\|layers\|Layer" frontend/src/components/builder/ frontend/src/components/map/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -20

# Heavy re-render patterns
grep -rn "useEffect\|useMemo\|useCallback\|React\.memo\|memo(" frontend/src/components/map/ frontend/src/components/builder/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -30

# Large state objects that might cause re-renders
grep -rn "useState\|useReducer\|useContext\|zustand\|jotai\|recoil" frontend/src/components/map/ frontend/src/components/builder/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -20
```

#### 7b. Data table performance

```bash
# Table/data grid component
find frontend/src -name "*Table*" -o -name "*DataGrid*" -o -name "*table*" 2>/dev/null | grep -E "\.(tsx|ts)$" | grep -v node_modules | grep -iv "ui/table"

# Virtualization
grep -rn "virtualize\|virtual\|react-virtual\|tanstack.*virtual\|react-window\|react-virtualized\|useVirtual" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules

# Pagination
grep -rn "page\|Page\|pagination\|Pagination\|limit\|offset\|pageSize" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -i "table\|data\|grid\|list" | head -20
```

**Data table targets:**
- 100 rows: instant render (< 50ms)
- 1000 rows: smooth scroll if virtualized, < 200ms initial render
- 10K+ rows: MUST be virtualized or server-side paginated

#### 7c. Bundle size analysis

```bash
# Check for bundle analysis tooling
cat frontend/package.json 2>/dev/null | python3 -c "
import sys, json
d = json.load(sys.stdin)
deps = {**d.get('dependencies', {}), **d.get('devDependencies', {})}
# Flag heavy dependencies
heavy = ['moment', 'lodash', 'date-fns', '@mui', '@chakra', 'antd']
for h in heavy:
  matches = [k for k in deps if h in k.lower()]
  if matches:
    print(f'Heavy dep: {matches}')
print(f'Total deps: {len(deps)}')
" 2>/dev/null

# Build size (if build artifacts exist)
ls -lh frontend/dist/ 2>/dev/null
find frontend/dist -name "*.js" -exec ls -lh {} \; 2>/dev/null
find frontend/dist -name "*.css" -exec ls -lh {} \; 2>/dev/null
```

**Bundle targets:**
- Initial JS bundle: < 500KB gzipped (target for gov networks which may be slow)
- CSS: < 50KB gzipped
- Largest chunk: < 200KB gzipped

#### 7d. Network waterfall assessment

```bash
# Lazy loading / code splitting
grep -rn "lazy\|Suspense\|React\.lazy\|import(\|dynamic" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | head -20

# Image optimization
find frontend/src frontend/public -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" -o -name "*.gif" 2>/dev/null | while read f; do
  ls -lh "$f"
done

# API call patterns — are there request waterfalls?
grep -rn "useQuery\|useSWR\|fetch\|axios\|useEffect.*fetch" frontend/src/pages/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -20
```

**Output:** Map rendering assessment, data table scalability, bundle size analysis, network waterfall findings.

---

## SYNTHESIS (Serial — after all subagents complete)

### Performance Scorecard

| Dimension | Metric | Target | Measured/Estimated | Grade |
|-----------|--------|--------|-------------------|-------|
| **Tile generation** | p95 latency @ z8 | < 500ms | ? | A–F |
| **Search (full-text)** | p95 latency | < 100ms | ? | A–F |
| **Search (semantic)** | p95 latency | < 500ms | ? | A–F |
| **Ingestion (10K features)** | Total time | < 30s | ? | A–F |
| **AI chat (first token)** | Time to first token | < 2s | ? | A–F |
| **PG configuration** | Tuned for workload | Appropriate for RAM | ? | A–F |
| **Memory headroom** | Remaining on 2GB VPS | > 300MB idle | ? | A–F |
| **Frontend bundle** | Gzipped JS size | < 500KB | ? | A–F |

**Overall performance health** = weighted average, with tile generation and search weighted 2x (these are the hot paths users perceive).

### Bottleneck Priority Matrix

Plot every identified bottleneck on two axes:

| | Low effort fix | High effort fix |
|---|---|---|
| **High impact** | **DO FIRST** (PG config, missing index, cache header) | **PLAN** (tile caching layer, query rewrite, connection pool) |
| **Low impact** | **QUICK WIN** (compression, timeout config) | **SKIP** (premature optimization) |

### Action Items

| Field | Description |
|-------|-------------|
| Priority | P0 (will fail on demo VPS), P1 (users will perceive), P2 (optimization opportunity) |
| Subsystem | Tiles / Search / Ingest / DB / AI / Memory / Frontend |
| Action | Specific fix with file path, SQL, or config change |
| Effort | Hours estimate |
| Expected impact | Latency reduction or memory savings (quantified) |
| Measurement | How to verify the improvement (specific query, endpoint, metric) |

Sort by: priority → impact → effort.

### Demo VPS Deployment Recommendations

If the audit reveals the stack won't fit in 2GB RAM, provide a specific mitigation plan:

```markdown
### 2GB VPS Survival Guide

PostgreSQL tuning:
- shared_buffers = ?
- work_mem = ?
- ...

Application tuning:
- Worker count: ?
- Connection pool: ?
- Cache strategy: ?

Services to disable for demo:
- ? (e.g., separate Titiler if memory-heavy)

Minimum viable resource allocation:
- PostgreSQL: ?MB
- Backend: ?MB
- Other: ?MB
- Headroom: ?MB
```

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/perf-profile-{YYYYMMDD}.md`

### Report structure

```markdown
# Performance Profile — {YYYY-MM-DD}

## Scorecard
<!-- Performance grades per dimension -->

## Executive Summary
<!-- 3-5 sentences: overall performance posture, critical bottlenecks, top fix -->

## 1. Vector Tile Generation
### 1a. Pipeline Analysis
### 1b. Latency Profile by Zoom Level
### 1c. SQL EXPLAIN Analysis
### 1d. Caching Assessment

## 2. Search Performance
### 2a. Full-Text Search
### 2b. Semantic Search
### 2c. Faceted Filtering
### 2d. Index Utilization

## 3. Data Ingestion Throughput
### 3a. Pipeline Analysis
### 3b. Throughput by Format/Size
### 3c. Background Processing

## 4. Database Configuration & Queries
### 4a. PostgreSQL Configuration
### 4b. Slow Queries
### 4c. Table & Index Health
### 4d. Connection Pool

## 5. AI Latency & Cost
### 5a. Response Time Profile
### 5b. Token Budget
### 5c. Caching Opportunities

## 6. Memory & Resources
### 6a. Service Memory Footprint
### 6b. 2GB VPS Feasibility
### 6c. OOM Risk Assessment
### 6d. CPU & Disk I/O

## 7. Frontend Rendering
### 7a. Map Builder Performance
### 7b. Data Table Scalability
### 7c. Bundle Size
### 7d. Network Waterfall

## 8. Bottleneck Priority Matrix
<!-- Effort vs. impact grid -->

## 9. Prioritized Action Items
<!-- Action items table -->

## 10. Demo VPS Deployment Guide
<!-- 2GB survival guide if applicable -->

## 11. Comparison to Prior Audit
<!-- If a previous perf-profile exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append reusable insights about PostGIS/pgvector performance tuning.
2. Print summary: overall grade + critical bottleneck count + "will it run on 2GB?" verdict.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/post-impl` — covers performance as one of its subagents alongside simplification and cleanup. This command provides deeper profiling with live benchmarks and query plan analysis.
- `/db-audit` — covers database configuration and bloat. This command covers application-level query performance and tile/search latency.
- `/docker-audit` — covers container resource limits. This command covers whether the application fits within those limits.

---

## WHAT NOT TO FLAG

- **Development-mode performance** — If the stack is running with hot-reload, debug logging, or unoptimized builds, note it but don't grade on dev-mode numbers. Focus on what production mode would look like.
- **Small dataset performance** — If only a tiny test dataset exists (< 100 rows), don't draw performance conclusions from it. Note the limitation and project based on query plans and algorithmic complexity.
- **AI latency from LLM provider** — The network round-trip to OpenAI/Anthropic is outside GeoLens's control. Focus on what GeoLens can control: prompt size, caching, model selection, streaming.
- **Frontend dev server bundle size** — Vite dev mode doesn't represent production. Only measure from `dist/` build output.
- **PostgreSQL not tuned from defaults** — Flag it as P0 (huge easy win) but don't treat it as a code quality failure. Postgres ships with deliberately conservative defaults.
- **Tile latency on z0/z1** — The guide notes PostGIS tolerance errors at very low zooms for complex geometries. z2+ is the realistic baseline.
- **Missing Redis/Memcached** — Not every deployment needs a separate cache layer. In-memory caching or HTTP cache headers may be sufficient at demo scale.